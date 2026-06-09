"""FastAPI server bridging Feishu Bot with the merchant automation pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response

from merchant_automation.accounts.manager import AccountManager
from merchant_automation.accounts.models import Account, AccountStatus, LoginStatus, PlatformAccount
from merchant_automation.accounts.store import AccountStore
from merchant_automation.config import Settings, get_config
from merchant_automation.feishu.bot import FeishuBot
from merchant_automation.feishu.client import get_feishu_client
from merchant_automation.feishu.resource import FeishuResourceDownloader, LarkFeishuResourceClient
from merchant_automation.tasks.models import Attachment, Task, TaskStatus
from merchant_automation.tasks.queue import TaskQueue

# merchant_automation components
from merchant_automation.operations.binder import BoundOperationTask
from merchant_automation.operations.preflight import CommitPolicy
from merchant_automation.operations.recipe_store import RecipeStore
from merchant_automation.operations.router import ExecutionRouter
from merchant_automation.operations.service import OperationPlanningService
from merchant_automation.operations.storage import OperationStore
from merchant_automation.operations.traces import trace_screenshot_paths

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
	level=logging.INFO,
	format='%(asctime)s [%(levelname)s] %(name)s - %(message)s',
)
logger = logging.getLogger(__name__)

LOGIN_WAIT_TIMEOUT_SECONDS = 15 * 60
LOGIN_CHECK_POLL_SECONDS = 3
LOGIN_PAGE_TEXT_LIMIT = 3000
LOGIN_BROWSER_START_TIMEOUT_SECONDS = 60

# Auto-retry: retry once on transient execution failures
AUTO_RETRY_MAX_ATTEMPTS = 2  # total attempts (1 initial + 1 retry)
AUTO_RETRY_DELAY_SECONDS = 5
AUTO_RETRYABLE_ERROR_TYPES = frozenset({
    'recipe_execution_failed',
    'execution_error',
    'pool_execution_failed',
})

# Task hard timeout: cancel tasks running longer than this
TASK_HARD_TIMEOUT_SECONDS = 5 * 60

# Stale task recovery: mark EXECUTING tasks older than this as FAILED on startup
STALE_TASK_TIMEOUT_SECONDS = 10 * 60

# Webhook dedup: ignore duplicate message_ids within this window
WEBHOOK_DEDUP_TTL_SECONDS = 600

LOGIN_DETECTION_RULES: dict[str, dict[str, tuple[str, ...]]] = {
	'meituan': {
		'login_url_markers': ('passport.meituan.com', 'epassport.meituan.com', '/login', 'unitivelogin', 'account'),
		'success_url_markers': ('e.waimai.meituan.com/new_fe', 'e.waimai.meituan.com/gw', '/home', '/dashboard'),
		'login_text_markers': ('账号登录', '手机登录', '密码登录', '扫码登录', '获取验证码', '请输入手机号', '验证码登录'),
		'success_text_markers': ('订单管理', '商品管理', '门店', '工作台', '商家中心', '营业时间', '经营数据', '菜品'),
	},
	'eleme': {
		'login_url_markers': ('login', 'passport', 'account'),
		'success_url_markers': ('/dashboard', '/workbench', '/home', '/store'),
		'login_text_markers': ('账号登录', '手机登录', '密码登录', '扫码登录', '获取验证码', '请输入手机号'),
		'success_text_markers': ('订单管理', '商品管理', '门店', '工作台', '商家中心', '营业时间', '经营数据'),
	},
	'douyin': {
		'login_url_markers': ('login', 'passport', 'sso', 'account'),
		'success_url_markers': ('/dashboard', '/workbench', '/merchant', '/shop'),
		'login_text_markers': ('账号登录', '手机登录', '密码登录', '扫码登录', '验证码', '请输入手机号'),
		'success_text_markers': ('门店', '订单', '商品', '工作台', '商家中心', '经营数据', '活动'),
	},
}

# Platform internal name -> user-facing Chinese name
_PLATFORM_DISPLAY_NAME: dict[str, str] = {
	'meituan': '美团',
	'eleme': '饿了么',
	'douyin': '抖音来客',
	'taobao': '淘宝',
}


def _platform_display(platform: str) -> str:
	"""Return user-facing platform name."""
	return _PLATFORM_DISPLAY_NAME.get(platform, platform)


def _ensure_login_browser_start_timeout() -> None:
	"""Give the visible manual-login browser enough time to launch on slow machines."""
	for env_var in ('TIMEOUT_BrowserStartEvent', 'TIMEOUT_BrowserLaunchEvent'):
		raw_value = os.environ.get(env_var)
		try:
			current_value = float(raw_value) if raw_value else 0
		except ValueError:
			current_value = 0
		if current_value < LOGIN_BROWSER_START_TIMEOUT_SECONDS:
			os.environ[env_var] = f'{LOGIN_BROWSER_START_TIMEOUT_SECONDS:g}'

# ---------------------------------------------------------------------------
# Task execution error types (for auto-retry logic)
# ---------------------------------------------------------------------------


class _RetryableError(Exception):
	"""Transient failure that can be retried (recipe execution, browser errors)."""

	def __init__(self, message: str, error_type: str) -> None:
		self.error_type = error_type
		super().__init__(message)


class _NonRetryableError(Exception):
	"""Permanent failure that should not be retried (planning, no tasks)."""

	def __init__(self, user_message: str, error_type: str) -> None:
		self.user_message = user_message
		self.error_type = error_type
		super().__init__(user_message)


# ---------------------------------------------------------------------------
# Globals — initialized in lifespan
# ---------------------------------------------------------------------------

_config: Settings = None  # type: ignore[assignment]
_task_queue: TaskQueue = None  # type: ignore[assignment]
_account_manager: AccountManager = None  # type: ignore[assignment]
_account_store: AccountStore | None = None
_feishu_bot: FeishuBot = None  # type: ignore[assignment]
_resource_downloader: FeishuResourceDownloader = None  # type: ignore[assignment]
_planning_service: OperationPlanningService = None  # type: ignore[assignment]
_operation_store: OperationStore = None  # type: ignore[assignment]
_recipe_store: RecipeStore = None  # type: ignore[assignment]
_pool: MerchantTaskExecutorPool = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Merchant Task Executor — bridges feishu Task to merchant_automation
# ---------------------------------------------------------------------------

class MerchantTaskExecutor:
	"""Executes tasks through merchant_automation's planning + execution pipeline."""

	def __init__(
		self,
		config: Settings,
		queue: TaskQueue,
		feishu_bot: FeishuBot,
		planning_service: OperationPlanningService,
		operation_store: OperationStore,
		recipe_store: RecipeStore,
		account_manager: AccountManager | None = None,
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

	async def execute(self, task: Task, cancel_event: asyncio.Event | None = None) -> None:
		"""Execute a task through the merchant_automation pipeline.

		Transient failures (recipe execution, browser errors) are automatically
		retried once after a short delay. Planning failures are not retried.
		"""
		last_error_type: str | None = None
		last_error: str | None = None

		for attempt in range(AUTO_RETRY_MAX_ATTEMPTS):
			if attempt > 0:
				logger.info('Task %s auto-retry attempt %d/%d', task.id, attempt + 1, AUTO_RETRY_MAX_ATTEMPTS)
				await self._notify(task.chat_id, '🔄 执行遇到问题，正在自动重试...')
				await asyncio.sleep(AUTO_RETRY_DELAY_SECONDS)

			try:
				await self._execute_once(task, cancel_event)
				return  # success
			except _NonRetryableError as exc:
				# Planning failures, no_tasks — don't retry
				await self._set_status(
					task,
					TaskStatus.FAILED,
					error=str(exc),
					error_type=exc.error_type,
					error_message_user=exc.user_message,
					error_message_internal=str(exc),
				)
				await self._notify(task.chat_id, exc.user_message)
				return
			except _RetryableError as exc:
				last_error_type = exc.error_type
				last_error = str(exc)
				logger.warning('Task %s attempt %d failed (retryable): %s', task.id, attempt + 1, last_error)
				continue
			except Exception as exc:
				last_error_type = 'execution_error'
				last_error = str(exc)
				logger.exception('Task %s attempt %d raised unhandled exception', task.id, attempt + 1)
				continue

		# All retries exhausted
		from merchant_automation.operations.failure import user_failure_message
		user_reason = user_failure_message(last_error_type, f'执行异常: {last_error[:100]}' if last_error else None)
		await self._set_status(
			task,
			TaskStatus.FAILED,
			error=last_error or 'unknown',
			error_type=last_error_type or 'execution_error',
			error_message_user=user_reason,
			error_message_internal=last_error or 'unknown',
		)
		await self._notify(task.chat_id, user_reason)

	async def _execute_once(self, task: Task, cancel_event: asyncio.Event | None) -> None:
		"""Single execution attempt. Raises _RetryableError or _NonRetryableError."""
		await self._set_status(task, TaskStatus.EXECUTING)
		await self._notify(task.chat_id, '🚀 任务开始执行...')

		# Step 1: Plan — parse text into BoundOperationTask
		from merchant_automation.operations.schemas import ExecutionMode
		policy = CommitPolicy()  # 默认不开启 commit
		result = self._planning_service.plan_text(
			task.instruction,
			mode=ExecutionMode.PREPARE,
			policy=policy,
		)

		# Save planning result
		run_id = self._operation_store.save_planning_result(result)

		# Check for planning issues
		if result.input_issues or result.plan_issues:
			issues = result.input_issues + result.plan_issues
			reason = '; '.join(issue.reason for issue in issues[:3])
			from merchant_automation.operations.failure import user_failure_message
			user_reason = user_failure_message('planning_failed', f'无法解析指令: {reason}')
			raise _NonRetryableError(user_reason, 'planning_failed')

		if not result.bound_tasks:
			# Provide more context if binding issues exist
			if result.binding_issues:
				binding_reasons = '; '.join(issue.reason for issue in result.binding_issues[:2])
				from merchant_automation.operations.failure import user_failure_message
				detail = user_failure_message('no_tasks', f'任务绑定失败: {binding_reasons}')
				raise _NonRetryableError(detail, 'no_tasks')
			raise _NonRetryableError(
				user_failure_message('no_tasks'),
				'no_tasks',
			)

		# Step 2: Execute each bound task
		bound_task = result.bound_tasks[0]  # 单任务场景取第一个
		attachments = await self._queue.get_task_attachments(task.id)
		attachments = await self._ensure_local_image_attachments(attachments)
		bound_task = _hydrate_latest_image_attachment(bound_task, attachments)
		await self._execute_bound_task(bound_task, task, run_id)

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
		from merchant_automation.operations.traces import TraceStep

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

		# Progress callback for real-time updates
		async def on_step_progress(step: TraceStep) -> None:
			"""Send progress update to Feishu on each step."""
			# Map step kind to emoji
			kind_emoji = {
				'page': '🌐',
				'action': '🖱️',
				'screenshot': '📸',
				'model_judgement': '🧠',
				'validation': '✅',
			}
			emoji = kind_emoji.get(step.kind.value, '📋')
			progress_msg = f"{emoji} 步骤 {step.step_number}: {step.message}"

			# Update task progress in memory and database
			task.progress_message = progress_msg
			try:
				await self._queue.update_progress(task.id, progress_msg)
				await self._feishu_bot.update_task_card(task)
			except Exception as e:
				logger.debug('Failed to update progress: %s', e)

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

			# Execute with progress callback
			trace = await router.execute(
				bound_task,
				raw_input=task.instruction,
				on_step_callback=on_step_progress,
			)

			# Save trace
			self._operation_store.save_trace(trace, run_id=run_id)

			# Report result
			if trace.outcome and trace.outcome.status.value == 'success':
				await self._set_status(task, TaskStatus.COMPLETED)

				# Send screenshot if available
				screenshot_paths = trace_screenshot_paths(trace)
				if screenshot_paths:
					try:
						# Upload and send the first screenshot
						image_key = await self._feishu_bot.upload_image(screenshot_paths[0])
						if image_key:
							await self._feishu_bot.send_image(task.chat_id, image_key)
							logger.info('Screenshot sent to chat %s', task.chat_id)
					except Exception as e:
						logger.warning('Failed to send screenshot: %s', e)

				await self._notify(
					task.chat_id,
					f'✅ 任务执行成功\n'
					f'{task.instruction[:50]}',
				)
			else:
				failure_msg = trace.outcome.message if trace.outcome else '未知错误'
				raise _RetryableError(failure_msg, 'recipe_execution_failed')

		finally:
			try:
				await browser_session.close()
			except Exception:
				pass

	async def _set_status(self, task: Task, status: TaskStatus, **kwargs) -> None:
		"""Update task status and refresh the Feishu task card."""
		await self._queue.update_status(task.id, status, **kwargs)
		task.status = status
		try:
			await self._feishu_bot.update_task_card(task)
		except Exception:
			logger.warning('Failed to update task card for %s', task.id, exc_info=True)

	async def _notify(self, chat_id: str, text: str) -> None:
		try:
			await self._feishu_bot.send_text(chat_id, text)
		except Exception:
			logger.warning('Failed to send notification to %s', chat_id, exc_info=True)


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
	global _config, _task_queue, _account_manager, _account_store, _feishu_bot, _resource_downloader
	global _planning_service, _operation_store, _recipe_store, _pool

	_config = get_config()

	# Initialize Feishu client + bot
	client = get_feishu_client()
	_feishu_bot = FeishuBot(client)
	db_dir = Path(_config.TASK_DB_PATH).expanduser().parent
	download_dir = Path(_config.ATTACHMENT_DOWNLOAD_DIR).expanduser() if _config.ATTACHMENT_DOWNLOAD_DIR else db_dir / 'attachments'
	_resource_downloader = FeishuResourceDownloader(
		client=LarkFeishuResourceClient(client),
		storage_dir=download_dir,
	)

	# Initialize task queue
	_task_queue = TaskQueue(db_path=_config.TASK_DB_PATH)
	await _task_queue.start()

	# Initialize account manager
	_account_manager = AccountManager(
		db_path=_config.TASK_DB_PATH,
		profiles_base_dir=_config.PROFILES_DIR,
	)
	await _account_manager.start()

	_account_store = AccountStore(db_dir / 'account.db')
	_account_store.initialize()
	await _sync_existing_login_accounts()

	# Initialize merchant_automation components
	llm = _create_llm()
	_planning_service = OperationPlanningService(llm=llm)

	_operation_store = OperationStore(db_dir / 'merchant.db')
	_operation_store.initialize()

	_recipe_store = RecipeStore(db_dir / 'recipe.db')
	_recipe_store.initialize()

	# Seed default recipes
	from merchant_automation.operations.recipes import RecipeRegistry
	for recipe in RecipeRegistry.default().recipes:
		_recipe_store.upsert_recipe(recipe)

	# Seed default recipe definitions
	from merchant_automation.operations.recipe_definitions import RECIPE_DEFINITIONS
	for definition in RECIPE_DEFINITIONS.values():
		_recipe_store.save_definition(definition, source='default')

	# Initialize executor + pool
	executor = MerchantTaskExecutor(
		config=_config,
		queue=_task_queue,
		feishu_bot=_feishu_bot,
		planning_service=_planning_service,
		operation_store=_operation_store,
		recipe_store=_recipe_store,
		account_manager=_account_manager,
		resource_downloader=_resource_downloader,
	)

	# Wrap in a simple pool adapter
	pool = MerchantTaskExecutorPool(executor=executor, task_queue=_task_queue, max_concurrent=_config.MAX_CONCURRENT_TASKS)
	_pool = pool

	# Mount dashboard
	_mount_dashboard()

	# Recover stale tasks from previous crash
	await _recover_stale_tasks()

	# Start background worker
	worker = asyncio.create_task(_worker_loop(pool))

	logger.info(
		'Merchant server started — port=%s, max_concurrent=%s',
		_config.SERVER_PORT,
		_config.MAX_CONCURRENT_TASKS,
	)
	yield

	# Shutdown
	worker.cancel()
	await pool.shutdown()
	_pool = None
	await _task_queue.close()
	await _account_manager.close()
	logger.info('Merchant server stopped')


async def _recover_stale_tasks() -> None:
	"""Recover tasks stuck in EXECUTING from a previous server crash."""
	from datetime import datetime, timedelta, timezone

	stale_threshold = datetime.now(timezone.utc) - timedelta(seconds=STALE_TASK_TIMEOUT_SECONDS)
	stale_tasks = await _task_queue.get_stale_executing_tasks(stale_threshold)
	for task in stale_tasks:
		logger.warning('Recovering stale task %s (stuck since %s)', task.id, task.updated_at)
		await _task_queue.update_status(
			task.id,
			TaskStatus.FAILED,
			error='服务重启，任务中断',
			error_type='server_restart',
			error_message_user='服务重启导致任务中断，请重新提交。',
			error_message_internal=f'stale recovery on startup, was EXECUTING since {task.updated_at}',
		)
		try:
			await _feishu_bot.send_text(task.chat_id, '⚠️ 服务重启，之前的任务已中断，请重新发送指令。')
		except Exception:
			logger.warning('Failed to notify stale task recovery for %s', task.id, exc_info=True)
	if stale_tasks:
		logger.info('Recovered %d stale tasks on startup', len(stale_tasks))


class MerchantTaskExecutorPool:
	"""Pool with global concurrency and per-account serialization."""

	def __init__(self, executor: MerchantTaskExecutor, task_queue: TaskQueue, max_concurrent: int = 3) -> None:
		self._executor = executor
		self._task_queue = task_queue
		self._global_semaphore = asyncio.Semaphore(max_concurrent)
		self._account_locks: dict[str, asyncio.Lock] = {}
		self._account_lock_mutex = asyncio.Lock()
		self._running_tasks: dict[str, asyncio.Task] = {}
		self._cancel_events: dict[str, asyncio.Event] = {}

	async def submit(self, task: Task) -> None:
		cancel_event = asyncio.Event()
		self._cancel_events[task.id] = cancel_event
		async_task = asyncio.create_task(self._execute_with_limits(task, cancel_event))
		self._running_tasks[task.id] = async_task
		async_task.add_done_callback(lambda t: self._on_task_done(task.id))

	def _on_task_done(self, task_id: str) -> None:
		self._running_tasks.pop(task_id, None)
		self._cancel_events.pop(task_id, None)

	async def _execute_with_limits(self, task: Task, cancel_event: asyncio.Event) -> None:
		account_id = task.account_id or '__no_account__'
		async with self._global_semaphore:
			account_lock = await self._get_account_lock(account_id)
			async with account_lock:
				try:
					await asyncio.wait_for(
						self._executor.execute(task, cancel_event=cancel_event),
						timeout=TASK_HARD_TIMEOUT_SECONDS,
					)
				except asyncio.TimeoutError:
					logger.warning('Task %s hard timeout after %ds', task.id, TASK_HARD_TIMEOUT_SECONDS)
					update_status = getattr(self._task_queue, 'update_status', None)
					if update_status is not None:
						try:
							await update_status(
								task.id,
								TaskStatus.FAILED,
								error=f'执行超时（{TASK_HARD_TIMEOUT_SECONDS}s）',
								error_type='task_timeout',
								error_message_user='任务执行超时，请稍后重试或简化操作内容。',
								error_message_internal=f'hard timeout after {TASK_HARD_TIMEOUT_SECONDS}s',
							)
						except Exception:
							logger.exception('Failed to persist timeout failure for task %s', task.id)
					try:
						await _feishu_bot.send_text(task.chat_id, '⏰ 任务执行超时，请稍后重试或简化操作内容。')
					except Exception:
						pass
				except asyncio.CancelledError:
					logger.info('Task %s was cancelled', task.id)
				except Exception as exc:
					logger.exception('Task %s raised unhandled exception', task.id)
					update_status = getattr(self._task_queue, 'update_status', None)
					if update_status is not None:
						try:
							await update_status(
								task.id,
								TaskStatus.FAILED,
								error=str(exc),
								error_type='pool_execution_failed',
								error_message_user='任务执行失败，请稍后重试',
								error_message_internal=str(exc),
							)
						except Exception:
							logger.exception('Failed to persist pool-level failure for task %s', task.id)

	async def _get_account_lock(self, account_id: str) -> asyncio.Lock:
		async with self._account_lock_mutex:
			if account_id not in self._account_locks:
				self._account_locks[account_id] = asyncio.Lock()
			return self._account_locks[account_id]

	def pending_count(self) -> int:
		return len(self._running_tasks)

	def get_running_task_ids(self) -> list[str]:
		return list(self._running_tasks.keys())

	async def cancel(self, task_id: str) -> bool:
		cancel_event = self._cancel_events.get(task_id)
		if cancel_event:
			cancel_event.set()

		async_task = self._running_tasks.get(task_id)
		if async_task and not async_task.done():
			async_task.cancel()
			try:
				await asyncio.wait_for(async_task, timeout=10.0)
			except (asyncio.CancelledError, asyncio.TimeoutError):
				pass
			return True
		return False

	async def shutdown(self) -> None:
		for task_id in list(self._running_tasks.keys()):
			await self.cancel(task_id)


# ---------------------------------------------------------------------------
# Feishu encryption helpers
# ---------------------------------------------------------------------------

def _decrypt_feishu_payload(encrypt: str) -> dict:
	"""Decrypt Feishu encrypted payload using AES-256-CBC."""
	import base64
	import hashlib
	from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
	from cryptography.hazmat.backends import default_backend

	config = get_config()
	if not config.FEISHU_ENCRYPT_KEY:
		raise ValueError('FEISHU_ENCRYPT_KEY not configured')

	# Key is SHA256 of the encrypt key
	key = hashlib.sha256(config.FEISHU_ENCRYPT_KEY.encode('utf-8')).digest()

	# Base64 decode
	encrypted_data = base64.b64decode(encrypt)

	# First 16 bytes are IV
	iv = encrypted_data[:16]
	ciphertext = encrypted_data[16:]

	# AES-256-CBC decrypt
	cipher = Cipher(algorithms.AES(key), modes.CBC(iv), backend=default_backend())
	decryptor = cipher.decryptor()
	decrypted_padded = decryptor.update(ciphertext) + decryptor.finalize()

	# Remove PKCS7 padding with validation
	pad_len = decrypted_padded[-1]
	if pad_len < 1 or pad_len > 16 or decrypted_padded[-pad_len:] != bytes([pad_len]) * pad_len:
		raise ValueError('Invalid PKCS7 padding')
	decrypted = decrypted_padded[:-pad_len]

	return json.loads(decrypted.decode('utf-8'))


# ---------------------------------------------------------------------------
# Webhook dedup
# ---------------------------------------------------------------------------

_seen_message_ids: dict[str, float] = {}  # message_id -> monotonic timestamp


def _is_duplicate_message(message_id: str) -> bool:
	"""Return True if this message_id was already seen within the dedup window."""
	if not message_id:
		return False
	now = asyncio.get_event_loop().time() if asyncio.get_event_loop().is_running() else 0
	# Evict stale entries periodically
	if len(_seen_message_ids) > 1000:
		cutoff = now - WEBHOOK_DEDUP_TTL_SECONDS
		stale = [k for k, v in _seen_message_ids.items() if v < cutoff]
		for k in stale:
			del _seen_message_ids[k]
	if message_id in _seen_message_ids:
		return True
	_seen_message_ids[message_id] = now
	return False


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title='Merchant Automation Server', lifespan=lifespan)


