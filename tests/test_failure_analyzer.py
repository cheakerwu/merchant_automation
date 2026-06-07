from merchant_automation.operations.failure import FailureAnalyzer
from merchant_automation.operations.schemas import ExecutionMode, FailureType
from merchant_automation.operations.traces import ExecutionTrace, TraceOutcome, TraceOutcomeStatus, TraceStep, TraceStepKind


def _failed_trace(failure_type: FailureType, message: str = '失败', failed_step_number: int = 2) -> ExecutionTrace:
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
			message=message,
			failure_type=failure_type,
			failed_step_number=failed_step_number,
		),
	)


def test_preflight_failure_is_not_retryable_or_recipe_stale():
	analysis = FailureAnalyzer().analyze(_failed_trace(FailureType.PREFLIGHT_FAILED, 'recipe disabled'))

	assert analysis.failure_type == FailureType.PREFLIGHT_FAILED
	assert analysis.user_reason == '执行前检查未通过：recipe disabled'
	assert analysis.retryable is False
	assert analysis.suspected_recipe_stale is False
	assert analysis.failed_step_number is None


def test_validation_failure_is_retryable_and_suggests_validation_review():
	analysis = FailureAnalyzer().analyze(_failed_trace(FailureType.VALIDATION_FAILED, '保存后重新读取电话不一致'))

	assert analysis.retryable is True
	assert analysis.failed_step_number == 2
	assert analysis.repair_suggestion == '检查结果校验条件或页面保存后的回读路径'


def test_repeated_submit_failures_mark_recipe_stale():
	analysis = FailureAnalyzer().analyze(
		_failed_trace(FailureType.SUBMIT_FAILED, '保存按钮找不到'),
		similar_recent_failures=3,
	)

	assert analysis.retryable is True
	assert analysis.suspected_recipe_stale is True
	assert analysis.repair_suggestion == '疑似后台页面变化，建议重新探索并生成 Recipe Candidate'


def test_unknown_commit_state_is_not_retryable():
	analysis = FailureAnalyzer().analyze(_failed_trace(FailureType.UNKNOWN_COMMIT_STATE, '提交状态无法确认'))

	assert analysis.retryable is False
	assert analysis.user_reason == '提交状态无法确认：提交状态无法确认'
