# Merchant Automation Project Optimization Roadmap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将项目从“飞书到商家后台链路可跑”推进到“交互清晰、解析稳定、执行可控、失败可诊断”的商家运营助手。

**Architecture:** 飞书端先走确定性命令路由，再进入商家操作解析，避免“帮助、账号、状态、历史”等系统指令被 LLM 当作后台任务。用户可见内容统一由 Feishu presenter/card builder 输出，不暴露 Dashboard 路径、后端 route、recipe id、本地文件路径等实现细节。执行侧继续沿用 `OperationPlanningService -> ExecutionRouter -> RecipeStepExecutor/AgentExplorer`，在图片附件、账号门店绑定、配方飞轮和失败归因上补强。

**Tech Stack:** FastAPI, SQLite/aiosqlite, Pydantic, lark-oapi, browser-use, OpenAI-compatible chat model, pytest, pytest-asyncio.

---

## 0. 当前状态锚点

- 飞书 webhook 入口在 `src/merchant_automation/server.py`，`_handle_message_event()` 负责文本、图片、文件消息分流。
- 特殊指令识别在 `src/merchant_automation/server.py` 的 `_classify_special_command()`、`_handle_special_command()`、`_is_account_management_command()`、`_is_store_management_command()`。
- 飞书卡片样式集中在 `src/merchant_automation/feishu/bot.py`，包括 `build_task_card()`、`build_help_card()`、`build_account_card()`、`build_attachment_card()`。
- LLM 泛化解析在 `src/merchant_automation/operations/llm_parser.py`，当前 `HybridParser` 为“正则优先，失败后 LLM”。
- 任务规划入口在 `src/merchant_automation/operations/service.py`，执行入口在 `src/merchant_automation/operations/router.py`。
- 账号持久化在 `src/merchant_automation/accounts/store.py` 和 `src/merchant_automation/accounts/manager.py`，飞书登录同步逻辑在 `src/merchant_automation/server.py` 的 `_sync_existing_login_accounts()`、`_sync_account_store()`、`_update_login_account_status()`。
- 图片自动下载与本地保存链路在 `src/merchant_automation/feishu/resource.py`、`src/merchant_automation/tasks/queue.py`、`src/merchant_automation/server.py` 的 `_handle_attachment_message()`、`_download_attachment_for_storage()`、`_hydrate_latest_image_attachment()`。
- 确定性 Recipe 默认定义在 `src/merchant_automation/operations/recipe_definitions.py`，Recipe 元数据在 `src/merchant_automation/operations/recipes.py`，执行器在 `src/merchant_automation/operations/executor.py`。

---

## 1. 优先级总览

| 优先级 | 方向 | 目标 |
|---|---|---|
| P0 | 商家后台执行成功率 | 图片上传、账号登录态、Recipe 执行路径在真实后台可重复验证 |
| P1 | 飞书端交互体验 | 消除旧项目遗留卡片风格和后端暴露文案，形成统一用户语言 |
| P1 | 系统指令识别 | 帮助、账号、状态、历史、附件、门店等指令稳定命中特殊命令 |
| P1 | 账号与门店绑定 | 任务执行前能明确使用哪个平台账号和门店，缺失时主动追问 |
| P1 | LLM 解析护栏 | LLM 只解析商家后台操作，低置信度不执行，高风险动作需确认 |
| P2 | 附件与图片能力 | 支持图片校验、去重、选择、清理，完整支撑“飞书发图 -> 后台上传” |
| P2 | 可观测性 | 用户看得到进度，开发者查得到 trace、失败分类和修复建议 |
| P2 | 配方飞轮 | 成功探索可沉淀候选 Recipe，人工审核后晋级为确定性路径 |
| P2 | 安全与发布控制 | 操作白名单、群聊权限、commit 门控和审计日志可解释 |
| P3 | 工程结构与测试 | 拆分大文件边界，补 E2E 场景，降低后续改动成本 |

---

## 2. 阶段 M1: 飞书系统指令与商家任务路由分层

**目标:** “帮助、账号、登录、状态、历史、附件、门店”等系统指令永远不进入 LLM 商家操作解析；商家任务才进入 `OperationPlanningService`。

**Files:**
- Modify: `src/merchant_automation/server.py`
- Create: `src/merchant_automation/feishu/commands.py`
- Test: `tests/test_feishu_command_routing.py`
- Extend: `tests/test_feishu_interactions.py`
- Extend: `tests/test_login_flow.py`

- [ ] **Step 1: 新增确定性命令分类器测试**

Create `tests/test_feishu_command_routing.py`:

```python
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
```

- [ ] **Step 2: 运行新测试确认失败**

Run:

```bash
pytest tests/test_feishu_command_routing.py -v
```

Expected:

```text
ModuleNotFoundError: No module named 'merchant_automation.feishu.commands'
```

- [ ] **Step 3: 抽出命令分类模块**

Create `src/merchant_automation/feishu/commands.py`:

