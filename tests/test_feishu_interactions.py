from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest

from merchant_automation import server
from merchant_automation.accounts.models import AccountStatus
from merchant_automation.feishu.bot import FeishuBot
from merchant_automation.tasks.models import Task, TaskResult, TaskStatus
from merchant_automation.tasks.queue import TaskQueue


@dataclass
class FakeAccount:
	id: str
	name: str
	platform: str = 'meituan'
	profile_dir: str = '/tmp/profile'
	status: AccountStatus = AccountStatus.ACTIVE
	last_used_at: object | None = None


class FakeTaskQueue:
	def __init__(self) -> None:
		self.submitted: list[object] = []

	async def submit(self, task: object) -> None:
		self.submitted.append(task)

	async def get_pending_tasks(self) -> list[object]:
		return []

	async def get_recent_tasks(self, chat_id: str, user_id: str | None = None, limit: int = 5) -> list[object]:
		return []

	async def get_events(self, task_id: str) -> list[object]:
		return []

	async def get_recent_attachments(self, chat_id: str, user_id: str | None = None, limit: int = 5) -> list[object]:
		return []


class FakeAccountManager:
	def __init__(self, accounts: list[FakeAccount] | None = None) -> None:
		self.accounts = accounts or []
		self.updated: list[tuple[str, AccountStatus]] = []

	async def get_all_accounts(self) -> list[FakeAccount]:
		return self.accounts

	async def get_account(self, account_id: str) -> FakeAccount | None:
		for account in self.accounts:
			if account.id == account_id:
				return account
		return None

	async def update_status(self, account_id: str, status: AccountStatus) -> None:
		self.updated.append((account_id, status))


class FakeFeishuBot:
	def __init__(self, *, allow_task_cards: bool = False) -> None:
		self.cards: list[tuple[str, dict]] = []
		self.sent_cards: list[tuple[str, dict]] = []
		self.texts: list[tuple[str, str]] = []
		self.task_cards: list[tuple[str, object]] = []
		self.allow_task_cards = allow_task_cards
		self._real = FeishuBot(object())  # type: ignore[arg-type]

	async def reply_card(self, message_id: str, card: dict) -> None:
		self.cards.append((message_id, card))

	async def reply_text(self, message_id: str, content: str) -> None:
		self.texts.append((message_id, content))

	async def send_card(self, chat_id: str, card: dict) -> None:
		self.sent_cards.append((chat_id, card))

	async def send_text(self, chat_id: str, content: str) -> None:
		self.texts.append((chat_id, content))

	def build_help_card(self) -> dict:
		return self._real.build_help_card()

	def build_account_card(self, accounts: list[object]) -> dict:
		return self._real.build_account_card(accounts)

	def build_attachment_card(self, attachments: list[object]) -> dict:
		return self._real.build_attachment_card(attachments)  # type: ignore[arg-type]

	async def reply_task_card(self, message_id: str, task: object) -> str:
		if not self.allow_task_cards:
			raise AssertionError('system commands should not create task cards')
		self.task_cards.append((message_id, task))
		return ''


def _visible_payload(bot: FakeFeishuBot) -> str:
	return json.dumps(
		{
			'reply_cards': bot.cards,
			'sent_cards': bot.sent_cards,
			'texts': bot.texts,
		},
		ensure_ascii=False,
	)


async def _send_text(text: str, *, allow_task_cards: bool = False) -> tuple[FakeTaskQueue, FakeFeishuBot]:
	queue = FakeTaskQueue()
	bot = FakeFeishuBot(allow_task_cards=allow_task_cards)
	server._pool = None
	server._account_manager = FakeAccountManager([FakeAccount(id='acct-1', name='江湖饭焗')])  # type: ignore[assignment]
	server._task_queue = queue  # type: ignore[assignment]
	server._feishu_bot = bot  # type: ignore[assignment]

	await server._handle_message_event(
		{
			'message': {
				'chat_id': 'chat-1',
				'message_id': 'msg-1',
				'message_type': 'text',
				'content': json.dumps({'text': text}),
			},
			'sender': {'sender_id': {'open_id': 'user-1'}},
		}
	)
	return queue, bot


@pytest.mark.asyncio
async def test_help_phrase_replies_help_card_before_task_submission():
	queue, bot = await _send_text('帮我看一下帮助')

	assert queue.submitted == []
	assert bot.cards
	assert bot.cards[0][0] == 'msg-1'
	card_text = json.dumps(bot.cards[0][1], ensure_ascii=False)
	assert '商家后台助手' in card_text
	assert '搜索咖啡' not in card_text


@pytest.mark.asyncio
async def test_account_list_phrase_replies_account_card_before_task_submission():
	queue, bot = await _send_text('账号列表')

	assert queue.submitted == []
	assert bot.cards
	card_text = json.dumps(bot.cards[0][1], ensure_ascii=False)
	assert '账号' in card_text
	assert '江湖饭焗' in card_text


@pytest.mark.asyncio
@pytest.mark.parametrize('phrase', ['账号详情', '账户详情', '查看账号'])
async def test_account_detail_alias_replies_account_card_before_task_submission(phrase: str):
	queue, bot = await _send_text(phrase)

	assert queue.submitted == []
	assert bot.cards
	card_text = json.dumps(bot.cards[0][1], ensure_ascii=False)
	assert '账号' in card_text
	assert '江湖饭焗' in card_text


