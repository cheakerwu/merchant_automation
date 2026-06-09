import pytest

from merchant_automation.operations.parser import OperationParseError, OperationParser
from merchant_automation.operations.schemas import ExecutionMode


def test_parse_update_store_phone_from_text():
	task = OperationParser().parse_text('把美团 A店 电话改成 13800138000', mode=ExecutionMode.PREPARE)

	assert task.platform == 'meituan'
	assert task.store_id == 'A店'
	assert task.operation_id == 'update_store_phone'
	assert task.params == {'phone': '13800138000'}
	assert task.mode == ExecutionMode.PREPARE


@pytest.mark.parametrize(
	'text',
	[
		'美团江湖饭焗修改商家电话为13888888888',
		'美团 江湖饭焗 修改商家电话为13888888888',
		'Meituan 江湖饭焗 修改商家电话为13888888888',
	],
)
def test_parse_update_store_phone_from_merchant_phone_phrase(text):
	task = OperationParser().parse_text(text, mode=ExecutionMode.PREPARE)

	assert task.platform == 'meituan'
	assert task.store_id == '江湖饭焗'
	assert task.operation_id == 'update_store_phone'
	assert task.params == {'phone': '13888888888'}
	assert task.mode == ExecutionMode.PREPARE


def test_parse_change_business_hours_from_text():
	task = OperationParser().parse_text('美团 A店 营业时间改为 09:00-22:00')

	assert task.platform == 'meituan'
	assert task.store_id == 'A店'
	assert task.operation_id == 'change_business_hours'
	assert task.params == {
		'business_hours': '09:00-22:00',
		'start_time': '09:00',
		'end_time': '22:00',
	}
	assert task.mode == ExecutionMode.PARSE_ONLY


def test_parse_update_store_photo_with_latest_image():
	task = OperationParser().parse_text('把美团 江湖饭焗 门店照片换成刚上传的图片')

	assert task.platform == 'meituan'
	assert task.store_id == '江湖饭焗'
	assert task.operation_id == 'update_store_decoration_image'
	assert task.params == {'attachment_id': 'latest_image'}


def test_parse_unsupported_price_task_raises_error():
	with pytest.raises(OperationParseError) as exc:
		OperationParser().parse_text('把美团 A店 牛肉饭价格改成 19.9')

	assert 'Unsupported operation' in str(exc.value)
