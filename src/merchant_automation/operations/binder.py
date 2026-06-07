from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from merchant_automation.operations.catalog import OperationCatalog
from merchant_automation.operations.preflight import CommitPolicy, PreflightResult, evaluate_preflight
from merchant_automation.operations.recipes import RecipeLookupError, RecipeRegistry
from merchant_automation.operations.schemas import JobPlan, OperationTask, RecipeMetadata


class BoundOperationTask(BaseModel):
	model_config = ConfigDict(extra='forbid')

	task: OperationTask
	recipe: RecipeMetadata
	preflight: PreflightResult


class BindingIssue(BaseModel):
	model_config = ConfigDict(extra='forbid')

	task_index: int
	reason: str
	task: OperationTask


class JobBindingResult(BaseModel):
	model_config = ConfigDict(extra='forbid')

	bound_tasks: list[BoundOperationTask] = Field(default_factory=list)
	issues: list[BindingIssue] = Field(default_factory=list)


class JobPlanBinder:
	def __init__(self, *, registry: RecipeRegistry | None = None, catalog: OperationCatalog | None = None) -> None:
		self._registry = registry or RecipeRegistry.default()
		self._catalog = catalog or OperationCatalog.default()

	def bind(self, plan: JobPlan, *, policy: CommitPolicy) -> JobBindingResult:
		bound_tasks: list[BoundOperationTask] = []
		issues: list[BindingIssue] = []

		for index, task in enumerate(plan.tasks):
			try:
				bound_tasks.append(self._bind_task(task, policy=policy))
			except RecipeLookupError as exc:
				issues.append(BindingIssue(task_index=index, reason=f'recipe_not_found: {exc}', task=task))
			except ValueError as exc:
				issues.append(BindingIssue(task_index=index, reason=str(exc), task=task))

		return JobBindingResult(bound_tasks=bound_tasks, issues=issues)

	def _bind_task(self, task: OperationTask, *, policy: CommitPolicy) -> BoundOperationTask:
		recipe = self._registry.select(platform=task.platform, operation_id=task.operation_id)
		try:
			operation = self._catalog.get(task.operation_id)
		except KeyError as exc:
			raise ValueError(f'unsupported_operation: {task.operation_id}') from exc

		preflight = evaluate_preflight(
			operation=operation,
			recipe=recipe,
			requested_mode=task.mode,
			policy=policy,
		)
		if not preflight.allowed:
			reason = ','.join(preflight.reasons)
			raise ValueError(f'preflight_failed: {reason}')

		bound_task = task.model_copy(update={'recipe_id': recipe.recipe_id, 'mode': preflight.effective_mode})
		return BoundOperationTask(task=bound_task, recipe=recipe, preflight=preflight)

