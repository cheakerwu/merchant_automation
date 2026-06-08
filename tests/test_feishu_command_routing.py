import pytest

from merchant_automation.feishu.commands import FeishuCommandType, classify_feishu_command


@pytest.mark.parametrize(
    "text, expected",
    [
        ("帮助", FeishuCommandType.HELP),
        ("help", FeishuCommandType.HELP),
        ("怎么用", FeishuCommandType.HELP),
        ("账号", FeishuCommandType.ACCOUNTS),
        ("账号列表", FeishuCommandType.ACCOUNTS),
        ("帮我查一下账号状态", FeishuCommandType.ACCOUNTS),
        ("登录帮助", FeishuCommandType.LOGIN_HELP),
        ("如何登录美团", FeishuCommandType.LOGIN_HELP),
        ("状态", FeishuCommandType.STATUS),
        ("任务进度", FeishuCommandType.STATUS),
        ("历史", FeishuCommandType.HISTORY),
        ("最近记录", FeishuCommandType.HISTORY),
        ("附件", FeishuCommandType.ATTACHMENTS),
        ("最近图片", FeishuCommandType.ATTACHMENTS),
        ("门店列表", FeishuCommandType.STORES),
        ("查看门店", FeishuCommandType.STORES),
    ],
)
def test_classify_system_commands(text: str, expected: FeishuCommandType) -> None:
    assert classify_feishu_command(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "美团江湖饭焗修改商家电话为13888888888",
        "把美团 江湖饭焗 门店照片换成刚上传的图片",
        "把美团 江湖饭焗 营业时间改为 09:00-22:00",
        "给美团江湖饭焗添加员工账号",
    ],
)
def test_classify_merchant_tasks_as_none(text: str) -> None:
    assert classify_feishu_command(text) is None
