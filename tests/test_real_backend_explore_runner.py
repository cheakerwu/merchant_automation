from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from merchant_automation.accounts.manager import AccountManager
from merchant_automation.accounts.models import AccountStatus
from merchant_automation.explore import ExplorationRequest, ExplorationRunError, run_exploration
from merchant_automation.operations.schemas import ExecutionMode
from merchant_automation.operations.storage import OperationStore
from merchant_automation.operations.traces import TraceRecorder


class FakeBrowserSession:
	def __init__(self) -> None:
		self.started = False
		self.closed = False
		self.navigated_urls: list[str] = []

	async def start(self) -> None:
		self.started = True

	async def navigate_to(self, url: str) -> None:
		self.navigated_urls.append(url)

	async def close(self) -> None:
		self.closed = True


class FakeRouter:
	def __init__(self) -> None:
		self.bound_task = None
		self.raw_input = None
		self.max_steps = None

	async def execute(self, bound_task, raw_input: str | None = None, max_steps: int = 30):
		self.bound_task = bound_task
		self.raw_input = raw_input
		self.max_steps = max_steps
		return TraceRecorder.start(bound_task, raw_input=raw_input).complete("fake exploration complete")


@pytest.mark.asyncio
async def test_run_exploration_uses_active_account_profile_and_prepare_mode(tmp_path: Path):
	db_path = tmp_path / "tasks.db"
	manager = AccountManager(db_path=str(db_path), profiles_base_dir=str(tmp_path / "profiles"))
	await manager.start()
	try:
		account = await manager.create_account(name="江湖饭焗", platform="meituan")
		await manager.update_status(account.id, AccountStatus.ACTIVE)
	finally:
		await manager.close()

	session = FakeBrowserSession()
	router = FakeRouter()

	result = await run_exploration(
		ExplorationRequest(
			instruction="把美团 江湖饭焗 联系电话改成 13800138000",
			account_keyword="江湖饭焗",
			platform="meituan",
			db_path=str(db_path),
			profiles_dir=str(tmp_path / "profiles"),
			max_steps=12,
		),
		browser_session_factory=lambda profile: session,
		llm_factory=lambda: MagicMock(),
		router_factory=lambda browser_session, llm, store: router,
	)

	assert session.started is True
	assert session.closed is True
	assert session.navigated_urls == ["https://e.waimai.meituan.com/"]
	assert router.raw_input == "把美团 江湖饭焗 联系电话改成 13800138000"
	assert router.max_steps == 12
	assert router.bound_task.task.account_id == account.id
	assert router.bound_task.task.mode == ExecutionMode.PREPARE
	assert result.status == "success"
	assert result.account_id == account.id
	assert result.mode == ExecutionMode.PREPARE

	store = OperationStore(tmp_path / "merchant.db")
	store.initialize()
	traces = store.list_traces()
	assert len(traces) == 1
	assert traces[0].trace_id == result.trace_id


@pytest.mark.asyncio
async def test_run_exploration_requires_matching_account(tmp_path: Path):
	with pytest.raises(ExplorationRunError, match="No account found"):
		await run_exploration(
			ExplorationRequest(
				instruction="把美团 江湖饭焗 联系电话改成 13800138000",
				account_keyword="江湖饭焗",
				platform="meituan",
				db_path=str(tmp_path / "tasks.db"),
				profiles_dir=str(tmp_path / "profiles"),
			),
			browser_session_factory=lambda profile: FakeBrowserSession(),
			llm_factory=lambda: MagicMock(),
			router_factory=lambda browser_session, llm, store: FakeRouter(),
		)
