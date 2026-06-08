"""Deterministic Feishu command classification before merchant task parsing."""

from __future__ import annotations

import re
from enum import StrEnum


class FeishuCommandType(StrEnum):
    HELP = "help"
    STATUS = "status"
    HISTORY = "history"
    ACCOUNTS = "accounts"
    LOGIN_HELP = "login_help"
    ATTACHMENTS = "attachments"
    STORES = "stores"


POLITE_COMMAND_PREFIXES = (
    "麻烦帮我",
    "请帮我",
    "帮我",
    "麻烦",
    "请",
    "给我",
    "我想",
    "我要",
    "想",
)

ACCOUNT_COMMAND_ALIASES = {
    "account",
    "accounts",
    "账号",
    "账户",
    "帐号",
    "帐户",
    "账号列表",
    "账户列表",
    "帐号列表",
    "帐户列表",
    "我的账号",
    "我的账户",
    "我的帐号",
    "我的帐户",
    "账号详情",
    "账户详情",
    "帐号详情",
    "帐户详情",
    "账号信息",
    "账户信息",
    "帐号信息",
    "帐户信息",
    "账号管理",
    "账户管理",
    "帐号管理",
    "帐户管理",
    "登录状态",
    "登陆状态",
    "登录情况",
    "登陆情况",
    "账号状态",
    "账户状态",
    "帐号状态",
    "帐户状态",
}

ACCOUNT_QUERY_VERBS = (
    "查看一下",
    "查询一下",
    "查一下",
    "看一下",
    "查看下",
    "查询下",
    "查下",
    "看下",
    "查看",
    "查询",
    "看看",
    "显示",
    "列出",
    "打开",
    "看",
)

ACCOUNT_TASK_CONTEXT_KEYWORDS = (
    "员工",
    "管理员",
    "权限",
    "角色",
)

LOGIN_HELP_ALIASES = {
    "登录",
    "登陆",
    "登入",
    "登录一下",
    "登陆一下",
    "登入一下",
    "登录下",
    "登陆下",
    "登入下",
    "重新登录",
    "重新登陆",
    "登录账号",
    "登陆账号",
    "登录账户",
    "登陆账户",
    "添加账号",
    "添加账户",
    "新增账号",
    "新增账户",
    "登录帮助",
    "登陆帮助",
    "登录说明",
    "登陆说明",
    "怎么登录",
    "怎么登陆",
    "如何登录",
    "如何登陆",
}

LOGIN_VERBS = ("登录", "登陆", "登入", "重新登录", "重新登陆", "打开", "进入")
LOGIN_PLATFORM_NAMES = ("美团外卖", "美团", "饿了么", "抖音来客", "抖音")


def normalize_command_text(text: str) -> str:
    return re.sub(r'[\s，。！？?、；;：:,.!`~"“""''（）()\[\]【】<>《》]+', "", text).lower()


def strip_polite_command_prefix(compact: str) -> str:
    for prefix in POLITE_COMMAND_PREFIXES:
        if compact.startswith(prefix):
            return compact[len(prefix):]
    return compact


def is_account_management_command(compact: str) -> bool:
    if any(keyword in compact for keyword in ACCOUNT_TASK_CONTEXT_KEYWORDS):
        return False

    candidates = {compact, strip_polite_command_prefix(compact)}
    for candidate in candidates:
        if candidate in ACCOUNT_COMMAND_ALIASES:
            return True
        for verb in ACCOUNT_QUERY_VERBS:
            if candidate.startswith(verb) and candidate[len(verb):] in ACCOUNT_COMMAND_ALIASES:
                return True
    return False


def is_login_help_command(compact: str) -> bool:
    if compact in ("登录状态", "登陆状态", "登录情况", "登陆情况"):
        return False

    candidate = strip_polite_command_prefix(compact)
    if candidate in LOGIN_HELP_ALIASES:
        return True
    if any(candidate == f"{verb}{platform}" for verb in LOGIN_VERBS for platform in LOGIN_PLATFORM_NAMES):
        return True
    return candidate.startswith(("怎么", "如何")) and any(verb in candidate for verb in ("登录", "登陆", "登入"))


def is_store_management_command(compact: str) -> bool:
    if compact in ("门店", "店铺", "stores"):
        return True
    query_phrases = (
        "门店列表",
        "店铺列表",
        "我的门店",
        "我的店铺",
        "查看门店",
        "查看店铺",
        "门店管理",
        "店铺管理",
        "门店信息",
        "店铺信息",
    )
    if compact not in query_phrases and not any(compact.startswith(prefix) for prefix in ("查看门店", "查看店铺")):
        return False
    operation_keywords = (
        "改",
        "修改",
        "更改",
        "变更",
        "设置",
        "设为",
        "换成",
        "上传",
        "电话",
        "营业时间",
        "照片",
        "图片",
        "地址",
        "名称",
        "公告",
        "简介",
    )
    return not any(keyword in compact for keyword in operation_keywords)


def classify_feishu_command(text: str) -> FeishuCommandType | None:
    raw = text.strip().lower()
    compact = normalize_command_text(text)
    if raw in ("?", "？") or compact in ("help", "帮助"):
        return FeishuCommandType.HELP
    if is_login_help_command(compact):
        return FeishuCommandType.LOGIN_HELP
    if any(keyword in compact for keyword in ("帮助", "怎么用", "如何使用", "使用说明", "指令说明")):
        return FeishuCommandType.HELP
    if compact in ("状态", "任务", "tasks") or any(keyword in compact for keyword in ("任务状态", "任务进度", "排队", "运行中")):
        return FeishuCommandType.STATUS
    if compact in ("历史", "history") or any(keyword in compact for keyword in ("历史记录", "最近记录", "执行记录")):
        return FeishuCommandType.HISTORY
    if is_account_management_command(compact):
        return FeishuCommandType.ACCOUNTS
    if compact in ("附件", "附件列表", "attachments") or any(
        keyword in compact for keyword in ("最近附件", "最近图片", "图片列表", "文件列表", "上传内容")
    ):
        return FeishuCommandType.ATTACHMENTS
    if is_store_management_command(compact):
        return FeishuCommandType.STORES
    return None