```python
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
    return re.sub(r'[\s，。！？?、；;：:,.!`~"“”\'‘’（）()\[\]【】<>《》]+', "", text).lower()


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
    if any(keyword in compact for keyword in ("帮助", "怎么用", "如何使用", "使用说明", "指令说明")):
        return FeishuCommandType.HELP
    if compact in ("状态", "任务", "tasks") or any(keyword in compact for keyword in ("任务状态", "任务进度", "排队", "运行中")):
        return FeishuCommandType.STATUS
    if compact in ("历史", "history") or any(keyword in compact for keyword in ("历史记录", "最近记录", "执行记录")):
        return FeishuCommandType.HISTORY
    if is_account_management_command(compact):
        return FeishuCommandType.ACCOUNTS
    if is_login_help_command(compact):
        return FeishuCommandType.LOGIN_HELP
    if compact in ("附件", "附件列表", "attachments") or any(
        keyword in compact for keyword in ("最近附件", "最近图片", "图片列表", "文件列表", "上传内容")
    ):
        return FeishuCommandType.ATTACHMENTS
    if is_store_management_command(compact):
        return FeishuCommandType.STORES
    return None
```

- [ ] **Step 4: 接入 `server.py` 并删除重复命令常量**

Modify `src/merchant_automation/server.py`:

```python
from merchant_automation.feishu.commands import FeishuCommandType, classify_feishu_command
```

Replace `_classify_special_command()` body:

```python
def _classify_special_command(text: str) -> str | None:
    command = classify_feishu_command(text)
    return command.value if command else None
```

Keep existing `_handle_special_command()` branches unchanged for this phase. Remove duplicated helper functions only after `tests/test_login_flow.py` and `tests/test_feishu_interactions.py` are green, because those tests may import the existing private helpers.

- [ ] **Step 5: 运行命令路由相关测试**

Run:

```bash
pytest tests/test_feishu_command_routing.py tests/test_feishu_interactions.py tests/test_login_flow.py -v
```

Expected:

```text
passed
```

- [ ] **Step 6: Commit**

```bash
git add src/merchant_automation/feishu/commands.py src/merchant_automation/server.py tests/test_feishu_command_routing.py tests/test_feishu_interactions.py tests/test_login_flow.py
git commit -m "fix: route feishu system commands before llm parsing"
```

---

## 3. 阶段 M2: 飞书卡片与文案统一，移除后端暴露内容

**目标:** 飞书端只展示用户能理解的“账号、门店、任务、图片、确认、失败原因”，不展示 Dashboard route、本地路径、recipe id、operation id、trace id、后端表名等实现细节。

**Files:**
- Modify: `src/merchant_automation/feishu/bot.py`
- Modify: `src/merchant_automation/server.py`
- Create: `src/merchant_automation/feishu/presenter.py`
- Extend: `tests/test_feishu_bot_cards.py`
- Extend: `tests/test_feishu_interactions.py`

- [ ] **Step 1: 新增用户可见文案安全测试**

Append to `tests/test_feishu_bot_cards.py`:

```python
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


def test_help_card_does_not_expose_backend_terms(fake_feishu_bot) -> None:
    card = fake_feishu_bot.build_help_card()
    text = _card_text(card)
    forbidden = ("Dashboard", "/dashboard", "recipe_id", "operation_id", "local_path")
    assert all(term not in text for term in forbidden)
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pytest tests/test_feishu_bot_cards.py -v
```

Expected:

```text
ModuleNotFoundError: No module named 'merchant_automation.feishu.presenter'
```

- [ ] **Step 3: 新增飞书 presenter**

Create `src/merchant_automation/feishu/presenter.py`:

```python
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
    return normalized
```

- [ ] **Step 4: 所有 `send_text` 与 `reply_text` 进入前清洗**

Modify `src/merchant_automation/feishu/bot.py`:

```python
from merchant_automation.feishu.presenter import sanitize_user_message
```

At the start of `send_text()` and `reply_text()`:

```python
content = sanitize_user_message(content)
```

- [ ] **Step 5: 改造门店管理回复**

Modify `src/merchant_automation/server.py` `_reply_store_management()` so it returns Feishu-native text:

```python
async def _reply_store_management(message_id: str) -> None:
    accounts = await _account_manager.get_all_accounts()
    lines = ["门店信息会跟随账号登录和任务绑定逐步完善。"]
    if accounts:
        lines.append("当前已配置账号：")
        for account in accounts[:5]:
            platform = getattr(account, "platform", "平台")
            name = getattr(account, "name", "未命名账号")
            lines.append(f"• {platform}/{name}")
    else:
        lines.append("当前还没有已配置账号。")
    lines.append("可以发送“账号列表”查看登录状态，或发送“登录 美团 <店铺名>”添加门店账号。")
    await _feishu_bot.reply_text(message_id, "\n".join(lines))
```

This explicitly replaces old strings such as:

```text
📋 门店管理请访问 Dashboard: /dashboard/stores
```

- [ ] **Step 6: 卡片视觉统一**

Modify `src/merchant_automation/feishu/bot.py`:

```python
HEADER_TITLES = {
    "task": "商家任务",
    "help": "商家后台助手",
    "metrics": "任务指标",
    "attachments": "最近上传",
    "accounts": "账号管理",
}

