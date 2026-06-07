"""Unified execution entry point — routes to RecipeStepExecutor or AgentExplorer based on recipe state."""
from __future__ import annotations

import logging

from browser_use import BrowserSession
from langchain_core.language_models.chat_models import BaseChatModel

from merchant_automation.operations.binder import BoundOperationTask
from merchant_automation.operations.catalog import OperationCatalog
from merchant_automation.operations.executor import RecipeStepExecutor, StepExecutionError
from merchant_automation.operations.explorer import AgentExplorer
from merchant_automation.operations.recipe_definition import RecipeDefinition
from merchant_automation.operations.schemas import ExecutionMode, FailureType
from merchant_automation.operations.storage import OperationStore
from merchant_automation.operations.traces import ExecutionTrace, TraceOutcomeStatus, TraceRecorder

logger = logging.getLogger(__name__)


class ExecutionRouter:
	"""统一执行入口: 根据 Recipe 状态选择执行策略。"""

	def __init__(
		self,
		browser_session: BrowserSession,
		llm: BaseChatModel | None = None,
		store: OperationStore | None = None,
		recipe_definitions: dict[str, RecipeDefinition] | None = None,
	) -> None:
		self._session = browser_session
		self._llm = llm
		self._store = store
		self._recipe_defs = recipe_definitions or {}
		self._step_executor = RecipeStepExecutor(browser_session, llm)
		self._explorer = AgentExplorer(browser_session, llm) if llm else None

	async def execute(
		self,
		bound_task: BoundOperationTask,
		raw_input: str | None = None,
		max_steps: int = 30,
	) -> ExecutionTrace:
		recorder = TraceRecorder.start(bound_task, raw_input=raw_input)

		# parse_only: 只解析不执行
		if bound_task.task.mode == ExecutionMode.PARSE_ONLY:
			return recorder.complete('仅解析，未执行')

		recipe = bound_task.recipe
		recipe_def = self._recipe_defs.get(recipe.recipe_id)
		recent_failures = self._count_recent_failures(recipe.recipe_id)

		# 层 1: Recipe 有步骤 + 最近没失败 → 按步骤执行
		if recipe_def and recipe_def.steps and recent_failures == 0:
			try:
				return await self._step_executor.execute(
					recipe_def,
					bound_task.task.params,
					recorder,
					mode=bound_task.task.mode,
				)
			except StepExecutionError as exc:
				logger.warning('Recipe step execution failed: %s', exc)
				# 步骤执行失败，降级到层 2

		# 层 2: Agent 探索
		if self._explorer:
			catalog = OperationCatalog.default()
			try:
				operation = catalog.get(bound_task.task.operation_id)
			except KeyError:
				return recorder.fail(
					failure_type=FailureType.SUBMIT_FAILED,
					message=f'未知操作: {bound_task.task.operation_id}',
				)
			return await self._explorer.explore(
				operation,
				bound_task.task.params,
				recorder,
				mode=bound_task.task.mode,
				max_steps=max_steps,
			)

		# 层 3: 无可用执行器
		return recorder.fail(
			failure_type=FailureType.SUBMIT_FAILED,
			message='无可用执行器: Recipe 无步骤且 Agent 未配置',
		)

	def _count_recent_failures(self, recipe_id: str) -> int:
		if self._store is None:
			return 0
		traces = self._store.list_traces()
		return sum(
			1 for t in traces
			if t.recipe_id == recipe_id and t.outcome_status == TraceOutcomeStatus.FAILED
		)

