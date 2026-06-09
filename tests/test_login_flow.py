from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from merchant_automation import server
from merchant_automation.accounts.models import AccountStatus, LoginStatus


@dataclass
class FakeAccount:
	id: str
	name: str
	platform: str
	profile_dir: str = '/tmp/profile'
	status: AccountStatus = AccountStatus.NEEDS_LOGIN


class FakeFeishuBot:
	def __init__(self) -> None:
		self.replies: list[tuple[str, str]] = []
		self.sent: list[tuple[str, str]] = []

	async def reply_text(self, message_id: str, content: str) -> None:
		self.replies.append((message_id, content))

	async def send_text(self, chat_id: str, content: str) -> None:
		self.sent.append((chat_id, content))


class FakeAccountManager:
	def __init__(self, existing: list[FakeAccount] | None = None) -> None:
		self.existing = existing or []
		self.created: list[tuple[str, str]] = []
		self.updated: list[tuple[str, object]] = []

	async def search_accounts(self, keyword: str) -> list[FakeAccount]:
		return [account for account in self.existing if keyword in account.name]

	async def create_account(self, name: str, platform: str) -> FakeAccount:
		self.created.append((name, platform))
		account = FakeAccount(id='acct-created', name=name, platform=platform)
		self.existing.append(account)
		return account

	async def update_status(self, account_id: str, status: object) -> None:
		self.updated.append((account_id, status))

	async def get_account(self, account_id: str) -> FakeAccount | None:
		for account in self.existing:
			if account.id == account_id:
				return account
		return None

	async def get_all_accounts(self) -> list[FakeAccount]:
		return self.existing


class FakeAccountStore:
	def __init__(self) -> None:
		self.upserted: list[object] = []

	def upsert_account(self, account: object) -> None:
		self.upserted.append(account)


def test_login_browser_start_timeout_defaults_to_sixty(monkeypatch):
	monkeypatch.delenv('TIMEOUT_BrowserStartEvent', raising=False)
	monkeypatch.delenv('TIMEOUT_BrowserLaunchEvent', raising=False)

	server._ensure_login_browser_start_timeout()

	assert os.environ['TIMEOUT_BrowserStartEvent'] == '60'
	assert os.environ['TIMEOUT_BrowserLaunchEvent'] == '60'


def test_login_browser_start_timeout_keeps_larger_existing_value(monkeypatch):
	monkeypatch.setenv('TIMEOUT_BrowserStartEvent', '90')
	monkeypatch.setenv('TIMEOUT_BrowserLaunchEvent', '120')

	server._ensure_login_browser_start_timeout()

	assert os.environ['TIMEOUT_BrowserStartEvent'] == '90'
	assert os.environ['TIMEOUT_BrowserLaunchEvent'] == '120'


@pytest.mark.asyncio
async def test_existing_login_accounts_are_backfilled_to_account_store(monkeypatch):
	account = FakeAccount(
		id='acct-1',
		name='江湖饭焗',
		platform='meituan',
		profile_dir='/tmp/profile',
		status=AccountStatus.ACTIVE,
	)
	account_manager = FakeAccountManager(existing=[account])
	account_store = FakeAccountStore()

	monkeypatch.setattr(server, '_account_manager', account_manager)
	monkeypatch.setattr(server, '_account_store', account_store)

	await server._sync_existing_login_accounts()

	assert len(account_store.upserted) == 1
	synced = account_store.upserted[0]
	assert synced.account_id == 'acct-1'
	assert synced.platform == 'meituan'
	assert synced.username == '江湖饭焗'
	assert synced.profile_path == '/tmp/profile'
	assert synced.login_status == LoginStatus.LOGGED_IN


@pytest.mark.asyncio
async def test_login_command_creates_account_and_starts_headful_login(monkeypatch):
	bot = FakeFeishuBot()
	account_manager = FakeAccountManager()
	account_store = FakeAccountStore()
	started: list[tuple[str, str]] = []

	async def fake_login_flow(account_id: str, chat_id: str) -> None:
		started.append((account_id, chat_id))

	monkeypatch.setattr(server, '_feishu_bot', bot)
	monkeypatch.setattr(server, '_account_manager', account_manager)
	monkeypatch.setattr(server, '_account_store', account_store)
	monkeypatch.setattr(server, '_execute_login_flow', fake_login_flow)

	handled = await server._handle_login_command(
		'登录美团江湖饭焗',
		user_id='user-1',
		chat_id='chat-1',
		message_id='msg-1',
	)
	await asyncio.sleep(0)

	assert handled is True
	assert account_manager.created == [('江湖饭焗', 'meituan')]
	assert started == [('acct-created', 'chat-1')]
	assert bot.replies[0][0] == 'msg-1'
	assert '正在打开浏览器登录 美团/江湖饭焗' in bot.replies[0][1]
	assert len(account_store.upserted) == 1
	synced = account_store.upserted[0]
	assert synced.account_id == 'acct-created'
	assert synced.platform == 'meituan'
	assert synced.username == '江湖饭焗'
	assert synced.profile_path == '/tmp/profile'
	assert synced.login_status == LoginStatus.EXPIRED


