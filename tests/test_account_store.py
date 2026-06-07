from __future__ import annotations

from pathlib import Path

from merchant_automation.accounts.models import LoginStatus, PlatformAccount, Store
from merchant_automation.accounts.store import AccountStore
from merchant_automation.operations.schemas import ExecutionMode


def _make_account(account_id: str = 'acct-1', platform: str = 'meituan', username: str = 'user1') -> PlatformAccount:
	return PlatformAccount(
		account_id=account_id,
		platform=platform,
		username=username,
	)


def _make_store(store_id: str = 'store-1', platform: str = 'meituan', account_id: str = 'acct-1') -> Store:
	return Store(
		store_id=store_id,
		platform=platform,
		account_id=account_id,
	)


def test_initialize_creates_tables(tmp_path: Path):
	store = AccountStore(tmp_path / 'accounts.db')
	store.initialize()

	assert 'accounts' in store.table_names()
	assert 'stores' in store.table_names()


def test_upsert_and_list_accounts(tmp_path: Path):
	store = AccountStore(tmp_path / 'accounts.db')
	store.initialize()
	a1 = _make_account('acct-1', 'meituan', 'alice')
	a2 = _make_account('acct-2', 'eleme', 'bob')

	store.upsert_account(a1)
	store.upsert_account(a2)

	summaries = store.list_accounts()
	assert len(summaries) == 2
	ids = {s.account_id for s in summaries}
	assert ids == {'acct-1', 'acct-2'}


def test_get_account_returns_full_model(tmp_path: Path):
	store = AccountStore(tmp_path / 'accounts.db')
	store.initialize()
	account = PlatformAccount(
		account_id='acct-1',
		platform='meituan',
		username='alice',
		profile_path='/profiles/alice',
		login_status=LoginStatus.LOGGED_IN,
		default_mode=ExecutionMode.DRY_RUN,
		commit_allowed=True,
		feishu_group_id='g-123',
		last_failure_reason=None,
	)
	store.upsert_account(account)

	loaded = store.get_account('acct-1')

	assert loaded is not None
	assert loaded.account_id == 'acct-1'
	assert loaded.platform == 'meituan'
	assert loaded.username == 'alice'
	assert loaded.profile_path == '/profiles/alice'
	assert loaded.login_status == LoginStatus.LOGGED_IN
	assert loaded.default_mode == ExecutionMode.DRY_RUN
	assert loaded.commit_allowed is True
	assert loaded.feishu_group_id == 'g-123'
	assert loaded.last_failure_reason is None


def test_get_account_returns_none_for_missing(tmp_path: Path):
	store = AccountStore(tmp_path / 'accounts.db')
	store.initialize()

	assert store.get_account('nonexistent') is None


def test_update_login_status(tmp_path: Path):
	store = AccountStore(tmp_path / 'accounts.db')
	store.initialize()
	store.upsert_account(_make_account('acct-1'))

	result = store.update_login_status('acct-1', LoginStatus.EXPIRED)

	assert result is True
	loaded = store.get_account('acct-1')
	assert loaded is not None
	assert loaded.login_status == LoginStatus.EXPIRED


def test_update_login_status_returns_false_for_missing(tmp_path: Path):
	store = AccountStore(tmp_path / 'accounts.db')
	store.initialize()

	result = store.update_login_status('nonexistent', LoginStatus.EXPIRED)

	assert result is False


def test_upsert_and_list_stores(tmp_path: Path):
	store = AccountStore(tmp_path / 'accounts.db')
	store.initialize()
	s1 = _make_store('store-1', 'meituan', 'acct-1')
	s2 = _make_store('store-2', 'eleme', 'acct-1')

	store.upsert_store(s1)
	store.upsert_store(s2)

	summaries = store.list_stores()
	assert len(summaries) == 2
	ids = {s.store_id for s in summaries}
	assert ids == {'store-1', 'store-2'}


def test_list_stores_filters_by_account_id(tmp_path: Path):
	store = AccountStore(tmp_path / 'accounts.db')
	store.initialize()
	store.upsert_store(_make_store('store-1', 'meituan', 'acct-1'))
	store.upsert_store(_make_store('store-2', 'eleme', 'acct-1'))
	store.upsert_store(_make_store('store-3', 'meituan', 'acct-2'))

	summaries = store.list_stores(account_id='acct-1')

	assert len(summaries) == 2
	assert all(s.account_id == 'acct-1' for s in summaries)


def test_get_store_returns_none_for_missing(tmp_path: Path):
	store = AccountStore(tmp_path / 'accounts.db')
	store.initialize()

	assert store.get_store('nonexistent') is None