@app.get('/healthz')
async def healthz():
	return {'status': 'ok', 'pending_tasks': _pool.pending_count() if _pool else 0}


# ---------------------------------------------------------------------------
# Feishu webhook
# ---------------------------------------------------------------------------

def _verify_feishu_token(body: dict) -> bool:
	"""Verify the request came from Feishu by checking the token.

	Supports both v1.0 (body.token) and v2.0 (header.token) formats.
	Returns True if verification is disabled (FEISHU_VERIFICATION_TOKEN not set).
	"""
	config = get_config()
	expected_token = config.FEISHU_VERIFICATION_TOKEN
	if not expected_token:
		logger.warning('FEISHU_VERIFICATION_TOKEN not set, skipping verification')
		return True

	# v2.0 format: header.token
	header_token = body.get('header', {}).get('token', '')
	if header_token:
		return header_token == expected_token

	# v1.0 format: body.token
	body_token = body.get('token', '')
	if body_token:
		return body_token == expected_token

	# No token found in request
	logger.warning('No token found in webhook request')
	return False


@app.post('/feishu/webhook')
async def feishu_webhook(request: Request) -> Response:
	# Read raw body with explicit UTF-8 encoding
	raw_body = await request.body()
	logger.info('Raw body length: %d', len(raw_body))

	# Parse JSON with error handling
	try:
		body = json.loads(raw_body.decode('utf-8'))
	except json.JSONDecodeError as exc:
		logger.warning('Invalid JSON in webhook body: %s', exc)
		return Response(
			content=json.dumps({'code': -1, 'msg': 'Invalid JSON'}),
			media_type='application/json',
			status_code=400,
		)

	# URL verification challenge (v1.0 format) — must respond before token check
	logger.info('Webhook body: %s', json.dumps(body, ensure_ascii=False)[:500])
	if 'challenge' in body:
		logger.info('Returning challenge: %s', body['challenge'])
		return Response(
			content=json.dumps({'challenge': body['challenge']}),
			media_type='application/json',
		)

	# URL verification challenge (v2.0 encrypted format)
	encrypt = body.get('encrypt')
	if encrypt:
		logger.info('Received encrypted payload, attempting decrypt...')
		try:
			body = _decrypt_feishu_payload(encrypt)
			logger.info('Decrypted body: %s', json.dumps(body, ensure_ascii=False)[:500])
			if 'challenge' in body:
				return Response(
					content=json.dumps({'challenge': body['challenge']}),
					media_type='application/json',
				)
		except Exception as e:
			logger.warning('Failed to decrypt: %s', e)
			return Response(
				content=json.dumps({'code': -1, 'msg': 'Decrypt failed'}),
				media_type='application/json',
				status_code=403,
			)

	# Verify request token
	if not _verify_feishu_token(body):
		logger.warning('Feishu token verification failed')
		return Response(
			content=json.dumps({'code': -1, 'msg': 'Invalid token'}),
			media_type='application/json',
			status_code=403,
		)

	# Event callback v2.0
	header = body.get('header', {})
	event_type = header.get('event_type', '')
	event = body.get('event', {})

	logger.info('Feishu event: type=%s', event_type)

	if event_type == 'im.message.receive_v1':
		# Dedup: Feishu may resend the same message on network issues
		msg_id = event.get('message', {}).get('message_id', '')
		if _is_duplicate_message(msg_id):
			logger.info('Dropping duplicate message: %s', msg_id)
		else:
			try:
				await _handle_message_event(event)
			except Exception:
				logger.exception('Error handling message event')

	elif event_type == 'card.action.trigger':
		try:
			await _handle_card_action_event(event)
		except Exception:
			logger.exception('Error handling card action event')

	return Response(
		content=json.dumps({'code': 0}),
		media_type='application/json',
	)