@pytest.mark.asyncio
async def test_login_command_reuses_existing_account_and_marks_needs_login(monkeypatch):
	bot = FakeFeishuBot()
	existing = FakeAccount(id='acct-1', name='江湖饭焗', platform='meituan')
	account_manager = FakeAccountManager(existing=[existing])
	started: list[tuple[str, str]] = []

	async def fake_login_flow(account_id: str, chat_id: str) -> None:
		started.append((account_id, chat_id))

	monkeypatch.setattr(server, '_feishu_bot', bot)
	monkeypatch.setattr(server, '_account_manager', account_manager)
	monkeypatch.setattr(server, '_execute_login_flow', fake_login_flow)

	handled = await server._handle_login_command(
		'登录 美团 江湖饭焗',
		user_id='user-1',
		chat_id='chat-1',
		message_id='msg-1',
	)
	await asyncio.sleep(0)

	assert handled is True
	assert account_manager.created == []
	assert account_manager.updated
	assert account_manager.updated[0][0] == 'acct-1'
	assert started == [('acct-1', 'chat-1')]


@pytest.mark.asyncio
@pytest.mark.parametrize('command', ['重新登录 美团 江湖饭焗', '登陆 美团 江湖饭焗', '登入 美团 江湖饭焗'])
async def test_login_command_accepts_common_login_aliases(monkeypatch, command: str):
	bot = FakeFeishuBot()
	existing = FakeAccount(id='acct-1', name='江湖饭焗', platform='meituan')
	account_manager = FakeAccountManager(existing=[existing])
	started: list[tuple[str, str]] = []

	async def fake_login_flow(account_id: str, chat_id: str) -> None:
		started.append((account_id, chat_id))

	monkeypatch.setattr(server, '_feishu_bot', bot)
	monkeypatch.setattr(server, '_account_manager', account_manager)
	monkeypatch.setattr(server, '_execute_login_flow', fake_login_flow)

	handled = await server._handle_login_command(
		command,
		user_id='user-1',
		chat_id='chat-1',
		message_id='msg-1',
	)
	await asyncio.sleep(0)

	assert handled is True
	assert account_manager.updated[0][0] == 'acct-1'
	assert started == [('acct-1', 'chat-1')]


@pytest.mark.asyncio
async def test_open_command_reuses_existing_meituan_account(monkeypatch):
	bot = FakeFeishuBot()
	existing = FakeAccount(id='acct-1', name='江湖饭焗', platform='meituan')
	account_manager = FakeAccountManager(existing=[existing])
	started: list[tuple[str, str]] = []

	async def fake_login_flow(account_id: str, chat_id: str) -> None:
		started.append((account_id, chat_id))

	monkeypatch.setattr(server, '_feishu_bot', bot)
	monkeypatch.setattr(server, '_account_manager', account_manager)
	monkeypatch.setattr(server, '_execute_login_flow', fake_login_flow)

	handled = await server._handle_login_command(
		'打开美团江湖饭焗',
		user_id='user-1',
		chat_id='chat-1',
		message_id='msg-1',
	)
	await asyncio.sleep(0)

	assert handled is True
	assert account_manager.created == []
	assert started == [('acct-1', 'chat-1')]


