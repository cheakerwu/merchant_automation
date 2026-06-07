from merchant_automation.operations.catalog import OperationCatalog
from merchant_automation.operations.preflight import CommitPolicy, evaluate_preflight
from merchant_automation.operations.schemas import ExecutionMode, RecipeMetadata, RecipeStatus


def _recipe(status=RecipeStatus.COMMIT_READY, rate=0.96):
	return RecipeMetadata(
		recipe_id='meituan.update_store_phone.v1',
		operation_id='update_store_phone',
		platform='meituan',
		version=1,
		status=status,
		allowed_modes={
			ExecutionMode.PARSE_ONLY,
			ExecutionMode.DRY_RUN,
			ExecutionMode.PREPARE,
			ExecutionMode.COMMIT,
		},
		success_rates={ExecutionMode.COMMIT: rate, ExecutionMode.PREPARE: 0.98},
	)


def test_commit_allowed_when_all_layers_pass():
	operation = OperationCatalog.default().get('update_store_phone')
	result = evaluate_preflight(
		operation=operation,
		recipe=_recipe(),
		requested_mode=ExecutionMode.COMMIT,
		policy=CommitPolicy(
			global_commit_enabled=True,
			account_commit_allowed=True,
			store_commit_allowed=True,
			min_recent_success_rate=0.95,
		),
	)

	assert result.allowed is True
	assert result.effective_mode == ExecutionMode.COMMIT
	assert result.reasons == []


def test_commit_downgrades_to_prepare_when_global_switch_is_off():
	operation = OperationCatalog.default().get('update_store_phone')
	result = evaluate_preflight(
		operation=operation,
		recipe=_recipe(),
		requested_mode=ExecutionMode.COMMIT,
		policy=CommitPolicy(global_commit_enabled=False),
	)

	assert result.allowed is True
	assert result.effective_mode == ExecutionMode.PREPARE
	assert 'global_commit_disabled' in result.reasons


def test_commit_downgrades_when_operation_disallows_commit():
	operation = OperationCatalog.default().get('replace_product_image')
	recipe = _recipe()
	recipe.operation_id = operation.operation_id
	result = evaluate_preflight(
		operation=operation,
		recipe=recipe,
		requested_mode=ExecutionMode.COMMIT,
		policy=CommitPolicy(global_commit_enabled=True, account_commit_allowed=True, store_commit_allowed=True),
	)

	assert result.allowed is True
	assert result.effective_mode == ExecutionMode.PREPARE
	assert 'operation_commit_not_allowed' in result.reasons


def test_disabled_recipe_blocks_execution():
	operation = OperationCatalog.default().get('update_store_phone')
	result = evaluate_preflight(
		operation=operation,
		recipe=_recipe(status=RecipeStatus.DISABLED),
		requested_mode=ExecutionMode.PREPARE,
		policy=CommitPolicy(),
	)

	assert result.allowed is False
	assert result.failure_type == 'preflight_failed'
	assert 'recipe_disabled' in result.reasons
