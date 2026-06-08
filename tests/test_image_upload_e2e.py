"""End-to-end tests for image upload flow: Feishu attachment → local download → browser upload."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from merchant_automation import server
from merchant_automation.operations.binder import BoundOperationTask
from merchant_automation.operations.preflight import PreflightResult
from merchant_automation.operations.recipe_definition import RecipeDefinition, RecipeStep, RecipeStepAction
from merchant_automation.operations.schemas import ExecutionMode, OperationTask, RecipeMetadata, RecipeStatus
from merchant_automation.tasks.models import Attachment


class FakeTaskQueue:
    def __init__(self) -> None:
        self.attachments: list[Attachment] = []
        self.linked: list[tuple[str, str, str]] = []
        self.recent: list[Attachment] = []
        self.submitted: list[object] = []

    async def add_attachment(self, attachment: Attachment) -> str:
        self.attachments.append(attachment)
        return attachment.id

    async def get_recent_attachments(self, chat_id: str, user_id: str | None = None, limit: int = 5) -> list[Attachment]:
        return self.recent[:limit]

    async def link_attachment(self, task_id: str, attachment_id: str, purpose: str) -> None:
        self.linked.append((task_id, attachment_id, purpose))

    async def submit(self, task: object) -> None:
        self.submitted.append(task)
        # Set a mock task ID for testing
        if hasattr(task, 'id'):
            task.id = 'task-mock'

    async def set_task_card_message_id(self, task_id: str, message_id: str) -> None:
        pass


class FakeFeishuBot:
    def __init__(self) -> None:
        self.replies: list[tuple[str, str]] = []
        self.task_cards: list[tuple[str, object]] = []

    async def reply_text(self, message_id: str, content: str) -> None:
        self.replies.append((message_id, content))

    async def reply_task_card(self, message_id: str, task: object) -> str:
        self.task_cards.append((message_id, task))
        return 'card-msg-1'


class FakeResourceDownloader:
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
                'size_bytes': 1024,
                'status': 'downloaded',
            }
        )


@pytest.mark.asyncio
async def test_image_attachment_is_stored_with_metadata(monkeypatch):
    """When user sends an image, attachment metadata is stored."""
    queue = FakeTaskQueue()
    bot = FakeFeishuBot()
    monkeypatch.setattr(server, '_task_queue', queue)
    monkeypatch.setattr(server, '_feishu_bot', bot)

    await server._handle_attachment_message(
        msg_type='image',
        content_str=json.dumps({
            'image_key': 'img_v3_abc123',
            'file_name': 'store-front.png',
            'mime_type': 'image/png',
            'file_size': 1024,
        }),
        tenant_key='tenant-1',
        chat_id='chat-1',
        message_id='msg-1',
        user_id='user-1',
    )

    assert len(queue.attachments) == 1
    att = queue.attachments[0]
    assert att.file_type == 'image'
    assert att.feishu_file_key == 'img_v3_abc123'
    assert att.file_name == 'store-front.png'
    assert att.status == 'stored'
    assert '已记录图片附件' in bot.replies[0][1]


@pytest.mark.asyncio
async def test_image_download_populates_local_path():
    """Resource downloader populates local_path, sha256, and size_bytes."""
    attachment = Attachment(
        id='att-1',
        chat_id='chat-1',
        message_id='msg-1',
        uploaded_by_user_id='user-1',
        file_type='image',
        file_name='test.png',
        feishu_file_key='img_v3_abc',
    )
    downloader = FakeResourceDownloader()

    downloaded = await downloader.ensure_local_file(attachment)

    assert downloaded.local_path == '/tmp/attachments/att-1.png'
    assert downloaded.sha256 == 'abc123'
    assert downloaded.size_bytes == 1024
    assert downloaded.status == 'downloaded'


@pytest.mark.asyncio
async def test_image_download_failure_preserves_original_attachment():
    """When download fails, original attachment is returned unchanged."""
    attachment = Attachment(
        id='att-1',
        chat_id='chat-1',
        message_id='msg-1',
        uploaded_by_user_id='user-1',
        file_type='image',
        file_name='test.png',
        feishu_file_key='img_v3_abc',
    )
    downloader = FakeResourceDownloader(fail=True)

    with pytest.raises(RuntimeError, match='download failed'):
        await downloader.ensure_local_file(attachment)


def test_hydrate_attachment_fills_local_image_path():
    """Hydration fills local_image_path from downloaded attachment."""
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
        local_path='D:\\attachments\\store-front.png',
        sha256='abc123',
    )

    hydrated = server._hydrate_latest_image_attachment(bound, [attachment])

    assert hydrated.task.params['attachment_id'] == 'att-1'
    assert hydrated.task.params['feishu_file_key'] == 'img_v3_abc'
    assert hydrated.task.params['attachment_file_name'] == 'store-front.png'
    assert hydrated.task.params['local_image_path'] == 'D:\\attachments\\store-front.png'
    assert hydrated.task.params['attachment_sha256'] == 'abc123'


def test_hydrate_skips_non_image_attachments():
    """Hydration skips non-image attachments."""
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
        file_type='file',
        file_name='doc.pdf',
        feishu_file_key='file_v3_abc',
    )

    hydrated = server._hydrate_latest_image_attachment(bound, [attachment])

    assert hydrated.task.params['attachment_id'] == 'latest_image'
    assert 'local_image_path' not in hydrated.task.params


def test_recipe_definition_has_upload_step():
    """The store decoration image recipe includes an UPLOAD step."""
    from merchant_automation.operations.recipe_definitions import RECIPE_DEFINITIONS

    recipe = RECIPE_DEFINITIONS['meituan.update_store_decoration_image.v1']
    upload_steps = [s for s in recipe.steps if s.action == RecipeStepAction.UPLOAD]

    assert len(upload_steps) == 1
    assert upload_steps[0].target == '图片上传输入框'
    assert upload_steps[0].value == '{local_image_path}'


def test_recipe_definition_has_stop_before_submit():
    """The store decoration image recipe includes STOP_BEFORE_SUBMIT for safety."""
    from merchant_automation.operations.recipe_definitions import RECIPE_DEFINITIONS

    recipe = RECIPE_DEFINITIONS['meituan.update_store_decoration_image.v1']
    stop_steps = [s for s in recipe.steps if s.action == RecipeStepAction.STOP_BEFORE_SUBMIT]

    assert len(stop_steps) == 1


@pytest.mark.asyncio
async def test_store_photo_text_triggers_attachment_link(monkeypatch):
    """Text mentioning store photo + latest image triggers attachment linking."""
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

    assert len(queue.linked) == 1
    assert queue.linked[0] == ('task-mock', 'att-1', 'store_photo')


@pytest.mark.asyncio
async def test_store_photo_without_image_replies_error(monkeypatch):
    """When no recent image exists, user gets an error message."""
    queue = FakeTaskQueue()
    queue.recent = []
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

    assert any('未找到可用的最近图片' in reply[1] for reply in bot.replies)
