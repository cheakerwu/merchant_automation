from pathlib import Path

from fastapi.testclient import TestClient

from merchant_automation.accounts.models import LoginStatus, PlatformAccount, Store
from merchant_automation.accounts.store import AccountStore
from merchant_automation.dashboard.routes import create_dashboard_app
from merchant_automation.operations.failure import FailureAnalyzer
from merchant_automation.operations.preflight import CommitPolicy
from merchant_automation.operations.recipe_definition import RecipeDefinition, RecipeStep, RecipeStepAction
from merchant_automation.operations.recipe_store import RecipeStore
from merchant_automation.operations.schemas import ExecutionMode, FailureType, RecipeMetadata, RecipeStatus
from merchant_automation.operations.service import OperationPlanningService
from merchant_automation.operations.storage import OperationStore
from merchant_automation.operations.traces import ExecutionTrace, TraceOutcome, TraceOutcomeStatus


def _seed_store(tmp_path: Path) -> OperationStore:
	store = OperationStore(tmp_path / 'merchant.db')
	store.initialize()
	planning = OperationPlanningService().plan_text('把美团 A店 电话改成 13800138000', policy=CommitPolicy())
	run_id = store.save_planning_result(planning)
	trace = ExecutionTrace(
		platform='meituan',
		store_id='A店',
		operation_id='update_store_phone',
		recipe_id='meituan.update_store_phone.v1',
		mode=ExecutionMode.PREPARE,
		params={'phone': '13800138000'},
		outcome=TraceOutcome(
			status=TraceOutcomeStatus.FAILED,
			message='保存按钮找不到',
			failure_type=FailureType.SUBMIT_FAILED,
			failed_step_number=1,
		),
	)
	trace_id = store.save_trace(trace, run_id=run_id)
	store.save_failure_analysis(FailureAnalyzer().analyze(trace, similar_recent_failures=3), trace_id=trace_id)
	return store


def test_dashboard_home_renders_planning_runs(tmp_path: Path):
	client = TestClient(create_dashboard_app(_seed_store(tmp_path)))

	response = client.get('/dashboard')

	assert response.status_code == 200
	assert '任务中心' in response.text
	assert 'text' in response.text
	assert '任务数' in response.text


def test_dashboard_traces_renders_trace_summaries(tmp_path: Path):
	client = TestClient(create_dashboard_app(_seed_store(tmp_path)))

	response = client.get('/dashboard/traces')

	assert response.status_code == 200
	assert '轨迹中心' in response.text
	assert 'update_store_phone' in response.text
	assert 'submit_failed' in response.text


def test_dashboard_failures_renders_failure_summaries(tmp_path: Path):
	client = TestClient(create_dashboard_app(_seed_store(tmp_path)))

	response = client.get('/dashboard/failures')

	assert response.status_code == 200
	assert '失败分析' in response.text
	assert 'submit_failed' in response.text
	assert '疑似过期' in response.text


def test_dashboard_escapes_stored_text(tmp_path: Path):
	store = OperationStore(tmp_path / 'merchant.db')
	store.initialize()
	store.save_trace(
		ExecutionTrace(
			platform='meituan',
			store_id='<script>alert(1)</script>',
			operation_id='update_store_phone',
			recipe_id='meituan.update_store_phone.v1',
			mode=ExecutionMode.PREPARE,
		)
	)
	client = TestClient(create_dashboard_app(store))

	response = client.get('/dashboard/traces')

	assert '<script>alert(1)</script>' not in response.text
	assert '&lt;script&gt;alert(1)&lt;/script&gt;' in response.text


def test_dashboard_requests_release_sqlite_file_handles(tmp_path: Path):
	db_path = tmp_path / 'merchant.db'
	store = OperationStore(db_path)
	store.initialize()
	store.save_planning_result(OperationPlanningService().plan_text('把美团 A店 电话改成 13800138000'))
	client = TestClient(create_dashboard_app(store))

	assert client.get('/dashboard').status_code == 200
	assert client.get('/dashboard/traces').status_code == 200
	assert client.get('/dashboard/failures').status_code == 200

	db_path.unlink()
	assert not db_path.exists()


