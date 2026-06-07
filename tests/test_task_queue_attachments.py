from __future__ import annotations

import pytest

from merchant_automation.tasks.models import Attachment
from merchant_automation.tasks.queue import TaskQueue


@pytest.mark.asyncio
async def test_update_attachment_persists_download_metadata(tmp_path):
	queue = TaskQueue(db_path=str(tmp_path / "tasks.db"))
	await queue.start()
	try:
		attachment = Attachment(
			id="att-1",
			file_type="image",
			file_name="store-front.png",
			mime_type="image/png",
			feishu_file_key="img-key-1",
			status="stored",
		)
		await queue.add_attachment(attachment)

		downloaded = attachment.model_copy(
			update={
				"local_path": str(tmp_path / "store-front.png"),
				"sha256": "abc123",
				"size_bytes": 345,
				"status": "downloaded",
			}
		)
		await queue.update_attachment(downloaded)

		loaded = await queue.get_attachment("att-1")
	finally:
		await queue.close()

	assert loaded is not None
	assert loaded.local_path == str(tmp_path / "store-front.png")
	assert loaded.sha256 == "abc123"
	assert loaded.size_bytes == 345
	assert loaded.status == "downloaded"
