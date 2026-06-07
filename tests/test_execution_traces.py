from merchant_automation.operations.binder import BoundOperationTask
from merchant_automation.operations.preflight import PreflightResult
from merchant_automation.operations.schemas import (
	ExecutionMode,
	FailureType,
	OperationTask,
	RecipeMetadata,
	RecipeStatus,
)
from merchant_automation.operations.traces import TraceOutcomeStatus, TraceRecorder, TraceStepKind


def _bound_task() -> BoundOperationTask:
	task = OperationTask(
		platform='meituan',
		store_id='A店',
		operation_id='update_store_phone',
		params={'phone': '13800138000'},
		mode=ExecutionMode.PREPARE,
		recipe_id='meituan.update_store_phone.v1',
	)
	recipe = RecipeMetadata(
		recipe_id='meituan.update_store_phone.v1',
		operation_id='update_store_phone',
		platform='meituan',
		version=1,
		status=RecipeStatus.PREPARE_READY,
		allowed_modes={ExecutionMode.PREPARE},
	)
	preflight = PreflightResult(allowed=True, requested_mode=ExecutionMode.PREPARE, effective_mode=ExecutionMode.PREPARE)
	return BoundOperationTask(task=task, recipe=recipe, preflight=preflight)


def test_trace_starts_from_bound_task():
	recorder = TraceRecorder.start(_bound_task(), raw_input='把美团 A店 电话改成 13800138000')
	trace = recorder.trace

	assert trace.platform == 'meituan'
	assert trace.store_id == 'A店'
	assert trace.operation_id == 'update_store_phone'
	assert trace.recipe_id == 'meituan.update_store_phone.v1'
	assert trace.mode == ExecutionMode.PREPARE
	assert trace.params == {'phone': '13800138000'}
	assert trace.raw_input == '把美团 A店 电话改成 13800138000'


def test_trace_records_ordered_steps():
	recorder = TraceRecorder.start(_bound_task())

	recorder.record_step(TraceStepKind.PAGE, '打开门店设置页', url='https://e.waimai.meituan.com/store')
	recorder.record_step(TraceStepKind.ACTION, '填写联系电话', target='phone-input')
	recorder.record_step(TraceStepKind.SCREENSHOT, '提交前截图', screenshot_path='screenshots/1.png')

	assert [step.step_number for step in recorder.trace.steps] == [1, 2, 3]
	assert recorder.trace.steps[0].url == 'https://e.waimai.meituan.com/store'
	assert recorder.trace.steps[1].target == 'phone-input'
	assert recorder.trace.steps[2].screenshot_path == 'screenshots/1.png'


def test_trace_complete_stores_success_outcome():
	recorder = TraceRecorder.start(_bound_task())
	recorder.record_step(TraceStepKind.ACTION, '停在最终提交前')

	trace = recorder.complete('prepare 完成，等待人工确认')

	assert trace.outcome is not None
	assert trace.outcome.status == TraceOutcomeStatus.SUCCESS
	assert trace.outcome.message == 'prepare 完成，等待人工确认'


def test_trace_fail_stores_failure_details():
	recorder = TraceRecorder.start(_bound_task())
	recorder.record_step(TraceStepKind.ACTION, '点击保存')

	trace = recorder.fail(
		failure_type=FailureType.VALIDATION_FAILED,
		message='保存后重新读取电话不一致',
		failed_step_number=1,
	)

	assert trace.outcome is not None
	assert trace.outcome.status == TraceOutcomeStatus.FAILED
	assert trace.outcome.failure_type == FailureType.VALIDATION_FAILED
	assert trace.outcome.failed_step_number == 1
	assert trace.outcome.message == '保存后重新读取电话不一致'