PLATFORM_NAME = {
    "meituan": "美团",
    "eleme": "饿了么/淘宝闪购",
    "douyin": "抖音来客",
    "taobao": "淘宝",
    "unknown": "未知",
}
```

Use these constants in `build_task_card()`, `build_metrics_card()`, `build_help_card()`, `build_attachment_card()`, and `build_account_card()` to remove repeated old copy and mixed emoji-heavy headers. Keep status colors from `_STATUS_DISPLAY`.

- [ ] **Step 7: 运行飞书卡片测试**

Run:

```bash
pytest tests/test_feishu_bot_cards.py tests/test_feishu_interactions.py -v
```

Expected:

```text
passed
```

- [ ] **Step 8: Commit**

```bash
git add src/merchant_automation/feishu/bot.py src/merchant_automation/feishu/presenter.py src/merchant_automation/server.py tests/test_feishu_bot_cards.py tests/test_feishu_interactions.py
git commit -m "fix: hide backend details from feishu messages"
```

---

## 4. 阶段 M3: LLM 解析护栏与低置信度追问

**目标:** LLM 解析增强泛化能力，但不吞掉系统指令，不越权生成危险任务，不在缺少关键参数时进入执行。

**Files:**
- Modify: `src/merchant_automation/operations/llm_parser.py`
- Modify: `src/merchant_automation/operations/service.py`
- Modify: `src/merchant_automation/server.py`
- Extend: `tests/test_operation_planning_service.py`
- Extend: `tests/test_operation_parser.py`
- Create: `tests/test_llm_parser_guardrails.py`

- [ ] **Step 1: 新增 LLM 护栏测试**

Create `tests/test_llm_parser_guardrails.py`:

```python
import pytest

from merchant_automation.operations.llm_parser import LLMParseError, LLMParser
from merchant_automation.operations.schemas import ExecutionMode


class FakeLLM:
    def __init__(self, completion: str) -> None:
        self.completion = completion

    async def ainvoke(self, messages):
        return type("Response", (), {"completion": self.completion})()


@pytest.mark.asyncio
async def test_llm_rejects_low_confidence_result() -> None:
    parser = LLMParser(FakeLLM('{"operation_id":"update_store_phone","platform":"meituan","store":"江湖饭焗","params":{"phone":"138"},"confidence":0.42}'))
    with pytest.raises(LLMParseError, match="置信度"):
        await parser.parse("改电话", mode=ExecutionMode.PREPARE)


@pytest.mark.asyncio
async def test_llm_rejects_missing_required_params() -> None:
    parser = LLMParser(FakeLLM('{"operation_id":"update_store_phone","platform":"meituan","store":"江湖饭焗","params":{},"confidence":0.96}'))
    with pytest.raises(LLMParseError, match="缺少参数"):
        await parser.parse("把电话改一下", mode=ExecutionMode.PREPARE)


@pytest.mark.asyncio
async def test_llm_rejects_system_command() -> None:
    parser = LLMParser(FakeLLM('{"operation_id":"view_order_list","platform":"meituan","store":"","params":{},"confidence":0.91}'))
    with pytest.raises(LLMParseError, match="系统指令"):
        await parser.parse("账号列表", mode=ExecutionMode.PREPARE)
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pytest tests/test_llm_parser_guardrails.py -v
```

Expected:

```text
FAILED
```

- [ ] **Step 3: LLM prompt 明确排除系统指令**

Modify `src/merchant_automation/operations/llm_parser.py` `PARSE_SYSTEM_PROMPT`:

```python
## 禁止解析为商家后台任务的系统指令

以下输入必须返回 operation_id=null：
- 帮助、help、怎么用、使用说明
- 账号、账号列表、账号状态、登录状态
- 登录帮助、怎么登录、如何登录
- 状态、任务状态、历史、最近记录
- 附件、最近图片、门店列表、门店管理

这些是飞书助手自身指令，不是商家后台操作。
```

- [ ] **Step 4: 结果校验函数**

Add to `LLMParser`:

```python
MIN_CONFIDENCE = 0.75

def _validate_result(self, result: dict[str, Any], original_text: str) -> None:
    from merchant_automation.feishu.commands import classify_feishu_command

    if classify_feishu_command(original_text) is not None:
        raise LLMParseError("系统指令不进入商家后台操作解析")

    operation_id = result.get("operation_id")
    if not operation_id:
        raise LLMParseError(f"无法识别的操作: {result.get('error', '未知错误')}")

    confidence = float(result.get("confidence") or 0)
    if confidence < self.MIN_CONFIDENCE:
        raise LLMParseError(f"解析置信度过低: {confidence:.2f}")

    try:
        contract = self._catalog.get(operation_id)
    except KeyError as exc:
        raise LLMParseError(f"无法识别的操作: {operation_id}") from exc

    params = result.get("params") or {}
    missing = [name for name in contract.required_params if name not in params or params[name] in ("", None)]
    if missing:
        raise LLMParseError(f"缺少参数: {', '.join(missing)}")
```

Call it in `parse()` before building `OperationTask`:

```python
self._validate_result(result, text)
```

- [ ] **Step 5: 规划失败时返回追问型用户文案**

Modify `src/merchant_automation/server.py` where `result.input_issues or result.plan_issues` is handled:

```python
user_reason = _friendly_planning_failure(reason)
await self._set_status(
    task,
    TaskStatus.FAILED,
    error=f"解析失败: {reason}",
    error_type="planning_failed",
    error_message_user=user_reason,
    error_message_internal=str(issues),
)
await self._notify(task.chat_id, user_reason)
```

Add:

```python
def _friendly_planning_failure(reason: str) -> str:
    if "缺少参数" in reason:
        return f"这条指令还缺少关键信息：{reason}。请补充店铺、要修改的内容和目标值。"
    if "置信度" in reason or "无法识别" in reason:
        return "我还没完全理解这条指令。可以换成“把美团 <店铺名> 电话改成 <手机号>”这样的格式再试一次。"
    return f"这条指令暂时无法执行：{reason}"
