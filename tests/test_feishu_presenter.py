import json

from merchant_automation.feishu.presenter import sanitize_user_message


def _card_text(card: dict) -> str:
    return json.dumps(card, ensure_ascii=False)


def test_sanitize_user_message_hides_backend_paths() -> None:
    message = "📋 门店管理请访问 Dashboard: /dashboard/stores"
    assert sanitize_user_message(message) == "门店管理入口已准备好，请在飞书内查看账号和门店状态。"


def test_sanitize_user_message_hides_local_paths() -> None:
    message = "图片已保存：/Users/demo/tasks/attachments/2026-06-08/a.png"
    assert sanitize_user_message(message) == "图片已保存，可以继续发送门店照片更新指令。"


def test_sanitize_user_message_removes_recipe_id() -> None:
    message = "任务执行成功 recipe_id=meituan.update_store_phone.v1"
    sanitized = sanitize_user_message(message)
    assert "recipe_id" not in sanitized
    assert "任务执行成功" in sanitized


def test_sanitize_user_message_removes_operation_id() -> None:
    message = "操作完成 operation_id=update_store_phone"
    sanitized = sanitize_user_message(message)
    assert "operation_id" not in sanitized
    assert "操作完成" in sanitized


def test_sanitize_user_message_preserves_normal_text() -> None:
    message = "任务执行成功，门店电话已更新。"
    assert sanitize_user_message(message) == message
