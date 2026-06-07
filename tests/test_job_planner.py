from merchant_automation.operations.planner import JobPlanner
from merchant_automation.operations.schemas import ExecutionMode


def test_table_rows_become_operation_tasks():
	result = JobPlanner().plan_table_rows(
		[
			{
				'platform': 'meituan',
				'store_id': 'A店',
				'account_id': 'account-a',
				'operation': 'update_store_phone',
				'phone': '13800138000',
				'mode': 'prepare',
			},
			{
				'平台': '美团',
				'门店': 'B店',
				'操作': 'change_business_hours',
				'营业时间': '09:00-22:00',
			},
		],
		source='table_upload',
	)

	assert len(result.plan.tasks) == 2
	assert result.plan.source == 'table_upload'
	assert result.issues == []
	assert result.plan.tasks[0].operation_id == 'update_store_phone'
	assert result.plan.tasks[0].mode == ExecutionMode.PREPARE
	assert result.plan.tasks[0].params == {'phone': '13800138000'}
	assert result.plan.tasks[1].store_id == 'B店'
	assert result.plan.tasks[1].params == {'business_hours': '09:00-22:00'}


def test_row_failure_does_not_stop_batch():
	result = JobPlanner().plan_table_rows(
		[
			{'platform': 'meituan', 'store_id': 'A店', 'operation': 'update_store_phone'},
			{'platform': 'meituan', 'store_id': 'B店', 'operation': 'update_store_phone', 'phone': '13900139000'},
		]
	)

	assert len(result.plan.tasks) == 1
	assert result.plan.tasks[0].store_id == 'B店'
	assert len(result.issues) == 1
	assert result.issues[0].row_number == 1
	assert result.issues[0].reason == 'missing_required_param: phone'


def test_unknown_operation_is_reported_as_issue():
	result = JobPlanner().plan_table_rows(
		[
			{'platform': 'meituan', 'store_id': 'A店', 'operation': 'change_product_price', 'price': 19.9},
		]
	)

	assert result.plan.tasks == []
	assert len(result.issues) == 1
	assert result.issues[0].reason == 'unsupported_operation: change_product_price'