# ---------------------------------------------------------------------------
# Recipe Console & Account/Store helpers
# ---------------------------------------------------------------------------


def _seed_recipe_store(tmp_path: Path) -> RecipeStore:
	store = RecipeStore(tmp_path / 'recipes.db')
	store.initialize()
	store.upsert_recipe(
		RecipeMetadata(
			recipe_id='meituan.update_store_phone.v1',
			operation_id='update_store_phone',
			platform='meituan',
			version=1,
			status=RecipeStatus.PREPARE_READY,
			allowed_modes={ExecutionMode.PREPARE, ExecutionMode.COMMIT},
			success_rates={ExecutionMode.PREPARE: 0.95, ExecutionMode.COMMIT: 0.80},
		)
	)
	store.upsert_recipe(
		RecipeMetadata(
			recipe_id='douyin.update_store_name.v2',
			operation_id='update_store_name',
			platform='douyin',
			version=2,
			status=RecipeStatus.CANDIDATE,
			allowed_modes={ExecutionMode.DRY_RUN},
			success_rates={ExecutionMode.DRY_RUN: 1.0},
		)
	)
	return store


def _seed_account_store(tmp_path: Path) -> AccountStore:
	store = AccountStore(tmp_path / 'accounts.db')
	store.initialize()
	store.upsert_account(
		PlatformAccount(
			account_id='acct-001',
			platform='meituan',
			username='merchant_user',
			login_status=LoginStatus.LOGGED_IN,
			default_mode=ExecutionMode.PREPARE,
			commit_allowed=True,
			last_failure_reason=None,
		)
	)
	store.upsert_account(
		PlatformAccount(
			account_id='acct-002',
			platform='douyin',
			username='dy_user',
			login_status=LoginStatus.EXPIRED,
			default_mode=ExecutionMode.DRY_RUN,
			commit_allowed=False,
			last_failure_reason='登录过期',
		)
	)
	store.upsert_store(
		Store(
			store_id='store-001',
			platform='meituan',
			account_id='acct-001',
			store_name='A 店',
		)
	)
	store.upsert_store(
		Store(
			store_id='store-002',
			platform='meituan',
			account_id='acct-001',
			store_name='B 店',
		)
	)
	return store


# ---------------------------------------------------------------------------
# Recipe Console tests
# ---------------------------------------------------------------------------


def test_recipe_console_renders_recipe_list(tmp_path: Path):
	recipe_store = _seed_recipe_store(tmp_path)
	client = TestClient(create_dashboard_app(_operation_store(tmp_path), recipe_store=recipe_store))

	response = client.get('/dashboard/recipes')

	assert response.status_code == 200
	assert 'meituan.update_store_phone.v1' in response.text
	assert 'douyin.update_store_name.v2' in response.text
	assert 'prepare_ready' in response.text
	assert 'candidate' in response.text


def _operation_store(tmp_path: Path) -> OperationStore:
	store = OperationStore(tmp_path / 'merchant.db')
	store.initialize()
	return store


def test_recipe_detail_renders_full_metadata(tmp_path: Path):
	recipe_store = _seed_recipe_store(tmp_path)
	client = TestClient(create_dashboard_app(_operation_store(tmp_path), recipe_store=recipe_store))

	response = client.get('/dashboard/recipes/meituan.update_store_phone.v1')

	assert response.status_code == 200
	assert 'meituan.update_store_phone.v1' in response.text
	assert 'update_store_phone' in response.text
	assert 'meituan' in response.text
	assert 'prepare_ready' in response.text
	assert 'Recipe 控制台' in response.text


