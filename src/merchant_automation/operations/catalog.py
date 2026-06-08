from __future__ import annotations

from dataclasses import dataclass

from merchant_automation.operations.schemas import OperationContract


@dataclass(frozen=True)
class OperationCatalog:
	operations: dict[str, OperationContract]

	@classmethod
	def default(cls) -> OperationCatalog:
		return cls(
			operations={
				# ==================== 门店信息管理 ====================
				'update_store_phone': OperationContract(
					operation_id='update_store_phone',
					title='修改门店联系电话',
					required_params=['store_id', 'phone'],
					success_criteria=['保存后重新进入页面，联系电话等于目标值', '返回执行截图'],
					forbidden_actions=['不能修改其他门店信息', '不能修改与电话无关字段'],
					allow_commit=True,
				),
				'update_store_address': OperationContract(
					operation_id='update_store_address',
					title='修改门店地址',
					required_params=['store_id', 'address'],
					success_criteria=['保存后重新进入页面，地址等于目标值', '返回执行截图'],
					forbidden_actions=['不能修改其他门店信息', '不能修改经纬度坐标'],
					allow_commit=True,
				),
				'update_store_name': OperationContract(
					operation_id='update_store_name',
					title='修改门店名称',
					required_params=['store_id', 'store_name'],
					success_criteria=['保存后重新进入页面，门店名称等于目标值', '返回执行截图'],
					forbidden_actions=['不能修改品牌名称', '不能修改其他门店信息'],
					allow_commit=True,
				),
				'update_store_logo': OperationContract(
					operation_id='update_store_logo',
					title='更换门店Logo',
					required_params=['store_id', 'attachment_id'],
					success_criteria=['prepare 模式停在最终提交前并返回截图'],
					forbidden_actions=['不能提交未审核图片', '不能修改店铺基础信息'],
					allow_commit=False,
				),
				'change_business_hours': OperationContract(
					operation_id='change_business_hours',
					title='修改营业时间',
					required_params=['store_id', 'business_hours'],
					success_criteria=['保存后重新进入页面，营业时间等于目标值', '返回执行截图'],
					forbidden_actions=['不能修改其他门店信息', '不能修改配送范围或商品信息'],
					allow_commit=True,
				),
				'update_store_notice': OperationContract(
					operation_id='update_store_notice',
					title='修改门店公告',
					required_params=['store_id', 'notice'],
					success_criteria=['保存后重新进入页面，公告内容等于目标值', '返回执行截图'],
					forbidden_actions=['不能修改其他门店信息', '不能包含违规内容'],
					allow_commit=True,
				),
				'update_store_description': OperationContract(
					operation_id='update_store_description',
					title='修改门店简介',
					required_params=['store_id', 'description'],
					success_criteria=['保存后重新进入页面，简介等于目标值', '返回执行截图'],
					forbidden_actions=['不能修改其他门店信息', '不能包含虚假宣传'],
					allow_commit=True,
				),

				# ==================== 商品管理 ====================
				'replace_product_image': OperationContract(
					operation_id='replace_product_image',
					title='替换商品图片',
					required_params=['store_id', 'product_id', 'attachment_id'],
					success_criteria=['prepare 模式停在最终提交前并返回截图'],
					forbidden_actions=['不能提交未审核图片', '不能修改商品价格或库存'],
					allow_commit=False,
				),
				'update_product_price': OperationContract(
					operation_id='update_product_price',
					title='修改商品价格',
					required_params=['store_id', 'product_id', 'price'],
					success_criteria=['保存后重新进入页面，商品价格等于目标值', '返回执行截图'],
					forbidden_actions=['不能修改其他商品信息', '价格不能低于平台最低限价'],
					allow_commit=True,
				),
				'update_product_stock': OperationContract(
					operation_id='update_product_stock',
					title='修改商品库存',
					required_params=['store_id', 'product_id', 'stock'],
					success_criteria=['保存后重新进入页面，库存等于目标值', '返回执行截图'],
					forbidden_actions=['不能修改其他商品信息', '库存不能为负数'],
					allow_commit=True,
				),
				'update_product_name': OperationContract(
					operation_id='update_product_name',
					title='修改商品名称',
					required_params=['store_id', 'product_id', 'product_name'],
					success_criteria=['保存后重新进入页面，商品名称等于目标值', '返回执行截图'],
					forbidden_actions=['不能修改其他商品信息', '不能包含违禁词'],
					allow_commit=True,
				),
				'update_product_description': OperationContract(
					operation_id='update_product_description',
					title='修改商品描述',
					required_params=['store_id', 'product_id', 'description'],
					success_criteria=['保存后重新进入页面，商品描述等于目标值', '返回执行截图'],
					forbidden_actions=['不能修改其他商品信息', '不能包含虚假宣传'],
					allow_commit=True,
				),
				'toggle_product_status': OperationContract(
					operation_id='toggle_product_status',
					title='上架/下架商品',
					required_params=['store_id', 'product_id', 'is_active'],
					success_criteria=['保存后重新进入页面，商品状态等于目标值', '返回执行截图'],
					forbidden_actions=['不能修改商品其他信息'],
					allow_commit=True,
				),
				'add_product_category': OperationContract(
					operation_id='add_product_category',
					title='添加商品分类',
					required_params=['store_id', 'category_name'],
					success_criteria=['保存后重新进入页面，分类列表包含目标分类', '返回执行截图'],
					forbidden_actions=['不能删除其他分类', '分类名称不能重复'],
					allow_commit=True,
				),
				'update_product_category': OperationContract(
					operation_id='update_product_category',
					title='修改商品分类',
					required_params=['store_id', 'category_id', 'category_name'],
					success_criteria=['保存后重新进入页面，分类名称等于目标值', '返回执行截图'],
					forbidden_actions=['不能删除分类', '不能修改其他分类信息'],
					allow_commit=True,
				),

				# ==================== 店铺装修 ====================
				'update_store_decoration_image': OperationContract(
					operation_id='update_store_decoration_image',
					title='替换店铺装修图片',
					required_params=['store_id', 'attachment_id'],
					success_criteria=['prepare 模式停在最终提交前并返回截图'],
					forbidden_actions=['不能提交未审核图片', '不能修改店铺基础信息'],
					allow_commit=False,
				),
				'update_store_banner': OperationContract(
					operation_id='update_store_banner',
					title='更换店铺Banner',
					required_params=['store_id', 'attachment_id'],
					success_criteria=['prepare 模式停在最终提交前并返回截图'],
					forbidden_actions=['不能提交未审核图片', '不能修改店铺基础信息'],
					allow_commit=False,
				),

				# ==================== 配送管理 ====================
				'update_delivery_range': OperationContract(
					operation_id='update_delivery_range',
					title='修改配送范围',
					required_params=['store_id', 'delivery_range'],
					success_criteria=['保存后重新进入页面，配送范围等于目标值', '返回执行截图'],
					forbidden_actions=['不能修改其他门店信息', '配送范围不能超出平台限制'],
					allow_commit=True,
				),
				'update_delivery_fee': OperationContract(
					operation_id='update_delivery_fee',
					title='修改配送费',
					required_params=['store_id', 'delivery_fee'],
					success_criteria=['保存后重新进入页面，配送费等于目标值', '返回执行截图'],
					forbidden_actions=['不能修改其他门店信息', '配送费不能低于平台最低限价'],
					allow_commit=True,
				),
				'update_min_order_amount': OperationContract(
					operation_id='update_min_order_amount',
					title='修改起送价',
					required_params=['store_id', 'min_order_amount'],
					success_criteria=['保存后重新进入页面，起送价等于目标值', '返回执行截图'],
					forbidden_actions=['不能修改其他门店信息', '起送价不能低于平台最低限价'],
					allow_commit=True,
				),

				# ==================== 营销活动 ====================
				'create_discount_activity': OperationContract(
					operation_id='create_discount_activity',
					title='创建折扣活动',
					required_params=['store_id', 'activity_name', 'discount_rate', 'start_time', 'end_time'],
					success_criteria=['保存后活动列表包含目标活动', '返回执行截图'],
					forbidden_actions=['不能修改其他活动', '折扣不能低于平台最低折扣'],
					allow_commit=True,
				),
				'update_discount_activity': OperationContract(
					operation_id='update_discount_activity',
					title='修改折扣活动',
					required_params=['store_id', 'activity_id', 'discount_rate'],
					success_criteria=['保存后重新进入页面，活动折扣等于目标值', '返回执行截图'],
					forbidden_actions=['不能删除活动', '不能修改活动时间'],
					allow_commit=True,
				),
				'cancel_discount_activity': OperationContract(
					operation_id='cancel_discount_activity',
					title='取消折扣活动',
					required_params=['store_id', 'activity_id'],
					success_criteria=['保存后活动状态变为已取消', '返回执行截图'],
					forbidden_actions=['不能删除活动记录'],
					allow_commit=True,
				),
				'create_full_reduction_activity': OperationContract(
					operation_id='create_full_reduction_activity',
					title='创建满减活动',
					required_params=['store_id', 'activity_name', 'full_amount', 'reduce_amount', 'start_time', 'end_time'],
					success_criteria=['保存后活动列表包含目标活动', '返回执行截图'],
					forbidden_actions=['不能修改其他活动', '满减金额不能超出预算'],
					allow_commit=True,
				),
				'update_full_reduction_activity': OperationContract(
					operation_id='update_full_reduction_activity',
					title='修改满减活动',
					required_params=['store_id', 'activity_id', 'full_amount', 'reduce_amount'],
					success_criteria=['保存后重新进入页面，满减金额等于目标值', '返回执行截图'],
					forbidden_actions=['不能删除活动', '不能修改活动时间'],
					allow_commit=True,
				),

				# ==================== 评价管理 ====================
				'reply_to_review': OperationContract(
					operation_id='reply_to_review',
					title='回复用户评价',
					required_params=['store_id', 'review_id', 'reply_content'],
					success_criteria=['保存后评价页面显示回复内容', '返回执行截图'],
					forbidden_actions=['不能删除评价', '不能修改评分', '回复不能包含违规内容'],
					allow_commit=True,
				),

				# ==================== 财务结算 ====================
				'view_settlement_detail': OperationContract(
					operation_id='view_settlement_detail',
					title='查看结算明细',
					required_params=['store_id', 'start_date', 'end_date'],
					success_criteria=['页面显示指定日期范围的结算明细', '返回执行截图'],
					forbidden_actions=['不能导出数据', '不能修改结算信息'],
					allow_commit=False,
				),

				# ==================== 订单管理 ====================
				'view_order_detail': OperationContract(
					operation_id='view_order_detail',
					title='查看订单详情',
					required_params=['store_id', 'order_id'],
					success_criteria=['页面显示订单详细信息', '返回执行截图'],
					forbidden_actions=['不能修改订单信息', '不能取消订单'],
					allow_commit=False,
				),
				'view_order_list': OperationContract(
					operation_id='view_order_list',
					title='查看订单列表',
					required_params=['store_id', 'order_status'],
					success_criteria=['页面显示指定状态的订单列表', '返回执行截图'],
					forbidden_actions=['不能修改订单信息'],
					allow_commit=False,
				),

				# ==================== 数据统计 ====================
				'view_sales_report': OperationContract(
					operation_id='view_sales_report',
					title='查看销售报表',
					required_params=['store_id', 'start_date', 'end_date'],
					success_criteria=['页面显示指定日期范围的销售数据', '返回执行截图'],
					forbidden_actions=['不能导出数据', '不能修改统计数据'],
					allow_commit=False,
				),
				'view_business_analysis': OperationContract(
					operation_id='view_business_analysis',
					title='查看经营分析',
					required_params=['store_id'],
					success_criteria=['页面显示经营分析数据', '返回执行截图'],
					forbidden_actions=['不能导出数据', '不能修改统计数据'],
					allow_commit=False,
				),

				# ==================== 资质证照 ====================
				'update_business_license': OperationContract(
					operation_id='update_business_license',
					title='更新营业执照',
					required_params=['store_id', 'attachment_id'],
					success_criteria=['prepare 模式停在最终提交前并返回截图'],
					forbidden_actions=['不能提交未审核图片', '不能修改其他资质信息'],
					allow_commit=False,
				),
				'update_food_license': OperationContract(
					operation_id='update_food_license',
					title='更新食品经营许可证',
					required_params=['store_id', 'attachment_id'],
					success_criteria=['prepare 模式停在最终提交前并返回截图'],
					forbidden_actions=['不能提交未审核图片', '不能修改其他资质信息'],
					allow_commit=False,
				),

				# ==================== 员工管理 ====================
				'add_staff_account': OperationContract(
					operation_id='add_staff_account',
					title='添加员工账号',
					required_params=['store_id', 'staff_name', 'staff_phone', 'role'],
					success_criteria=['保存后员工列表包含目标员工', '返回执行截图'],
					forbidden_actions=['不能删除其他员工', '不能修改管理员账号'],
					allow_commit=True,
				),
				'update_staff_role': OperationContract(
					operation_id='update_staff_role',
					title='修改员工角色',
					required_params=['store_id', 'staff_id', 'role'],
					success_criteria=['保存后员工角色等于目标值', '返回执行截图'],
					forbidden_actions=['不能删除员工', '不能修改管理员角色'],
					allow_commit=True,
				),
				'delete_staff_account': OperationContract(
					operation_id='delete_staff_account',
					title='删除员工账号',
					required_params=['store_id', 'staff_id'],
					success_criteria=['保存后员工列表不包含目标员工', '返回执行截图'],
					forbidden_actions=['不能删除管理员账号'],
					allow_commit=True,
				),
			}
		)

	def get(self, operation_id: str) -> OperationContract:
		try:
			return self.operations[operation_id]
		except KeyError as exc:
			raise KeyError(f'Unsupported operation: {operation_id}') from exc