```

- [ ] **Step 6: 运行解析相关测试**

Run:

```bash
pytest tests/test_llm_parser_guardrails.py tests/test_operation_planning_service.py tests/test_operation_parser.py -v
```

Expected:

```text
passed
```

- [ ] **Step 7: Commit**

```bash
git add src/merchant_automation/operations/llm_parser.py src/merchant_automation/operations/service.py src/merchant_automation/server.py tests/test_llm_parser_guardrails.py tests/test_operation_planning_service.py tests/test_operation_parser.py
git commit -m "fix: add guardrails for llm operation parsing"
```

---

## 5. 阶段 M4: 账号与门店绑定前置检查

**目标:** 当前登录账号信息能可靠写入数据库；任务执行前能确定账号、门店和登录态，缺失时通过飞书卡片引导用户登录或选择。

**Files:**
- Modify: `src/merchant_automation/accounts/store.py`
- Modify: `src/merchant_automation/server.py`
- Modify: `src/merchant_automation/feishu/bot.py`
- Extend: `tests/test_account_store.py`
- Extend: `tests/test_login_flow.py`
- Create: `tests/test_account_task_binding.py`

- [ ] **Step 1: 覆盖账号登录同步写入**

Append to `tests/test_login_flow.py`:

```python
@pytest.mark.asyncio
async def test_login_success_persists_account_store_status(monkeypatch):
    account = FakeAccount(id="acct-1", name="江湖饭焗", platform="meituan")
    account_manager = FakeAccountManager(existing=[account])
    account_store = FakeAccountStore()

    monkeypatch.setattr(server, "_account_manager", account_manager)
    monkeypatch.setattr(server, "_account_store", account_store)

    await server._update_login_account_status(account, AccountStatus.ACTIVE)

    assert account_store.upserted
    synced = account_store.upserted[-1]
    assert synced.account_id == "acct-1"
    assert synced.platform == "meituan"
    assert synced.login_status == LoginStatus.ACTIVE
```

- [ ] **Step 2: 覆盖任务执行前缺账号提醒**

Create `tests/test_account_task_binding.py`:

```python
import pytest

from merchant_automation.tasks.models import Task
from merchant_automation.tasks.queue import TaskQueue


@pytest.mark.asyncio
async def test_task_without_matching_account_fails_with_user_message(tmp_path, monkeypatch):
    # Use the existing server-level fakes from tests/test_login_flow.py when implementing.
    # Expected behavior: no browser session is started; user sees login guidance.
    assert True
```

Replace the placeholder assertion during implementation with concrete fakes for `_planning_service`, `_account_manager`, `_task_queue`, and `_feishu_bot`. The expected user message is:

```text
还没有找到可用的美团账号。请先发送“登录 美团 <店铺名>”完成登录。
```

- [ ] **Step 3: 运行测试确认失败**

Run:

```bash
pytest tests/test_login_flow.py tests/test_account_task_binding.py -v
```

Expected:

```text
FAILED
```

- [ ] **Step 4: 登录状态更新时同步账号库**

Modify `src/merchant_automation/server.py` `_update_login_account_status()`:

```python
async def _update_login_account_status(account: Account, status: AccountStatus) -> None:
    await _account_manager.update_status(account.id, status)
    refreshed = await _account_manager.get_account(account.id)
    _sync_account_store(refreshed or account, status)
```

Ensure `_sync_account_store()` maps status:

```python
login_status = LoginStatus.ACTIVE if status == AccountStatus.ACTIVE else LoginStatus.NEEDS_LOGIN
```

- [ ] **Step 5: 执行前账号解析**

Add to `src/merchant_automation/server.py`:

```python
async def _resolve_task_account(task: Task, bound_task: BoundOperationTask) -> Account | None:
    if task.account_id:
        return await _account_manager.get_account(task.account_id)
    candidates = await _account_manager.find_account_for_message(
        bound_task.task.store_id,
        platform=bound_task.task.platform,
    )
    if candidates:
        return candidates[0]
    return None
```

Use it before creating `BrowserSession`:

```python
account = await _resolve_task_account(task, bound_task)
if account is None:
    raise ValueError(f"还没有找到可用的{bound_task.task.platform}账号。请先发送“登录 美团 <店铺名>”完成登录。")
if account.status != AccountStatus.ACTIVE:
    raise ValueError(f"{account.name} 需要重新登录。请发送“登录 美团 {account.name}”完成登录。")
profile_dir = account.profile_dir
```

- [ ] **Step 6: 账号卡片显示门店绑定状态**

Modify `src/merchant_automation/feishu/bot.py` `build_account_card()` account line:

```python
info_line = f"{icon} **{account.name}** ({platform_display})  {status_text}  最后使用: {time_str}"
```

When store summaries are available in later account store integration, render:

```text
默认门店: <store_name>
```

Do not include database id unless the action value requires it.

- [ ] **Step 7: 运行账号相关测试**

Run:

```bash
pytest tests/test_account_store.py tests/test_login_flow.py tests/test_account_task_binding.py -v
```

Expected:

```text
passed
```

- [ ] **Step 8: Commit**

```bash
git add src/merchant_automation/accounts/store.py src/merchant_automation/server.py src/merchant_automation/feishu/bot.py tests/test_account_store.py tests/test_login_flow.py tests/test_account_task_binding.py
git commit -m "fix: persist account login state before task execution"
```

---

## 6. 阶段 M5: 图片附件流程产品化

**目标:** 支持用户在飞书发图片后，系统自动下载、校验、记录、绑定到门店照片任务，并在真正保存前给出清晰确认。

**Files:**
- Modify: `src/merchant_automation/feishu/resource.py`
- Modify: `src/merchant_automation/tasks/models.py`
- Modify: `src/merchant_automation/tasks/queue.py`
- Modify: `src/merchant_automation/server.py`
- Modify: `src/merchant_automation/feishu/bot.py`
- Extend: `tests/test_feishu_resource_downloader.py`
- Extend: `tests/test_task_queue_attachments.py`
- Extend: `tests/test_image_attachment_flow.py`
- Extend: `tests/test_recipe_executor.py`

- [ ] **Step 1: 附件校验测试**

Append to `tests/test_image_attachment_flow.py`:

```python
def test_image_attachment_user_message_does_not_include_local_path() -> None:
    from merchant_automation.feishu.presenter import sanitize_user_message

    text = "图片已保存：/private/tmp/attachments/a.png"
    assert "/private/tmp" not in sanitize_user_message(text)


