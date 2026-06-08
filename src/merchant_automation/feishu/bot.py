from __future__ import annotations

import json
import logging
from pathlib import Path

import lark_oapi as lark

logger = logging.getLogger(__name__)
from lark_oapi.api.im.v1 import (
	CreateImageRequest,
	CreateImageRequestBody,
	CreateMessageRequest,
	CreateMessageRequestBody,
	ReplyMessageRequest,
	ReplyMessageRequestBody,
	UpdateMessageRequest,
	UpdateMessageRequestBody,
)

from merchant_automation.tasks.models import Attachment, Task, TaskMetrics, TaskStatus

# Status -> (display label, header color)
_STATUS_DISPLAY: dict[str, tuple[str, str]] = {
	TaskStatus.PENDING.value: ("等待中", "grey"),
	TaskStatus.PARSING.value: ("解析中", "blue"),
	TaskStatus.PREPARING.value: ("准备中", "blue"),
	TaskStatus.EXECUTING.value: ("执行中", "blue"),
	TaskStatus.AWAITING_APPROVAL.value: ("等待确认", "orange"),
	TaskStatus.COMPLETED.value: ("已完成", "green"),
	TaskStatus.FAILED.value: ("失败", "red"),
	TaskStatus.CANCELLED.value: ("已取消", "grey"),
}


