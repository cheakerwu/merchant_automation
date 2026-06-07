from pydantic import ValidationError

from merchant_automation.operations.schemas import (
	ExecutionMode,
	FailureType,
	OperationContract,
	RecipeMetadata,
	RecipeStatus,
)


def test_operation_contract_requires_named_parameters():
	contract = OperationContract(
		operation_id='update_store_phone',
		title='修改门店联系电话',
		required_params=['store_id', 'phone'],
		success_criteria=['保存后重新读取电话等于目标值'],
		forbidden_actions=['不能修改其他门店信息'],
		allow_commit=True,
	)

	assert contract.operation_id == 'update_store_phone'
	assert contract.required_params == ['store_id', 'phone']
	assert contract.allow_commit is True


def test_recipe_metadata_tracks_platform_status_and_modes():
	recipe = RecipeMetadata(
		recipe_id='meituan.update_store_phone.v1',
		operation_id='update_store_phone',
		platform='meituan',
		version=1,
		status=RecipeStatus.PREPARE_READY,
		allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE},
		success_rates={ExecutionMode.PREPARE: 0.96},
	)

	assert ExecutionMode.PREPARE in recipe.allowed_modes
	assert recipe.success_rates[ExecutionMode.PREPARE] == 0.96


def test_invalid_recipe_success_rate_is_rejected():
	try:
		RecipeMetadata(
			recipe_id='meituan.update_store_phone.v1',
			operation_id='update_store_phone',
			platform='meituan',
			version=1,
			status=RecipeStatus.PREPARE_READY,
			success_rates={ExecutionMode.PREPARE: 1.5},
		)
	except ValidationError as exc:
		assert 'less than or equal to 1' in str(exc)
	else:
		raise AssertionError('expected ValidationError')


def test_failure_type_includes_unknown_commit_state():
	assert FailureType.UNKNOWN_COMMIT_STATE.value == 'unknown_commit_state'
