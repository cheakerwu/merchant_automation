from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from merchant_automation.operations.schemas import FailureType
from merchant_automation.operations.traces import ExecutionTrace, TraceOutcomeStatus

USER_FAILURE_MESSAGES = {
    "planning_failed": (
        "我还没理解这条指令。\n\n"
        "你可以试试这样说：\n"
        "- 把美团 <店铺名> 电话改成 13800138000\n"
        "- 把美团 <店铺名> 门店照片换成刚上传的图片\n"
        "- 把美团 <店铺名> 配送费改成 5 元\n"
        "- 把美团 <店铺名> 公告改成 欢迎光临\n\n"
        '也可以发送「帮助」查看所有支持的操作。'
    ),
    "no_tasks": (
        "未能生成可执行任务。\n\n"
        "可能原因：\n"
        "- 指令中缺少店铺名称\n"
        "- 该操作暂不支持\n"
        "- 格式不太对，请参考上面的示例重新发送\n\n"
        '发送「帮助」查看支持的操作列表。'
    ),
    "login_required": "账号需要重新登录。",
    "attachment_missing": "没有找到可用图片，请先上传图片。",
    "attachment_download_failed": "图片下载失败，请重新发送图片。",
    "recipe_execution_failed": "后台操作失败，请查看任务详情或稍后重试。",
    "execution_error": "任务执行异常，请稍后重试。",
}


def user_failure_message(error_type: str | None, fallback: str | None = None) -> str:
    if error_type and error_type in USER_FAILURE_MESSAGES:
        return USER_FAILURE_MESSAGES[error_type]
    return fallback or "任务执行失败，请稍后重试。"


class FailureAnalysis(BaseModel):
	model_config = ConfigDict(extra='forbid')

	failure_type: FailureType
	user_reason: str
	internal_reason: str
	failed_step_number: int | None = None
	retryable: bool
	suspected_recipe_stale: bool = False
	repair_suggestion: str


class FailureAnalyzer:
	def analyze(self, trace: ExecutionTrace, *, similar_recent_failures: int = 0) -> FailureAnalysis:
		if trace.outcome is None or trace.outcome.status != TraceOutcomeStatus.FAILED or trace.outcome.failure_type is None:
			raise ValueError('trace has no failed outcome to analyze')

		failure_type = trace.outcome.failure_type
		message = trace.outcome.message
		failed_step_number = trace.outcome.failed_step_number

		if failure_type == FailureType.PREFLIGHT_FAILED:
			return FailureAnalysis(
				failure_type=failure_type,
				user_reason=f'执行前检查未通过：{message}',
				internal_reason=f'preflight failed before recipe execution: {message}',
				failed_step_number=None,
				retryable=False,
				repair_suggestion='检查 commit 开关、Recipe 状态、账号或门店权限',
			)

		if failure_type == FailureType.UNKNOWN_COMMIT_STATE:
			return FailureAnalysis(
				failure_type=failure_type,
				user_reason=f'提交状态无法确认：{message}',
				internal_reason=f'commit outcome unknown for {trace.recipe_id}: {message}',
				failed_step_number=failed_step_number,
				retryable=False,
				repair_suggestion='不要自动重试；先人工核对后台真实状态',
			)

		if failure_type == FailureType.VALIDATION_FAILED:
			return FailureAnalysis(
				failure_type=failure_type,
				user_reason=f'结果校验未通过：{message}',
				internal_reason=f'validation failed after recipe execution: {message}',
				failed_step_number=failed_step_number,
				retryable=True,
				repair_suggestion='检查结果校验条件或页面保存后的回读路径',
			)

		suspected_recipe_stale = similar_recent_failures >= 3 and failure_type in {
			FailureType.SUBMIT_FAILED,
			FailureType.PARTIAL_SUCCESS,
		}
		return FailureAnalysis(
			failure_type=failure_type,
			user_reason=f'执行过程中失败：{message}',
			internal_reason=f'{failure_type.value} in {trace.recipe_id}: {message}',
			failed_step_number=failed_step_number,
			retryable=True,
			suspected_recipe_stale=suspected_recipe_stale,
			repair_suggestion=(
				'疑似后台页面变化，建议重新探索并生成 Recipe Candidate'
				if suspected_recipe_stale
				else '检查失败步骤截图和页面定位规则'
			),
		)