class FeishuBot:
	"""Feishu bot that sends messages and interactive cards via the lark-oapi SDK."""

	def __init__(self, client: lark.Client) -> None:
		self._client = client

	async def send_text(self, chat_id: str, content: str) -> None:
		"""Send a plain text message to a chat."""
		from merchant_automation.feishu.presenter import sanitize_user_message
		content = sanitize_user_message(content)
		body = (
			CreateMessageRequestBody.builder()
			.receive_id(chat_id)
			.msg_type("text")
			.content(json.dumps({"text": content}))
			.build()
		)
		request = (
			CreateMessageRequest.builder()
			.receive_id_type("chat_id")
			.request_body(body)
			.build()
		)
		response = await self._client.im.v1.message.acreate(request)
		if not response.success():
			raise RuntimeError(
				f"Failed to send text message: {response.code} {response.msg}"
			)

	async def send_card(self, chat_id: str, card: dict) -> None:
		"""Send an interactive card message to a chat."""
		body = (
			CreateMessageRequestBody.builder()
			.receive_id(chat_id)
			.msg_type("interactive")
			.content(json.dumps(card))
			.build()
		)
		request = (
			CreateMessageRequest.builder()
			.receive_id_type("chat_id")
			.request_body(body)
			.build()
		)
		response = await self._client.im.v1.message.acreate(request)
		if not response.success():
			raise RuntimeError(
				f"Failed to send card message: {response.code} {response.msg}"
			)

	async def reply_text(self, message_id: str, content: str) -> None:
		"""Reply to a specific message with plain text."""
		from merchant_automation.feishu.presenter import sanitize_user_message
		content = sanitize_user_message(content)
		body = (
			ReplyMessageRequestBody.builder()
			.msg_type("text")
			.content(json.dumps({"text": content}))
			.build()
		)
		request = (
			ReplyMessageRequest.builder()
			.message_id(message_id)
			.request_body(body)
			.build()
		)
		response = await self._client.im.v1.message.areply(request)
		if not response.success():
			raise RuntimeError(
				f"Failed to reply to message: {response.code} {response.msg}"
			)

	async def reply_card(self, message_id: str, card: dict) -> None:
		"""Reply to a specific message with an interactive card."""
		body = (
			ReplyMessageRequestBody.builder()
			.msg_type("interactive")
			.content(json.dumps(card))
			.build()
		)
		request = (
			ReplyMessageRequest.builder()
			.message_id(message_id)
			.request_body(body)
			.build()
		)
		response = await self._client.im.v1.message.areply(request)
		if not response.success():
			raise RuntimeError(
				f"Failed to reply with card: {response.code} {response.msg}"
			)

	async def reply_task_card(self, message_id: str, task: Task) -> str | None:
		"""Reply with a task card and return the created card message id."""
		card = self.build_task_card(task)
		body = (
			ReplyMessageRequestBody.builder()
			.msg_type("interactive")
			.content(json.dumps(card))
			.build()
		)
		request = (
			ReplyMessageRequest.builder()
			.message_id(message_id)
			.request_body(body)
			.build()
		)
		response = await self._client.im.v1.message.areply(request)
		if not response.success():
			raise RuntimeError(
				f"Failed to reply with task card: {response.code} {response.msg}"
			)
		return getattr(response.data, "message_id", None) if response.data else None

	async def update_task_card(self, task: Task) -> None:
		"""Update the existing Feishu task card for a task."""
		if not task.task_card_message_id:
			return

		card = self.build_task_card(task)
		body = (
			UpdateMessageRequestBody.builder()
			.msg_type("interactive")
			.content(json.dumps(card))
			.build()
		)
		request = (
			UpdateMessageRequest.builder()
			.message_id(task.task_card_message_id)
			.request_body(body)
			.build()
		)
		response = await self._client.im.v1.message.aupdate(request)
		if not response.success():
			raise RuntimeError(
				f"Failed to update task card: {response.code} {response.msg}"
			)

	async def upload_image(self, image_path: str) -> str | None:
		"""Upload an image file to Feishu and return the image_key.

		Args:
			image_path: Path to the image file.

		Returns:
			image_key string on success, None on failure.
		"""
		try:
			with Path(image_path).open("rb") as image_file:
				body = (
					CreateImageRequestBody.builder()
					.image_type("message")
					.image(image_file)
					.build()
				)
				request = CreateImageRequest.builder().request_body(body).build()
				response = await self._client.im.v1.image.acreate(request)
			if response.success() and response.data:
				return response.data.image_key
			logger.warning("Failed to upload image: %s %s", response.code, response.msg)
			return None
		except Exception:
			logger.warning("Failed to upload image", exc_info=True)
			return None

	async def send_image(self, chat_id: str, image_key: str) -> None:
		"""Send an image message to a chat using an uploaded image_key."""
		body = (
			CreateMessageRequestBody.builder()
			.receive_id(chat_id)
			.msg_type("image")
			.content(json.dumps({"image_key": image_key}))
			.build()
		)
		request = (
			CreateMessageRequest.builder()
			.receive_id_type("chat_id")
			.request_body(body)
			.build()
		)
		response = await self._client.im.v1.message.acreate(request)
		if not response.success():
			raise RuntimeError(
				f"Failed to send image: {response.code} {response.msg}"
			)

	def build_task_card(self, task: Task) -> dict:
		"""Build an interactive card displaying user-facing task status."""
		label, color = _STATUS_DISPLAY.get(
			task.status.value, ("未知", "grey")
		)

		created_at_str = task.created_at.strftime("%Y-%m-%d %H:%M:%S")
		_PLATFORM_NAME = {
			"meituan": "美团",
			"eleme": "饿了么/淘宝闪购",
			"douyin": "抖音来客",
			"taobao": "淘宝",
		}

		# Header
		card: dict = {
			"config": {"wide_screen_mode": True},
			"header": {
				"title": {"tag": "plain_text", "content": f"任务 {task.id[:8]} · {label}"},
				"template": color,
			},
			"elements": [],
		}

		elements: list[dict] = card["elements"]

		fields: list[dict] = [
			{
				"is_short": True,
				"text": {"tag": "lark_md", "content": f"**任务ID:**\n{task.id[:8]}"},
			},
			{
				"is_short": True,
				"text": {"tag": "lark_md", "content": f"**平台:**\n{_PLATFORM_NAME.get(task.platform, task.platform)}"},
			},
			{
				"is_short": True,
				"text": {"tag": "lark_md", "content": f"**状态:**\n{label}"},
			},
			{
				"is_short": True,
				"text": {"tag": "lark_md", "content": f"**创建时间:**\n{created_at_str}"},
			},
		]
		if task.intent:
			fields.append(
				{
					"is_short": True,
					"text": {"tag": "lark_md", "content": f"**操作:**\n{task.intent}"},
				}
			)
		if task.intent_target:
			fields.append(
				{
					"is_short": True,
					"text": {"tag": "lark_md", "content": f"**目标:**\n{task.intent_target}"},
				}
			)
		if task.policy_status:
			fields.append(
				{
					"is_short": True,
					"text": {"tag": "lark_md", "content": f"**安全检查:**\n{task.policy_status}"},
				}
			)
		elements.append({"tag": "div", "fields": fields})

		instruction_lines = ["**指令:**", task.instruction]
		if task.raw_text and task.raw_text != task.instruction:
			instruction_lines.extend(["", f"**来源输入:**\n{task.raw_text}"])
		if task.policy_reason:
			instruction_lines.extend(["", f"**安全说明:**\n{task.policy_reason}"])

		elements.append({"tag": "hr"})
		elements.append(
			{
				"tag": "div",
				"text": {
					"tag": "lark_md",
					"content": "\n".join(instruction_lines),
				},
			}
		)

		if task.result is not None:
			elements.append({"tag": "hr"})
			result_label = "成功" if task.result.success else "失败"
			elements.append(
				{
					"tag": "div",
					"text": {
						"tag": "lark_md",
						"content": f"**执行结果:**\n{result_label}: {task.result.message}",
					},
				}
			)
		elif task.error is not None:
			elements.append({"tag": "hr"})
			failure_reason = task.error_message_user or task.error
			elements.append(
				{
					"tag": "div",
					"text": {
						"tag": "lark_md",
						"content": f"**失败原因:**\n{failure_reason}",
					},
				}
			)

		elements.append({"tag": "hr"})
		actions: list[dict] = []

		if task.status in (
			TaskStatus.PENDING,
			TaskStatus.PARSING,
			TaskStatus.PREPARING,
			TaskStatus.EXECUTING,
		):
			actions.append(
				{
					"tag": "button",
					"text": {"tag": "plain_text", "content": "取消"},
					"type": "default",
					"value": {"action": "cancel", "task_id": task.id},
				}
			)

		if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
			actions.append(
				{
					"tag": "button",
					"text": {"tag": "plain_text", "content": "重试"},
					"type": "primary",
					"value": {"action": "retry", "task_id": task.id},
				}
			)

		if actions:
			elements.append({"tag": "action", "actions": actions})

		return card

	def build_metrics_card(self, metrics: TaskMetrics) -> dict:
		"""Build an operations metrics card from aggregated task metrics."""
		def _pct(value: float) -> str:
			return f"{value * 100:.1f}%"

		_PLATFORM_NAME = {
			"meituan": "美团",
			"eleme": "饿了么/淘宝闪购",
			"douyin": "抖音来客",
			"taobao": "淘宝",
			"unknown": "未知",
		}

		card: dict = {
			"config": {"wide_screen_mode": True},
			"header": {
				"title": {"tag": "plain_text", "content": "📊 任务指标"},
				"template": "blue",
			},
			"elements": [],
		}
		elements: list[dict] = card["elements"]
		elements.append({
			"tag": "div",
			"fields": [
				{"is_short": True, "text": {"tag": "lark_md", "content": f"**总任务:**\n{metrics.total_tasks}"}},
				{"is_short": True, "text": {"tag": "lark_md", "content": f"**终态任务:**\n{metrics.terminal_tasks}"}},
				{"is_short": True, "text": {"tag": "lark_md", "content": f"**成功率:**\n{_pct(metrics.success_rate)}"}},
				{"is_short": True, "text": {"tag": "lark_md", "content": f"**失败率:**\n{_pct(metrics.failure_rate)}"}},
				{"is_short": True, "text": {"tag": "lark_md", "content": f"**平均耗时:**\n{metrics.average_duration_seconds:.1f}s"}},
			],
		})

		if metrics.by_platform:
			lines = ["**平台维度**"]
			for platform, bucket in sorted(metrics.by_platform.items()):
				lines.append(
					f"- {_PLATFORM_NAME.get(platform, platform)}：总 {bucket.total} / 成功 {bucket.completed} / 失败 {bucket.failed}"
				)
			elements.append({"tag": "hr"})
			elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}})

		if metrics.error_types:
			lines = ["**失败类型**"]
			for error_type, count in sorted(metrics.error_types.items(), key=lambda item: item[1], reverse=True):
				lines.append(f"- {error_type}: {count}")
			elements.append({"tag": "hr"})
			elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}})

		return card

	def build_help_card(self) -> dict:
		"""Build a concise onboarding card with supported commands."""
		return {
			"config": {"wide_screen_mode": True},
			"header": {
				"title": {"tag": "plain_text", "content": "商家后台助手"},
				"template": "blue",
			},
			"elements": [
				{
					"tag": "div",
					"text": {
						"tag": "lark_md",
						"content": (
							"**创建任务**\n"
							"- 美团江湖饭焗修改商家电话为13888888888\n"
							"- 把美团 江湖饭焗 营业时间改为 09:00-22:00\n"
							"- 把美团 江湖饭焗 门店照片换成刚上传的图片"
						),
					},
				},
				{"tag": "hr"},
				{
					"tag": "div",
					"text": {
						"tag": "lark_md",
						"content": (
							"**账号与状态**\n"
							"- 登录 美团 江湖饭焗\n"
							"- 账号列表\n"
							"- 状态 / 历史\n"
							"- 门店列表 / 附件"
						),
					},
				},
				{"tag": "hr"},
				{
					"tag": "div",
					"text": {
						"tag": "lark_md",
						"content": (
							"**图片和表格**\n"
							"可以先发送图片，系统会记录最近上传内容。发送 `附件` 可查看，"
							"再发送门店照片替换任务即可使用最近图片。"
						),
					},
				},
			],
		}

	def build_attachment_card(self, attachments: list[Attachment]) -> dict:
		"""Build a card listing recently received attachment metadata."""
		card: dict = {
			"config": {"wide_screen_mode": True},
			"header": {
				"title": {"tag": "plain_text", "content": "最近附件"},
				"template": "blue",
			},
			"elements": [],
		}
		elements: list[dict] = card["elements"]
		if not attachments:
			elements.append({
				"tag": "div",
				"text": {"tag": "lark_md", "content": "暂无最近附件。可以先发送图片或表格，系统会记录下来。"},
			})
			return card

		lines = ["**最近上传内容**"]
		for attachment in attachments:
			created_at = attachment.created_at.strftime("%Y-%m-%d %H:%M")
			name = attachment.file_name or attachment.id[:8]
			file_type = "图片" if attachment.file_type == "image" else "文件"
			size = f" / {self._format_size(attachment.size_bytes)}" if attachment.size_bytes else ""
			lines.append(
				f"- {file_type}: {name}{size} / {created_at} / ID {attachment.id[:8]}"
			)
		elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}})
		elements.append({"tag": "hr"})
		elements.append({
			"tag": "div",
			"text": {
				"tag": "lark_md",
				"content": "后续图片替换、表格批量改价会基于这里的附件记录承接。",
			},
		})
		return card

	def _format_size(self, size_bytes: int | None) -> str:
		if size_bytes is None:
			return "-"
		if size_bytes < 1024:
			return f"{size_bytes} B"
		if size_bytes < 1024 * 1024:
			return f"{size_bytes / 1024:.1f} KB"
		return f"{size_bytes / (1024 * 1024):.1f} MB"

	async def send_task_card(self, chat_id: str, task: Task) -> None:
		"""Build and send a task card to the given chat."""
		card = self.build_task_card(task)
		await self.send_card(chat_id, card)

	async def send_task_update(self, task: Task) -> None:
		"""Send an updated task card to the task's originating chat."""
		card = self.build_task_card(task)
		await self.send_card(task.chat_id, card)

	def build_account_card(self, accounts: list) -> dict:
		"""Build an interactive card for account management.

		Args:
			accounts: List of Account objects to display.

		Returns:
			Feishu interactive card dict.
		"""
		from merchant_automation.accounts.models import AccountStatus

		_STATUS_ICON = {
			AccountStatus.ACTIVE.value: "🟢",
			AccountStatus.NEEDS_LOGIN.value: "🟡",
			AccountStatus.DISABLED.value: "🔴",
		}
		_STATUS_LABEL = {
			AccountStatus.ACTIVE.value: "已登录",
			AccountStatus.NEEDS_LOGIN.value: "需要登录",
			AccountStatus.DISABLED.value: "已停用",
		}

		_PLATFORM_NAME = {
			"meituan": "美团",
			"douyin": "抖音",
			"eleme": "饿了么",
			"taobao": "淘宝",
		}

		card: dict = {
			"config": {"wide_screen_mode": True},
			"header": {
				"title": {"tag": "plain_text", "content": "📋 账号管理"},
				"template": "blue",
			},
			"elements": [],
		}
		elements: list[dict] = card["elements"]

		if not accounts:
			elements.append({
				"tag": "div",
				"text": {
					"tag": "lark_md",
					"content": "暂无已配置的账号。\n发送“登录 <平台> <店铺名>”即可添加。",
				},
			})
		else:
			for account in accounts:
				icon = _STATUS_ICON.get(account.status.value, "⚪")
				platform_display = _PLATFORM_NAME.get(account.platform, account.platform)
				status_text = _STATUS_LABEL.get(account.status.value, account.status.value)

				# Last used time
				if account.last_used_at:
					from datetime import datetime
					delta = datetime.now() - account.last_used_at
					if delta.total_seconds() < 60:
						time_str = "刚刚"
					elif delta.total_seconds() < 3600:
						time_str = f"{int(delta.total_seconds() // 60)}分钟前"
					elif delta.total_seconds() < 86400:
						time_str = f"{int(delta.total_seconds() // 3600)}小时前"
					else:
						time_str = f"{int(delta.days)}天前"
				else:
					time_str = "从未使用"

				# Account info line
				info_line = f"{icon} **{account.name}** ({platform_display})　{status_text}　最后使用: {time_str}"

				elements.append({
					"tag": "div",
					"text": {"tag": "lark_md", "content": info_line},
				})

				# Action buttons per account
				elements.append({
					"tag": "action",
					"actions": [
						{
							"tag": "button",
							"text": {"tag": "plain_text", "content": "🔐 重新登录"},
							"type": "primary",
							"value": {
								"action": "account_login",
								"account_id": account.id,
								"platform": account.platform,
								"name": account.name,
							},
						},
					],
				})

				elements.append({"tag": "hr"})

		# Bottom action buttons
		elements.append({
			"tag": "action",
			"actions": [
				{
					"tag": "button",
					"text": {"tag": "plain_text", "content": "➕ 添加账号"},
					"type": "default",
					"value": {"action": "account_add"},
				},
				{
					"tag": "button",
					"text": {"tag": "plain_text", "content": "🔄 刷新状态"},
					"type": "default",
					"value": {"action": "account_refresh"},
				},
			],
		})

		return card
