#!/usr/bin/env python3
"""CLI test script for merchant automation shortcut commands.

Usage:
    python test_cli_commands.py [command]

Commands:
    help        - Show help card
    accounts    - Show account list
    status      - Show task status
    history     - Show history
    attachments - Show attachments
    stores      - Show store management
    all         - Test all commands
"""

import asyncio
import json
import sys
from dataclasses import dataclass
from typing import Any

from merchant_automation.accounts.models import AccountStatus
from merchant_automation.feishu.bot import FeishuBot


@dataclass
class FakeAccount:
    id: str
    name: str
    platform: str = 'meituan'
    profile_dir: str = '/tmp/profile'
    status: AccountStatus = AccountStatus.ACTIVE
    last_used_at: object | None = None


class FakeTaskQueue:
    def __init__(self) -> None:
        self.submitted: list[object] = []

    async def submit(self, task: object) -> None:
        self.submitted.append(task)

    async def get_pending_tasks(self) -> list[object]:
        return []

    async def get_recent_attachments(self, chat_id: str, user_id: str | None = None, limit: int = 5) -> list[object]:
        return []

    async def set_task_card_message_id(self, task_id: str, message_id: str) -> None:
        pass

    async def link_attachment(self, task_id: str, attachment_id: str, purpose: str) -> None:
        pass


class FakeAccountManager:
    def __init__(self, accounts: list[FakeAccount] | None = None) -> None:
        self.accounts = accounts or []
        self.updated: list[tuple[str, AccountStatus]] = []

    async def get_all_accounts(self) -> list[FakeAccount]:
        return self.accounts

    async def get_account(self, account_id: str) -> FakeAccount | None:
        for account in self.accounts:
            if account.id == account_id:
                return account
        return None

    async def update_status(self, account_id: str, status: AccountStatus) -> None:
        self.updated.append((account_id, status))

    async def search_accounts(self, keyword: str) -> list[FakeAccount]:
        """Search accounts by name (fuzzy match)."""
        return [a for a in self.accounts if keyword.lower() in a.name.lower()]

    async def create_account(self, name: str, platform: str, username: str | None = None) -> FakeAccount:
        """Create a new account."""
        import uuid
        account = FakeAccount(
            id=f'acct-{uuid.uuid4().hex[:8]}',
            name=name,
            platform=platform,
        )
        self.accounts.append(account)
        return account


class FakeFeishuBot:
    def __init__(self) -> None:
        self.cards: list[tuple[str, dict]] = []
        self.sent_cards: list[tuple[str, dict]] = []
        self.texts: list[tuple[str, str]] = []
        self.task_cards: list[tuple[str, object]] = []
        self._real = FeishuBot(object())  # type: ignore[arg-type]

    async def reply_card(self, message_id: str, card: dict) -> None:
        self.cards.append((message_id, card))

    async def reply_text(self, message_id: str, content: str) -> None:
        self.texts.append((message_id, content))

    async def send_card(self, chat_id: str, card: dict) -> None:
        self.sent_cards.append((chat_id, card))

    async def send_text(self, chat_id: str, content: str) -> None:
        self.texts.append((chat_id, content))

    async def reply_task_card(self, message_id: str, task: object) -> str:
        self.task_cards.append((message_id, task))
        return 'task-card-msg-id'

    def build_help_card(self) -> dict:
        return self._real.build_help_card()

    def build_account_card(self, accounts: list[object]) -> dict:
        return self._real.build_account_card(accounts)

    def build_attachment_card(self, attachments: list[object]) -> dict:
        return self._real.build_attachment_card(attachments)  # type: ignore[arg-type]


def print_card(card: dict) -> None:
    """Print a Feishu card in a readable format."""
    header = card.get('header', {})
    title = header.get('title', {}).get('content', 'No Title')
    print(f"\n{'='*60}")
    print(f"📋 {title}")
    print('='*60)

    elements = card.get('elements', [])
    for element in elements:
        tag = element.get('tag')
        if tag == 'div':
            text_content = element.get('text', {}).get('content', '')
            if text_content:
                print(text_content)
        elif tag == 'hr':
            print('-' * 40)
        elif tag == 'action':
            actions = element.get('actions', [])
            for action in actions:
                button_text = action.get('text', {}).get('content', '')
                if button_text:
                    print(f"  [{button_text}]")


def print_text(texts: list[tuple[str, str]]) -> None:
    """Print text messages."""
    for msg_id, content in texts:
        print(f"\n💬 {content}")


async def test_command(command: str) -> None:
    """Test a single command."""
    import merchant_automation.server as server

    # Setup fake dependencies
    queue = FakeTaskQueue()
    bot = FakeFeishuBot()
    server._pool = None
    server._account_manager = FakeAccountManager([
        FakeAccount(id='acct-1', name='江湖饭焗'),
        FakeAccount(id='acct-2', name='小龙坎', platform='eleme'),
    ])
    server._task_queue = queue  # type: ignore[assignment]
    server._feishu_bot = bot  # type: ignore[assignment]

    # Simulate sending the command
    await server._handle_message_event({
        'message': {
            'chat_id': 'chat-1',
            'message_id': 'msg-1',
            'message_type': 'text',
            'content': json.dumps({'text': command}),
        },
        'sender': {'sender_id': {'open_id': 'user-1'}},
    })

    # Print results
    print(f"\n🔍 Testing command: '{command}'")

    if bot.cards:
        print("\n📨 Reply Cards:")
        for msg_id, card in bot.cards:
            print_card(card)

    if bot.sent_cards:
        print("\n📨 Sent Cards:")
        for chat_id, card in bot.sent_cards:
            print_card(card)

    if bot.texts:
        print("\n📨 Text Messages:")
        print_text(bot.texts)

    if bot.task_cards:
        print("\n📋 Task Cards Created:")
        for msg_id, task in bot.task_cards:
            print(f"  • Task ID: {task.id[:8]} - {task.instruction[:50]}...")

    if queue.submitted:
        print("\n📤 Tasks Submitted to Queue:")
        for task in queue.submitted:
            print(f"  • {task.instruction[:50]}...")

    if not bot.cards and not bot.sent_cards and not bot.texts and not bot.task_cards and not queue.submitted:
        print("\n⚠️  No response received")


async def test_all_commands() -> None:
    """Test all shortcut commands."""
    commands = [
        '帮助',
        'help',
        '?',
        '账号列表',
        '账号',
        '状态',
        '任务',
        '历史',
        '附件',
        '门店',
        '店铺管理',
    ]

    for cmd in commands:
        await test_command(cmd)
        print("\n" + "="*80 + "\n")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == 'all':
        asyncio.run(test_all_commands())
    elif command in ['help', '帮助', '?']:
        asyncio.run(test_command('帮助'))
    elif command in ['accounts', '账号', '账号列表']:
        asyncio.run(test_command('账号列表'))
    elif command in ['status', '状态', '任务']:
        asyncio.run(test_command('状态'))
    elif command in ['history', '历史']:
        asyncio.run(test_command('历史'))
    elif command in ['attachments', '附件']:
        asyncio.run(test_command('附件'))
    elif command in ['stores', '门店', '店铺']:
        asyncio.run(test_command('门店'))
    else:
        # Treat as custom command
        asyncio.run(test_command(command))


if __name__ == '__main__':
    main()