async def _handle_card_action_event(event: dict) -> None:
	"""Handle card action callbacks (retry, cancel, etc.)."""
	action = event.get('action', {})
	value = action.get('value', {})
	action_type = value.get('action')
	chat_id = event.get('context', {}).get('open_chat_id', '')

	logger.info('Card action: type=%s, value=%s, chat_id=%s', action_type, value, chat_id)

	if not action_type:
		return

	if action_type == 'account_login':
		account_id = value.get('account_id')
		if not account_id:
			await _feishu_bot.send_text(chat_id, '未找到要登录的账号，请发送“账号列表”后重试。')
			return
		account = await _account_manager.get_account(account_id)
		if account is None:
			await _feishu_bot.send_text(chat_id, '账号不存在或已被移除，请发送“账号列表”查看当前账号。')
			return
		await _update_login_account_status(account, AccountStatus.NEEDS_LOGIN)
		await _feishu_bot.send_text(
			chat_id,
			f'正在打开 {account.platform}/{account.name} 的登录窗口，请在浏览器中完成登录。',
		)
		asyncio.create_task(_execute_login_flow(account.id, chat_id))
		return

	if action_type == 'account_refresh':
		await _send_account_card(chat_id)
		return

	if action_type == 'account_add':
		await _feishu_bot.send_text(
			chat_id,
			'发送“登录 <平台> <店铺名>”即可添加或重新登录账号，例如：登录 美团 江湖饭焗。',
		)
		return

	if action_type == 'account_delete':
		await _feishu_bot.send_text(chat_id, '为避免误删，飞书端暂不直接删除账号。需要停用账号请联系管理员处理。')
		return

	task_id = value.get('task_id')

	if action_type == 'retry' and task_id:
		task = await _task_queue.get_task(task_id)
		if task:
			new_task = Task(
				user_id=task.user_id,
				chat_id=task.chat_id,
				message_id=task.message_id,
				raw_text=task.raw_text,
				platform=task.platform,
				instruction=task.instruction,
				account_id=task.account_id,
			)
			await _task_queue.submit(new_task)
			await _feishu_bot.send_text(chat_id, '🔄 任务已重新提交')
		return

	if action_type == 'cancel' and task_id:
		await _task_queue.cancel(task_id)
		if _pool:
			await _pool.cancel(task_id)
		await _feishu_bot.send_text(chat_id, '🛑 已取消')
		return


