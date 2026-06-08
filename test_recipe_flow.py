#!/usr/bin/env python3
"""Test recipe flow: prepare first, then commit.

Usage:
    python test_recipe_flow.py [--commit]

Options:
    --commit    Actually execute in commit mode (default: prepare only)
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from merchant_automation.accounts.manager import AccountManager
from merchant_automation.accounts.models import AccountStatus
from merchant_automation.operations.preflight import CommitPolicy
from merchant_automation.operations.recipe_store import RecipeStore
from merchant_automation.operations.router import ExecutionRouter
from merchant_automation.operations.schemas import ExecutionMode
from merchant_automation.operations.service import OperationPlanningService
from merchant_automation.operations.storage import OperationStore


async def run_recipe_flow(
    instruction: str,
    account_keyword: str,
    platform: str = 'meituan',
    mode: ExecutionMode = ExecutionMode.PREPARE,
    db_path: str = 'tasks.db',
) -> dict:
    """Run the recipe flow for a given instruction."""

    db_dir = Path(db_path).parent

    # Initialize managers
    account_manager = AccountManager(db_path=db_path)
    await account_manager.start()

    try:
        # Find account
        accounts = await account_manager.find_account_for_message(account_keyword, platform=platform)
        if not accounts:
            return {'status': 'error', 'message': f'未找到账号: {account_keyword}'}

        account = accounts[0]
        print(f'✅ 找到账号: {account.name} ({account.platform})')
        print(f'   状态: {account.status.value}')
        print(f'   Profile: {account.profile_dir}')

        if account.status != AccountStatus.ACTIVE:
            return {'status': 'error', 'message': f'账号未登录，请先执行: 登录 {platform} {account_keyword}'}

        # Initialize stores
        operation_store = OperationStore(db_dir / 'merchant.db')
        operation_store.initialize()

        recipe_store = RecipeStore(db_dir / 'recipe.db')
        recipe_store.initialize()

        # Plan the operation
        print(f'\n📋 解析指令: {instruction}')
        planning_service = OperationPlanningService()

        if mode == ExecutionMode.COMMIT:
            policy = CommitPolicy(
                global_commit_enabled=True,
                account_commit_allowed=True,
                store_commit_allowed=True,
            )
        else:
            policy = CommitPolicy()

        planning = planning_service.plan_text(
            instruction,
            mode=mode,
            policy=policy,
        )

        # Save planning result
        run_id = operation_store.save_planning_result(planning)

        # Check for issues
        if planning.input_issues or planning.plan_issues or planning.binding_issues:
            issues = planning.input_issues + planning.plan_issues + planning.binding_issues
            reasons = [issue.reason for issue in issues]
            return {
                'status': 'error',
                'message': f'解析失败: {"; ".join(reasons)}',
                'run_id': run_id,
            }

        if not planning.bound_tasks:
            return {'status': 'error', 'message': '未生成可执行任务', 'run_id': run_id}

        bound_task = planning.bound_tasks[0]
        print(f'\n🔧 操作类型: {bound_task.task.operation_id}')
        print(f'   Recipe: {bound_task.recipe.recipe_id}')
        print(f'   模式: {mode.value}')
        print(f'   参数: {json.dumps(bound_task.task.params, ensure_ascii=False)}')

        # Create browser session
        from browser_use import BrowserSession
        from browser_use.browser.profile import BrowserProfile

        profile = BrowserProfile(
            headless=False,  # 显示浏览器以便观察
            user_data_dir=account.profile_dir,
            window_size={'width': 1280, 'height': 900},
        )
        session = BrowserSession(browser_profile=profile)

        try:
            print('\n🌐 启动浏览器...')
            await session.start()

            # Navigate to merchant backend
            start_url = {
                'meituan': 'https://e.waimai.meituan.com/',
                'eleme': 'https://shop.ele.me/',
                'douyin': 'https://life.douyin.com/',
            }.get(platform, 'https://e.waimai.meituan.com/')

            print(f'   导航到: {start_url}')
            await session.navigate_to(start_url)

            # Create LLM and router
            from browser_use.llm.openai.chat import ChatOpenAI
            from merchant_automation.config import get_config

            config = get_config()
            llm = ChatOpenAI(
                model=config.LLM_MODEL,
                base_url=config.LLM_BASE_URL,
                api_key=config.LLM_API_KEY,
            )

            recipe_defs = {d.recipe_id: d for d in recipe_store.list_definitions()}
            router = ExecutionRouter(
                browser_session=session,
                llm=llm,
                store=operation_store,
                recipe_definitions=recipe_defs,
                recipe_store=recipe_store,
            )

            # Execute
            print(f'\n🚀 执行任务 ({mode.value} 模式)...')
            trace = await router.execute(bound_task, raw_input=instruction, max_steps=30)

            # Save trace
            trace_id = operation_store.save_trace(trace, run_id=run_id)
            await account_manager.touch(account.id)

            # Report result
            result = {
                'run_id': run_id,
                'trace_id': trace_id,
                'status': trace.outcome.status.value if trace.outcome else 'unknown',
                'message': trace.outcome.message if trace.outcome else None,
                'account_id': account.id,
                'account_name': account.name,
                'recipe_id': bound_task.recipe.recipe_id,
                'mode': mode.value,
                'trace_steps': len(trace.steps),
            }

            if trace.outcome and trace.outcome.status.value == 'success':
                print(f'\n✅ 任务执行成功!')
                print(f'   Trace ID: {trace_id[:16]}...')
                print(f'   执行步骤: {len(trace.steps)}')
            else:
                print(f'\n❌ 任务执行失败')
                print(f'   原因: {trace.outcome.message if trace.outcome else "未知错误"}')

            return result

        finally:
            print('\n🔒 关闭浏览器...')
            await session.close()

    finally:
        await account_manager.close()


def main():
    parser = argparse.ArgumentParser(description='Test recipe flow for merchant automation')
    parser.add_argument('--commit', action='store_true', help='Execute in commit mode (actually submit changes)')
    parser.add_argument('--instruction', default='把美团江湖饭焗电话修改为18888888888', help='Instruction to execute')
    parser.add_argument('--account', default='江湖饭焗', help='Account keyword')
    parser.add_argument('--platform', default='meituan', help='Platform (meituan/eleme/douyin)')

    args = parser.parse_args()

    mode = ExecutionMode.COMMIT if args.commit else ExecutionMode.PREPARE

    print('='*60)
    print('📋 商家后台自动化 - Recipe 流程测试')
    print('='*60)
    print(f'指令: {args.instruction}')
    print(f'账号: {args.account}')
    print(f'平台: {args.platform}')
    print(f'模式: {mode.value}')
    print('='*60)

    result = asyncio.run(run_recipe_flow(
        instruction=args.instruction,
        account_keyword=args.account,
        platform=args.platform,
        mode=mode,
    ))

    print('\n' + '='*60)
    print('📊 执行结果')
    print('='*60)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
