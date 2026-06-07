from pydantic import ValidationError

from merchant_automation.operations.schemas import ExecutionMode, JobPlan, OperationTask


def test_operation_task_represents_one_atomic_operation():
	task = OperationTask(
		platform='meituan',
		store_id='store-a',
		account_id='account-1',
		operation_id='update_store_phone',
		params={'phone': '13800138000'},
		mode=ExecutionMode.PREPARE,
		recipe_id='meituan.update_store_phone.v1',
	)

	assert task.platform == 'meituan'
	assert task.store_id == 'store-a'
	assert task.params == {'phone': '13800138000'}
	assert task.mode == ExecutionMode.PREPARE


def test_job_plan_groups_tasks_from_one_user_input():
	task = OperationTask(
		platform='meituan',
		store_id='store-a',
		operation_id='change_business_hours',
		params={'business_hours': '09:00-22:00'},
	)
	plan = JobPlan(source='feishu_text', raw_input='美团 A店 营业时间改为 09:00-22:00', tasks=[task])

	assert plan.source == 'feishu_text'
	assert plan.tasks == [task]


def test_operation_task_rejects_unknown_fields():
	try:
		OperationTask(
			platform='meituan',
			store_id='store-a',
			operation_id='update_store_phone',
			params={'phone': '13800138000'},
			unknown='value',
		)
	except ValidationError as exc:
		assert 'Extra inputs are not permitted' in str(exc)
	else:
		raise AssertionError('expected ValidationError')
