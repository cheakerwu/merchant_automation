from __future__ import annotations

from dataclasses import dataclass

from merchant_automation.operations.schemas import ExecutionMode, RecipeMetadata, RecipeStatus


class RecipeLookupError(LookupError):
	"""Raised when no recipe exists for a platform and operation pair."""


@dataclass(frozen=True)
class RecipeRegistry:
	recipes: list[RecipeMetadata]

	@classmethod
	def default(cls) -> RecipeRegistry:
		return cls(
			recipes=[
				RecipeMetadata(
					recipe_id='meituan.update_store_phone.v1',
					operation_id='update_store_phone',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_READY,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE, ExecutionMode.COMMIT},
					success_rates={ExecutionMode.PREPARE: 0.98, ExecutionMode.COMMIT: 0.0},
				),
				RecipeMetadata(
					recipe_id='meituan.change_business_hours.v1',
					operation_id='change_business_hours',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_READY,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE, ExecutionMode.COMMIT},
					success_rates={ExecutionMode.PREPARE: 0.96, ExecutionMode.COMMIT: 0.0},
				),
				RecipeMetadata(
					recipe_id='meituan.replace_product_image.v1',
					operation_id='replace_product_image',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_TESTING,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE},
					success_rates={ExecutionMode.PREPARE: 0.75},
				),
				RecipeMetadata(
					recipe_id='meituan.update_store_decoration_image.v1',
					operation_id='update_store_decoration_image',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_TESTING,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE},
					success_rates={ExecutionMode.PREPARE: 0.75},
				),
			]
		)

	def select(self, *, platform: str, operation_id: str) -> RecipeMetadata:
		matches = [
			recipe
			for recipe in self.recipes
			if recipe.platform == platform and recipe.operation_id == operation_id
		]
		if not matches:
			raise RecipeLookupError(f'No recipe for {platform}/{operation_id}')
		return max(matches, key=lambda recipe: recipe.version)

