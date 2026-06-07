from pathlib import Path

from merchant_automation.operations.failure import FailureAnalyzer
from merchant_automation.operations.schemas import ExecutionMode, FailureType
from merchant_automation.operations.storage import OperationStore
from merchant_automation.operations.traces import (
	ExecutionTrace,
	TraceOutcome,
	TraceOutcomeStatus,
	TraceStep,
	TraceStepKind,
)


def _failed_trace() -> ExecutionTrace:
	return ExecutionTrace(
		platform='meituan',
		store_id='A店',
		operation_id='update_store_phone',
		recipe_id='meituan.update_store_phone.v1',
		mode=ExecutionMode.PREPARE,
		params={'phone': '13800138000'},
		steps=[
			TraceStep(step_number=1, kind=TraceStepKind.PAGE, message='打开设置页'),
			TraceStep(step_number=2, kind=TraceStepKind.ACTION, message='点击保存'),
		],
		outcome=TraceOutcome(
			status=TraceOutcomeStatus.FAILED,
			message='保存按钮找不到',
			failure_type=FailureType.SUBMIT_FAILED,
			failed_step_number=2,
		),
	)


def test_trace_round_trips(tmp_path: Path):
	store = OperationStore(tmp_path / 'merchant.db')
	store.initialize()
	trace = _failed_trace()

	trace_id = store.save_trace(trace, run_id='run-1')
	loaded = store.get_trace(trace_id)

	assert loaded is not None
	assert loaded.operation_id == 'update_store_phone'
	assert loaded.outcome is not None
	assert loaded.outcome.failure_type == FailureType.SUBMIT_FAILED
	assert loaded.steps[1].message == '点击保存'


def test_list_traces_filters_by_operation(tmp_path: Path):
	store = OperationStore(tmp_path / 'merchant.db')
	store.initialize()
	first_id = store.save_trace(_failed_trace(), run_id='run-1')
	store.save_trace(
		ExecutionTrace(
			platform='meituan',
			store_id='B店',
			operation_id='change_business_hours',
			recipe_id='meituan.change_business_hours.v1',
			mode=ExecutionMode.PREPARE,
			outcome=TraceOutcome(status=TraceOutcomeStatus.SUCCESS, message='ok'),
		),
		run_id='run-2',
	)

	summaries = store.list_traces(operation_id='update_store_phone')

	assert len(summaries) == 1
	assert summaries[0].trace_id == first_id
	assert summaries[0].outcome_status == TraceOutcomeStatus.FAILED
	assert summaries[0].failure_type == FailureType.SUBMIT_FAILED


def test_failure_analysis_round_trips(tmp_path: Path):
	store = OperationStore(tmp_path / 'merchant.db')
	store.initialize()
	trace = _failed_trace()
	trace_id = store.save_trace(trace)
	analysis = FailureAnalyzer().analyze(trace, similar_recent_failures=3)

	analysis_id = store.save_failure_analysis(analysis, trace_id=trace_id)
	loaded = store.get_failure_analysis(analysis_id)

	assert loaded is not None
	assert loaded.failure_type == FailureType.SUBMIT_FAILED
	assert loaded.suspected_recipe_stale is True


def test_list_failure_analyses_returns_dashboard_summary(tmp_path: Path):
	store = OperationStore(tmp_path / 'merchant.db')
	store.initialize()
	trace = _failed_trace()
	trace_id = store.save_trace(trace)
	analysis = FailureAnalyzer().analyze(trace, similar_recent_failures=3)
	analysis_id = store.save_failure_analysis(analysis, trace_id=trace_id)

	summaries = store.list_failure_analyses()

	assert len(summaries) == 1
	assert summaries[0].analysis_id == analysis_id
	assert summaries[0].trace_id == trace_id
	assert summaries[0].retryable is True
	assert summaries[0].suspected_recipe_stale is True
