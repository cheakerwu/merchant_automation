"""User-facing Feishu text helpers."""

from __future__ import annotations

import re


BACKEND_EXPOSURE_PATTERNS = (
    re.compile(r"Dashboard:\s*/dashboard/\S+", re.IGNORECASE),
    re.compile(r"/dashboard/\S*", re.IGNORECASE),
    re.compile(r"\b(recipe_id|operation_id|trace_id|local_path)\b", re.IGNORECASE),
    re.compile(r"(/Users|/private|/tmp|[A-Za-z]:\\)[^\s，。；;]*"),
)


def sanitize_user_message(message: str) -> str:
    normalized = message.strip()
    if "门店管理" in normalized and any(pattern.search(normalized) for pattern in BACKEND_EXPOSURE_PATTERNS):
        return "门店管理入口已准备好，请在飞书内查看账号和门店状态。"
    if "图片已保存" in normalized and any(pattern.search(normalized) for pattern in BACKEND_EXPOSURE_PATTERNS):
        return "图片已保存，可以继续发送门店照片更新指令。"
    for pattern in BACKEND_EXPOSURE_PATTERNS:
        normalized = pattern.sub("", normalized).strip()
    if not normalized:
        return "操作已完成。"
    return normalized
