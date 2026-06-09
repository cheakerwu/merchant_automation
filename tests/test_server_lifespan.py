from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from merchant_automation import server


class _FakeQueue:
	async def start(self) -> None:
		pass

	async def close(self) -> None:
		pass


class _FakeAccountManager:
	async def start(self) -> None:
		pass

	async def close(self) -> None:
		pass

	async def get_all_accounts(self) -> list[object]:
		return []


class _FakeStore:
	def __init__(self, *args: object, **kwargs: object) -> None:
		pass

	def initialize(self) -> None:
		pass

	def upsert_recipe(self, recipe: object) -> None:
		pass

	def save_definition(self, definition: object, source: str = 'default') -> None:
		pass


class _FakePool:
	def __init__(self, *args: object, **kwargs: object) -> None:
		self.shutdown_called = False

	def pending_count(self) -> int:
		return 7

	async def shutdown(self) -> None:
		self.shutdown_called = True


@pytest.mark.asyncio
async def test_lifespan_assigns_global_executor_pool(monkeypatch):
	created_pools: list[_FakePool] = []
	config = SimpleNamespace(
		TASK_DB_PATH=':memory:',
		ATTACHMENT_DOWNLOAD_DIR=None,
		PROFILES_DIR=None,
		MAX_CONCURRENT_TASKS=3,
		SERVER_PORT=8000,
	)

	def fake_pool_factory(*args: object, **kwargs: object) -> _FakePool:
		pool = _FakePool(*args, **kwargs)
		created_pools.append(pool)
		return pool

	async def idle_worker(pool: object) -> None:
		try:
			await asyncio.Event().wait()
		except asyncio.CancelledError:
			raise

	async def noop_recover_stale_tasks() -> None:
		pass

	monkeypatch.setattr(server, 'get_config', lambda: config)
	monkeypatch.setattr(server, 'get_feishu_client', lambda: object())
	monkeypatch.setattr(server, 'FeishuBot', lambda client: object())
	monkeypatch.setattr(server, 'TaskQueue', lambda db_path: _FakeQueue())
	monkeypatch.setattr(server, 'AccountManager', lambda **kwargs: _FakeAccountManager())
	monkeypatch.setattr(server, 'AccountStore', lambda *args, **kwargs: _FakeStore())
	monkeypatch.setattr(server, 'OperationStore', lambda *args, **kwargs: _FakeStore())
	monkeypatch.setattr(server, 'RecipeStore', lambda *args, **kwargs: _FakeStore())
	monkeypatch.setattr(server, 'FeishuResourceDownloader', lambda **kwargs: object())
	monkeypatch.setattr(server, 'LarkFeishuResourceClient', lambda client: object())
	monkeypatch.setattr(server, '_create_llm', lambda: object())
	monkeypatch.setattr(server, '_mount_dashboard', lambda: None)
	monkeypatch.setattr(server, '_recover_stale_tasks', noop_recover_stale_tasks)
	monkeypatch.setattr(server, 'MerchantTaskExecutor', lambda **kwargs: object())
	monkeypatch.setattr(server, 'MerchantTaskExecutorPool', fake_pool_factory)
	monkeypatch.setattr(server, '_worker_loop', idle_worker)
	monkeypatch.setattr(server, '_pool', None)

	async with server.lifespan(SimpleNamespace()):
		assert created_pools
		assert server._pool is created_pools[0]
		assert await server.healthz() == {'status': 'ok', 'pending_tasks': 7}