@pytest.mark.asyncio
@pytest.mark.parametrize('phrase', ['登陆', '登录'])
async def test_bare_login_alias_replies_login_help_before_task_submission(phrase: str):
	queue, bot = await _send_text(phrase)

	assert queue.submitted == []
	assert bot.task_cards == []
	assert bot.texts
	assert '格式：登录 <平台> <账号/店铺名>' in bot.texts[0][1]


@pytest.mark.asyncio
async def test_store_management_phrase_stays_in_feishu_without_backend_paths():
	queue, bot = await _send_text('门店管理')

	assert queue.submitted == []
	payload = _visible_payload(bot)
	assert 'Dashboard' not in payload
	assert '/dashboard' not in payload
	assert '门店' in payload


@pytest.mark.asyncio
async def test_history_phrase_stays_in_feishu_without_backend_paths():
	queue, bot = await _send_text('历史')

	assert queue.submitted == []
	payload = _visible_payload(bot)
	assert 'Dashboard' not in payload
	assert '/dashboard' not in payload
	assert '状态' in payload


@pytest.mark.asyncio
async def test_history_phrase_renders_recent_success_and_failure_from_task_db(tmp_path):
	queue = TaskQueue(db_path=str(tmp_path / 'tasks.db'))
	await queue.start()
	bot = FakeFeishuBot()
	server._pool = None
	server._account_manager = FakeAccountManager()  # type: ignore[assignment]
	server._task_queue = queue  # type: ignore[assignment]
	server._feishu_bot = bot  # type: ignore[assignment]

	now = datetime.now().replace(microsecond=0)
	success = Task(
		id='task-success-1',
		user_id='user-1',
		chat_id='chat-1',
		message_id='origin-success',
		platform='meituan',
		instruction='把美团 江湖饭焗 电话改成 13800138000',
		created_at=now - timedelta(minutes=5),
		updated_at=now - timedelta(minutes=5),
	)
	failure = Task(
		id='task-failed-1',
		user_id='user-1',
		chat_id='chat-1',
		message_id='origin-failed',
		platform='meituan',
		instruction='把美团 江湖饭焗 门店照片换成刚上传的图片',
		created_at=now - timedelta(minutes=3),
		updated_at=now - timedelta(minutes=3),
	)

	try:
		await queue.submit(success)
		await queue.update_status(
			success.id,
			TaskStatus.COMPLETED,
			result=TaskResult(success=True, message='电话已更新为 13800138000'),
		)
		await queue.submit(failure)
		await queue.update_status(
			failure.id,
			TaskStatus.FAILED,
			error='页面找不到门店照片入口',
			error_message_user='找不到门店照片入口，请检查账号权限',
		)

		handled = await server._handle_special_command('历史', 'user-1', 'chat-1', 'msg-history')
	finally:
		await queue.close()

	assert handled is True
	assert bot.texts
	reply = bot.texts[0][1]
	assert '历史记录正在整理中' not in reply
	assert '今天' in reply
	assert '最近任务' in reply
	assert '已完成' in reply
	assert '电话已更新为 13800138000' in reply
	assert '执行失败' in reply
	assert '找不到门店照片入口，请检查账号权限' in reply
	assert '把美团 江湖饭焗 电话改成' in reply
	assert '把美团 江湖饭焗 门店照片' in reply


@pytest.mark.asyncio
async def test_store_update_task_is_not_misclassified_as_store_management():
	queue, bot = await _send_text('美团江湖饭焗修改门店电话为13888888888', allow_task_cards=True)

	assert len(queue.submitted) == 1
	assert bot.task_cards


@pytest.mark.asyncio
async def test_staff_account_task_is_not_misclassified_as_account_management():
	queue, bot = await _send_text('美团江湖饭焗添加员工账号张三手机号13888888888', allow_task_cards=True)

	assert len(queue.submitted) == 1
	assert bot.task_cards


@pytest.mark.asyncio
async def test_account_login_card_action_starts_login_flow(monkeypatch):
	bot = FakeFeishuBot()
	account_manager = FakeAccountManager([FakeAccount(id='acct-1', name='江湖饭焗')])
	started: list[tuple[str, str]] = []

	async def fake_login_flow(account_id: str, chat_id: str) -> None:
		started.append((account_id, chat_id))

	server._feishu_bot = bot  # type: ignore[assignment]
	server._account_manager = account_manager  # type: ignore[assignment]
	server._account_store = None
	monkeypatch.setattr(server, '_execute_login_flow', fake_login_flow)

	await server._handle_card_action_event(
		{
			'action': {'value': {'action': 'account_login', 'account_id': 'acct-1'}},
			'context': {'open_chat_id': 'chat-1'},
		}
	)
	await asyncio.sleep(0)

	assert account_manager.updated == [('acct-1', AccountStatus.NEEDS_LOGIN)]
	assert started == [('acct-1', 'chat-1')]


@pytest.mark.asyncio
async def test_account_refresh_card_action_sends_current_account_card():
	bot = FakeFeishuBot()
	server._feishu_bot = bot  # type: ignore[assignment]
	server._account_manager = FakeAccountManager([FakeAccount(id='acct-1', name='江湖饭焗')])  # type: ignore[assignment]

	await server._handle_card_action_event(
		{
			'action': {'value': {'action': 'account_refresh'}},
			'context': {'open_chat_id': 'chat-1'},
		}
	)

	assert bot.sent_cards
	card_text = json.dumps(bot.sent_cards[0][1], ensure_ascii=False)
	assert '江湖饭焗' in card_text