def test_recipe_status_toggle(tmp_path: Path):
	recipe_store = _seed_recipe_store(tmp_path)
	client = TestClient(create_dashboard_app(_operation_store(tmp_path), recipe_store=recipe_store))

	response = client.post(
		'/dashboard/recipes/meituan.update_store_phone.v1/status',
		data={'new_status': 'disabled'},
		follow_redirects=False,
	)

	assert response.status_code == 307
	assert response.headers['location'] == '/dashboard/recipes/meituan.update_store_phone.v1'

	recipe = recipe_store.get_recipe('meituan.update_store_phone.v1')
	assert recipe is not None
	assert recipe.status == RecipeStatus.DISABLED


def test_recipe_console_shows_message_when_no_store(tmp_path: Path):
	client = TestClient(create_dashboard_app(_operation_store(tmp_path)))

	response = client.get('/dashboard/recipes')

	assert response.status_code == 200
	assert 'Recipe Store 未配置' in response.text


# ---------------------------------------------------------------------------
# Account & Store Center tests
# ---------------------------------------------------------------------------


def test_accounts_page_renders_account_list(tmp_path: Path):
	account_store = _seed_account_store(tmp_path)
	client = TestClient(create_dashboard_app(_operation_store(tmp_path), account_store=account_store))

	response = client.get('/dashboard/accounts')

	assert response.status_code == 200
	assert 'acct-001' in response.text
	assert 'acct-002' in response.text
	assert 'merchant_user' in response.text
	assert 'dy_user' in response.text
	assert 'logged_in' in response.text
	assert 'expired' in response.text


def test_account_detail_shows_stores(tmp_path: Path):
	account_store = _seed_account_store(tmp_path)
	client = TestClient(create_dashboard_app(_operation_store(tmp_path), account_store=account_store))

	response = client.get('/dashboard/accounts/acct-001')

	assert response.status_code == 200
	assert 'acct-001' in response.text
	assert 'merchant_user' in response.text
	assert 'store-001' in response.text
	assert 'store-002' in response.text


def test_stores_page_renders_store_list(tmp_path: Path):
	account_store = _seed_account_store(tmp_path)
	client = TestClient(create_dashboard_app(_operation_store(tmp_path), account_store=account_store))

	response = client.get('/dashboard/stores')

	assert response.status_code == 200
	assert 'store-001' in response.text
	assert 'store-002' in response.text
	assert 'A 店' in response.text
	assert 'B 店' in response.text


def test_accounts_page_shows_message_when_no_store(tmp_path: Path):
	client = TestClient(create_dashboard_app(_operation_store(tmp_path)))

	response = client.get('/dashboard/accounts')

	assert response.status_code == 200
	assert 'Account Store 未配置' in response.text


def test_recipe_detail_returns_404_for_unknown_id(tmp_path: Path):
	recipe_store = _seed_recipe_store(tmp_path)
	client = TestClient(create_dashboard_app(_operation_store(tmp_path), recipe_store=recipe_store))

	response = client.get('/dashboard/recipes/nonexistent.recipe.v1')

	assert response.status_code == 404


def test_account_detail_returns_404_for_unknown_id(tmp_path: Path):
	account_store = _seed_account_store(tmp_path)
	client = TestClient(create_dashboard_app(_operation_store(tmp_path), account_store=account_store))

	response = client.get('/dashboard/accounts/nonexistent')

	assert response.status_code == 404


def test_nav_bar_includes_new_links(tmp_path: Path):
	client = TestClient(create_dashboard_app(_operation_store(tmp_path)))

	response = client.get('/dashboard')

	assert response.status_code == 200
	assert '/dashboard/recipes' in response.text
	assert '/dashboard/accounts' in response.text
	assert 'Recipe 控制台' in response.text
	assert '账号门店' in response.text


# ---------------------------------------------------------------------------
# M4: Definition-aware Recipe Console tests
# ---------------------------------------------------------------------------


