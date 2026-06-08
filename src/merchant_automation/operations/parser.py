from __future__ import annotations

import re

from merchant_automation.operations.schemas import ExecutionMode, OperationTask

PLATFORM_ALIASES = {
	'美团': 'meituan',
	'美团外卖': 'meituan',
	'meituan': 'meituan',
	'饿了么': 'eleme',
	'eleme': 'eleme',
	'抖音': 'douyin',
	'抖音来客': 'douyin',
	'douyin': 'douyin',
}

PLATFORM_PATTERN = r'美团外卖|美团|饿了么|抖音来客|抖音|meituan|eleme|douyin'


class OperationParseError(ValueError):
	"""Raised when text cannot be parsed into a supported operation."""


class OperationParser:
	def parse_text(self, text: str, *, mode: ExecutionMode = ExecutionMode.PARSE_ONLY) -> OperationTask:
		normalized = text.strip()

		# 商品管理（优先匹配，避免被门店名称匹配）
		price_task = self._parse_update_product_price(normalized, mode=mode)
		if price_task is not None:
			return price_task

		stock_task = self._parse_update_product_stock(normalized, mode=mode)
		if stock_task is not None:
			return stock_task

		product_name_task = self._parse_update_product_name(normalized, mode=mode)
		if product_name_task is not None:
			return product_name_task

		product_desc_task = self._parse_update_product_description(normalized, mode=mode)
		if product_desc_task is not None:
			return product_desc_task

		category_task = self._parse_add_product_category(normalized, mode=mode)
		if category_task is not None:
			return category_task

		update_category_task = self._parse_update_product_category(normalized, mode=mode)
		if update_category_task is not None:
			return update_category_task

		# 门店信息管理
		phone_task = self._parse_update_store_phone(normalized, mode=mode)
		if phone_task is not None:
			return phone_task

		address_task = self._parse_update_store_address(normalized, mode=mode)
		if address_task is not None:
			return address_task

		name_task = self._parse_update_store_name(normalized, mode=mode)
		if name_task is not None:
			return name_task

		notice_task = self._parse_update_store_notice(normalized, mode=mode)
		if notice_task is not None:
			return notice_task

		description_task = self._parse_update_store_description(normalized, mode=mode)
		if description_task is not None:
			return description_task

		hours_task = self._parse_change_business_hours(normalized, mode=mode)
		if hours_task is not None:
			return hours_task

		store_photo_task = self._parse_update_store_photo(normalized, mode=mode)
		if store_photo_task is not None:
			return store_photo_task

		# 配送管理
		delivery_fee_task = self._parse_update_delivery_fee(normalized, mode=mode)
		if delivery_fee_task is not None:
			return delivery_fee_task

		delivery_range_task = self._parse_update_delivery_range(normalized, mode=mode)
		if delivery_range_task is not None:
			return delivery_range_task

		min_order_task = self._parse_update_min_order_amount(normalized, mode=mode)
		if min_order_task is not None:
			return min_order_task

		# 评价管理
		reply_task = self._parse_reply_to_review(normalized, mode=mode)
		if reply_task is not None:
			return reply_task

		# 查看类
		order_detail_task = self._parse_view_order_detail(normalized, mode=mode)
		if order_detail_task is not None:
			return order_detail_task

		order_list_task = self._parse_view_order_list(normalized, mode=mode)
		if order_list_task is not None:
			return order_list_task

		sales_report_task = self._parse_view_sales_report(normalized, mode=mode)
		if sales_report_task is not None:
			return sales_report_task

		analysis_task = self._parse_view_business_analysis(normalized, mode=mode)
		if analysis_task is not None:
			return analysis_task

		settlement_task = self._parse_view_settlement_detail(normalized, mode=mode)
		if settlement_task is not None:
			return settlement_task

		raise OperationParseError(f'Unsupported operation text: {text}')

	def _parse_update_store_phone(self, text: str, *, mode: ExecutionMode) -> OperationTask | None:
		match = re.match(
			r'^(?:把|将)?\s*'
			rf'(?P<platform>{PLATFORM_PATTERN})\s*'
			r'(?P<store>.+?)\s*'
			r'(?:(?:商家|门店|店铺)?(?:电话|联系电话)\s*(?:改成|改为|设为|设置为|修改为|更改为|变更为)|'
			r'(?:修改|更改|变更)\s*(?:商家|门店|店铺)?(?:电话|联系电话)\s*(?:为|成|到)?)\s*'
			r'(?P<phone>[\d+\-\s]{7,20})$',
			text,
			flags=re.IGNORECASE,
		)
		if not match:
			return None

		platform = self._resolve_platform(match.group('platform'))
		if platform is None:
			return None

		phone = re.sub(r'\s+', '', match.group('phone'))
		return OperationTask(
			platform=platform,
			store_id=match.group('store').strip(),
			operation_id='update_store_phone',
			params={'phone': phone},
			mode=mode,
		)

	def _parse_change_business_hours(self, text: str, *, mode: ExecutionMode) -> OperationTask | None:
		match = re.match(
			r'^(?:把|将)?\s*(?P<platform>\S+)\s+(?P<store>\S+)\s+营业时间\s*(?:改成|改为|设为|设置为)\s*(?P<hours>\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2})$',
			text,
		)
		if not match:
			return None

		platform = self._resolve_platform(match.group('platform'))
		if platform is None:
			return None

		hours = re.sub(r'\s+', '', match.group('hours'))
		return OperationTask(
			platform=platform,
			store_id=match.group('store'),
			operation_id='change_business_hours',
			params={'business_hours': hours},
			mode=mode,
		)

	def _parse_update_store_photo(self, text: str, *, mode: ExecutionMode) -> OperationTask | None:
		match = re.match(
			r'^(?:把|将)?\s*'
			r'(?P<platform>美团外卖|美团|饿了么|抖音来客|抖音|meituan|eleme|douyin)\s*'
			r'(?P<store>.+?)\s*'
			r'(?:门店照片|门店图片|门头图|店铺图|店铺图片|装修图|门店装修图片)\s*'
			r'(?:换成|替换为|改成|改为|设置为)\s*'
			r'(?:刚上传的|最近的|最近上传的)?图片$',
			text,
		)
		if not match:
			return None

		platform = self._resolve_platform(match.group('platform'))
		if platform is None:
			return None

		return OperationTask(
			platform=platform,
			store_id=match.group('store').strip(),
			operation_id='update_store_decoration_image',
			params={'attachment_id': 'latest_image'},
			mode=mode,
		)

	def _resolve_platform(self, value: str) -> str | None:
		return PLATFORM_ALIASES.get(value.strip().lower()) or PLATFORM_ALIASES.get(value.strip())

	# ==================== 门店信息管理解析 ====================

	def _parse_update_store_address(self, text: str, *, mode: ExecutionMode) -> OperationTask | None:
		match = re.match(
			r'^(?:把|将)?\s*'
			rf'(?P<platform>{PLATFORM_PATTERN})\s*'
			r'(?P<store>.+?)\s*'
			r'(?:(?:门店|店铺)?地址\s*(?:改成|改为|设为|设置为|修改为|更改为|变更为)|'
			r'(?:修改|更改|变更)\s*(?:门店|店铺)?地址\s*(?:为|成|到)?)\s*'
			r'(?P<address>.+)$',
			text,
			flags=re.IGNORECASE,
		)
		if not match:
			return None

		platform = self._resolve_platform(match.group('platform'))
		if platform is None:
			return None

		return OperationTask(
			platform=platform,
			store_id=match.group('store').strip(),
			operation_id='update_store_address',
			params={'address': match.group('address').strip()},
			mode=mode,
		)

	def _parse_update_store_name(self, text: str, *, mode: ExecutionMode) -> OperationTask | None:
		match = re.match(
			r'^(?:把|将)?\s*'
			rf'(?P<platform>{PLATFORM_PATTERN})\s*'
			r'(?P<store>.+?)\s*'
			r'(?:(?:门店|店铺)?名称?\s*(?:改成|改为|设为|设置为|修改为|更改为|变更为)|'
			r'(?:修改|更改|变更)\s*(?:门店|店铺)?名称?\s*(?:为|成|到)?)\s*'
			r'(?P<name>.+)$',
			text,
			flags=re.IGNORECASE,
		)
		if not match:
			return None

		platform = self._resolve_platform(match.group('platform'))
		if platform is None:
			return None

		return OperationTask(
			platform=platform,
			store_id=match.group('store').strip(),
			operation_id='update_store_name',
			params={'store_name': match.group('name').strip()},
			mode=mode,
		)

	def _parse_update_store_notice(self, text: str, *, mode: ExecutionMode) -> OperationTask | None:
		match = re.match(
			r'^(?:把|将)?\s*'
			rf'(?P<platform>{PLATFORM_PATTERN})\s*'
			r'(?P<store>.+?)\s*'
			r'(?:(?:门店|店铺)?公告\s*(?:改成|改为|设为|设置为|修改为|更改为|变更为)|'
			r'(?:修改|更改|变更)\s*(?:门店|店铺)?公告\s*(?:为|成|到)?)\s*'
			r'(?P<notice>.+)$',
			text,
			flags=re.IGNORECASE,
		)
		if not match:
			return None

		platform = self._resolve_platform(match.group('platform'))
		if platform is None:
			return None

		return OperationTask(
			platform=platform,
			store_id=match.group('store').strip(),
			operation_id='update_store_notice',
			params={'notice': match.group('notice').strip()},
			mode=mode,
		)

	def _parse_update_store_description(self, text: str, *, mode: ExecutionMode) -> OperationTask | None:
		match = re.match(
			r'^(?:把|将)?\s*'
			rf'(?P<platform>{PLATFORM_PATTERN})\s*'
			r'(?P<store>.+?)\s*'
			r'(?:(?:门店|店铺)?简介\s*(?:改成|改为|设为|设置为|修改为|更改为|变更为)|'
			r'(?:修改|更改|变更)\s*(?:门店|店铺)?简介\s*(?:为|成|到)?)\s*'
			r'(?P<desc>.+)$',
			text,
			flags=re.IGNORECASE,
		)
		if not match:
			return None

		platform = self._resolve_platform(match.group('platform'))
		if platform is None:
			return None

		return OperationTask(
			platform=platform,
			store_id=match.group('store').strip(),
			operation_id='update_store_description',
			params={'description': match.group('desc').strip()},
			mode=mode,
		)

	# ==================== 商品管理解析 ====================

	def _parse_update_product_price(self, text: str, *, mode: ExecutionMode) -> OperationTask | None:
		match = re.match(
			r'^(?:把|将)?\s*'
			rf'(?P<platform>{PLATFORM_PATTERN})\s*'
			r'(?P<store>.+?)\s*'
			r'(?:(?:第\s*(?P<index>\d+)\s*个)?商品价格\s*(?:改成|改为|设为|设置为|修改为|更改为)|'
			r'(?:修改|更改|变更)\s*(?:第\s*(?P<index2>\d+)\s*个)?商品价格\s*(?:为|成|到)?)\s*'
			r'(?P<price>[\d.]+)\s*(?:元)?$',
			text,
			flags=re.IGNORECASE,
		)
		if not match:
			return None

		platform = self._resolve_platform(match.group('platform'))
		if platform is None:
			return None

		index = match.group('index') or match.group('index2') or '1'
		return OperationTask(
			platform=platform,
			store_id=match.group('store').strip(),
			operation_id='update_product_price',
			params={'product_index': int(index), 'price': match.group('price')},
			mode=mode,
		)

	def _parse_update_product_stock(self, text: str, *, mode: ExecutionMode) -> OperationTask | None:
		match = re.match(
			r'^(?:把|将)?\s*'
			rf'(?P<platform>{PLATFORM_PATTERN})\s*'
			r'(?P<store>.+?)\s*'
			r'(?:(?:第\s*(?P<index>\d+)\s*个)?商品库存\s*(?:改成|改为|设为|设置为|修改为|更改为)|'
			r'(?:修改|更改|变更)\s*(?:第\s*(?P<index2>\d+)\s*个)?商品库存\s*(?:为|成|到)?)\s*'
			r'(?P<stock>\d+)\s*(?:件|个)?$',
			text,
			flags=re.IGNORECASE,
		)
		if not match:
			return None

		platform = self._resolve_platform(match.group('platform'))
		if platform is None:
			return None

		index = match.group('index') or match.group('index2') or '1'
		return OperationTask(
			platform=platform,
			store_id=match.group('store').strip(),
			operation_id='update_product_stock',
			params={'product_index': int(index), 'stock': match.group('stock')},
			mode=mode,
		)

	def _parse_update_product_name(self, text: str, *, mode: ExecutionMode) -> OperationTask | None:
		match = re.match(
			r'^(?:把|将)?\s*'
			rf'(?P<platform>{PLATFORM_PATTERN})\s*'
			r'(?P<store>.+?)\s*'
			r'(?:(?:第\s*(?P<index>\d+)\s*个)?商品名称?\s*(?:改成|改为|设为|设置为|修改为|更改为)|'
			r'(?:修改|更改|变更)\s*(?:第\s*(?P<index2>\d+)\s*个)?商品名称?\s*(?:为|成|到)?)\s*'
			r'(?P<name>.+)$',
			text,
			flags=re.IGNORECASE,
		)
		if not match:
			return None

		platform = self._resolve_platform(match.group('platform'))
		if platform is None:
			return None

		index = match.group('index') or match.group('index2') or '1'
		return OperationTask(
			platform=platform,
			store_id=match.group('store').strip(),
			operation_id='update_product_name',
			params={'product_index': int(index), 'product_name': match.group('name').strip()},
			mode=mode,
		)

	def _parse_update_product_description(self, text: str, *, mode: ExecutionMode) -> OperationTask | None:
		match = re.match(
			r'^(?:把|将)?\s*'
			rf'(?P<platform>{PLATFORM_PATTERN})\s*'
			r'(?P<store>.+?)\s*'
			r'(?:(?:第\s*(?P<index>\d+)\s*个)?商品描述\s*(?:改成|改为|设为|设置为|修改为|更改为)|'
			r'(?:修改|更改|变更)\s*(?:第\s*(?P<index2>\d+)\s*个)?商品描述\s*(?:为|成|到)?)\s*'
			r'(?P<desc>.+)$',
			text,
			flags=re.IGNORECASE,
		)
		if not match:
			return None

		platform = self._resolve_platform(match.group('platform'))
		if platform is None:
			return None

		index = match.group('index') or match.group('index2') or '1'
		return OperationTask(
			platform=platform,
			store_id=match.group('store').strip(),
			operation_id='update_product_description',
			params={'product_index': int(index), 'description': match.group('desc').strip()},
			mode=mode,
		)

	def _parse_add_product_category(self, text: str, *, mode: ExecutionMode) -> OperationTask | None:
		match = re.match(
			r'^(?:给|为)?\s*'
			rf'(?P<platform>{PLATFORM_PATTERN})\s*'
			r'(?P<store>.+?)\s*'
			r'(?:添加|新建|创建)\s*(?:一个)?(?:分类|类别)\s*(?:叫|名为|叫做|名称为)?\s*'
			r'(?P<name>.+)$',
			text,
			flags=re.IGNORECASE,
		)
		if not match:
			return None

		platform = self._resolve_platform(match.group('platform'))
		if platform is None:
			return None

		return OperationTask(
			platform=platform,
			store_id=match.group('store').strip(),
			operation_id='add_product_category',
			params={'category_name': match.group('name').strip()},
			mode=mode,
		)

	def _parse_update_product_category(self, text: str, *, mode: ExecutionMode) -> OperationTask | None:
		match = re.match(
			r'^(?:把|将)?\s*'
			rf'(?P<platform>{PLATFORM_PATTERN})\s*'
			r'(?P<store>.+?)\s*'
			r'(?:(?:第\s*(?P<index>\d+)\s*个)?分类名称?\s*(?:改成|改为|设为|设置为|修改为|更改为)|'
			r'(?:修改|更改|变更)\s*(?:第\s*(?P<index2>\d+)\s*个)?分类名称?\s*(?:为|成|到)?)\s*'
			r'(?P<name>.+)$',
			text,
			flags=re.IGNORECASE,
		)
		if not match:
			return None

		platform = self._resolve_platform(match.group('platform'))
		if platform is None:
			return None

		index = match.group('index') or match.group('index2') or '1'
		return OperationTask(
			platform=platform,
			store_id=match.group('store').strip(),
			operation_id='update_product_category',
			params={'category_index': int(index), 'category_name': match.group('name').strip()},
			mode=mode,
		)

	# ==================== 配送管理解析 ====================

	def _parse_update_delivery_fee(self, text: str, *, mode: ExecutionMode) -> OperationTask | None:
		match = re.match(
			r'^(?:把|将)?\s*'
			rf'(?P<platform>{PLATFORM_PATTERN})\s*'
			r'(?P<store>.+?)\s*'
			r'(?:(?:配送费|外卖费)\s*(?:改成|改为|设为|设置为|修改为|更改为)|'
			r'(?:修改|更改|变更)\s*(?:配送费|外卖费)\s*(?:为|成|到)?)\s*'
			r'(?P<fee>[\d.]+)\s*(?:元)?$',
			text,
			flags=re.IGNORECASE,
		)
		if not match:
			return None

		platform = self._resolve_platform(match.group('platform'))
		if platform is None:
			return None

		return OperationTask(
			platform=platform,
			store_id=match.group('store').strip(),
			operation_id='update_delivery_fee',
			params={'delivery_fee': match.group('fee')},
			mode=mode,
		)

	def _parse_update_delivery_range(self, text: str, *, mode: ExecutionMode) -> OperationTask | None:
		match = re.match(
			r'^(?:把|将)?\s*'
			rf'(?P<platform>{PLATFORM_PATTERN})\s*'
			r'(?P<store>.+?)\s*'
			r'(?:(?:配送范围|配送距离)\s*(?:改成|改为|设为|设置为|修改为|更改为)|'
			r'(?:修改|更改|变更)\s*(?:配送范围|配送距离)\s*(?:为|成|到)?)\s*'
			r'(?P<range>[\d.]+)\s*(?:公里|km)?$',
			text,
			flags=re.IGNORECASE,
		)
		if not match:
			return None

		platform = self._resolve_platform(match.group('platform'))
		if platform is None:
			return None

		return OperationTask(
			platform=platform,
			store_id=match.group('store').strip(),
			operation_id='update_delivery_range',
			params={'delivery_range': match.group('range').strip()},
			mode=mode,
		)

	def _parse_update_min_order_amount(self, text: str, *, mode: ExecutionMode) -> OperationTask | None:
		match = re.match(
			r'^(?:把|将)?\s*'
			rf'(?P<platform>{PLATFORM_PATTERN})\s*'
			r'(?P<store>.+?)\s*'
			r'(?:(?:起送价|最低消费|起送金额)\s*(?:改成|改为|设为|设置为|修改为|更改为)|'
			r'(?:修改|更改|变更)\s*(?:起送价|最低消费|起送金额)\s*(?:为|成|到)?)\s*'
			r'(?P<amount>[\d.]+)\s*(?:元)?$',
			text,
			flags=re.IGNORECASE,
		)
		if not match:
			return None

		platform = self._resolve_platform(match.group('platform'))
		if platform is None:
			return None

		return OperationTask(
			platform=platform,
			store_id=match.group('store').strip(),
			operation_id='update_min_order_amount',
			params={'min_order_amount': match.group('amount')},
			mode=mode,
		)

	# ==================== 评价管理解析 ====================

	def _parse_reply_to_review(self, text: str, *, mode: ExecutionMode) -> OperationTask | None:
		match = re.match(
			r'^(?:给|为)?\s*'
			rf'(?P<platform>{PLATFORM_PATTERN})\s*'
			r'(?P<store>.+?)\s*'
			r'(?:(?:最新)?评价\s*(?:回复|答复)|(?:回复|答复)\s*(?:最新)?评价)\s*'
			r'[:：]?\s*'
			r'(?P<reply>.+)$',
			text,
			flags=re.IGNORECASE,
		)
		if not match:
			return None

		platform = self._resolve_platform(match.group('platform'))
		if platform is None:
			return None

		return OperationTask(
			platform=platform,
			store_id=match.group('store').strip(),
			operation_id='reply_to_review',
			params={'reply_content': match.group('reply').strip()},
			mode=mode,
		)

	# ==================== 查看类解析 ====================

	def _parse_view_order_detail(self, text: str, *, mode: ExecutionMode) -> OperationTask | None:
		match = re.match(
			r'(?:查看|看|查)\s*'
			rf'(?P<platform>{PLATFORM_PATTERN})\s*'
			r'(?P<store>.+?)\s*'
			r'(?:(?:最新)?订单详情|订单详细信息)',
			text,
			flags=re.IGNORECASE,
		)
		if not match:
			return None

		platform = self._resolve_platform(match.group('platform'))
		if platform is None:
			return None

		return OperationTask(
			platform=platform,
			store_id=match.group('store').strip(),
			operation_id='view_order_detail',
			params={'order_id': 'latest'},
			mode=ExecutionMode.PREPARE,
		)

	def _parse_view_order_list(self, text: str, *, mode: ExecutionMode) -> OperationTask | None:
		match = re.match(
			r'(?:查看|看|查)\s*'
			rf'(?P<platform>{PLATFORM_PATTERN})\s*'
			r'(?P<store>.+?)\s*'
			r'订单列表',
			text,
			flags=re.IGNORECASE,
		)
		if not match:
			return None

		platform = self._resolve_platform(match.group('platform'))
		if platform is None:
			return None

		return OperationTask(
			platform=platform,
			store_id=match.group('store').strip(),
			operation_id='view_order_list',
			params={'order_status': 'all'},
			mode=ExecutionMode.PREPARE,
		)

	def _parse_view_sales_report(self, text: str, *, mode: ExecutionMode) -> OperationTask | None:
		match = re.match(
			r'(?:查看|看|查)\s*'
			rf'(?P<platform>{PLATFORM_PATTERN})\s*'
			r'(?P<store>.+?)\s*'
			r'(?:(?:今天|今日|本周|本月)?销售报表|(?:今天|今日|本周|本月)?销售数据)',
			text,
			flags=re.IGNORECASE,
		)
		if not match:
			return None

		platform = self._resolve_platform(match.group('platform'))
		if platform is None:
			return None

		return OperationTask(
			platform=platform,
			store_id=match.group('store').strip(),
			operation_id='view_sales_report',
			params={'start_date': 'today', 'end_date': 'today'},
			mode=ExecutionMode.PREPARE,
		)

	def _parse_view_business_analysis(self, text: str, *, mode: ExecutionMode) -> OperationTask | None:
		match = re.match(
			r'(?:查看|看|查)\s*'
			rf'(?P<platform>{PLATFORM_PATTERN})\s*'
			r'(?P<store>.+?)\s*'
			r'(?:经营分析|经营数据|营业分析)',
			text,
			flags=re.IGNORECASE,
		)
		if not match:
			return None

		platform = self._resolve_platform(match.group('platform'))
		if platform is None:
			return None

		return OperationTask(
			platform=platform,
			store_id=match.group('store').strip(),
			operation_id='view_business_analysis',
			params={},
			mode=ExecutionMode.PREPARE,
		)

	def _parse_view_settlement_detail(self, text: str, *, mode: ExecutionMode) -> OperationTask | None:
		match = re.match(
			r'(?:查看|看|查)\s*'
			rf'(?P<platform>{PLATFORM_PATTERN})\s*'
			r'(?P<store>.+?)\s*'
			r'(?:(?:今天|今日|本周|本月)?结算明细|结算详情|账单)',
			text,
			flags=re.IGNORECASE,
		)
		if not match:
			return None

		platform = self._resolve_platform(match.group('platform'))
		if platform is None:
			return None

		return OperationTask(
			platform=platform,
			store_id=match.group('store').strip(),
			operation_id='view_settlement_detail',
			params={'start_date': 'month_start', 'end_date': 'today'},
			mode=ExecutionMode.PREPARE,
		)
