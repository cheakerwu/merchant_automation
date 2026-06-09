from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from merchant_automation.operations.catalog import OperationCatalog
from merchant_automation.operations.parser import PLATFORM_ALIASES, derive_business_hours_params
from merchant_automation.operations.schemas import ExecutionMode, JobPlan, OperationTask


class PlanIssue(BaseModel):
	model_config = ConfigDict(extra='forbid')

	row_number: int
	reason: str
	raw_row: dict[str, object]


class JobPlanResult(BaseModel):
	model_config = ConfigDict(extra='forbid')

	plan: JobPlan
	issues: list[PlanIssue] = Field(default_factory=list)


class JobPlanner:
	def __init__(self, catalog: OperationCatalog | None = None) -> None:
		self._catalog = catalog or OperationCatalog.default()

	def plan_table_rows(self, rows: list[dict[str, object]], *, source: str = 'table') -> JobPlanResult:
		tasks: list[OperationTask] = []
		issues: list[PlanIssue] = []

		for index, row in enumerate(rows, start=1):
			try:
				tasks.append(self._task_from_row(row))
			except ValueError as exc:
				issues.append(PlanIssue(row_number=index, reason=str(exc), raw_row=row))

		return JobPlanResult(plan=JobPlan(source=source, tasks=tasks), issues=issues)

	def _task_from_row(self, row: dict[str, object]) -> OperationTask:
		operation_id = _string_value(row, 'operation_id', 'operation', '操作')
		if operation_id is None:
			raise ValueError('missing_required_field: operation')

		try:
			operation = self._catalog.get(operation_id)
		except KeyError as exc:
			raise ValueError(f'unsupported_operation: {operation_id}') from exc

		platform = _resolve_platform(_string_value(row, 'platform', '平台'))
		if platform is None:
			raise ValueError('missing_required_field: platform')

		store_id = _string_value(row, 'store_id', 'store', '门店', '店铺')
		if store_id is None:
			raise ValueError('missing_required_field: store_id')

		params: dict[str, object] = {}
		for param_name in operation.required_params:
			if param_name == 'store_id':
				continue
			value = _param_value(row, param_name)
			if value is None:
				raise ValueError(f'missing_required_param: {param_name}')
			params[param_name] = value
		params = _derive_operation_params(operation_id, params)

		return OperationTask(
			platform=platform,
			store_id=store_id,
			account_id=_string_value(row, 'account_id', '账号', '平台账号'),
			operation_id=operation_id,
			params=params,
			mode=_execution_mode(row),
		)


def _derive_operation_params(operation_id: str, params: dict[str, object]) -> dict[str, object]:
	if operation_id == 'change_business_hours' and 'business_hours' in params:
		return {
			**params,
			**derive_business_hours_params(str(params['business_hours'])),
		}
	return params


def _string_value(row: dict[str, object], *keys: str) -> str | None:
	for key in keys:
		value = row.get(key)
		if value is not None and str(value).strip():
			return str(value).strip()
	return None


def _param_value(row: dict[str, object], param_name: str) -> object | None:
	aliases = {
		'phone': ('phone', '电话', '联系电话', '新电话'),
		'business_hours': ('business_hours', '营业时间', 'hours'),
		'product_id': ('product_id', '商品ID', '商品id', '商品'),
		'attachment_id': ('attachment_id', '附件ID', '附件id', '图片', '图片ID', '图片id'),
	}
	for key in aliases.get(param_name, (param_name,)):
		value = row.get(key)
		if value is not None and str(value).strip():
			return str(value).strip()
	return None


def _resolve_platform(value: str | None) -> str | None:
	if value is None:
		return None
	return PLATFORM_ALIASES.get(value.lower()) or PLATFORM_ALIASES.get(value)


def _execution_mode(row: dict[str, object]) -> ExecutionMode:
	mode = _string_value(row, 'mode', '执行模式')
	if mode is None:
		return ExecutionMode.PARSE_ONLY
	return ExecutionMode(mode)
