from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from merchant_automation.server import MerchantTaskExecutorPool


@dataclass
class FakeTask:
	id: str
	account_id: str | None = None


@pytest.mark.asyncio
async def test_pool_serializes_tasks_for_same_account():
	started: list[str] = []
	release_first = asyncio.Event()

	class FakeExecutor:
		async def execute(self, task: FakeTask, cancel_event: asyncio.Event | None = None) -> None:
			started.append(task.id)
			if task.id == 'task-1':
				await release_first.wait()

	pool = MerchantTaskExecutorPool(
		executor=FakeExecutor(),
		task_queue=object(),
		max_concurrent=2,
	)

	await pool.submit(FakeTask(id='task-1', account_id='acct-1'))
	await pool.submit(FakeTask(id='task-2', account_id='acct-1'))
	await asyncio.sleep(0.05)

	assert started == ['task-1']

	release_first.set()
	await asyncio.sleep(0.05)

	assert started == ['task-1', 'task-2']
	await pool.shutdown()
