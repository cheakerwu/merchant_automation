import pytest

from merchant_automation.operations.recipes import RecipeLookupError, RecipeRegistry
from merchant_automation.operations.schemas import ExecutionMode, RecipeMetadata, RecipeStatus


def test_default_registry_selects_first_batch_recipe():
	registry = RecipeRegistry.default()

	recipe = registry.select(platform='meituan', operation_id='update_store_phone')

	assert recipe.recipe_id == 'meituan.update_store_phone.v1'
	assert recipe.platform == 'meituan'
	assert recipe.operation_id == 'update_store_phone'
	assert recipe.status == RecipeStatus.PREPARE_READY
	assert ExecutionMode.PREPARE in recipe.allowed_modes


def test_default_registry_has_no_commit_ready_image_recipe():
	registry = RecipeRegistry.default()

	recipe = registry.select(platform='meituan', operation_id='replace_product_image')

	assert recipe.recipe_id == 'meituan.replace_product_image.v1'
	assert recipe.status == RecipeStatus.PREPARE_TESTING
	assert ExecutionMode.COMMIT not in recipe.allowed_modes


def test_registry_raises_for_missing_recipe():
	registry = RecipeRegistry(recipes=[])

	with pytest.raises(RecipeLookupError) as exc:
		registry.select(platform='meituan', operation_id='update_store_phone')

	assert 'No recipe for meituan/update_store_phone' in str(exc.value)


def test_registry_returns_disabled_recipe_for_preflight_to_block():
	disabled = RecipeMetadata(
		recipe_id='meituan.update_store_phone.disabled',
		operation_id='update_store_phone',
		platform='meituan',
		version=1,
		status=RecipeStatus.DISABLED,
		allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.PREPARE},
	)
	registry = RecipeRegistry(recipes=[disabled])

	recipe = registry.select(platform='meituan', operation_id='update_store_phone')

	assert recipe.status == RecipeStatus.DISABLED


def test_registry_selection_is_platform_specific():
	registry = RecipeRegistry(
		recipes=[
			RecipeMetadata(
				recipe_id='meituan.update_store_phone.v1',
				operation_id='update_store_phone',
				platform='meituan',
				version=1,
				status=RecipeStatus.PREPARE_READY,
				allowed_modes={ExecutionMode.PREPARE},
			),
			RecipeMetadata(
				recipe_id='eleme.update_store_phone.v1',
				operation_id='update_store_phone',
				platform='eleme',
				version=1,
				status=RecipeStatus.PREPARE_READY,
				allowed_modes={ExecutionMode.PREPARE},
			),
		]
	)

	recipe = registry.select(platform='eleme', operation_id='update_store_phone')

	assert recipe.recipe_id == 'eleme.update_store_phone.v1'