async def _send_account_card(chat_id: str) -> None:
	accounts = await _account_manager.get_all_accounts()
	await _feishu_bot.send_card(chat_id, _feishu_bot.build_account_card(accounts))


async def _find_account_for_instruction(text: str) -> str | None:
	"""Find matching account based on store name in instruction.

	Strategy:
	1. Extract store name from instruction
	2. Search accounts by store name (fuzzy match)
	3. If only one account exists on this platform, use it as default
	4. Otherwise return None (user needs to specify account)
	"""
	import re

	if _account_manager is None:
		return None

	# Extract store name from instruction patterns
	patterns = [
		r'(?:把|将)\s*(?:美团外卖|美团|饿了么|抖音来客|抖音)\s*(.+?)\s*(?:电话|地址|名称|公告|简介|营业时间|门店照片|配送费|配送范围|起送价)',
		r'(?:美团外卖|美团|饿了么|抖音来客|抖音)\s+(.+?)\s+(?:修改|更改|变更)',
	]

	store_name = None
	for pattern in patterns:
		match = re.search(pattern, text)
		if match:
			store_name = match.group(1).strip()
			break

	# Strategy 1: Search by store name
	if store_name:
		if hasattr(_account_manager, 'find_account_for_message'):
			accounts = await _account_manager.find_account_for_message(store_name)
		elif hasattr(_account_manager, 'search_accounts'):
			accounts = await _account_manager.search_accounts(store_name)
		else:
			accounts = []
		if accounts:
			logger.info('Found account for store "%s": %s', store_name, accounts[0].id)
			return accounts[0].id

	# Strategy 2: If only one account exists on this platform, use it as default
	all_accounts = await _account_manager.get_all_accounts()
	if len(all_accounts) == 1:
		logger.info('Only one account exists, using as default: %s', all_accounts[0].id)
		return all_accounts[0].id

	# Strategy 3: If multiple accounts, try to match by username containing store name
	if store_name:
		for account in all_accounts:
			if store_name in (account.name or '') or store_name in (account.username or ''):
				logger.info('Matched account by name/username containing "%s": %s', store_name, account.id)
				return account.id

	return None