def test_latest_image_selection_prefers_downloaded_image() -> None:
    attachments = [
        Attachment(file_type="image", feishu_file_key="img-old", local_path=None, status="stored"),
        Attachment(file_type="image", feishu_file_key="img-new", local_path="/tmp/new.png", status="downloaded"),
    ]
    selected = server._select_latest_usable_image(attachments)
    assert selected is not None
    assert selected.feishu_file_key == "img-new"
```

- [ ] **Step 2: 运行测试确认失败**

Run:

```bash
pytest tests/test_image_attachment_flow.py tests/test_feishu_resource_downloader.py tests/test_task_queue_attachments.py -v
```

Expected:

```text
FAILED
```

- [ ] **Step 3: 增加附件选择函数**

Add to `src/merchant_automation/server.py`:

```python
def _select_latest_usable_image(attachments: list[Attachment]) -> Attachment | None:
    for attachment in attachments:
        if attachment.file_type == "image" and attachment.local_path and attachment.status == "downloaded":
            return attachment
    for attachment in attachments:
        if attachment.file_type == "image" and attachment.feishu_file_key:
            return attachment
    return None
```

Use it in `_resolve_store_photo_attachment()` and `_hydrate_latest_image_attachment()`.

- [ ] **Step 4: 图片格式与大小限制**

Add to `src/merchant_automation/feishu/resource.py`:

```python
MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


def validate_image_resource(content: bytes, content_type: str | None) -> None:
    normalized = (content_type or "").split(";", 1)[0].strip().lower()
    if normalized and normalized not in ALLOWED_IMAGE_TYPES:
        raise FeishuResourceDownloadError(f"暂不支持这种图片格式: {normalized}")
    if len(content) > MAX_IMAGE_BYTES:
        raise FeishuResourceDownloadError("图片超过 10MB，请压缩后重新上传")
```

Call it in `FeishuResourceDownloader.ensure_local_file()` before writing the temp file:

```python
if attachment.file_type == "image":
    validate_image_resource(resource.content, content_type)
```

- [ ] **Step 5: 图片上传成功后发送行动卡片**

Add `build_image_received_card()` to `src/merchant_automation/feishu/bot.py`:

```python
def build_image_received_card(self, attachment: Attachment) -> dict:
    name = attachment.file_name or "图片"
    size = self._format_size(attachment.size_bytes)
    return {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": "图片已保存"}, "template": "green"},
        "elements": [
            {"tag": "div", "fields": [
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**文件:**\n{name}"}},
                {"is_short": True, "text": {"tag": "lark_md", "content": f"**大小:**\n{size}"}},
            ]},
            {"tag": "hr"},
            {"tag": "div", "text": {"tag": "lark_md", "content": "可以继续发送“把美团 <店铺名> 门店照片换成刚上传的图片”。"}},
        ],
    }
```

Use `reply_card()` in `_handle_attachment_message()` when image download succeeds.

- [ ] **Step 6: 真保存前确认**

Current behavior allows explicit store photo task to run `COMMIT`. Change to two-step confirmation:

1. First text task creates a task with `ExecutionMode.PREPARE`.
2. Task card shows “确认保存” button when the prepare trace reaches `STOP_BEFORE_SUBMIT`.
3. Card action `confirm_commit` reruns the same bound task in `ExecutionMode.COMMIT`.

Add action handling in `src/merchant_automation/server.py`:

```python
if action_type == "confirm_commit" and task_id:
    task = await _task_queue.get_task(task_id)
    if task:
        commit_task = task.model_copy(update={"instruction": f"{task.instruction} 确认保存"})
        await _task_queue.submit(commit_task)
        await _feishu_bot.send_text(chat_id, f"已确认保存，任务 {commit_task.id[:8]} 开始执行。")
    return
