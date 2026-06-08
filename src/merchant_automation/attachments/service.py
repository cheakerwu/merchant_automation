"""Attachment service — handles Feishu image download and local storage."""

from __future__ import annotations

import logging
from pathlib import Path

from merchant_automation.feishu.resource import FeishuResourceDownloader
from merchant_automation.tasks.models import Attachment
from merchant_automation.tasks.queue import TaskQueue

logger = logging.getLogger(__name__)


class AttachmentService:
    """Manages attachment lifecycle: store, download, and select."""

    def __init__(self, queue: TaskQueue, downloader: FeishuResourceDownloader | None) -> None:
        self._queue = queue
        self._downloader = downloader

    async def store_feishu_image(
        self,
        *,
        tenant_key: str,
        chat_id: str,
        message_id: str,
        user_id: str,
        image_key: str,
        file_name: str | None = None,
        mime_type: str | None = None,
        file_size: int | None = None,
    ) -> Attachment:
        """Store a Feishu image attachment metadata."""
        attachment = Attachment(
            tenant_key=tenant_key,
            chat_id=chat_id,
            message_id=message_id,
            uploaded_by_user_id=user_id,
            file_type='image',
            file_name=file_name or 'image',
            mime_type=mime_type or 'image/*',
            feishu_file_key=image_key,
            size_bytes=file_size,
            status='stored',
        )
        await self._queue.add_attachment(attachment)
        return attachment

    async def store_feishu_file(
        self,
        *,
        tenant_key: str,
        chat_id: str,
        message_id: str,
        user_id: str,
        file_key: str,
        file_name: str | None = None,
        mime_type: str | None = None,
        file_size: int | None = None,
    ) -> Attachment:
        """Store a Feishu file attachment metadata."""
        attachment = Attachment(
            tenant_key=tenant_key,
            chat_id=chat_id,
            message_id=message_id,
            uploaded_by_user_id=user_id,
            file_type='file',
            file_name=file_name,
            mime_type=mime_type,
            feishu_file_key=file_key,
            size_bytes=file_size,
            status='stored',
        )
        await self._queue.add_attachment(attachment)
        return attachment

    async def ensure_local_file(self, attachment: Attachment) -> Attachment:
        """Download attachment to local storage if not already downloaded."""
        if self._downloader is None:
            return attachment

        if attachment.file_type != 'image' or not attachment.feishu_file_key:
            return attachment

        downloaded = await self._downloader.ensure_local_file(attachment)
        if downloaded != attachment:
            await self._queue.update_attachment(downloaded)
        return downloaded

    async def get_recent_images(
        self,
        chat_id: str,
        user_id: str | None = None,
        limit: int = 5,
    ) -> list[Attachment]:
        """Get recent image attachments for a chat."""
        attachments = await self._queue.get_recent_attachments(chat_id=chat_id, user_id=user_id, limit=limit)
        return [a for a in attachments if a.file_type == 'image']

    def select_latest_usable_image(self, attachments: list[Attachment]) -> Attachment | None:
        """Select the most recent usable image attachment.

        Priority:
        1. Already downloaded images (local_path exists and status is 'downloaded')
        2. Images with feishu_file_key (can be downloaded)
        """
        for attachment in attachments:
            if attachment.file_type == 'image' and attachment.local_path and attachment.status == 'downloaded':
                return attachment
        for attachment in attachments:
            if attachment.file_type == 'image' and attachment.feishu_file_key:
                return attachment
        return None

    async def resolve_store_photo_attachment(
        self,
        chat_id: str,
        user_id: str,
    ) -> Attachment | None:
        """Resolve the latest usable image attachment for store photo task."""
        attachments = await self.get_recent_images(chat_id, user_id)
        return self.select_latest_usable_image(attachments)
