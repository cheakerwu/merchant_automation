"""Unified execution entry point — routes to RecipeStepExecutor or AgentExplorer based on recipe state."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from browser_use import BrowserSession
from langchain_core.language_models.chat_models import BaseChatModel

from merchant_automation.operations.binder import BoundOperationTask
from merchant_automation.operations.catalog import OperationCatalog
from merchant_automation.operations.executor import RecipeStepExecutor, StepExecutionError
from merchant_automation.operations.explorer import AgentExplorer
from merchant_automation.operations.recipe_definition import RecipeDefinition
from merchant_automation.operations.recipe_definitions import merge_recipe_definitions
from merchant_automation.operations.recipe_store import RecipeStore
from merchant_automation.operations.schemas import ExecutionMode, FailureType, RecipeMetadata, RecipeStatus
from merchant_automation.operations.storage import OperationStore
from merchant_automation.operations.traces import ExecutionTrace, TraceOutcomeStatus, TraceRecorder

logger = logging.getLogger(__name__)

# Time window for counting recent failures (hours).
# Failures older than this are ignored, allowing newly synthesized recipes to proceed.
RECENT_FAILURE_WINDOW_HOURS = 24

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
		_validate_synthesized: bool = False,
	) -> None:
		self._session = browser_session
		self._llm = llm
		self._store = store
		self._recipe_defs = merge_recipe_definitions(recipe_definitions)
		self._recipe_store = recipe_store
		self._validate_synthesized = _validate_synthesized
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

			# Validate synthesized recipe before saving (if enabled)
			if self._validate_synthesized:
				if not self._validate_definition(defn, bound_task):
					logger.warning('Synthesized recipe validation failed for %s, skipping save', recipe_id)
					return

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

	def _validate_definition(self, defn: RecipeDefinition, bound_task: BoundOperationTask) -> bool:
		"""Validate synthesized recipe by dry-run execution.

		Returns True if validation passes, False otherwise.
		"""
		try:
			# Create a dry-run recorder (no persistence)
			from merchant_automation.operations.traces import TraceRecorder
			recorder = TraceRecorder.start(bound_task, raw_input='validation')

			# Execute in DRY_RUN mode to validate steps
			trace = self._step_executor.execute_sync(
				defn,
				bound_task.task.params,
				recorder,
				mode=ExecutionMode.DRY_RUN,
			)

			# Check if execution succeeded
			if trace.outcome and trace.outcome.status == TraceOutcomeStatus.SUCCESS:
				logger.info('Recipe validation passed for %s', defn.recipe_id)
				return True
			else:
				logger.warning('Recipe validation failed for %s: %s', defn.recipe_id, trace.outcome)
				return False
		except Exception as exc:
			logger.warning('Recipe validation error for %s: %s', defn.recipe_id, exc)
			return False

	def _count_recent_failures(self, recipe_id: str) -> int:
		"""Count failures within the configured time window.

		Only failures from the last RECENT_FAILURE_WINDOW_HOURS are counted.
		This prevents old failures from permanently blocking newly synthesized recipes.
		"""
		if self._store is None:
			return 0

		cutoff = datetime.now(timezone.utc) - timedelta(hours=RECENT_FAILURE_WINDOW_HOURS)
		traces = self._store.list_traces()

		count = 0
		for t in traces:
			if t.recipe_id != recipe_id or t.outcome_status != TraceOutcomeStatus.FAILED:
				continue
			try:
				trace_time = datetime.fromisoformat(t.created_at)
				if trace_time.tzinfo is None:
					trace_time = trace_time.replace(tzinfo=timezone.utc)
				if trace_time >= cutoff:
					count += 1
			except (ValueError, TypeError):
				# If we can't parse the time, count it as recent to be safe
				count += 1
		return count
