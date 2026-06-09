from __future__ import annotations

import json

import pytest

from merchant_automation import server
from merchant_automation.operations.binder import BoundOperationTask
from merchant_automation.operations.preflight import PreflightResult
from merchant_automation.operations.schemas import ExecutionMode, OperationTask, RecipeMetadata, RecipeStatus
from merchant_automation.operations.service import OperationPlanningService
from merchant_automation.tasks.models import Attachment


class FakeTaskQueue:
	def __init__(self) -> None:
		self.attachments: list[object] = []
		self.updated: list[object] = []
		self.submitted: list[object] = []
		self.linked: list[tuple[str, str, str]] = []
		self.recent: list[Attachment] = []

	async def add_attachment(self, attachment: object) -> str:
		self.attachments.append(attachment)
		return getattr(attachment, 'id')

	async def update_attachment(self, attachment: object) -> None:
		self.updated.append(attachment)
		for index, existing in enumerate(self.attachments):
			if getattr(existing, 'id', None) == getattr(attachment, 'id', None):
				self.attachments[index] = attachment
				break

	async def submit(self, task: object) -> None:
		self.submitted.append(task)

	async def set_task_card_message_id(self, task_id: str, message_id: str) -> None:
		pass

	async def get_recent_attachments(self, chat_id: str, user_id: str | None = None, limit: int = 5) -> list[Attachment]:
		return self.recent[:limit]

	async def link_attachment(self, task_id: str, attachment_id: str, purpose: str) -> None:
		self.linked.append((task_id, attachment_id, purpose))


class FakeFeishuBot:
	def __init__(self) -> None:
		self.replies: list[tuple[str, str]] = []

	async def reply_text(self, message_id: str, content: str) -> None:
		self.replies.append((message_id, content))

	async def reply_task_card(self, message_id: str, task: object) -> str:
		return 'card-msg-1'


class FakeDownloader:
	def __init__(self, *, fail: bool = False) -> None:
		self.fail = fail
		self.calls: list[Attachment] = []

	async def ensure_local_file(self, attachment: Attachment) -> Attachment:
		self.calls.append(attachment)
		if self.fail:
			raise RuntimeError('download failed')
		return attachment.model_copy(
			update={
				'local_path': f'/tmp/attachments/{attachment.id}.png',
				'sha256': 'abc123',
				'size_bytes': 11,
				'status': 'downloaded',
			}
		)


@pytest.mark.asyncio
async def test_store_photo_text_task_binds_latest_image_attachment(monkeypatch):
	queue = FakeTaskQueue()
	queue.recent = [
		Attachment(
			id='att-1',
			chat_id='chat-1',
			uploaded_by_user_id='user-1',
			file_type='image',
			file_name='store-front.png',
			feishu_file_key='img_v3_abc',
		)
	]
	bot = FakeFeishuBot()
	monkeypatch.setattr(server, '_task_queue', queue)
	monkeypatch.setattr(server, '_feishu_bot', bot)

	await server._handle_message_event(
		{
			'message': {
				'chat_id': 'chat-1',
				'message_id': 'msg-2',
				'message_type': 'text',
				'content': json.dumps({'text': '把美团 江湖饭焗 门店照片换成刚上传的图片'}),
			},
			'sender': {'sender_id': {'open_id': 'user-1'}},
		}
	)

	assert len(queue.submitted) == 1
	task = queue.submitted[0]
	assert task.platform == 'meituan'
	assert task.instruction == '把美团 江湖饭焗 门店照片换成刚上传的图片'
	assert queue.linked == [(task.id, 'att-1', 'store_photo')]


def test_latest_image_param_is_replaced_with_bound_attachment():
	bound = BoundOperationTask(
		task=OperationTask(
			platform='meituan',
			store_id='江湖饭焗',
			operation_id='update_store_decoration_image',
			params={'attachment_id': 'latest_image'},
			mode=ExecutionMode.PREPARE,
		),
		recipe=RecipeMetadata(
			recipe_id='meituan.update_store_decoration_image.v1',
			operation_id='update_store_decoration_image',
			platform='meituan',
			version=1,
			status=RecipeStatus.PREPARE_TESTING,
			allowed_modes={ExecutionMode.PREPARE},
			success_rates={ExecutionMode.PREPARE: 0.75},
		),
		preflight=PreflightResult(allowed=True, requested_mode=ExecutionMode.PREPARE, effective_mode=ExecutionMode.PREPARE),
	)
	attachment = Attachment(
		id='att-1',
		file_type='image',
		file_name='store-front.png',
		feishu_file_key='img_v3_abc',
		local_path='/tmp/attachments/store-front.png',
		sha256='abc123',
	)

	hydrated = server._hydrate_latest_image_attachment(bound, [attachment])

	assert hydrated.task.params['attachment_id'] == 'att-1'
	assert hydrated.task.params['feishu_file_key'] == 'img_v3_abc'
	assert hydrated.task.params['attachment_file_name'] == 'store-front.png'
	assert hydrated.task.params['local_image_path'] == '/tmp/attachments/store-front.png'
	assert hydrated.task.params['attachment_sha256'] == 'abc123'
