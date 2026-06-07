from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from merchant_automation.operations.binder import BindingIssue, BoundOperationTask, JobPlanBinder
from merchant_automation.operations.parser import OperationParseError, OperationParser
from merchant_automation.operations.planner import JobPlanner, PlanIssue
from merchant_automation.operations.preflight import CommitPolicy
from merchant_automation.operations.schemas import ExecutionMode, JobPlan


class PlanningInputIssue(BaseModel):
	model_config = ConfigDict(extra='forbid')

	source: str
	reason: str
	raw_input: str | None = None


class OperationPlanningResult(BaseModel):
	model_config = ConfigDict(extra='forbid')

	plan: JobPlan
	bound_tasks: list[BoundOperationTask] = Field(default_factory=list)
	input_issues: list[PlanningInputIssue] = Field(default_factory=list)
	plan_issues: list[PlanIssue] = Field(default_factory=list)
	binding_issues: list[BindingIssue] = Field(default_factory=list)


class OperationPlanningService:
	def __init__(
		self,
		*,
		parser: OperationParser | None = None,
		planner: JobPlanner | None = None,
		binder: JobPlanBinder | None = None,
	) -> None:
		self._parser = parser or OperationParser()
		self._planner = planner or JobPlanner()
		self._binder = binder or JobPlanBinder()

	def plan_text(
		self,
		text: str,
		*,
		mode: ExecutionMode = ExecutionMode.PARSE_ONLY,
		policy: CommitPolicy | None = None,
	) -> OperationPlanningResult:
		try:
			task = self._parser.parse_text(text, mode=mode)
		except OperationParseError as exc:
			return OperationPlanningResult(
				plan=JobPlan(source='text', raw_input=text),
				input_issues=[PlanningInputIssue(source='text', reason=str(exc), raw_input=text)],
			)

		plan = JobPlan(source='text', raw_input=text, tasks=[task])
		binding = self._binder.bind(plan, policy=policy or CommitPolicy())
		return OperationPlanningResult(
			plan=plan,
			bound_tasks=binding.bound_tasks,
			binding_issues=binding.issues,
		)

	def plan_table_rows(
		self,
		rows: list[dict[str, object]],
		*,
		source: str = 'table',
		policy: CommitPolicy | None = None,
	) -> OperationPlanningResult:
		planned = self._planner.plan_table_rows(rows, source=source)
		binding = self._binder.bind(planned.plan, policy=policy or CommitPolicy())
		return OperationPlanningResult(
			plan=planned.plan,
			bound_tasks=binding.bound_tasks,
			plan_issues=planned.issues,
			binding_issues=binding.issues,
		)

