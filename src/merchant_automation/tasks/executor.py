"""Merchant task executor — bridges task queue with browser automation."""

from __future__ import annotations

import logging
from typing import Any

from merchant_automation.accounts.manager import AccountManager
from merchant_automation.accounts.models import Account, AccountStatus
from merchant_automation.config import Settings
from merchant_automation.feishu.bot import FeishuBot
from merchant_automation.feishu.resource import FeishuResourceDownloader
from merchant_automation.operations.binder import BoundOperationTask
from merchant_automation.operations.recipe_store import RecipeStore
from merchant_automation.operations.router import ExecutionRouter
from merchant_automation.operations.service import OperationPlanningService
from merchant_automation.operations.storage import OperationStore
from merchant_automation.tasks.models import Attachment, Task, TaskStatus
from merchant_automation.tasks.queue import TaskQueue

logger = logging.getLogger(__name__)


class MerchantTaskExecutor:
    """Executes merchant tasks by bridging task queue with browser automation."""

    def __init__(
        self,
        config: Settings,
        queue: TaskQueue,
        feishu_bot: FeishuBot,
        planning_service: OperationPlanningService,
        operation_store: OperationStore,
        recipe_store: RecipeStore,
        account_manager: AccountManager,
        resource_downloader: FeishuResourceDownloader | None = None,
    ) -> None:
        self._config = config
        self._queue = queue
        self._feishu_bot = feishu_bot
        self._planning_service = planning_service
        self._operation_store = operation_store
        self._recipe_store = recipe_store
        self._account_manager = account_manager
        self._resource_downloader = resource_downloader

    async def execute(self, task: Task) -> None:
        """Execute a single task through the planning and execution pipeline."""
        run_id = self._operation_store.start_run(source='task', task_count=1)
        await self._set_status(task, TaskStatus.PARSING)

        try:
            # Step 1: Plan
            result = await self._planning_service.plan_text(task.instruction, mode=None)

            if result.input_issues or result.plan_issues:
                issues = result.input_issues + result.plan_issues
                reason = '; '.join(issue.reason for issue in issues[:3])
                from merchant_automation.operations.failure import user_failure_message
                user_reason = user_failure_message('planning_failed', f'无法解析指令: {reason}')
                await self._set_status(
                    task,
                    TaskStatus.FAILED,
                    error=f'解析失败: {reason}',
                    error_type='planning_failed',
                    error_message_user=user_reason,
                    error_message_internal=str(issues),
                )
                await self._notify(task.chat_id, user_reason)
                return

            if not result.bound_tasks:
                await self._set_status(
                    task,
                    TaskStatus.FAILED,
                    error='无可用任务',
                    error_type='no_tasks',
                    error_message_user='未能生成任何可执行任务',
                    error_message_internal='bound_tasks is empty',
                )
                await self._notify(task.chat_id, '未能生成任何可执行任务')
                return

            # Step 2: Execute each bound task
            bound_task = result.bound_tasks[0]  # 单任务场景取第一个
            attachments = await self._queue.get_task_attachments(task.id)
            attachments = await self._ensure_local_image_attachments(attachments)
            bound_task = self._hydrate_latest_image_attachment(bound_task, attachments)
            await self._execute_bound_task(bound_task, task, run_id)

        except Exception as exc:
            logger.exception('Task %s execution failed', task.id)
            from merchant_automation.operations.failure import user_failure_message
            user_reason = user_failure_message('execution_error', f'执行异常: {str(exc)[:100]}')
            await self._set_status(
                task,
                TaskStatus.FAILED,
                error=str(exc),
                error_type='execution_error',
                error_message_user=user_reason,
                error_message_internal=str(exc),
            )
            await self._notify(task.chat_id, user_reason)

    async def _ensure_local_image_attachments(self, attachments: list[Attachment]) -> list[Attachment]:
        """Download linked Feishu images before browser upload tasks execute."""
        if self._resource_downloader is None:
            return attachments

        local_attachments: list[Attachment] = []
        for attachment in attachments:
            if attachment.file_type != 'image' or not attachment.feishu_file_key:
                local_attachments.append(attachment)
                continue

            downloaded = await self._resource_downloader.ensure_local_file(attachment)
            if downloaded != attachment:
                await self._queue.update_attachment(downloaded)
            local_attachments.append(downloaded)
        return local_attachments

    async def _execute_bound_task(
        self,
        bound_task: BoundOperationTask,
        task: Task,
        run_id: str,
    ) -> None:
        """Execute a single bound task through ExecutionRouter."""
        from browser_use import BrowserSession
        from browser_use.browser.profile import BrowserProfile
        from browser_use.llm.openai.chat import ChatOpenAI

        # Resolve account profile
        profile_dir = None
        if task.account_id:
            account = await self._account_manager.get_account(task.account_id)
            if account:
                profile_dir = account.profile_dir

        # Create browser session
        profile_kwargs: dict = {'headless': self._config.BROWSER_HEADLESS}
        if profile_dir:
            profile_kwargs['user_data_dir'] = profile_dir
        elif self._config.BROWSER_USER_DATA_DIR:
            profile_kwargs['user_data_dir'] = self._config.BROWSER_USER_DATA_DIR

        profile = BrowserProfile(**profile_kwargs)
        browser_session = BrowserSession(browser_profile=profile)

        try:
            # Create LLM
            llm = ChatOpenAI(
                model=self._config.LLM_MODEL,
                base_url=self._config.LLM_BASE_URL,
                api_key=self._config.LLM_API_KEY,
            )

            # Build recipe definitions map
            recipe_defs = {d.recipe_id: d for d in self._recipe_store.list_definitions()}

            # Create ExecutionRouter
            router = ExecutionRouter(
                browser_session=browser_session,
                llm=llm,
                store=self._operation_store,
                recipe_definitions=recipe_defs,
                recipe_store=self._recipe_store,
            )

            # Execute
            trace = await router.execute(bound_task, raw_input=task.instruction)

            # Save trace
            self._operation_store.save_trace(trace, run_id=run_id)

            # Report result
            if trace.outcome and trace.outcome.status.value == 'success':
                await self._set_status(task, TaskStatus.COMPLETED)
                await self._notify(
                    task.chat_id,
                    f'任务 {task.id[:8]} 执行成功\n'
                    f'操作: {bound_task.task.operation_id}\n'
                    f'平台: {bound_task.task.platform}\n'
                    f'门店: {bound_task.task.store_id}',
                )
            else:
                failure_msg = trace.outcome.message if trace.outcome else '未知错误'
                from merchant_automation.operations.failure import user_failure_message
                user_reason = user_failure_message('recipe_execution_failed', f'执行失败: {failure_msg}')
                await self._set_status(
                    task,
                    TaskStatus.FAILED,
                    error=failure_msg,
                    error_type='recipe_execution_failed',
                    error_message_user=user_reason,
                    error_message_internal=failure_msg,
                )
                await self._notify(task.chat_id, user_reason)

        finally:
            try:
                await browser_session.close()
            except Exception:
                pass

    def _hydrate_latest_image_attachment(self, bound_task: BoundOperationTask, attachments: list[Attachment]) -> BoundOperationTask:
        """Replace attachment_id=latest_image with the image attachment linked to the task."""
        if bound_task.task.params.get('attachment_id') != 'latest_image':
            return bound_task

        image_attachment = self._select_latest_usable_image(attachments)
        if image_attachment is None:
            return bound_task

        params = {
            **bound_task.task.params,
            'attachment_id': image_attachment.id,
            'feishu_file_key': image_attachment.feishu_file_key,
            'attachment_file_name': image_attachment.file_name,
        }
        if image_attachment.local_path:
            params['local_image_path'] = image_attachment.local_path
        if image_attachment.sha256:
            params['attachment_sha256'] = image_attachment.sha256
        operation_task = bound_task.task.model_copy(update={'params': params})
        return bound_task.model_copy(update={'task': operation_task})

    def _select_latest_usable_image(self, attachments: list[Attachment]) -> Attachment | None:
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

    async def _set_status(
        self,
        task: Task,
        status: TaskStatus,
        *,
        error: str | None = None,
        error_type: str | None = None,
        error_message_user: str | None = None,
        error_message_internal: str | None = None,
    ) -> None:
        """Update task status and notify."""
        await self._queue.update_status(
            task.id,
            status,
            error=error,
            error_type=error_type,
            error_message_user=error_message_user,
            error_message_internal=error_message_internal,
        )

    async def _notify(self, chat_id: str, message: str) -> None:
        """Send notification to Feishu chat."""
        try:
            await self._feishu_bot.send_text(chat_id, message)
        except Exception:
            logger.warning('Failed to send notification to chat %s', chat_id, exc_info=True)