def _seed_recipe_store_with_definitions(tmp_path: Path) -> RecipeStore:
	"""Seed recipe store with both metadata and definitions."""
	store = RecipeStore(tmp_path / 'recipes.db')
	store.initialize()

	# Recipe with definition (auto-synthesized)
	store.upsert_recipe(
		RecipeMetadata(
			recipe_id='meituan.update_store_phone.v1',
			operation_id='update_store_phone',
			platform='meituan',
			version=1,
			status=RecipeStatus.CANDIDATE,
			allowed_modes={ExecutionMode.PREPARE},
			success_rates={},
		)
	)
	store.save_definition(
		RecipeDefinition(
			recipe_id='meituan.update_store_phone.v1',
			steps=[
				RecipeStep(action=RecipeStepAction.NAVIGATE, url='https://e.waimai.meituan.com/', value='https://e.waimai.meituan.com/'),
				RecipeStep(action=RecipeStepAction.CLICK, target='电话输入框'),
				RecipeStep(action=RecipeStepAction.FILL, target='电话输入框', value='{phone}'),
				RecipeStep(action=RecipeStepAction.STOP_BEFORE_SUBMIT),
			],
			entry_url='https://e.waimai.meituan.com/',
		),
		source='auto',
	)

	# Recipe without definition
	store.upsert_recipe(
		RecipeMetadata(
			recipe_id='douyin.update_store_name.v2',
			operation_id='update_store_name',
			platform='douyin',
			version=2,
			status=RecipeStatus.PREPARE_READY,
			allowed_modes={ExecutionMode.DRY_RUN},
			success_rates={ExecutionMode.DRY_RUN: 1.0},
		)
	)

	return store


def test_recipe_list_shows_step_count_and_source(tmp_path: Path):
	recipe_store = _seed_recipe_store_with_definitions(tmp_path)
	client = TestClient(create_dashboard_app(_operation_store(tmp_path), recipe_store=recipe_store))

	response = client.get('/dashboard/recipes')

	assert response.status_code == 200
	# Should show step count and source columns
	assert '步骤数' in response.text
	assert '来源' in response.text
	# First recipe has 4 steps, auto source
	assert '4' in response.text
	assert 'auto' in response.text
	# Second recipe has no definition
	assert '-' in response.text  # placeholder for missing definition


def test_recipe_detail_renders_synthesized_steps(tmp_path: Path):
	recipe_store = _seed_recipe_store_with_definitions(tmp_path)
	client = TestClient(create_dashboard_app(_operation_store(tmp_path), recipe_store=recipe_store))

	response = client.get('/dashboard/recipes/meituan.update_store_phone.v1')

	assert response.status_code == 200
	# Should show entry_url
	assert 'https://e.waimai.meituan.com/' in response.text
	# Should show step table headers
	assert '操作' in response.text
	assert '目标' in response.text
	assert '值' in response.text
	# Should show step actions
	assert 'navigate' in response.text
	assert 'click' in response.text
	assert 'fill' in response.text
	assert 'stop_before_submit' in response.text
	# Should show targets
	assert '电话输入框' in response.text


def test_recipe_status_promotion_via_form(tmp_path: Path):
	recipe_store = _seed_recipe_store_with_definitions(tmp_path)
	client = TestClient(create_dashboard_app(_operation_store(tmp_path), recipe_store=recipe_store))

	# Promote candidate → prepare_ready
	response = client.post(
		'/dashboard/recipes/meituan.update_store_phone.v1/status',
		data={'new_status': 'prepare_ready'},
		follow_redirects=False,
	)

	assert response.status_code == 307

	recipe = recipe_store.get_recipe('meituan.update_store_phone.v1')
	assert recipe is not None
	assert recipe.status == RecipeStatus.PREPARE_READY


def test_recipe_detail_shows_entry_url(tmp_path: Path):
	recipe_store = _seed_recipe_store_with_definitions(tmp_path)
	client = TestClient(create_dashboard_app(_operation_store(tmp_path), recipe_store=recipe_store))

	response = client.get('/dashboard/recipes/meituan.update_store_phone.v1')

	assert response.status_code == 200
	assert '入口 URL' in response.text
	assert 'https://e.waimai.meituan.com/' in response.text