async def _handle_message_event(event: dict) -> None:
	message = event.get('message', {})
	chat_id = message.get('chat_id', '')
	sender = event.get('sender', {}).get('sender_id', {})
	user_id = sender.get('open_id', '')
	msg_type = message.get('message_type', '')
	message_id = message.get('message_id', '')

	if msg_type != 'text':
		await _handle_attachment_message(
			msg_type=msg_type,
			content_str=message.get('content', '{}'),
			tenant_key=event.get('tenant_key', ''),
			chat_id=chat_id,
			message_id=message_id,
			user_id=user_id,
		)
		return

	content_str = message.get('content', '{}')
	content = json.loads(content_str)
	text = content.get('text', '').strip()

	# Strip @mention tags
	text = re.sub(r'@_\w+\s*', '', text)
	text = re.sub(r'<at\s+user_id=[^>]*>[^<]*</at>\s*', '', text)
	text = text.strip()

	if not text:
		return

	logger.info('Text message: user=%s, text=%r', user_id, text)

	# Special commands
	if await _handle_special_command(text, user_id, chat_id, message_id):
		return

	store_photo_attachment = await _resolve_store_photo_attachment(text, chat_id=chat_id, user_id=user_id)
	if _is_store_photo_image_task(text) and store_photo_attachment is None:
		await _feishu_bot.reply_text(
			message_id,
			'未找到可用的最近图片。请先上传图片，再发送“把美团 <店铺名> 门店照片换成刚上传的图片”。',
		)
		return

	# Create task and submit
	# Try to find matching account based on store name in instruction
	account_id = await _find_account_for_instruction(text)

	task = Task(
		user_id=user_id,
		chat_id=chat_id,
		message_id=message_id,
		raw_text=text,
		platform='meituan',  # TODO: auto-detect from text
		instruction=text,
		account_id=account_id,
	)

	await _task_queue.submit(task)
	if store_photo_attachment is not None:
		await _task_queue.link_attachment(task.id, store_photo_attachment.id, 'store_photo')
	task_card_msg_id = await _feishu_bot.reply_task_card(message_id, task)
	if task_card_msg_id:
		await _task_queue.set_task_card_message_id(task.id, task_card_msg_id)


