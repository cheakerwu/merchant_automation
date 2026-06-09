from __future__ import annotations

import logging
from typing import Any

from browser_use import Agent, BrowserSession
from langchain_core.language_models.chat_models import BaseChatModel

from merchant_automation.operations.schemas import ExecutionMode, FailureType, OperationContract
from merchant_automation.operations.traces import (
	ExecutionTrace,
	TraceRecorder,
	TraceStepKind,
	record_screenshot_bytes,
	trace_screenshot_paths,
)

logger = logging.getLogger(__name__)


def _agent_failure_message(result: Any) -> str | None:
	all_results = getattr(result, 'all_results', None)
	if not all_results:
		return None

	done_results = [item for item in all_results if getattr(item, 'is_done', False)]
	final_result = done_results[-1] if done_results else all_results[-1]
	judgement = getattr(final_result, 'judgement', None)
	if getattr(final_result, 'success', None) is not False and not getattr(judgement, 'impossible_task', False):
		return None

	failure_reason = getattr(judgement, 'failure_reason', None) if judgement is not None else None
	extracted_content = getattr(final_result, 'extracted_content', None)
	error = getattr(final_result, 'error', None)
	for candidate in (failure_reason, extracted_content, error, str(result)):
		if candidate:
			return str(candidate)
	return 'Agent 最终判定任务失败'


class AgentExplorer:
	"""用 browser_use.Agent 探索后台，记录执行轨迹。"""

	def __init__(
		self,
		browser_session: BrowserSession,
		llm: BaseChatModel,
	) -> None:
		self._session = browser_session
		self._llm = llm
		self.last_history: Any = None

	async def explore(
		self,
		operation: OperationContract,
		params: dict[str, object],
		recorder: TraceRecorder,
		*,
		mode: ExecutionMode = ExecutionMode.DRY_RUN,
		max_steps: int = 30,
		entry_url: str | None = None,
	) -> ExecutionTrace:
		"""Agent 自由探索，记录轨迹。"""
		task_prompt = self._build_task_prompt(operation, params, mode, entry_url=entry_url)

		agent = Agent(
			task=task_prompt,
			llm=self._llm,
			browser_session=self._session,
			max_failures=3,
			use_vision=True,
			keep_alive=True,  # 保持浏览器打开以便截图
		)

		# Track the last screenshot step to replace it
		last_screenshot_step: int | None = None

		async def on_step_end(agent_ref: Any) -> None:
			nonlocal last_screenshot_step
			try:
				url = await self._session.get_current_page_url()
				title = await self._session.get_current_page_title()
				recorder.record_step(
					TraceStepKind.MODEL_JUDGEMENT,
					f'Agent step: {title}',
					url=url,
					page_title=title,
				)

				# In PREPARE mode, take a screenshot at each step (replacing the previous one)
				if mode == ExecutionMode.PREPARE:
					try:
						screenshot_bytes = await self._session.take_screenshot()
						# Remove previous screenshot step if exists
						if last_screenshot_step is not None:
							recorder.trace.steps = [
								s for s in recorder.trace.steps
								if not (s.kind == TraceStepKind.SCREENSHOT and s.step_number == last_screenshot_step)
							]
						# Record new screenshot
						step = record_screenshot_bytes(
							recorder,
							'prepare 证据截图',
							screenshot_bytes,
						)
						last_screenshot_step = step.step_number
					except Exception as e:
						logger.debug('Failed to take screenshot: %s', e)

			except Exception:
				logger.warning('Failed to record agent step', exc_info=True)

		try:
			result = await agent.run(max_steps=max_steps, on_step_end=on_step_end)
			self.last_history = result

			await self._record_prepare_evidence_screenshot(mode, recorder)
			failure_message = _agent_failure_message(result)
			if failure_message:
				return recorder.fail(
					failure_type=FailureType.SUBMIT_FAILED,
					message=f'Agent 探索失败: {failure_message}',
				)
			return recorder.complete(f'Agent 探索完成: {result}')
		except Exception as exc:
			return recorder.fail(
				failure_type=FailureType.SUBMIT_FAILED,
				message=f'Agent 探索失败: {exc}',
			)

	async def _record_prepare_evidence_screenshot(
		self,
		mode: ExecutionMode,
		recorder: TraceRecorder,
	) -> None:
		"""在 prepare 模式下截图作为证据。"""
		if mode != ExecutionMode.PREPARE or trace_screenshot_paths(recorder.trace):
			return
		try:
			screenshot_bytes = await self._session.take_screenshot()
			record_screenshot_bytes(
				recorder,
				'prepare 证据截图',
				screenshot_bytes,
			)
			logger.info('Prepare evidence screenshot taken successfully')
		except Exception as e:
			logger.warning('Failed to take prepare evidence screenshot: %s', e)

	def _build_task_prompt(
		self,
		operation: OperationContract,
		params: dict[str, object],
		mode: ExecutionMode,
		entry_url: str | None = None,
	) -> str:
		params_text = ', '.join(f'{k}={v}' for k, v in params.items())
		criteria_text = '\n'.join(f'  - {c}' for c in operation.success_criteria)
		forbidden_text = '\n'.join(f'  - {f}' for f in operation.forbidden_actions)

		mode_instruction = ''
		if mode == ExecutionMode.DRY_RUN:
			mode_instruction = '\n注意: 这是 dry_run 模式，只探索路径和验证字段，不要修改真实数据。'
		elif mode == ExecutionMode.PREPARE:
			mode_instruction = '\n注意: 这是 prepare 模式，可以填写字段或上传图片，但停在最终提交前，不要点击保存/提交按钮。'
		elif mode == ExecutionMode.COMMIT:
			mode_instruction = '\n注意: 这是 commit 模式，完成操作并真实提交。'

		url_instruction = ''
		if entry_url:
			url_instruction = f'\n请先导航到以下页面: {entry_url}'

		return f"""你是一个后台操作助手。请完成以下操作:
{url_instruction}

操作: {operation.title}
参数: {params_text}

成功标准:
{criteria_text}

禁止行为:
{forbidden_text}
{mode_instruction}

请一步步操作，完成后报告结果。"""
