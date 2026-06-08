from __future__ import annotations

import json

from merchant_automation.feishu.bot import FeishuBot
from merchant_automation.tasks.models import Task, TaskStatus


def _card_text(card: dict) -> str:
	return json.dumps(card, ensure_ascii=False)


def test_task_card_uses_current_user_facing_summary_without_legacy_fields():
	task = Task(
		user_id='user-1',
		chat_id='chat-1',
		message_id='msg-1',
		raw_text='美团江湖饭焗修改商家电话为13888888888',
		platform='meituan',
		instruction='美团江湖饭焗修改商家电话为13888888888',
		status=TaskStatus.PENDING,
	)

	card = FeishuBot(object()).build_task_card(task)  # type: ignore[arg-type]
	text = _card_text(card)

	assert '等待中' in text
	assert '指令' in text
	assert '美团江湖饭焗修改商家电话为13888888888' in text
	assert 'Prompt' not in text
	assert '置信度' not in text
	assert '策略' not in text
	assert '原始输入' not in text


def test_failed_task_card_prefers_user_facing_failure_reason():
	task = Task(
		user_id='user-1',
		chat_id='chat-1',
		message_id='msg-1',
		raw_text='美团江湖饭焗修改商家电话为13888888888',
		platform='meituan',
		instruction='美团江湖饭焗修改商家电话为13888888888',
		status=TaskStatus.FAILED,
		error='解析失败: Unsupported operation text: 美团江湖饭焗修改商家电话为13888888888',
		error_message_user='未识别到可执行任务，请确认平台、店铺和修改内容。',
	)

	card = FeishuBot(object()).build_task_card(task)  # type: ignore[arg-type]
	text = _card_text(card)

	assert '失败原因' in text
	assert '未识别到可执行任务，请确认平台、店铺和修改内容。' in text
	assert 'Unsupported operation text' not in text
	assert 'Error' not in text