```

Add a card button in `build_task_card()` for `TaskStatus.AWAITING_APPROVAL`:

```python
{
    "tag": "button",
    "text": {"tag": "plain_text", "content": "确认保存"},
    "type": "primary",
    "value": {"action": "confirm_commit", "task_id": task.id},
}
```

- [ ] **Step 7: 运行图片链路测试**

Run:

```bash
pytest tests/test_image_attachment_flow.py tests/test_feishu_resource_downloader.py tests/test_task_queue_attachments.py tests/test_recipe_executor.py -v
```

Expected:

```text
passed
```

- [ ] **Step 8: Commit**

```bash
git add src/merchant_automation/feishu/resource.py src/merchant_automation/tasks/models.py src/merchant_automation/tasks/queue.py src/merchant_automation/server.py src/merchant_automation/feishu/bot.py tests/test_feishu_resource_downloader.py tests/test_task_queue_attachments.py tests/test_image_attachment_flow.py tests/test_recipe_executor.py
git commit -m "feat: productize feishu image upload flow"
```

---

## 7. 阶段 M6: 任务状态、历史与失败归因

**目标:** 用户能在飞书看到任务处于“已收到、解析中、等待登录、准备保存、等待确认、正在保存、完成、失败”中的哪一步；开发者能从 Dashboard/trace 查到失败类型和修复建议。

**Files:**
- Modify: `src/merchant_automation/tasks/models.py`
- Modify: `src/merchant_automation/tasks/queue.py`
- Modify: `src/merchant_automation/operations/failure.py`
- Modify: `src/merchant_automation/operations/storage.py`
- Modify: `src/merchant_automation/feishu/bot.py`
- Modify: `src/merchant_automation/server.py`
- Extend: `tests/test_task_queue_attachments.py`
- Extend: `tests/test_operation_storage_traces.py`
- Extend: `tests/test_failure_analyzer.py`
- Extend: `tests/test_feishu_bot_cards.py`

- [ ] **Step 1: 定义用户状态标签测试**

Append to `tests/test_feishu_bot_cards.py`:

```python
def test_task_card_shows_user_friendly_failure(fake_feishu_bot, failed_task):
    failed_task.error_type = "login_required"
    failed_task.error_message_user = "账号需要重新登录。请发送“登录 美团 江湖饭焗”。"
    card = fake_feishu_bot.build_task_card(failed_task)
    text = json.dumps(card, ensure_ascii=False)
    assert "login_required" not in text
    assert "账号需要重新登录" in text
```

- [ ] **Step 2: 失败类型映射**

Add to `src/merchant_automation/operations/failure.py`:

```python
USER_FAILURE_MESSAGES = {
    "planning_failed": "我还没理解这条指令，请补充店铺和要修改的内容。",
    "login_required": "账号需要重新登录。",
    "attachment_missing": "没有找到可用图片，请先上传图片。",
    "attachment_download_failed": "图片下载失败，请重新发送图片。",
    "recipe_execution_failed": "后台操作失败，请查看任务详情或稍后重试。",
    "execution_error": "任务执行异常，请稍后重试。",
}


def user_failure_message(error_type: str | None, fallback: str | None = None) -> str:
    if error_type and error_type in USER_FAILURE_MESSAGES:
        return USER_FAILURE_MESSAGES[error_type]
    return fallback or "任务执行失败，请稍后重试。"
```

- [ ] **Step 3: 历史记录改为卡片**

Add `build_history_card(tasks_with_events)` to `src/merchant_automation/feishu/bot.py` with:

```python
{
    "config": {"wide_screen_mode": True},
    "header": {"title": {"tag": "plain_text", "content": "最近任务"}, "template": "blue"},
    "elements": [...]
}
```

Use one `div` per task:

```text
<time> | <status> | <short instruction>
<detail label>: <detail>
```

Replace `_reply_task_history()` plain text reply with `reply_card()`.

- [ ] **Step 4: Dashboard trace 只服务开发者**

Keep Dashboard routes in dashboard module, but do not send Dashboard links to Feishu. In `src/merchant_automation/server.py`, search for `/dashboard`, `Dashboard`, `trace_id`, `recipe_id` and remove them from user-facing calls to `_feishu_bot.send_text()` and `_feishu_bot.reply_text()`.

- [ ] **Step 5: 运行状态与失败测试**

Run:

```bash
pytest tests/test_failure_analyzer.py tests/test_operation_storage_traces.py tests/test_feishu_bot_cards.py tests/test_feishu_interactions.py -v
```

Expected:

```text
passed
```

- [ ] **Step 6: Commit**

```bash
git add src/merchant_automation/tasks/models.py src/merchant_automation/tasks/queue.py src/merchant_automation/operations/failure.py src/merchant_automation/operations/storage.py src/merchant_automation/feishu/bot.py src/merchant_automation/server.py tests/test_task_queue_attachments.py tests/test_operation_storage_traces.py tests/test_failure_analyzer.py tests/test_feishu_bot_cards.py
git commit -m "feat: improve task status and failure visibility"
```

---

## 8. 阶段 M7: Recipe 飞轮与真实后台校准

**目标:** 让 Agent 探索成功的路径沉淀为候选 Recipe；人工审核后晋级，减少后续对 LLM 和 Agent 探索的依赖。

**Files:**
- Modify: `src/merchant_automation/operations/router.py`
- Modify: `src/merchant_automation/operations/synthesizer.py`
- Modify: `src/merchant_automation/operations/recipe_store.py`
- Modify: `src/merchant_automation/operations/recipe_definitions.py`
- Modify: `src/merchant_automation/operations/executor.py`
- Extend: `tests/test_recipe_synthesizer.py`
- Extend: `tests/test_execution_router.py`
- Extend: `tests/test_recipe_store.py`
- Extend: `tests/test_recipe_executor.py`
- Extend: `tests/test_real_backend_explore_runner.py`

- [ ] **Step 1: 真实美团图片上传校准脚本**

Use current CLI entry:

```bash
merchant-explore --instruction "把美团 江湖饭焗 门店照片换成刚上传的图片" --account "江湖饭焗" --platform meituan --mode prepare --keep-open
```

Expected:

```text
outcome=success
```

Manual observation to record in `docs/PLAN-project-optimization-roadmap.md` after validation:

```text
entry_url:
upload target:
save button:
success marker:
known page variants:
```

- [ ] **Step 2: 图片上传 Recipe 定位测试**

Extend `tests/test_recipe_executor.py` with a local page containing:

```html
<button aria-label="门店照片">门店照片</button>
<input type="file" aria-label="图片上传输入框" />
<button>保存</button>
```

Assert `RecipeStepAction.UPLOAD` receives `local_image_path` and fails early when the file does not exist.

- [ ] **Step 3: RecipeDefinition 增加页面版本信息**

Modify `src/merchant_automation/operations/recipe_definition.py`:

```python
page_variant: str | None = None
verified_at: str | None = None
verified_account_id: str | None = None
```

Persist these fields through `RecipeStore.save_definition()` because definitions are stored as JSON payload.

- [ ] **Step 4: 合成 Recipe 不覆盖人工晋级版本**

Extend `tests/test_execution_router.py`:

```python
def test_router_does_not_overwrite_commit_ready_recipe(...):
    ...
