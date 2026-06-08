from merchant_automation.operations.preflight import CommitPolicy
from merchant_automation.operations.service import OperationPlanningService
from merchant_automation.operations.schemas import ExecutionMode


def test_plan_text_returns_bound_task_with_recipe_and_effective_mode():
	result = OperationPlanningService().plan_text(
		'把美团 A店 电话改成 13800138000',
		mode=ExecutionMode.PREPARE,
		policy=CommitPolicy(),
	)

	assert result.input_issues == []
	assert result.plan_issues == []
	assert result.binding_issues == []
	assert len(result.bound_tasks) == 1
	assert result.bound_tasks[0].task.operation_id == 'update_store_phone'
	assert result.bound_tasks[0].task.recipe_id == 'meituan.update_store_phone.v1'
	assert result.bound_tasks[0].task.mode == ExecutionMode.PREPARE


def test_plan_text_returns_parse_issue_without_raising():
	result = OperationPlanningService().plan_text('把美团 A店 牛肉饭价格改成 19.9')

	assert result.plan.tasks == []
	assert result.bound_tasks == []
	assert len(result.input_issues) == 1
	assert result.input_issues[0].reason == 'Unsupported operation text: 把美团 A店 牛肉饭价格改成 19.9'


def test_plan_table_rows_preserves_plan_and_binding_issues():
	result = OperationPlanningService().plan_table_rows(
		[
			{'platform': 'meituan', 'store_id': 'A店', 'operation': 'update_store_phone'},
			{'platform': 'eleme', 'store_id': 'B店', 'operation': 'update_store_phone', 'phone': '13900139000'},
			{'platform': 'meituan', 'store_id': 'C店', 'operation': 'update_store_phone', 'phone': '13700137000'},
		],
		policy=CommitPolicy(),
	)

	assert len(result.bound_tasks) == 1
	assert result.bound_tasks[0].task.store_id == 'C店'
	assert len(result.plan_issues) == 1
	assert result.plan_issues[0].reason == 'missing_required_param: phone'
	assert len(result.binding_issues) == 1
	assert result.binding_issues[0].reason == 'recipe_not_found: No recipe for eleme/update_store_phone'