def _is_store_photo_image_task(text: str) -> bool:
	normalized = re.sub(r'\s+', '', text)
	has_photo_target = any(
		keyword in normalized
		for keyword in ('门店照片', '门店图片', '门头图', '店铺图', '店铺图片', '装修图', '门店装修图片')
	)
	has_latest_image = any(keyword in normalized for keyword in ('刚上传的图片', '最近图片', '最近的图片', '最近上传的图片'))
	return has_photo_target and has_latest_image


def _select_latest_usable_image(attachments: list[Attachment]) -> Attachment | None:
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


async def _resolve_store_photo_attachment(text: str, *, chat_id: str, user_id: str) -> Attachment | None:
	if not _is_store_photo_image_task(text):
		return None

	attachments = await _task_queue.get_recent_attachments(chat_id=chat_id, user_id=user_id, limit=5)
	return _select_latest_usable_image(attachments)


def _hydrate_latest_image_attachment(bound_task: BoundOperationTask, attachments: list[Attachment]) -> BoundOperationTask:
	"""Replace attachment_id=latest_image with the image attachment linked to the task."""
	if bound_task.task.params.get('attachment_id') != 'latest_image':
		return bound_task

	image_attachment = _select_latest_usable_image(attachments)
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


async def _handle_attachment_message(
	msg_type: str,
	content_str: str,
	tenant_key: str,
	chat_id: str,
	message_id: str,
	user_id: str,
) -> None:
	"""Store Feishu image/file attachment metadata for future task execution."""
	if msg_type not in {'image', 'file'}:
		await _feishu_bot.reply_text(message_id, '暂时只支持文字、图片和文件消息哦~\n请发送文本指令、图片或文件。')
		return

	try:
		content = json.loads(content_str or '{}')
	except json.JSONDecodeError:
		content = {}

	if msg_type == 'image':
		attachment = Attachment(
			tenant_key=tenant_key,
			chat_id=chat_id,
			message_id=message_id,
			uploaded_by_user_id=user_id,
			file_type='image',
			file_name=content.get('file_name') or 'image',
			mime_type=content.get('mime_type') or 'image/*',
			feishu_file_key=content.get('image_key'),
			size_bytes=content.get('file_size'),
			status='stored',
		)
		await _task_queue.add_attachment(attachment)
		await _feishu_bot.reply_text(
			message_id,
			'📎 图片已记录！\n'
			'发送「把美团 <店铺名> 门店照片换成刚上传的图片」即可使用。',
		)
		return

	attachment = Attachment(
		tenant_key=tenant_key,
		chat_id=chat_id,
		message_id=message_id,
		uploaded_by_user_id=user_id,
		file_type='file',
		file_name=content.get('file_name'),
		mime_type=content.get('mime_type'),
		feishu_file_key=content.get('file_key'),
		size_bytes=content.get('file_size'),
		status='stored',
	)
	await _task_queue.add_attachment(attachment)
	await _feishu_bot.reply_text(
		message_id,
		f'📎 文件已记录：{attachment.file_name or "未命名文件"}\n'
		'发送「附件」可查看最近上传的内容。',
	)


def _normalize_command_text(text: str) -> str:
	return re.sub(r'[\s，。！？?、；;：:,.!`~"“”\'‘’（）()\[\]【】<>《》]+', '', text).lower()


def _classify_special_command(text: str) -> str | None:
	from merchant_automation.feishu.commands import classify_feishu_command
	command = classify_feishu_command(text)
	return command.value if command else None