```

Expected behavior: `RecipeStatus.PREPARE_READY` and `RecipeStatus.COMMIT_READY` definitions are never overwritten by auto-synthesis.

- [ ] **Step 5: 运行 Recipe 飞轮测试**

Run:

```bash
pytest tests/test_recipe_synthesizer.py tests/test_execution_router.py tests/test_recipe_store.py tests/test_recipe_executor.py tests/test_real_backend_explore_runner.py -v
```

Expected:

```text
passed
```

- [ ] **Step 6: Commit**

```bash
git add src/merchant_automation/operations/router.py src/merchant_automation/operations/synthesizer.py src/merchant_automation/operations/recipe_store.py src/merchant_automation/operations/recipe_definition.py src/merchant_automation/operations/recipe_definitions.py src/merchant_automation/operations/executor.py tests/test_recipe_synthesizer.py tests/test_execution_router.py tests/test_recipe_store.py tests/test_recipe_executor.py tests/test_real_backend_explore_runner.py
git commit -m "feat: harden recipe flywheel for real backend reuse"
```

---

## 9. 阶段 M8: 安全、权限与发布控制

**目标:** 真实保存、批量修改、账号权限相关操作必须可审计、可确认、可回滚到安全模式。

**Files:**
- Modify: `src/merchant_automation/operations/preflight.py`
- Modify: `src/merchant_automation/operations/catalog.py`
- Modify: `src/merchant_automation/server.py`
- Modify: `src/merchant_automation/tasks/queue.py`
- Extend: `tests/test_preflight.py`
- Extend: `tests/test_operation_catalog.py`
- Extend: `tests/test_feishu_interactions.py`

- [ ] **Step 1: 高风险操作二次确认测试**

Extend `tests/test_preflight.py`:

```python
def test_commit_requires_confirmation_for_high_risk_operations():
    policy = CommitPolicy(global_commit_enabled=True, account_commit_allowed=True, store_commit_allowed=True)
    decision = evaluate_commit_policy(
        operation_id="delete_staff_account",
        mode=ExecutionMode.COMMIT,
        policy=policy,
        confirmed=False,
    )
    assert decision.allowed is False
    assert "确认" in decision.reason
```

- [ ] **Step 2: 操作目录标记风险等级**

Modify `src/merchant_automation/operations/catalog.py` operation contracts:

```python
risk_level="high"
```

Use high risk for:

```text
delete_staff_account
update_product_stock
update_product_price
replace_product_image
update_store_decoration_image
```

- [ ] **Step 3: 群聊权限检查**

Add config:

```python
ALLOWED_FEISHU_CHAT_IDS: list[str] = []
```

In `_handle_message_event()`, before creating tasks:

```python
if _config.ALLOWED_FEISHU_CHAT_IDS and chat_id not in _config.ALLOWED_FEISHU_CHAT_IDS:
    await _feishu_bot.reply_text(message_id, "当前群聊未开启商家后台助手，请联系管理员。")
    return
```

- [ ] **Step 4: 审计事件写入**

Use existing `TaskEvent` in `src/merchant_automation/tasks/queue.py` to record:

```text
approval_requested
approval_confirmed
commit_started
commit_completed
commit_failed
```

Include `user_id`, `chat_id`, `operation_id`, `account_id`, and `attachment_id` in `details`.

- [ ] **Step 5: 运行安全测试**

Run:

```bash
pytest tests/test_preflight.py tests/test_operation_catalog.py tests/test_feishu_interactions.py -v
```

Expected:

```text
passed
```

- [ ] **Step 6: Commit**

```bash
git add src/merchant_automation/operations/preflight.py src/merchant_automation/operations/catalog.py src/merchant_automation/server.py src/merchant_automation/tasks/queue.py tests/test_preflight.py tests/test_operation_catalog.py tests/test_feishu_interactions.py
git commit -m "feat: add safety gates for commit operations"
```

---

## 10. 阶段 M9: 工程结构拆分

**目标:** 降低 `server.py` 继续膨胀带来的维护成本，把飞书命令、附件、登录、任务执行桥接拆成清晰服务。

**Files:**
- Create: `src/merchant_automation/feishu/handlers.py`
- Create: `src/merchant_automation/feishu/cards.py`
- Create: `src/merchant_automation/attachments/service.py`
- Create: `src/merchant_automation/accounts/login_service.py`
- Create: `src/merchant_automation/tasks/executor.py`
- Modify: `src/merchant_automation/server.py`
- Move tests into focused files without changing behavior.

- [ ] **Step 1: 先加集成保护测试**

Run before refactor:

```bash
pytest tests/test_feishu_interactions.py tests/test_login_flow.py tests/test_image_attachment_flow.py tests/test_execution_router.py -v
```

Expected:

```text
passed
```

- [ ] **Step 2: 抽 `MerchantTaskExecutor`**

Move `MerchantTaskExecutor` and `MerchantTaskExecutorPool` from `src/merchant_automation/server.py` to `src/merchant_automation/tasks/executor.py`.

Keep constructor signature:

```python
class MerchantTaskExecutor:
    def __init__(
        self,
        config: Settings,
        queue: TaskQueue,
        feishu_bot: FeishuBot,
        planning_service: OperationPlanningService,
        operation_store: OperationStore,
        recipe_store: RecipeStore,
        resource_downloader: FeishuResourceDownloader | None = None,
    ) -> None:
        ...
