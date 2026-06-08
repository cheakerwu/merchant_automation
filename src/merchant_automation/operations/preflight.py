from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from merchant_automation.operations.schemas import (
	ExecutionMode,
	FailureType,
	OperationContract,
	RecipeMetadata,
	RecipeStatus,
)


class CommitPolicy(BaseModel):
	model_config = ConfigDict(extra='forbid')

	global_commit_enabled: bool = False
	account_commit_allowed: bool = False
	store_commit_allowed: bool = False
	min_recent_success_rate: float = Field(default=0.95, ge=0, le=1)


class PreflightResult(BaseModel):
	model_config = ConfigDict(extra='forbid')

	allowed: bool
	requested_mode: ExecutionMode
	effective_mode: ExecutionMode | None = None
	reasons: list[str] = Field(default_factory=list)
	failure_type: FailureType | None = None


def evaluate_preflight(
	*,
	operation: OperationContract,
	recipe: RecipeMetadata,
	requested_mode: ExecutionMode,
	policy: CommitPolicy,
	confirmed: bool = False,
) -> PreflightResult:
	if recipe.status == RecipeStatus.DISABLED:
		return PreflightResult(
			allowed=False,
			requested_mode=requested_mode,
			reasons=['recipe_disabled'],
			failure_type=FailureType.PREFLIGHT_FAILED,
		)

	if requested_mode not in recipe.allowed_modes:
		return PreflightResult(
			allowed=False,
			requested_mode=requested_mode,
			reasons=['mode_not_allowed_by_recipe'],
			failure_type=FailureType.PREFLIGHT_FAILED,
		)

	if requested_mode != ExecutionMode.COMMIT:
		return PreflightResult(allowed=True, requested_mode=requested_mode, effective_mode=requested_mode)

	# 高风险操作需要二次确认
	if operation.risk_level == 'high' and not confirmed:
		return PreflightResult(
			allowed=True,
			requested_mode=requested_mode,
			effective_mode=ExecutionMode.PREPARE,
			reasons=['high_risk_operation_requires_confirmation'],
		)

	reasons: list[str] = []
	if not policy.global_commit_enabled:
		reasons.append('global_commit_disabled')
	if not operation.allow_commit:
		reasons.append('operation_commit_not_allowed')
	if recipe.status != RecipeStatus.COMMIT_READY:
		reasons.append('recipe_not_commit_ready')
	if not policy.account_commit_allowed:
		reasons.append('account_commit_disabled')
	if not policy.store_commit_allowed:
		reasons.append('store_commit_disabled')
	if recipe.success_rates.get(ExecutionMode.COMMIT, 0) < policy.min_recent_success_rate:
		reasons.append('recipe_success_rate_below_threshold')

	if reasons:
		if ExecutionMode.PREPARE in recipe.allowed_modes:
			return PreflightResult(
				allowed=True,
				requested_mode=requested_mode,
				effective_mode=ExecutionMode.PREPARE,
				reasons=reasons,
			)
		return PreflightResult(
			allowed=False,
			requested_mode=requested_mode,
			reasons=[*reasons, 'prepare_mode_not_available'],
			failure_type=FailureType.PREFLIGHT_FAILED,
		)

	return PreflightResult(allowed=True, requested_mode=requested_mode, effective_mode=ExecutionMode.COMMIT)

