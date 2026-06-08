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
from merchant_automation.operations.recipe_store import RecipeStore
from merchant_automation.operations.schemas import ExecutionMode, FailureType, RecipeMetadata, RecipeStatus
from merchant_automation.operations.storage import OperationStore
from merchant_automation.operations.traces import ExecutionTrace, TraceOutcomeStatus, TraceRecorder

logger = logging.getLogger(__name__)

# Statuses that are considered "promoted" — auto-synthesis must not overwrite them.
_PROMOTED_STATUSES = {RecipeStatus.PREPARE_READY, RecipeStatus.COMMIT_READY}


class ExecutionRouter:
	"""统一执行入口: 根据 Recipe 状态选择执行策略。"""

	def __init__(
		self,
		browser_session: BrowserSession,
		llm: BaseChatModel | None = None,
		store: OperationStore | None = None,
		recipe_definitions: dict[str, RecipeDefinition] | None = None,
		recipe_store: RecipeStore | None = None,
	) -> None:
		self._session = browser_session
		self._llm = llm
		self._store = store
		self._recipe_defs = recipe_definitions or {}
		self._recipe_store = recipe_store
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
			trace = await self._explorer.explore(
				operation,
				bound_task.task.params,
				recorder,
				mode=bound_task.task.mode,
				max_steps=max_steps,
			)

			# 飞轮闭环: 成功探索后自动合成 candidate Recipe
			if trace.outcome and trace.outcome.status == TraceOutcomeStatus.SUCCESS:
				self._maybe_synthesize_recipe(bound_task)

			return trace

		# 层 3: 无可用执行器
		return recorder.fail(
			failure_type=FailureType.SUBMIT_FAILED,
			message='无可用执行器: Recipe 无步骤且 Agent 未配置',
		)

	def _maybe_synthesize_recipe(self, bound_task: BoundOperationTask) -> None:
		"""After successful agent exploration, synthesize and save a candidate RecipeDefinition.

		Only synthesizes when:
		- recipe_store is configured
		- recipe has no existing definition OR existing metadata is still 'candidate'
		- recipe metadata is NOT promoted (prepare_ready or above)
		"""
		if self._recipe_store is None or self._explorer is None:
			return

		recipe_id = bound_task.recipe.recipe_id

		# Check if already promoted — do not overwrite
		existing_recipe = self._recipe_store.get_recipe(recipe_id)
		if existing_recipe and existing_recipe.status in _PROMOTED_STATUSES:
			logger.info('Skipping synthesis for promoted recipe %s (status=%s)', recipe_id, existing_recipe.status)
			return

		# Check if definition already exists and is not candidate
		existing_def = self._recipe_store.get_definition(recipe_id)
		if existing_def and existing_recipe and existing_recipe.status != RecipeStatus.CANDIDATE:
			logger.info('Skipping synthesis: recipe %s has non-candidate status', recipe_id)
			return

		# Synthesize from agent history
		history = self._explorer.last_history
		if history is None:
			logger.warning('No agent history available for synthesis')
			return

		try:
			from merchant_automation.operations.synthesizer import synthesize_recipe_definition

			defn = synthesize_recipe_definition(
				history,
				recipe_id=recipe_id,
				params=bound_task.task.params,
			)
			self._recipe_store.save_definition(defn, source='auto')
			logger.info('Synthesized candidate recipe definition for %s (%d steps)', recipe_id, len(defn.steps))

			# Ensure metadata exists as candidate
			if existing_recipe is None:
				self._recipe_store.upsert_recipe(
					RecipeMetadata(
						recipe_id=recipe_id,
						operation_id=bound_task.recipe.operation_id,
						platform=bound_task.recipe.platform,
						version=bound_task.recipe.version,
						status=RecipeStatus.CANDIDATE,
					)
				)
		except Exception:
			logger.warning('Failed to synthesize recipe definition for %s', recipe_id, exc_info=True)

	def _count_recent_failures(self, recipe_id: str) -> int:
		if self._store is None:
			return 0
		traces = self._store.list_traces()
		return sum(
			1 for t in traces
			if t.recipe_id == recipe_id and t.outcome_status == TraceOutcomeStatus.FAILED
		)

