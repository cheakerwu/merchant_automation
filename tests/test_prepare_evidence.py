from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module

import pytest

from merchant_automation import server
from merchant_automation.operations.binder import BoundOperationTask
from merchant_automation.operations.preflight import PreflightResult
from merchant_automation.operations.schemas import (
	ExecutionMode,
	OperationTask,
	RecipeMetadata,
	RecipeStatus,
)
from merchant_automation.operations.traces import (
	ExecutionTrace,
	TraceOutcome,
	TraceOutcomeStatus,
	TraceStep,
	TraceStepKind,
)
from merchant_automation.tasks.models import Task, TaskStatus


@dataclass
class FakeConfig:
	BROWSER_HEADLESS: bool = True
	BROWSER_USER_DATA_DIR: str | None = None
	LLM_MODEL: str = 'test-model'
	LLM_BASE_URL: str | None = None
	LLM_API_KEY: str = 'test-key'


class FakeQueue:
	def __init__(self) -> None:
		self.status_updates: list[tuple[str, TaskStatus, dict]] = []

	async def update_status(self, task_id: str, status: TaskStatus, **kwargs) -> None:
		self.status_updates.append((task_id, status, kwargs))


class FakeFeishuBot:
	def __init__(self) -> None:
		self.card_updates: list[Task] = []
		self.texts: list[tuple[str, str]] = []
		self.uploads: list[str] = []
		self.images: list[tuple[str, str]] = []

	async def update_task_card(self, task: Task) -> None:
		self.card_updates.append(task.model_copy(deep=True))

	async def send_text(self, chat_id: str, text: str) -> None:
		self.texts.append((chat_id, text))

	async def upload_image(self, image_path: str) -> str | None:
		self.uploads.append(image_path)
		return f'image-key-{len(self.uploads)}'

	async def send_image(self, chat_id: str, image_key: str) -> None:
		self.images.append((chat_id, image_key))


class FakeOperationStore:
	def __init__(self) -> None:
		self.saved_traces: list[tuple[ExecutionTrace, str]] = []

	def save_trace(self, trace: ExecutionTrace, *, run_id: str | None = None) -> str:
		self.saved_traces.append((trace, run_id or ''))
		return 'trace-1'


class FakeRecipeStore:
	def list_definitions(self) -> list[object]:
		return []


class FakeBrowserProfile:
	def __init__(self, **kwargs) -> None:
		self.kwargs = kwargs


class FakeBrowserSession:
	def __init__(self, browser_profile: FakeBrowserProfile) -> None:
		self.browser_profile = browser_profile
		self.closed = False

	async def close(self) -> None:
		self.closed = True


class FakeChatOpenAI:
	def __init__(self, **kwargs) -> None:
		self.kwargs = kwargs


def _bound_prepare_task() -> BoundOperationTask:
	return BoundOperationTask(
		task=OperationTask(
			platform='meituan',
			store_id='江湖饭焗',
			operation_id='update_store_phone',
			params={'phone': '13800138000'},
			mode=ExecutionMode.PREPARE,
		),
		recipe=RecipeMetadata(
			recipe_id='meituan.update_store_phone.v1',
			operation_id='update_store_phone',
			platform='meituan',
			version=1,
			status=RecipeStatus.PREPARE_READY,
		),
		preflight=PreflightResult(
			allowed=True,
			requested_mode=ExecutionMode.PREPARE,
			effective_mode=ExecutionMode.PREPARE,
		),
	)


@pytest.mark.asyncio
async def test_prepare_success_uploads_screenshot_evidence(monkeypatch, tmp_path):
	screenshot_path = tmp_path / 'prepare-evidence.png'
	screenshot_path.write_bytes(b'fake-png')
	trace = ExecutionTrace(
		platform='meituan',
		store_id='江湖饭焗',
		operation_id='update_store_phone',
		recipe_id='meituan.update_store_phone.v1',
		mode=ExecutionMode.PREPARE,
		steps=[
			TraceStep(
				step_number=1,
				kind=TraceStepKind.SCREENSHOT,
				message='prepare 证据截图',
				screenshot_path=str(screenshot_path),
			)
		],
		outcome=TraceOutcome(status=TraceOutcomeStatus.SUCCESS, message='执行完成'),
	)

	class FakeRouter:
		def __init__(self, **kwargs) -> None:
			self.kwargs = kwargs

		async def execute(self, bound_task: BoundOperationTask, raw_input: str | None = None) -> ExecutionTrace:
			return trace

	browser_use = import_module('browser_use')
	profile_module = import_module('browser_use.browser.profile')
	chat_module = import_module('browser_use.llm.openai.chat')
	monkeypatch.setattr(browser_use, 'BrowserSession', FakeBrowserSession)
	monkeypatch.setattr(profile_module, 'BrowserProfile', FakeBrowserProfile)
	monkeypatch.setattr(chat_module, 'ChatOpenAI', FakeChatOpenAI)
	monkeypatch.setattr(server, 'ExecutionRouter', FakeRouter)

	queue = FakeQueue()
	bot = FakeFeishuBot()
	operation_store = FakeOperationStore()
	executor = server.MerchantTaskExecutor(
		config=FakeConfig(),
		queue=queue,
		feishu_bot=bot,
		planning_service=object(),
		operation_store=operation_store,
		recipe_store=FakeRecipeStore(),
	)
	task = Task(
		id='task-12345678',
		user_id='user-1',
		chat_id='chat-1',
		message_id='msg-1',
		platform='meituan',
		instruction='把美团 江湖饭焗 电话改成 13800138000',
	)

	await executor._execute_bound_task(_bound_prepare_task(), task, run_id='run-1')

	assert operation_store.saved_traces == [(trace, 'run-1')]
	assert queue.status_updates
	_, status, kwargs = queue.status_updates[-1]
	assert status == TaskStatus.COMPLETED
	assert kwargs['result'].success is True
	assert kwargs['result'].screenshots == [str(screenshot_path)]
	assert 'prepare 截图证据 1 张' in kwargs['result'].message
	assert bot.uploads == [str(screenshot_path)]
	assert bot.images == [('chat-1', 'image-key-1')]
	assert bot.card_updates[-1].result is not None
	assert bot.card_updates[-1].result.screenshots == [str(screenshot_path)]
