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
				'update_store_phone': OperationContract(
					operation_id='update_store_phone',
					title='修改门店联系电话',
					required_params=['store_id', 'phone'],
					success_criteria=['保存后重新进入页面，联系电话等于目标值', '返回执行截图'],
					forbidden_actions=['不能修改其他门店信息', '不能修改与电话无关字段'],
					allow_commit=True,
				),
				'change_business_hours': OperationContract(
					operation_id='change_business_hours',
					title='修改营业时间',
					required_params=['store_id', 'business_hours'],
					success_criteria=['保存后重新进入页面，营业时间等于目标值', '返回执行截图'],
					forbidden_actions=['不能修改其他门店信息', '不能修改配送范围或商品信息'],
					allow_commit=True,
				),
				'replace_product_image': OperationContract(
					operation_id='replace_product_image',
					title='替换商品图片',
					required_params=['store_id', 'product_id', 'attachment_id'],
					success_criteria=['prepare 模式停在最终提交前并返回截图'],
					forbidden_actions=['不能提交未审核图片', '不能修改商品价格或库存'],
					allow_commit=False,
				),
				'update_store_decoration_image': OperationContract(
					operation_id='update_store_decoration_image',
					title='替换店铺装修图片',
					required_params=['store_id', 'attachment_id'],
					success_criteria=['prepare 模式停在最终提交前并返回截图'],
					forbidden_actions=['不能提交未审核图片', '不能修改店铺基础信息'],
					allow_commit=False,
				),
			}
		)

	def get(self, operation_id: str) -> OperationContract:
		try:
			return self.operations[operation_id]
		except KeyError as exc:
			raise KeyError(f'Unsupported operation: {operation_id}') from exc

