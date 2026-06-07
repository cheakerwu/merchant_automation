from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from pydantic import BaseModel, ConfigDict

from merchant_automation.accounts.models import LoginStatus, PlatformAccount, Store
from merchant_automation.operations.schemas import ExecutionMode


class AccountSummary(BaseModel):
	model_config = ConfigDict(extra='forbid')

	account_id: str
	platform: str
	username: str
	login_status: LoginStatus
	default_mode: ExecutionMode
	commit_allowed: bool
	last_failure_reason: str | None = None


class StoreSummary(BaseModel):
	model_config = ConfigDict(extra='forbid')

	store_id: str
	platform: str
	account_id: str
	store_name: str | None = None


class AccountStore:
	def __init__(self, db_path: str | Path) -> None:
		self._db_path = Path(db_path)

	def initialize(self) -> None:
		self._db_path.parent.mkdir(parents=True, exist_ok=True)
		with self._connection() as connection:
			connection.execute(
				'''
				CREATE TABLE IF NOT EXISTS accounts (
					account_id TEXT PRIMARY KEY,
					platform TEXT NOT NULL,
					username TEXT NOT NULL,
					login_status TEXT NOT NULL,
					payload_json TEXT NOT NULL,
					created_at TEXT NOT NULL,
					updated_at TEXT NOT NULL
				)
				'''
			)
			connection.execute(
				'''
				CREATE TABLE IF NOT EXISTS stores (
					store_id TEXT PRIMARY KEY,
					platform TEXT NOT NULL,
					account_id TEXT NOT NULL,
					store_name TEXT,
					payload_json TEXT NOT NULL,
					created_at TEXT NOT NULL,
					updated_at TEXT NOT NULL
				)
				'''
			)

	def table_names(self) -> set[str]:
		with self._connection() as connection:
			rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
		return {row['name'] for row in rows}

	def list_accounts(self) -> list[AccountSummary]:
		with self._connection() as connection:
			rows = connection.execute(
				'''
				SELECT account_id, platform, username, login_status, payload_json
				FROM accounts
				ORDER BY platform, username
				'''
			).fetchall()
		results: list[AccountSummary] = []
		for row in rows:
			payload = json.loads(row['payload_json'])
			results.append(
				AccountSummary(
					account_id=row['account_id'],
					platform=row['platform'],
					username=row['username'],
					login_status=row['login_status'],
					default_mode=ExecutionMode(payload['default_mode']),
					commit_allowed=payload['commit_allowed'],
					last_failure_reason=payload.get('last_failure_reason'),
				)
			)
		return results

	def get_account(self, account_id: str) -> PlatformAccount | None:
		with self._connection() as connection:
			row = connection.execute(
				'SELECT payload_json FROM accounts WHERE account_id = ?',
				(account_id,),
			).fetchone()
		if row is None:
			return None
		return PlatformAccount.model_validate_json(row['payload_json'])

	def upsert_account(self, account: PlatformAccount) -> None:
		now = _now()
		with self._connection() as connection:
			connection.execute(
				'''
				INSERT INTO accounts (account_id, platform, username, login_status, payload_json, created_at, updated_at)
				VALUES (?, ?, ?, ?, ?, ?, ?)
				ON CONFLICT(account_id) DO UPDATE SET
					platform = excluded.platform,
					username = excluded.username,
					login_status = excluded.login_status,
					payload_json = excluded.payload_json,
					updated_at = excluded.updated_at
				''',
				(
					account.account_id,
					account.platform,
					account.username,
					account.login_status.value,
					_dump_model(account),
					now,
					now,
				),
			)

	def update_login_status(self, account_id: str, status: LoginStatus) -> bool:
		with self._connection() as connection:
			row = connection.execute(
				'SELECT payload_json FROM accounts WHERE account_id = ?',
				(account_id,),
			).fetchone()
			if row is None:
				return False
			account = PlatformAccount.model_validate_json(row['payload_json'])
			updated = account.model_copy(update={'login_status': status})
			connection.execute(
				'''
				UPDATE accounts SET login_status = ?, payload_json = ?, updated_at = ?
				WHERE account_id = ?
				''',
				(status.value, _dump_model(updated), _now(), account_id),
			)
		return True

	def list_stores(self, *, account_id: str | None = None) -> list[StoreSummary]:
		sql = 'SELECT store_id, platform, account_id, store_name FROM stores'
		params: tuple[str, ...] = ()
		if account_id is not None:
			sql += ' WHERE account_id = ?'
			params = (account_id,)
		sql += ' ORDER BY platform, store_id'

		with self._connection() as connection:
			rows = connection.execute(sql, params).fetchall()
		return [StoreSummary(**dict(row)) for row in rows]

	def get_store(self, store_id: str) -> Store | None:
		with self._connection() as connection:
			row = connection.execute(
				'SELECT payload_json FROM stores WHERE store_id = ?',
				(store_id,),
			).fetchone()
		if row is None:
			return None
		return Store.model_validate_json(row['payload_json'])

	def upsert_store(self, store: Store) -> None:
		now = _now()
		with self._connection() as connection:
			connection.execute(
				'''
				INSERT INTO stores (store_id, platform, account_id, store_name, payload_json, created_at, updated_at)
				VALUES (?, ?, ?, ?, ?, ?, ?)
				ON CONFLICT(store_id) DO UPDATE SET
					platform = excluded.platform,
					account_id = excluded.account_id,
					store_name = excluded.store_name,
					payload_json = excluded.payload_json,
					updated_at = excluded.updated_at
				''',
				(
					store.store_id,
					store.platform,
					store.account_id,
					store.store_name,
					_dump_model(store),
					now,
					now,
				),
			)

	@contextmanager
	def _connection(self) -> Iterator[sqlite3.Connection]:
		connection = sqlite3.connect(self._db_path)
		connection.row_factory = sqlite3.Row
		try:
			yield connection
			connection.commit()
		finally:
			connection.close()


def _dump_model(model: BaseModel) -> str:
	return json.dumps(model.model_dump(mode='json'), ensure_ascii=False, sort_keys=True)


def _now() -> str:
	return datetime.now(timezone.utc).isoformat()

