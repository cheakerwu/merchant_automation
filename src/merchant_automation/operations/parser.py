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


class OperationParseError(ValueError):
	"""Raised when text cannot be parsed into a supported operation."""


class OperationParser:
	def parse_text(self, text: str, *, mode: ExecutionMode = ExecutionMode.PARSE_ONLY) -> OperationTask:
		normalized = text.strip()

		phone_task = self._parse_update_store_phone(normalized, mode=mode)
		if phone_task is not None:
			return phone_task

		hours_task = self._parse_change_business_hours(normalized, mode=mode)
		if hours_task is not None:
			return hours_task

		store_photo_task = self._parse_update_store_photo(normalized, mode=mode)
		if store_photo_task is not None:
			return store_photo_task

		if '价格' in normalized or '改价' in normalized:
			raise OperationParseError('Unsupported operation: change_product_price')

		raise OperationParseError(f'Unsupported operation text: {text}')

	def _parse_update_store_phone(self, text: str, *, mode: ExecutionMode) -> OperationTask | None:
		match = re.match(
			r'^(?:把|将)?\s*(?P<platform>\S+)\s+(?P<store>\S+)\s+(?:电话|联系电话)\s*(?:改成|改为|设为|设置为)\s*(?P<phone>[\d+\-\s]{7,20})$',
			text,
		)
		if not match:
			return None

		platform = self._resolve_platform(match.group('platform'))
		if platform is None:
			return None

		phone = re.sub(r'\s+', '', match.group('phone'))
		return OperationTask(
			platform=platform,
			store_id=match.group('store'),
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

