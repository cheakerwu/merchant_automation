from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from merchant_automation.feishu.resource import (
	FeishuResourceDownload,
	FeishuResourceDownloadError,
	FeishuResourceDownloader,
)
from merchant_automation.tasks.models import Attachment


class FakeResourceClient:
	def __init__(self, content: bytes = b"image-bytes", content_type: str = "image/png") -> None:
		self.content = content
		self.content_type = content_type
		self.calls: list[tuple[str, str, str, str | None]] = []

	async def download_message_resource(
		self,
		*,
		message_id: str,
		file_key: str,
		resource_type: str,
		tenant_key: str | None = None,
	) -> FeishuResourceDownload:
		self.calls.append((message_id, file_key, resource_type, tenant_key))
		return FeishuResourceDownload(content=self.content, content_type=self.content_type)


@pytest.mark.asyncio
async def test_downloader_downloads_message_image_to_local_file(tmp_path: Path):
	client = FakeResourceClient(content=b"store-front-bytes", content_type="image/png")
	downloader = FeishuResourceDownloader(client=client, storage_dir=tmp_path)
	attachment = Attachment(
		id="att-1",
		tenant_key="tenant-1",
		message_id="msg-1",
		file_type="image",
		file_name="store-front.png",
		mime_type="image/png",
		feishu_file_key="img-key-1",
	)

	downloaded = await downloader.ensure_local_file(attachment)

	local_path = Path(downloaded.local_path or "")
	assert local_path.exists()
	assert local_path.read_bytes() == b"store-front-bytes"
	assert local_path.suffix == ".png"
	assert local_path.parent.parent == tmp_path
	assert downloaded.sha256 == hashlib.sha256(b"store-front-bytes").hexdigest()
	assert downloaded.size_bytes == len(b"store-front-bytes")
	assert downloaded.status == "downloaded"
	assert client.calls == [("msg-1", "img-key-1", "image", "tenant-1")]


@pytest.mark.asyncio
async def test_downloader_reuses_existing_local_file(tmp_path: Path):
	existing_path = tmp_path / "existing.jpg"
	existing_path.write_bytes(b"already-downloaded")
	client = FakeResourceClient()
	downloader = FeishuResourceDownloader(client=client, storage_dir=tmp_path)
	attachment = Attachment(
		id="att-1",
		message_id="msg-1",
		file_type="image",
		file_name="store-front.jpg",
		feishu_file_key="img-key-1",
		local_path=str(existing_path),
	)

	downloaded = await downloader.ensure_local_file(attachment)

	assert downloaded.local_path == str(existing_path)
	assert downloaded.sha256 == hashlib.sha256(b"already-downloaded").hexdigest()
	assert downloaded.size_bytes == len(b"already-downloaded")
	assert downloaded.status == "downloaded"
	assert client.calls == []


@pytest.mark.asyncio
async def test_downloader_requires_message_id_and_file_key(tmp_path: Path):
	downloader = FeishuResourceDownloader(client=FakeResourceClient(), storage_dir=tmp_path)
	attachment = Attachment(
		id="att-1",
		file_type="image",
		file_name="store-front.png",
	)

	with pytest.raises(FeishuResourceDownloadError):
		await downloader.ensure_local_file(attachment)
