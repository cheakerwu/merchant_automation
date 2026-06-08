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
				# ==================== 门店信息管理 ====================
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
					recipe_id='meituan.update_store_address.v1',
					operation_id='update_store_address',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_TESTING,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE, ExecutionMode.COMMIT},
					success_rates={ExecutionMode.PREPARE: 0.85},
				),
				RecipeMetadata(
					recipe_id='meituan.update_store_name.v1',
					operation_id='update_store_name',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_TESTING,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE, ExecutionMode.COMMIT},
					success_rates={ExecutionMode.PREPARE: 0.90},
				),
				RecipeMetadata(
					recipe_id='meituan.update_store_logo.v1',
					operation_id='update_store_logo',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_TESTING,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE},
					success_rates={ExecutionMode.PREPARE: 0.75},
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
					recipe_id='meituan.update_store_notice.v1',
					operation_id='update_store_notice',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_TESTING,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE, ExecutionMode.COMMIT},
					success_rates={ExecutionMode.PREPARE: 0.92},
				),
				RecipeMetadata(
					recipe_id='meituan.update_store_description.v1',
					operation_id='update_store_description',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_TESTING,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE, ExecutionMode.COMMIT},
					success_rates={ExecutionMode.PREPARE: 0.90},
				),

				# ==================== 商品管理 ====================
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
					recipe_id='meituan.update_product_price.v1',
					operation_id='update_product_price',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_TESTING,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE, ExecutionMode.COMMIT},
					success_rates={ExecutionMode.PREPARE: 0.88},
				),
				RecipeMetadata(
					recipe_id='meituan.update_product_stock.v1',
					operation_id='update_product_stock',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_TESTING,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE, ExecutionMode.COMMIT},
					success_rates={ExecutionMode.PREPARE: 0.90},
				),
				RecipeMetadata(
					recipe_id='meituan.update_product_name.v1',
					operation_id='update_product_name',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_TESTING,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE, ExecutionMode.COMMIT},
					success_rates={ExecutionMode.PREPARE: 0.85},
				),
				RecipeMetadata(
					recipe_id='meituan.update_product_description.v1',
					operation_id='update_product_description',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_TESTING,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE, ExecutionMode.COMMIT},
					success_rates={ExecutionMode.PREPARE: 0.82},
				),
				RecipeMetadata(
					recipe_id='meituan.toggle_product_status.v1',
					operation_id='toggle_product_status',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_TESTING,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE, ExecutionMode.COMMIT},
					success_rates={ExecutionMode.PREPARE: 0.92},
				),
				RecipeMetadata(
					recipe_id='meituan.add_product_category.v1',
					operation_id='add_product_category',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_TESTING,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE, ExecutionMode.COMMIT},
					success_rates={ExecutionMode.PREPARE: 0.88},
				),
				RecipeMetadata(
					recipe_id='meituan.update_product_category.v1',
					operation_id='update_product_category',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_TESTING,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE, ExecutionMode.COMMIT},
					success_rates={ExecutionMode.PREPARE: 0.85},
				),

				# ==================== 店铺装修 ====================
				RecipeMetadata(
					recipe_id='meituan.update_store_decoration_image.v1',
					operation_id='update_store_decoration_image',
					platform='meituan',
					version=1,
					status=RecipeStatus.COMMIT_READY,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE, ExecutionMode.COMMIT},
					success_rates={ExecutionMode.PREPARE: 0.75, ExecutionMode.COMMIT: 0.95},
				),
				RecipeMetadata(
					recipe_id='meituan.update_store_banner.v1',
					operation_id='update_store_banner',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_TESTING,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE},
					success_rates={ExecutionMode.PREPARE: 0.75},
				),

				# ==================== 配送管理 ====================
				RecipeMetadata(
					recipe_id='meituan.update_delivery_range.v1',
					operation_id='update_delivery_range',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_TESTING,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE, ExecutionMode.COMMIT},
					success_rates={ExecutionMode.PREPARE: 0.80},
				),
				RecipeMetadata(
					recipe_id='meituan.update_delivery_fee.v1',
					operation_id='update_delivery_fee',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_TESTING,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE, ExecutionMode.COMMIT},
					success_rates={ExecutionMode.PREPARE: 0.90},
				),
				RecipeMetadata(
					recipe_id='meituan.update_min_order_amount.v1',
					operation_id='update_min_order_amount',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_TESTING,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE, ExecutionMode.COMMIT},
					success_rates={ExecutionMode.PREPARE: 0.90},
				),

				# ==================== 营销活动 ====================
				RecipeMetadata(
					recipe_id='meituan.create_discount_activity.v1',
					operation_id='create_discount_activity',
					platform='meituan',
					version=1,
					status=RecipeStatus.CANDIDATE,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE},
					success_rates={ExecutionMode.PREPARE: 0.70},
				),
				RecipeMetadata(
					recipe_id='meituan.update_discount_activity.v1',
					operation_id='update_discount_activity',
					platform='meituan',
					version=1,
					status=RecipeStatus.CANDIDATE,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE},
					success_rates={ExecutionMode.PREPARE: 0.70},
				),
				RecipeMetadata(
					recipe_id='meituan.cancel_discount_activity.v1',
					operation_id='cancel_discount_activity',
					platform='meituan',
					version=1,
					status=RecipeStatus.CANDIDATE,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE, ExecutionMode.COMMIT},
					success_rates={ExecutionMode.PREPARE: 0.75},
				),
				RecipeMetadata(
					recipe_id='meituan.create_full_reduction_activity.v1',
					operation_id='create_full_reduction_activity',
					platform='meituan',
					version=1,
					status=RecipeStatus.CANDIDATE,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE},
					success_rates={ExecutionMode.PREPARE: 0.65},
				),
				RecipeMetadata(
					recipe_id='meituan.update_full_reduction_activity.v1',
					operation_id='update_full_reduction_activity',
					platform='meituan',
					version=1,
					status=RecipeStatus.CANDIDATE,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE},
					success_rates={ExecutionMode.PREPARE: 0.65},
				),

				# ==================== 评价管理 ====================
				RecipeMetadata(
					recipe_id='meituan.reply_to_review.v1',
					operation_id='reply_to_review',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_TESTING,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE, ExecutionMode.COMMIT},
					success_rates={ExecutionMode.PREPARE: 0.85},
				),

				# ==================== 财务结算 ====================
				RecipeMetadata(
					recipe_id='meituan.view_settlement_detail.v1',
					operation_id='view_settlement_detail',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_TESTING,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE},
					success_rates={ExecutionMode.PREPARE: 0.95},
				),

				# ==================== 订单管理 ====================
				RecipeMetadata(
					recipe_id='meituan.view_order_detail.v1',
					operation_id='view_order_detail',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_TESTING,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE},
					success_rates={ExecutionMode.PREPARE: 0.95},
				),
				RecipeMetadata(
					recipe_id='meituan.view_order_list.v1',
					operation_id='view_order_list',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_TESTING,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE},
					success_rates={ExecutionMode.PREPARE: 0.95},
				),

				# ==================== 数据统计 ====================
				RecipeMetadata(
					recipe_id='meituan.view_sales_report.v1',
					operation_id='view_sales_report',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_TESTING,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE},
					success_rates={ExecutionMode.PREPARE: 0.95},
				),
				RecipeMetadata(
					recipe_id='meituan.view_business_analysis.v1',
					operation_id='view_business_analysis',
					platform='meituan',
					version=1,
					status=RecipeStatus.PREPARE_TESTING,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE},
					success_rates={ExecutionMode.PREPARE: 0.95},
				),

				# ==================== 资质证照 ====================
				RecipeMetadata(
					recipe_id='meituan.update_business_license.v1',
					operation_id='update_business_license',
					platform='meituan',
					version=1,
					status=RecipeStatus.CANDIDATE,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE},
					success_rates={ExecutionMode.PREPARE: 0.70},
				),
				RecipeMetadata(
					recipe_id='meituan.update_food_license.v1',
					operation_id='update_food_license',
					platform='meituan',
					version=1,
					status=RecipeStatus.CANDIDATE,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE},
					success_rates={ExecutionMode.PREPARE: 0.70},
				),

				# ==================== 员工管理 ====================
				RecipeMetadata(
					recipe_id='meituan.add_staff_account.v1',
					operation_id='add_staff_account',
					platform='meituan',
					version=1,
					status=RecipeStatus.CANDIDATE,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE, ExecutionMode.COMMIT},
					success_rates={ExecutionMode.PREPARE: 0.75},
				),
				RecipeMetadata(
					recipe_id='meituan.update_staff_role.v1',
					operation_id='update_staff_role',
					platform='meituan',
					version=1,
					status=RecipeStatus.CANDIDATE,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE, ExecutionMode.COMMIT},
					success_rates={ExecutionMode.PREPARE: 0.80},
				),
				RecipeMetadata(
					recipe_id='meituan.delete_staff_account.v1',
					operation_id='delete_staff_account',
					platform='meituan',
					version=1,
					status=RecipeStatus.CANDIDATE,
					allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.DRY_RUN, ExecutionMode.PREPARE, ExecutionMode.COMMIT},
					success_rates={ExecutionMode.PREPARE: 0.80},
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