def _is_store_management_command(compact: str) -> bool:
	if compact in ('门店', '店铺', 'stores'):
		return True
	query_phrases = (
		'门店列表',
		'店铺列表',
		'我的门店',
		'我的店铺',
		'查看门店',
		'查看店铺',
		'门店管理',
		'店铺管理',
		'门店信息',
		'店铺信息',
	)
	if compact not in query_phrases and not any(compact.startswith(prefix) for prefix in ('查看门店', '查看店铺')):
		return False
	operation_keywords = (
		'改',
		'修改',
		'更改',
		'变更',
		'设置',
		'设为',
		'换成',
		'上传',
		'电话',
		'营业时间',
		'照片',
		'图片',
		'地址',
		'名称',
		'公告',
		'简介',
	)
	return not any(keyword in compact for keyword in operation_keywords)


async def _handle_special_command(text: str, user_id: str, chat_id: str, message_id: str) -> bool:
	# 登录命令处理
	if await _handle_login_command(text, user_id, chat_id, message_id):
		return True

	command = _classify_special_command(text)

	if command == 'help':
		await _feishu_bot.reply_card(message_id, _feishu_bot.build_help_card())
		return True

	if command == 'login_help':
		await _feishu_bot.reply_card(message_id, _feishu_bot.build_help_card())
		return True

	if command == 'status':
		pending = await _task_queue.get_pending_tasks()
		running = _pool.get_running_task_ids() if _pool else []
		if not pending and not running:
			await _feishu_bot.reply_text(message_id, '📭 当前没有运行中或等待中的任务')
		else:
			lines = [f'📊 运行中: {len(running)}, 等待中: {len(pending)}']
			for t in pending[:5]:
				instruction_preview = t.instruction[:40] + ('...' if len(t.instruction) > 40 else '')
				lines.append(f'  • {instruction_preview}')
			await _feishu_bot.reply_text(message_id, '\n'.join(lines))
		return True

	if command == 'history':
		await _feishu_bot.reply_text(
			message_id,
			'暂不支持查看历史记录。\n任务完成后飞书卡片会同步更新结果，也可发送「状态」查看当前进度。',
		)
		return True

	if command == 'accounts':
		accounts = await _account_manager.get_all_accounts()
		await _feishu_bot.reply_card(message_id, _feishu_bot.build_account_card(accounts))
		return True

	if command == 'stores':
		await _reply_store_management(message_id)
		return True

	if command == 'attachments':
		attachments = await _task_queue.get_recent_attachments(chat_id=chat_id, user_id=user_id, limit=5)
		await _feishu_bot.reply_card(message_id, _feishu_bot.build_attachment_card(attachments))
		return True

	return False


async def _reply_store_management(message_id: str) -> None:
	accounts = await _account_manager.get_all_accounts()
	lines = ['门店信息会跟随账号登录和任务绑定逐步完善。']
	if accounts:
		lines.append('当前已配置账号：')
		for account in accounts[:5]:
			platform = getattr(account, 'platform', '平台')
			name = getattr(account, 'name', '未命名账号')
			lines.append(f'• {platform}/{name}')
	else:
		lines.append('当前还没有已配置账号。')
	lines.append('可以发送“账号列表”查看登录状态，或发送“登录 美团 <店铺名>”添加门店账号。')
	await _feishu_bot.reply_text(message_id, '\n'.join(lines))


async def _handle_login_command(text: str, user_id: str, chat_id: str, message_id: str) -> bool:
	"""处理登录命令，如：登录美团江湖饭焗"""
	match = re.match(
		r'^(?:重新登录|重新登陆|重新登入|登录|登陆|登入|打开|进入)\s*'
		r'(?P<platform>美团外卖|美团|饿了么|抖音来客|抖音)\s*(?P<store>.+)$',
		text,
	)
	if not match:
		return False

	platform_name = match.group('platform')
	store_name = match.group('store').strip()
	if not store_name:
		await _feishu_bot.reply_text(message_id, '格式：登录 <平台> <账号/店铺名>\n例如：登录 美团 江湖饭焗')
		return True

	# 解析平台
	platform_map = {
		'美团': 'meituan',
		'美团外卖': 'meituan',
		'饿了么': 'eleme',
		'抖音': 'douyin',
		'抖音来客': 'douyin',
	}
	platform = platform_map.get(platform_name) or platform_map.get(platform_name.lower())
	if not platform:
		await _feishu_bot.reply_text(message_id, f'❌ 不支持的平台: {platform_name}')
		return True

	accounts = await _account_manager.search_accounts(store_name)
	accounts = [account for account in accounts if account.platform == platform]
	if accounts:
		account = accounts[0]
		await _update_login_account_status(account, AccountStatus.NEEDS_LOGIN)
	else:
		account = await _account_manager.create_account(name=store_name, platform=platform)
		_sync_account_store(account, AccountStatus.NEEDS_LOGIN)

	await _feishu_bot.reply_text(
		message_id,
		f'🔐 正在打开浏览器登录 {_platform_display(platform)}/{account.name}...\n'
		f'请在弹出的浏览器窗口中完成登录操作。',
	)

	# 异步执行登录流程
	asyncio.create_task(_execute_login_flow(account.id, chat_id))
	return True