@pytest.mark.asyncio
async def test_login_flow_notifies_chat_with_send_text(monkeypatch):
	bot = FakeFeishuBot()
	account = FakeAccount(id='acct-1', name='江湖饭焗', platform='meituan')
	account_manager = FakeAccountManager(existing=[account])

	class FakeSession:
		def __init__(self, browser_profile: object) -> None:
			self.browser_profile = browser_profile

		async def start(self) -> None:
			pass

		async def navigate_to(self, url: str) -> None:
			pass

		async def get_current_page_url(self) -> str:
			return 'https://passport.meituan.com/account/unitivelogin'

		async def get_current_page_title(self) -> str:
			return '美团商家登录'

		async def get_current_page(self) -> None:
			return None

		async def close(self) -> None:
			pass

	monkeypatch.setattr(server, '_feishu_bot', bot)
	monkeypatch.setattr(server, '_account_manager', account_manager)
	monkeypatch.setattr(server, 'LOGIN_WAIT_TIMEOUT_SECONDS', 0, raising=False)
	monkeypatch.setattr(server, 'LOGIN_CHECK_POLL_SECONDS', 0, raising=False)
	monkeypatch.setattr('browser_use.BrowserSession', FakeSession)
	monkeypatch.setattr('browser_use.browser.profile.BrowserProfile', lambda **kwargs: SimpleNamespace(**kwargs))

	await server._execute_login_flow('acct-1', 'chat-1')

	assert bot.replies == []
	assert bot.sent
	assert all(chat_id == 'chat-1' for chat_id, _ in bot.sent)
	assert '暂未检测到登录成功' in bot.sent[-1][1]


@pytest.mark.asyncio
async def test_login_flow_waits_for_success_before_closing(monkeypatch):
	bot = FakeFeishuBot()
	account = FakeAccount(id='acct-1', name='江湖饭焗', platform='meituan')
	account_manager = FakeAccountManager(existing=[account])
	account_store = FakeAccountStore()
	created_sessions: list[object] = []

	class FakePage:
		def __init__(self, session: 'FakeSession') -> None:
			self._session = session

		async def evaluate(self, page_function: str) -> str:
			return self._session.page_texts[min(self._session.poll_count, len(self._session.page_texts) - 1)]

	class FakeSession:
		def __init__(self, browser_profile: object) -> None:
			self.browser_profile = browser_profile
			self.started = False
			self.navigated_to: list[str] = []
			self.closed = False
			self.poll_count = 0
			self.urls = [
				'https://passport.meituan.com/account/unitivelogin',
				'https://passport.meituan.com/account/unitivelogin',
				'https://e.waimai.meituan.com/new_fe/home',
			]
			self.titles = ['美团商家登录', '美团商家登录', '美团外卖商家中心']
			self.page_texts = ['账号登录 手机号 验证码', '账号登录 手机号 验证码', '订单管理 商品管理 门店 工作台']
			created_sessions.append(self)

		async def start(self) -> None:
			self.started = True

		async def navigate_to(self, url: str) -> None:
			self.navigated_to.append(url)

		async def get_current_page_url(self) -> str:
			url = self.urls[min(self.poll_count, len(self.urls) - 1)]
			self.poll_count += 1
			return url

		async def get_current_page_title(self) -> str:
			return self.titles[min(self.poll_count - 1, len(self.titles) - 1)]

		async def get_current_page(self) -> FakePage:
			return FakePage(self)

		async def close(self) -> None:
			self.closed = True

	class ForbiddenAgent:
		def __init__(self, *args: object, **kwargs: object) -> None:
			raise AssertionError('login flow should not rely on Agent for manual login detection')

	monkeypatch.setattr(server, '_feishu_bot', bot)
	monkeypatch.setattr(server, '_account_manager', account_manager)
	monkeypatch.setattr(server, '_account_store', account_store)
	monkeypatch.setattr(server, 'LOGIN_WAIT_TIMEOUT_SECONDS', 1, raising=False)
	monkeypatch.setattr(server, 'LOGIN_CHECK_POLL_SECONDS', 0, raising=False)
	monkeypatch.setattr('browser_use.Agent', ForbiddenAgent)
	monkeypatch.setattr('browser_use.BrowserSession', FakeSession)
	monkeypatch.setattr('browser_use.browser.profile.BrowserProfile', lambda **kwargs: SimpleNamespace(**kwargs))

	await server._execute_login_flow('acct-1', 'chat-1')

	assert created_sessions
	session = created_sessions[0]
	assert session.started is True
	assert session.browser_profile.headless is False
	assert session.browser_profile.enable_default_extensions is False
	assert session.browser_profile.user_data_dir == '/tmp/profile'
	assert session.navigated_to == ['https://e.waimai.meituan.com/']
	assert session.closed is True
	assert account_manager.updated[-1][0] == 'acct-1'
	assert str(account_manager.updated[-1][1]) == 'AccountStatus.ACTIVE'
	assert bot.sent[-1] == ('chat-1', '✅ 江湖饭焗 登录成功，登录态已保存。')
	assert account_store.upserted
	synced = account_store.upserted[-1]
	assert synced.account_id == 'acct-1'
	assert synced.login_status == LoginStatus.LOGGED_IN