```

Update imports in `server.py`:

```python
from merchant_automation.tasks.executor import MerchantTaskExecutor, MerchantTaskExecutorPool
```

- [ ] **Step 3: 抽附件服务**

Create `src/merchant_automation/attachments/service.py`:

```python
class AttachmentService:
    def __init__(self, queue: TaskQueue, downloader: FeishuResourceDownloader | None) -> None:
        self._queue = queue
        self._downloader = downloader

    async def store_feishu_image(...):
        ...

    async def latest_usable_image(...):
        ...
```

Move `_download_attachment_for_storage()`, `_select_latest_usable_image()`, `_resolve_store_photo_attachment()` logic into this service.

- [ ] **Step 4: 抽登录服务**

Create `src/merchant_automation/accounts/login_service.py` with:

```python
class LoginService:
    async def start_login(self, platform: str, store_name: str, chat_id: str) -> Account:
        ...

    async def wait_for_login_success(self, account: Account, chat_id: str) -> bool:
        ...
```

Move `_execute_login_flow()`, `_wait_for_login_success()`, `_login_url_for_platform()`, `_detect_login_success()` from `server.py`.

- [ ] **Step 5: `server.py` 只保留 HTTP wiring**

After extraction, `src/merchant_automation/server.py` should retain:

```text
FastAPI app
lifespan setup
webhook verification/decryption
event dispatch
dependency wiring
```

It should not contain browser execution step logic, image download details, or long command alias lists.

- [ ] **Step 6: 运行全量测试**

Run:

```bash
pytest -q
```

Expected:

```text
passed
```

- [ ] **Step 7: Commit**

```bash
git add src/merchant_automation/server.py src/merchant_automation/feishu/handlers.py src/merchant_automation/feishu/cards.py src/merchant_automation/attachments/service.py src/merchant_automation/accounts/login_service.py src/merchant_automation/tasks/executor.py tests
git commit -m "refactor: split feishu server responsibilities"
```

---

## 11. 验收标准

### P0 完成标准

- 使用真实美团账号在 prepare 模式下能打开正确页面、选择图片、停在保存前。
- 使用 commit 模式时，只有用户明确确认后才点击保存。
- 图片不存在、下载失败、账号未登录、Recipe 定位失败时，用户看到的是可理解的处理建议。
- `pytest -q` 全量通过。

### P1 完成标准

- 飞书输入“帮助、账号、账号列表、登录帮助、状态、历史、附件、门店列表”均命中特殊指令，不进入 LLM。
- 飞书端没有 `Dashboard: /dashboard/stores`、`/dashboard/...`、`recipe_id`、`operation_id`、`local_path` 等后端概念。
- 任务卡片、账号卡片、附件卡片、帮助卡片使用统一标题、状态标签和行动按钮。
- LLM 低置信度、缺参数、系统指令误解析都不会进入执行。

### P2 完成标准

- 图片附件有 `sha256`、`size_bytes`、`mime_type`、`status`，重复图片可识别。
- 最近图片选择规则稳定：优先已下载图片，再兜底可下载图片。
- 失败 trace 有用户原因、内部原因、失败类型和修复建议。
- Recipe candidate 不覆盖人工晋级 Recipe。

### P3 完成标准

- `server.py` 只负责 FastAPI wiring 和事件分发。
- 飞书命令、卡片展示、附件处理、登录流程、任务执行桥接都有独立模块。
- 关键链路有 focused tests，新增功能不依赖真实后台才能在 CI 中验证。

---

## 12. 推荐下一步

1. 先执行 M1 和 M2，解决“LLM 接入后帮助/账号等指令无法识别”和“飞书暴露后端内容”的用户可见问题。
2. 再执行 M4，确认登录成功后账号信息写入 `account.db`，并在任务执行前拦截未登录账号。
3. 然后执行 M5，用真实美团后台校准“飞书发图 -> 本地下载 -> 后台上传 -> 用户确认保存”的完整闭环。
4. M6-M9 作为稳定性与工程化阶段，等核心链路稳定后分批做，每个阶段独立提交。

---

## 13. 当前已知风险

- 飞书图片下载依赖租户 token 和消息资源权限，测试环境需要 mock `LarkFeishuResourceClient`，真实环境需要确认机器人具备读取消息资源权限。
- 美团后台页面结构可能按账号或灰度版本不同而变化，Recipe 定位必须保留 LLM/文本兜底。
- 当前项目已有较多本地未提交改动，执行本计划时每个阶段只 stage 对应文件，避免混入无关改动。
- 如果本地环境缺少 `pytest_asyncio`，先安装依赖再运行异步测试；用户已说明可以安装。
