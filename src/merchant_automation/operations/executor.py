"""Recipe step executor — drives BrowserSession through RecipeDefinition steps."""
from __future__ import annotations

import asyncio
import logging
import re
import tempfile

from browser_use.browser.session import BrowserSession
from browser_use.llm.messages import UserMessage
from merchant_automation.operations.recipe_definition import (
	RecipeDefinition,
	RecipeStep,
	RecipeStepAction,
)
from merchant_automation.operations.schemas import ExecutionMode, FailureType
from merchant_automation.operations.traces import ExecutionTrace, TraceRecorder, TraceStepKind

logger = logging.getLogger(__name__)


class StepExecutionError(Exception):
	"""Recipe step execution failed."""

	def __init__(self, message: str, step_index: int, step: RecipeStep) -> None:
		self.step_index = step_index
		self.step = step
		super().__init__(message)


class RecipeStepExecutor:
	"""Executes RecipeDefinition steps by driving BrowserSession with optional LLM-assisted element finding."""

	def __init__(
		self,
		browser_session: BrowserSession,
		llm=None,
	) -> None:
		self._session = browser_session
		self._llm = llm

	async def execute(
		self,
		recipe: RecipeDefinition,
		params: dict[str, object],
		recorder: TraceRecorder,
		*,
		mode: ExecutionMode = ExecutionMode.PREPARE,
	) -> 'ExecutionTrace':
		"""Execute recipe steps sequentially. Raises StepExecutionError on failure."""
		for i, step in enumerate(recipe.steps):
			# COMMIT 模式下跳过 STOP_BEFORE_SUBMIT
			if step.action == RecipeStepAction.STOP_BEFORE_SUBMIT and mode == ExecutionMode.COMMIT:
				continue

			try:
				should_stop = await self._execute_step(step, i, params, recorder)
				if should_stop:
					break
			except StepExecutionError:
				recorder.fail(
					failure_type=FailureType.SUBMIT_FAILED,
					message=f'步骤 {i + 1} 执行失败: {step.action.value}',
					failed_step_number=i + 1,
				)
				raise

		recorder.complete('执行完成')
		return recorder.trace

	def execute_sync(
		self,
		recipe: RecipeDefinition,
		params: dict[str, object],
		recorder: TraceRecorder,
		*,
		mode: ExecutionMode = ExecutionMode.DRY_RUN,
	) -> ExecutionTrace:
		"""Synchronous wrapper for execute() — used for validation."""
		loop = asyncio.new_event_loop()
		try:
			return loop.run_until_complete(self.execute(recipe, params, recorder, mode=mode))
		finally:
			loop.close()

	async def _execute_step(
		self,
		step: RecipeStep,
		step_index: int,
		params: dict[str, object],
		recorder: TraceRecorder,
	) -> bool:
		"""Execute a single step. Returns True if execution should stop."""
		action = step.action

		if action == RecipeStepAction.NAVIGATE:
			await self._do_navigate(step, params, recorder)
		elif action == RecipeStepAction.FILL:
			await self._do_fill(step, step_index, params, recorder)
		elif action == RecipeStepAction.CLICK:
			await self._do_click(step, step_index, params, recorder)
		elif action == RecipeStepAction.SCREENSHOT:
			await self._do_screenshot(step, recorder)
		elif action == RecipeStepAction.WAIT:
			await self._do_wait(step, recorder)
		elif action == RecipeStepAction.STOP_BEFORE_SUBMIT:
			await self._do_stop_before_submit(step, recorder)
			return True
		elif action == RecipeStepAction.VERIFY:
			await self._do_verify(step, step_index, recorder)
		elif action == RecipeStepAction.UPLOAD:
			await self._do_upload(step, step_index, params, recorder)
		else:
			raise StepExecutionError(
				f'未知操作类型: {action}', step_index, step
			)

		return False

	# ----- Action handlers -----

	async def _do_navigate(
		self,
		step: RecipeStep,
		params: dict[str, object],
		recorder: TraceRecorder,
	) -> None:
		url = self._resolve_template(step.url, params)
		if not url:
			raise StepExecutionError('NAVIGATE 步骤缺少 url', -1, step)
		await self._session.navigate_to(url)
		recorder.record_step(
			TraceStepKind.PAGE,
			step.description or f'打开 {url}',
			url=url,
		)

	async def _do_fill(
		self,
		step: RecipeStep,
		step_index: int,
		params: dict[str, object],
		recorder: TraceRecorder,
	) -> None:
		if not step.target:
			raise StepExecutionError('FILL 步骤缺少 target', step_index, step)
		index = await self._find_element(step.target)
		value = self._resolve_template(step.value, params) or ''
		element = await self._get_element_by_index(index, step, step_index)
		await element.fill(value)
		recorder.record_step(
			TraceStepKind.ACTION,
			step.description or f'填写 {step.target}',
			target=step.target,
			input_value=value,
		)

	async def _do_click(
		self,
		step: RecipeStep,
		step_index: int,
		params: dict[str, object],
		recorder: TraceRecorder,
	) -> None:
		if not step.target:
			raise StepExecutionError('CLICK 步骤缺少 target', step_index, step)
		index = await self._find_element(step.target)
		element = await self._get_element_by_index(index, step, step_index)
		try:
			await element.click()
		except RuntimeError as exc:
			raise StepExecutionError(f'点击元素失败: {exc}', step_index, step) from exc
		recorder.record_step(
			TraceStepKind.ACTION,
			step.description or f'点击 {step.target}',
			target=step.target,
		)

	async def _do_screenshot(
		self,
		step: RecipeStep,
		recorder: TraceRecorder,
	) -> None:
		screenshot_bytes = await self._session.take_screenshot()
		tmp = tempfile.NamedTemporaryFile(
			suffix='.png', delete=False, prefix='recipe_'
		)
		tmp.write(screenshot_bytes)
		tmp.close()
		recorder.record_step(
			TraceStepKind.SCREENSHOT,
			step.description or '截图',
			screenshot_path=tmp.name,
		)

	async def _do_wait(
		self,
		step: RecipeStep,
		recorder: TraceRecorder,
	) -> None:
		duration = step.timeout or 1.0
		await asyncio.sleep(duration)
		recorder.record_step(
			TraceStepKind.ACTION,
			f'等待 {duration}s',
		)

	async def _do_stop_before_submit(
		self,
		step: RecipeStep,
		recorder: TraceRecorder,
	) -> None:
		recorder.record_step(
			TraceStepKind.ACTION,
			step.description or '停在提交前',
		)

		# 截图作为证据，确认修改正确
		try:
			screenshot_bytes = await self._session.take_screenshot()
			with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
				tmp.write(screenshot_bytes)
				recorder.record_step(
					TraceStepKind.SCREENSHOT,
					'停在提交前 - 截图确认',
					screenshot_path=tmp.name,
				)
		except Exception:
			logger.warning('STOP_BEFORE_SUBMIT 截图失败', exc_info=True)

	async def _do_verify(
		self,
		step: RecipeStep,
		step_index: int,
		recorder: TraceRecorder,
	) -> None:
		page = await self._session.must_get_current_page()
		page_text = await page.evaluate('(...args) => document.body.innerText')
		if step.value and step.value not in page_text:
			raise StepExecutionError(
				f'验证失败: 页面不包含 "{step.value}"', step_index, step
			)
		recorder.record_step(
			TraceStepKind.VALIDATION,
			step.description or f'验证: {step.target}',
		)

	async def _do_upload(
		self,
		step: RecipeStep,
		step_index: int,
		params: dict[str, object],
		recorder: TraceRecorder,
	) -> None:
		if not step.target:
			raise StepExecutionError('UPLOAD 步骤缺少 target', step_index, step)
		index = await self._find_element(step.target)
		value = self._resolve_template(step.value, params)
		element = await self._get_element_by_index(index, step, step_index)
		page = await self._session.must_get_current_page()
		# Use CDP to set input files
		node_id = await element._get_node_id()
		await self._session.cdp_client.send.DOM.setFileInputFiles(
			params={'files': [value] if value else [], 'nodeId': node_id},
			session_id=await page._ensure_session(),
		)
		recorder.record_step(
			TraceStepKind.ACTION,
			f'上传 {value}',
			target=step.target,
		)

	# ----- Helpers -----

	async def _get_element_by_index(self, index: int, step: RecipeStep, step_index: int):
		"""Get element by index, raising StepExecutionError if not found."""
		node = await self._session.get_element_by_index(index)
		if node is None:
			raise StepExecutionError(
				f'元素 index={index} 不存在', step_index, step
			)
		page = await self._session.must_get_current_page()
		return await page.get_element(node.backend_node_id)

	# ----- Element finding -----

	async def _find_element(self, target_description: str, timeout: float = 5.0) -> int:
		"""Find element index using LLM or text-matching fallback.

		Triggers DOM state refresh and retries until selector_map is populated.
		"""
		selector_map: dict[int, object] = {}
		elapsed = 0.0
		interval = 0.5

		while elapsed < timeout:
			# Trigger DOM refresh to populate selector_map
			await self._session.get_browser_state_summary(include_screenshot=False)
			selector_map = await self._session.get_selector_map()
			if selector_map:
				break
			await asyncio.sleep(interval)
			elapsed += interval

		if not selector_map:
			raise StepExecutionError(
				f'页面无可用元素，无法找到: {target_description}',
				-1,
				RecipeStep(action=RecipeStepAction.CLICK, target=target_description),
			)

		if self._llm is not None:
			return await self._find_element_with_llm(target_description, selector_map)

		return self._find_element_by_text(target_description, selector_map)

	async def _find_element_with_llm(
		self,
		target_description: str,
		selector_map: dict[int, object],
	) -> int:
		"""Use LLM to find the element matching target_description."""
		candidates = []
		for index, node in selector_map.items():
			text = getattr(node, 'node_value', '') or ''
			attrs = getattr(node, 'attributes', {}) or {}
			label = (
				attrs.get('aria-label', '')
				or attrs.get('placeholder', '')
				or attrs.get('name', '')
			)
			tag = getattr(node, 'tag_name', 'unknown')
			candidates.append(f'[{index}] <{tag}> text="{text}" label="{label}"')

		prompt = (
			f'从以下网页元素中找到"{target_description}"对应的元素。'
			f'只返回元素的 index 数字，不要其他内容。\n\n'
		)
		prompt += '\n'.join(candidates[:50])

		response = await self._llm.ainvoke([UserMessage(content=prompt)])
		match = re.search(r'\d+', _llm_response_text(response))
		if match:
			index = int(match.group())
			element = await self._session.get_element_by_index(index)
			if element is not None:
				return index

		raise StepExecutionError(
			f'LLM 无法找到元素: {target_description}',
			-1,
			RecipeStep(action=RecipeStepAction.CLICK, target=target_description),
		)

	def _find_element_by_text(
		self,
		target_description: str,
		selector_map: dict[int, object],
	) -> int:
		"""Fallback: find element by matching text/label attributes."""
		best_index = -1
		best_score = 0

		for index, node in selector_map.items():
			text = getattr(node, 'node_value', '') or ''
			attrs = getattr(node, 'attributes', {}) or {}
			label = (
				attrs.get('aria-label', '')
				or attrs.get('placeholder', '')
				or attrs.get('name', '')
			)
			combined = f'{text} {label}'
			if target_description in combined:
				score = len(target_description)
				if score > best_score:
					best_score = score
					best_index = index

		if best_index >= 0:
			return best_index

		raise StepExecutionError(
			f'文本匹配无法找到元素: {target_description}',
			-1,
			RecipeStep(action=RecipeStepAction.CLICK, target=target_description),
		)

	# ----- Template resolution -----

	def _resolve_template(
		self, template: str | None, params: dict[str, object]
	) -> str | None:
		"""Resolve template variables like {phone} -> params['phone']."""
		if template is None:
			return None
		result = template
		for key, value in params.items():
			result = result.replace(f'{{{key}}}', str(value))
		return result


def _llm_response_text(response: object) -> str:
	for attr in ('completion', 'content', 'text'):
		value = getattr(response, attr, None)
		if value is not None:
			return str(value)
	return str(response)