async def _execute_login_flow(account_id: str, chat_id: str) -> None:
	"""执行登录流程"""
	from browser_use import BrowserSession
	from browser_use.browser.profile import BrowserProfile

	account = await _account_manager.get_account(account_id)
	if not account:
		await _feishu_bot.send_text(chat_id, '❌ 账号不存在')
		return

	login_url = _login_url_for_platform(account.platform)
	session: BrowserSession | None = None
	should_close_session = False
	try:
		_ensure_login_browser_start_timeout()
		profile = BrowserProfile(
			headless=False,
			user_data_dir=account.profile_dir,
			window_size={'width': 1280, 'height': 900},
			enable_default_extensions=False,
		)
		session = BrowserSession(browser_profile=profile)
		await session.start()
		await session.navigate_to(login_url)

		await _feishu_bot.send_text(
			chat_id,
			f'🔐 已打开 {_platform_display(account.platform)}/{account.name} 登录页面。\n'
			f'请在浏览器窗口中完成登录，系统检测到登录成功后会自动关闭窗口。',
		)

		login_success = await _wait_for_login_success(
			session,
			account.platform,
			timeout_seconds=LOGIN_WAIT_TIMEOUT_SECONDS,
			poll_seconds=LOGIN_CHECK_POLL_SECONDS,
		)

		if login_success:
			should_close_session = True
			await _update_login_account_status(account, AccountStatus.ACTIVE)
			await _feishu_bot.send_text(chat_id, f'✅ {account.name} 登录成功，登录态已保存。')
		else:
			await _update_login_account_status(account, AccountStatus.NEEDS_LOGIN)
			await _feishu_bot.send_text(
				chat_id,
				f'⚠️ {account.name} 暂未检测到登录成功，浏览器窗口已保留。\n'
				f'如果你已完成登录，可重新发送任务；如果仍未登录，请继续在窗口中操作或再次发送「登录 {_platform_display(account.platform)} {account.name}」。',
			)

	except Exception:
		logger.exception('Login flow failed')
		await _update_login_account_status(account, AccountStatus.NEEDS_LOGIN)
		await _feishu_bot.send_text(chat_id, f'❌ {account.name} 登录过程中出现问题，请稍后重试。')
	finally:
		if session is not None and should_close_session:
			try:
				await session.close()
			except Exception:
				logger.warning('Failed to close login browser session', exc_info=True)


async def _wait_for_login_success(
	session,
	platform: str,
	timeout_seconds: float,
	poll_seconds: float,
) -> bool:
	"""Wait until the visible login browser reaches an authenticated merchant backend page."""
	loop = asyncio.get_running_loop()
	deadline = loop.time() + timeout_seconds
	while loop.time() <= deadline:
		url, title, page_text = await _read_login_probe(session)
		logger.info('Login probe platform=%s url=%s title=%s', platform, url[:200], title[:80])
		if _is_login_success(platform, url=url, title=title, page_text=page_text):
			return True
		await asyncio.sleep(poll_seconds)
	return False


async def _read_login_probe(session) -> tuple[str, str, str]:
	"""Read a small page snapshot for deterministic login-state detection."""
	url = ''
	title = ''
	page_text = ''
	try:
		url = await session.get_current_page_url()
	except Exception:
		logger.debug('Failed to read login page url', exc_info=True)
	try:
		title = await session.get_current_page_title()
	except Exception:
		logger.debug('Failed to read login page title', exc_info=True)
	try:
		page = await session.get_current_page()
		if page is not None:
			page_text = await page.evaluate(
				f'() => ((document.body && document.body.innerText) || "").slice(0, {LOGIN_PAGE_TEXT_LIMIT})'
			)
	except Exception:
		logger.debug('Failed to read login page text', exc_info=True)
	return url, title, page_text


def _is_login_success(platform: str, *, url: str, title: str, page_text: str) -> bool:
	"""Return True only when the page looks like an authenticated merchant backend."""
	rules = LOGIN_DETECTION_RULES.get(platform, LOGIN_DETECTION_RULES['meituan'])
	url_lower = url.lower()
	combined = f'{url}\n{title}\n{page_text}'.lower()

	if any(marker in url_lower for marker in rules['login_url_markers']):
		return False

	if any(marker in url_lower for marker in rules['success_url_markers']):
		return True

	success_hits = sum(1 for marker in rules['success_text_markers'] if marker.lower() in combined)
	login_hits = sum(1 for marker in rules['login_text_markers'] if marker.lower() in combined)

	if success_hits >= 3:
		return True
	return success_hits >= 2 and login_hits == 0


def _login_url_for_platform(platform: str) -> str:
	login_urls = {
		'meituan': 'https://e.waimai.meituan.com/',
		'eleme': 'https://shop.ele.me/',
		'douyin': 'https://life.douyin.com/',
	}
	return login_urls.get(platform, 'https://e.waimai.meituan.com/')


async def _update_login_account_status(account: Account, status: AccountStatus) -> None:
	await _account_manager.update_status(account.id, status)
	_sync_account_store(account, status)


async def _sync_existing_login_accounts() -> None:
	if _account_store is None:
		return

	for account in await _account_manager.get_all_accounts():
		_sync_account_store(account, account.status)


def _sync_account_store(account: Account, status: AccountStatus) -> None:
	if _account_store is None:
		return

	_account_store.upsert_account(
		PlatformAccount(
			account_id=account.id,
			platform=account.platform,
			username=getattr(account, 'username', None) or account.name,
			profile_path=account.profile_dir,
			login_status=_to_login_status(status),
		)
	)


def _to_login_status(status: AccountStatus) -> LoginStatus:
	if status == AccountStatus.ACTIVE:
		return LoginStatus.LOGGED_IN
	if status == AccountStatus.NEEDS_LOGIN:
		return LoginStatus.EXPIRED
	return LoginStatus.UNKNOWN


def _create_llm():
	from browser_use.llm.openai.chat import ChatOpenAI

	return ChatOpenAI(
		model=_config.LLM_MODEL,
		base_url=_config.LLM_BASE_URL,
		api_key=_config.LLM_API_KEY,
	)


# ---------------------------------------------------------------------------
# Dashboard mount
# ---------------------------------------------------------------------------

def _mount_dashboard():
	"""Mount the merchant_automation dashboard routes."""
	from merchant_automation.dashboard.routes import create_dashboard_router

	db_dir = Path(_config.TASK_DB_PATH).parent if _config else Path('.')
	account_store = _account_store
	if account_store is None:
		account_store = AccountStore(db_dir / 'account.db')
		account_store.initialize()

	router = create_dashboard_router(
		_operation_store,
		recipe_store=_recipe_store,
		account_store=account_store,
	)
	app.include_router(router)


# ---------------------------------------------------------------------------
# Background worker
# ---------------------------------------------------------------------------

async def _worker_loop(pool: MerchantTaskExecutorPool) -> None:
	while True:
		try:
			task = await _task_queue.process_next(timeout=5.0)
			if task is None:
				continue
			logger.info('Worker picked up task %s', task.id)
			await pool.submit(task)
		except asyncio.CancelledError:
			break
		except Exception:
			logger.exception('Worker loop error')
			await asyncio.sleep(5)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == '__main__':
	import uvicorn

	port = int(os.environ.get('PORT', get_config().SERVER_PORT))
	uvicorn.run('merchant_automation.server:app', host='0.0.0.0', port=port, reload=False)
