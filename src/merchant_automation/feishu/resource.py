"""Download Feishu message resources into local files for browser uploads."""

from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import quote

from merchant_automation.tasks.models import Attachment


@dataclass(frozen=True)
class FeishuResourceDownload:
	content: bytes
	content_type: str | None = None
	file_name: str | None = None


class FeishuResourceDownloadError(RuntimeError):
	"""Raised when a Feishu resource cannot be downloaded or stored."""


class FeishuResourceClient(Protocol):
	async def download_message_resource(
		self,
		*,
		message_id: str,
		file_key: str,
		resource_type: str,
		tenant_key: str | None = None,
	) -> FeishuResourceDownload:
		"""Download a Feishu message resource as bytes."""


class LarkFeishuResourceClient:
	"""Feishu resource client implemented with the lark-oapi SDK raw request path."""

	def __init__(self, client: Any) -> None:
		self._client = client

	async def download_message_resource(
		self,
		*,
		message_id: str,
		file_key: str,
		resource_type: str,
		tenant_key: str | None = None,
	) -> FeishuResourceDownload:
		import lark_oapi as lark

		request = lark.BaseRequest()
		request.http_method = lark.HttpMethod.GET
		request.uri = (
			f"/open-apis/im/v1/messages/{quote(message_id, safe='')}"
			f"/resources/{quote(file_key, safe='')}"
		)
		request.token_types = {lark.AccessTokenType.TENANT}
		request.add_query("type", resource_type)

		option = lark.RequestOption()
		if tenant_key:
			option.tenant_key = tenant_key

		response = await self._client.arequest(request, option)
		raw = getattr(response, "raw", None)
		status_code = getattr(raw, "status_code", None)
		if getattr(response, "code", None) != 0 or status_code is None or not 200 <= status_code < 300:
			raise FeishuResourceDownloadError(
				f"Feishu resource download failed: code={getattr(response, 'code', None)}, status={status_code}"
			)

		content = getattr(raw, "content", None) or b""
		if not content:
			raise FeishuResourceDownloadError("Feishu resource download returned empty content")

		headers = getattr(raw, "headers", {}) or {}
		return FeishuResourceDownload(
			content=content,
			content_type=_header_value(headers, "Content-Type"),
		)


class FeishuResourceDownloader:
	"""Persist Feishu resources locally and return updated attachment metadata."""

	def __init__(self, client: FeishuResourceClient, storage_dir: str | Path) -> None:
		self._client = client
		self._storage_dir = Path(storage_dir)

	async def ensure_local_file(self, attachment: Attachment) -> Attachment:
		"""Return attachment metadata with local_path, sha256, and size_bytes populated."""
		existing_path = Path(attachment.local_path) if attachment.local_path else None
		if existing_path and existing_path.exists():
			content = existing_path.read_bytes()
			return attachment.model_copy(
				update={
					"sha256": hashlib.sha256(content).hexdigest(),
					"size_bytes": len(content),
					"status": "downloaded",
				}
			)

		if not attachment.message_id or not attachment.feishu_file_key:
			raise FeishuResourceDownloadError("Attachment requires message_id and feishu_file_key before download")

		resource = await self._client.download_message_resource(
			message_id=attachment.message_id,
			file_key=attachment.feishu_file_key,
			resource_type=_resource_type_for_attachment(attachment),
			tenant_key=attachment.tenant_key,
		)
		if not resource.content:
			raise FeishuResourceDownloadError("Feishu resource download returned empty content")

		content_type = resource.content_type or attachment.mime_type
		local_path = self._target_path(attachment, resource.file_name, content_type)
		local_path.parent.mkdir(parents=True, exist_ok=True)
		temp_path = local_path.with_suffix(f"{local_path.suffix}.tmp")
		temp_path.write_bytes(resource.content)
		temp_path.replace(local_path)

		return attachment.model_copy(
			update={
				"local_path": str(local_path),
				"sha256": hashlib.sha256(resource.content).hexdigest(),
				"size_bytes": len(resource.content),
				"mime_type": content_type or attachment.mime_type,
				"status": "downloaded",
			}
		)

	def _target_path(self, attachment: Attachment, downloaded_file_name: str | None, content_type: str | None) -> Path:
		created_at = attachment.created_at if attachment.created_at else datetime.now()
		date_dir = created_at.strftime("%Y-%m-%d")
		suffix = _infer_suffix(downloaded_file_name or attachment.file_name, content_type, attachment.file_type)
		return self._storage_dir / date_dir / f"{attachment.id}{suffix}"


def _resource_type_for_attachment(attachment: Attachment) -> str:
	if attachment.file_type == "image":
		return "image"
	if attachment.file_type == "file":
		return "file"
	return attachment.file_type


def _infer_suffix(file_name: str | None, content_type: str | None, file_type: str) -> str:
	if file_name:
		suffix = Path(file_name).suffix
		if suffix:
			return suffix.lower()

	if content_type:
		normalized = content_type.split(";", 1)[0].strip().lower()
		suffix = mimetypes.guess_extension(normalized)
		if suffix:
			return suffix

	if file_type == "image":
		return ".jpg"
	return ".bin"


def _header_value(headers: dict[str, Any], key: str) -> str | None:
	for header_key, value in headers.items():
		if header_key.lower() == key.lower():
			return str(value)
	return None
