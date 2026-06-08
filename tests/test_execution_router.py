"""Tests for ExecutionRouter — layered execution entry point."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merchant_automation.operations.binder import BoundOperationTask
from merchant_automation.operations.preflight import PreflightResult
from merchant_automation.operations.recipe_definition import RecipeDefinition, RecipeStep, RecipeStepAction
from merchant_automation.operations.router import ExecutionRouter
from merchant_automation.operations.schemas import (
	ExecutionMode,
	FailureType,
	OperationTask,
	RecipeMetadata,
	RecipeStatus,
)
from merchant_automation.operations.traces import ExecutionTrace, TraceOutcome, TraceOutcomeStatus


@pytest.fixture
def mock_browser_session():
	return MagicMock()


@pytest.fixture
def mock_llm():
	return MagicMock()


@pytest.fixture
def sample_bound_task():
	return BoundOperationTask(
		task=OperationTask(
			platform='meituan',
			store_id='A店',
			operation_id='update_store_phone',
			params={'phone': '13800138000'},
			mode=ExecutionMode.PREPARE,
		),
		recipe=RecipeMetadata(
			recipe_id='meituan.update_store_phone.v1',
			operation_id='update_store_phone',
			platform='meituan',
			version=1,
			status=RecipeStatus.PREPARE_READY,
		),
		preflight=PreflightResult(
			allowed=True,
			requested_mode=ExecutionMode.PREPARE,
			effective_mode=ExecutionMode.PREPARE,
		),
	)


@pytest.fixture
def unseeded_bound_task(sample_bound_task):
	task = sample_bound_task.task.model_copy(update={'recipe_id': 'custom.update_store_phone.v1'})
	recipe = sample_bound_task.recipe.model_copy(
		update={
			'recipe_id': 'custom.update_store_phone.v1',
			'status': RecipeStatus.CANDIDATE,
		}
	)
	return sample_bound_task.model_copy(update={'task': task, 'recipe': recipe})


@pytest.fixture
def parse_only_bound_task():
	return BoundOperationTask(
		task=OperationTask(
			platform='meituan',
			store_id='A店',
			operation_id='update_store_phone',
			params={'phone': '13800138000'},
			mode=ExecutionMode.PARSE_ONLY,
		),
		recipe=RecipeMetadata(
			recipe_id='meituan.update_store_phone.v1',
			operation_id='update_store_phone',
			platform='meituan',
			version=1,
			status=RecipeStatus.PREPARE_READY,
		),
		preflight=PreflightResult(
			allowed=True,
			requested_mode=ExecutionMode.PARSE_ONLY,
			effective_mode=ExecutionMode.PARSE_ONLY,
		),
	)


@pytest.fixture
def sample_recipe_def():
	return RecipeDefinition(
		recipe_id='meituan.update_store_phone.v1',
		steps=[RecipeStep(action=RecipeStepAction.NAVIGATE, url='https://example.com')],
	)


def _make_success_trace() -> ExecutionTrace:
	return ExecutionTrace(
		platform='meituan',
		store_id='A店',
		operation_id='update_store_phone',
		recipe_id='meituan.update_store_phone.v1',
		mode=ExecutionMode.PREPARE,
		outcome=TraceOutcome(status=TraceOutcomeStatus.SUCCESS, message='done'),
	)


# ---------- Test 1: parse_only returns immediately ----------

@pytest.mark.asyncio
async def test_parse_only_returns_immediately(parse_only_bound_task, mock_browser_session):
	"""PARSE_ONLY mode should return a completed trace without calling any executor."""
	from merchant_automation.operations.router import ExecutionRouter

	router = ExecutionRouter(mock_browser_session)

	trace = await router.execute(parse_only_bound_task)

	assert trace.outcome is not None
	assert trace.outcome.status == TraceOutcomeStatus.SUCCESS
	assert '仅解析' in trace.outcome.message


# ---------- Test 2: routes to step executor when recipe has steps ----------

@pytest.mark.asyncio
@patch('merchant_automation.operations.router.RecipeStepExecutor')
async def test_routes_to_step_executor_when_recipe_has_steps(
	mock_step_class,
	mock_browser_session,
	mock_llm,
	sample_bound_task,
	sample_recipe_def,
):
	"""When a RecipeDefinition with steps exists, ExecutionRouter should delegate to RecipeStepExecutor."""
	from merchant_automation.operations.router import ExecutionRouter

	mock_executor = MagicMock()
	mock_step_class.return_value = mock_executor
	mock_executor.execute = AsyncMock(return_value=_make_success_trace())

	router = ExecutionRouter(
		mock_browser_session,
		mock_llm,
		recipe_definitions={'meituan.update_store_phone.v1': sample_recipe_def},
	)
	trace = await router.execute(sample_bound_task)

	mock_executor.execute.assert_called_once()
	assert trace.outcome is not None
	assert trace.outcome.status == TraceOutcomeStatus.SUCCESS


# ---------- Test 2.1: routes to built-in defaults when persisted definitions are empty ----------

@pytest.mark.asyncio
@patch('merchant_automation.operations.router.RecipeStepExecutor')
async def test_routes_to_builtin_default_definition_when_definition_map_empty(
	mock_step_class,
	mock_browser_session,
	sample_bound_task,
):
	"""Built-in default definitions keep default recipes deterministic when the DB table is empty."""
	mock_executor = MagicMock()
	mock_step_class.return_value = mock_executor
	mock_executor.execute = AsyncMock(return_value=_make_success_trace())

	router = ExecutionRouter(
		mock_browser_session,
		llm=None,
		recipe_definitions={},
	)
	trace = await router.execute(sample_bound_task)

	mock_executor.execute.assert_called_once()
	default_definition = mock_executor.execute.call_args.args[0]
	assert default_definition.recipe_id == 'meituan.update_store_phone.v1'
	assert default_definition.steps
	assert trace.outcome is not None
	assert trace.outcome.status == TraceOutcomeStatus.SUCCESS


# ---------- Test 3: routes to agent explorer when no steps ----------

@pytest.mark.asyncio
@patch('merchant_automation.operations.router.RecipeStepExecutor')
@patch('merchant_automation.operations.router.AgentExplorer')
async def test_routes_to_agent_explorer_when_no_steps(
	mock_explorer_class,
	mock_step_class,
	mock_browser_session,
	mock_llm,
	unseeded_bound_task,
):
	"""When no RecipeDefinition is found, ExecutionRouter should fall back to AgentExplorer."""
	from merchant_automation.operations.router import ExecutionRouter

	mock_explorer = MagicMock()
	mock_explorer_class.return_value = mock_explorer
	mock_explorer.explore = AsyncMock(return_value=_make_success_trace())

	router = ExecutionRouter(mock_browser_session, mock_llm)
	trace = await router.execute(unseeded_bound_task)

	mock_explorer.explore.assert_called_once()


# ---------- Test 3.1: forwards max_steps to explorer ----------

@pytest.mark.asyncio
@patch('merchant_automation.operations.router.AgentExplorer')
async def test_forwards_max_steps_to_agent_explorer(
	mock_explorer_class,
	mock_browser_session,
	mock_llm,
	unseeded_bound_task,
):
	mock_explorer = MagicMock()
	mock_explorer_class.return_value = mock_explorer
	mock_explorer.explore = AsyncMock(return_value=_make_success_trace())

	router = ExecutionRouter(
		browser_session=mock_browser_session,
		llm=mock_llm,
		recipe_definitions={},
	)

	trace = await router.execute(unseeded_bound_task, raw_input='test input', max_steps=12)

	mock_explorer.explore.assert_called_once()
	assert mock_explorer.explore.call_args.kwargs['max_steps'] == 12
	assert trace.outcome is not None
	assert trace.outcome.status == TraceOutcomeStatus.SUCCESS


# ---------- Test 4: falls back to explorer on step failure ----------

@pytest.mark.asyncio
@patch('merchant_automation.operations.router.RecipeStepExecutor')
@patch('merchant_automation.operations.router.AgentExplorer')
async def test_falls_back_to_explorer_on_step_failure(
	mock_explorer_class,
	mock_step_class,
	mock_browser_session,
	mock_llm,
	sample_bound_task,
	sample_recipe_def,
):
	"""When StepExecutor raises StepExecutionError, ExecutionRouter should fall back to AgentExplorer."""
	from merchant_automation.operations.executor import StepExecutionError
	from merchant_automation.operations.router import ExecutionRouter

	mock_executor = MagicMock()
	mock_step_class.return_value = mock_executor
	failed_step = RecipeStep(action=RecipeStepAction.CLICK, target='missing')
	mock_executor.execute = AsyncMock(
		side_effect=StepExecutionError('element not found', 0, failed_step)
	)

	mock_explorer = MagicMock()
	mock_explorer_class.return_value = mock_explorer
	mock_explorer.explore = AsyncMock(return_value=_make_success_trace())

	router = ExecutionRouter(
		mock_browser_session,
		mock_llm,
		recipe_definitions={'meituan.update_store_phone.v1': sample_recipe_def},
	)
	trace = await router.execute(sample_bound_task)

	mock_executor.execute.assert_called_once()
	mock_explorer.explore.assert_called_once()
	assert trace.outcome is not None
	assert trace.outcome.status == TraceOutcomeStatus.SUCCESS


# ---------- Test 5: fails when no executor available ----------

@pytest.mark.asyncio
@patch('merchant_automation.operations.router.RecipeStepExecutor')
async def test_fails_when_no_executor_available(
	mock_step_class,
	mock_browser_session,
	unseeded_bound_task,
):
	"""When no RecipeDefinition exists and no LLM is configured, ExecutionRouter should fail."""
	from merchant_automation.operations.router import ExecutionRouter

	router = ExecutionRouter(mock_browser_session, llm=None)
	trace = await router.execute(unseeded_bound_task)

	assert trace.outcome is not None
	assert trace.outcome.status == TraceOutcomeStatus.FAILED
	assert trace.outcome.failure_type == FailureType.SUBMIT_FAILED
	assert '无可用执行器' in trace.outcome.message


# ---------- Test 6: counts recent failures ----------

def test_counts_recent_failures(
	mock_browser_session,
	mock_llm,
	sample_bound_task,
	sample_recipe_def,
):
	"""ExecutionRouter should count failures from OperationStore and skip step executor when failures > 0."""
	from datetime import datetime, timedelta, timezone
	from merchant_automation.operations.router import ExecutionRouter
	from merchant_automation.operations.storage import TraceSummary

	recent_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

	mock_store = MagicMock()
	failed_traces = [
		TraceSummary(
			trace_id='t1',
			operation_id='update_store_phone',
			platform='meituan',
			store_id='A店',
			recipe_id='meituan.update_store_phone.v1',
			mode=ExecutionMode.PREPARE,
			outcome_status=TraceOutcomeStatus.FAILED,
			created_at=recent_time,
		),
		TraceSummary(
			trace_id='t2',
			operation_id='update_store_phone',
			platform='meituan',
			store_id='A店',
			recipe_id='meituan.update_store_phone.v1',
			mode=ExecutionMode.PREPARE,
			outcome_status=TraceOutcomeStatus.FAILED,
			created_at=recent_time,
		),
		TraceSummary(
			trace_id='t3',
			operation_id='update_store_phone',
			platform='meituan',
			store_id='A店',
			recipe_id='meituan.update_store_phone.v1',
			mode=ExecutionMode.PREPARE,
			outcome_status=TraceOutcomeStatus.SUCCESS,
			created_at=recent_time,
		),
	]
	mock_store.list_traces.return_value = failed_traces

	router = ExecutionRouter(
		mock_browser_session,
		mock_llm,
		store=mock_store,
	)

	count = router._count_recent_failures('meituan.update_store_phone.v1')

	assert count == 2


# ---------- Test 7: skips step executor when recent failures ----------

@pytest.mark.asyncio
@patch('merchant_automation.operations.router.RecipeStepExecutor')
@patch('merchant_automation.operations.router.AgentExplorer')
async def test_skips_step_executor_when_recent_failures(
	mock_explorer_class,
	mock_step_class,
	mock_browser_session,
	mock_llm,
	sample_bound_task,
	sample_recipe_def,
):
	"""When recent failures > 0, ExecutionRouter should skip RecipeStepExecutor and go directly to AgentExplorer."""
	from datetime import datetime, timedelta, timezone
	from merchant_automation.operations.router import ExecutionRouter
	from merchant_automation.operations.storage import TraceSummary

	recent_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

	mock_store = MagicMock()
	mock_store.list_traces.return_value = [
		TraceSummary(
			trace_id='t1',
			operation_id='update_store_phone',
			platform='meituan',
			store_id='A店',
			recipe_id='meituan.update_store_phone.v1',
			mode=ExecutionMode.PREPARE,
			outcome_status=TraceOutcomeStatus.FAILED,
			created_at=recent_time,
		),
	]

	mock_explorer = MagicMock()
	mock_explorer_class.return_value = mock_explorer
	mock_explorer.explore = AsyncMock(return_value=_make_success_trace())

	router = ExecutionRouter(
		mock_browser_session,
		mock_llm,
		store=mock_store,
		recipe_definitions={'meituan.update_store_phone.v1': sample_recipe_def},
	)
	trace = await router.execute(sample_bound_task)

	# StepExecutor should NOT have been called
	mock_step_class.return_value.execute.assert_not_called()
	# Explorer should have been called
	mock_explorer.explore.assert_called_once()
	assert trace.outcome is not None
	assert trace.outcome.status == TraceOutcomeStatus.SUCCESS


# ---------- Test 8: synthesizes candidate after successful agent ----------

@pytest.mark.asyncio
@patch('merchant_automation.operations.router.AgentExplorer')
@patch('merchant_automation.operations.router.RecipeStepExecutor')
async def test_router_synthesizes_candidate_after_successful_agent(
	mock_step_class,
	mock_explorer_class,
	mock_browser_session,
	mock_llm,
	unseeded_bound_task,
):
	"""After successful agent exploration, router should synthesize and save a candidate RecipeDefinition."""
	from merchant_automation.operations.router import ExecutionRouter
	from merchant_automation.operations.recipe_store import RecipeStore

	# Mock explorer to return success
	mock_explorer = MagicMock()
	mock_explorer_class.return_value = mock_explorer
	mock_explorer.explore = AsyncMock(return_value=_make_success_trace())
	mock_explorer.last_history = MagicMock()
	mock_explorer.last_history.model_actions.return_value = [
		{'navigate': {'url': 'https://example.com'}, 'interacted_element': None},
	]

	# Mock recipe store
	mock_recipe_store = MagicMock(spec=RecipeStore)
	mock_recipe_store.get_definition.return_value = None
	mock_recipe_store.get_recipe.return_value = None

	router = ExecutionRouter(
		mock_browser_session,
		mock_llm,
		recipe_store=mock_recipe_store,
	)
	trace = await router.execute(unseeded_bound_task)

	# Should have called save_definition
	mock_recipe_store.save_definition.assert_called_once()
	saved_def = mock_recipe_store.save_definition.call_args[0][0]
	assert saved_def.recipe_id == 'custom.update_store_phone.v1'
	assert len(saved_def.steps) > 0

	# Should have upserted candidate metadata
	mock_recipe_store.upsert_recipe.assert_called_once()


# ---------- Test 9: does not overwrite promoted recipe ----------

@pytest.mark.asyncio
@patch('merchant_automation.operations.router.AgentExplorer')
@patch('merchant_automation.operations.router.RecipeStepExecutor')
async def test_router_does_not_overwrite_promoted_recipe(
	mock_step_class,
	mock_explorer_class,
	mock_browser_session,
	mock_llm,
	unseeded_bound_task,
):
	"""Router should NOT synthesize a new definition when recipe is already promoted (prepare_ready+)."""
	from merchant_automation.operations.router import ExecutionRouter
	from merchant_automation.operations.recipe_store import RecipeStore

	# Mock explorer to return success
	mock_explorer = MagicMock()
	mock_explorer_class.return_value = mock_explorer
	mock_explorer.explore = AsyncMock(return_value=_make_success_trace())

	# Mock recipe store - recipe already promoted
	mock_recipe_store = MagicMock(spec=RecipeStore)
	mock_recipe_store.get_definition.return_value = None
	promoted_recipe = RecipeMetadata(
		recipe_id='custom.update_store_phone.v1',
		operation_id='update_store_phone',
		platform='meituan',
		version=1,
		status=RecipeStatus.PREPARE_READY,
	)
	mock_recipe_store.get_recipe.return_value = promoted_recipe

	router = ExecutionRouter(
		mock_browser_session,
		mock_llm,
		recipe_store=mock_recipe_store,
	)
	trace = await router.execute(unseeded_bound_task)

	# Should NOT have called save_definition (recipe already promoted)
	mock_recipe_store.save_definition.assert_not_called()
	mock_recipe_store.upsert_recipe.assert_not_called()


# ---------- Test 10: counts only recent failures within time window ----------

def test_counts_only_recent_failures_within_time_window(
	mock_browser_session,
	mock_llm,
	sample_bound_task,
):
	"""Should only count failures within the configured time window, ignoring old failures."""
	from datetime import datetime, timedelta, timezone
	from merchant_automation.operations.router import ExecutionRouter, RECENT_FAILURE_WINDOW_HOURS
	from merchant_automation.operations.storage import TraceSummary

	now = datetime.now(timezone.utc)
	recent_time = (now - timedelta(hours=1)).isoformat()
	old_time = (now - timedelta(hours=RECENT_FAILURE_WINDOW_HOURS + 1)).isoformat()

	mock_store = MagicMock()
	mock_store.list_traces.return_value = [
		TraceSummary(
			trace_id='t-old',
			operation_id='update_store_phone',
			platform='meituan',
			store_id='A店',
			recipe_id='meituan.update_store_phone.v1',
			mode=ExecutionMode.PREPARE,
			outcome_status=TraceOutcomeStatus.FAILED,
			created_at=old_time,
		),
		TraceSummary(
			trace_id='t-recent',
			operation_id='update_store_phone',
			platform='meituan',
			store_id='A店',
			recipe_id='meituan.update_store_phone.v1',
			mode=ExecutionMode.PREPARE,
			outcome_status=TraceOutcomeStatus.FAILED,
			created_at=recent_time,
		),
	]

	router = ExecutionRouter(
		mock_browser_session,
		mock_llm,
		store=mock_store,
	)

	count = router._count_recent_failures('meituan.update_store_phone.v1')

	# Should only count the recent failure, not the old one
	assert count == 1


# ---------- Test 11: ignores old failures ----------

def test_ignores_old_failures(
	mock_browser_session,
	mock_llm,
	sample_bound_task,
	sample_recipe_def,
):
	"""Old failures should not block step executor execution."""
	from datetime import datetime, timedelta, timezone
	from merchant_automation.operations.router import ExecutionRouter, RECENT_FAILURE_WINDOW_HOURS
	from merchant_automation.operations.storage import TraceSummary

	old_time = (datetime.now(timezone.utc) - timedelta(hours=RECENT_FAILURE_WINDOW_HOURS + 1)).isoformat()

	mock_store = MagicMock()
	mock_store.list_traces.return_value = [
		TraceSummary(
			trace_id='t-old-1',
			operation_id='update_store_phone',
			platform='meituan',
			store_id='A店',
			recipe_id='meituan.update_store_phone.v1',
			mode=ExecutionMode.PREPARE,
			outcome_status=TraceOutcomeStatus.FAILED,
			created_at=old_time,
		),
		TraceSummary(
			trace_id='t-old-2',
			operation_id='update_store_phone',
			platform='meituan',
			store_id='A店',
			recipe_id='meituan.update_store_phone.v1',
			mode=ExecutionMode.PREPARE,
			outcome_status=TraceOutcomeStatus.FAILED,
			created_at=old_time,
		),
	]

	router = ExecutionRouter(
		mock_browser_session,
		mock_llm,
		store=mock_store,
	)

	count = router._count_recent_failures('meituan.update_store_phone.v1')

	# Old failures should be ignored
	assert count == 0


# ---------- Test 12: validates synthesized recipe before saving ----------

@pytest.mark.asyncio
@patch('merchant_automation.operations.router.AgentExplorer')
@patch('merchant_automation.operations.router.RecipeStepExecutor')
async def test_router_validates_synthesized_recipe_before_saving(
	mock_step_class,
	mock_explorer_class,
	mock_browser_session,
	mock_llm,
	unseeded_bound_task,
):
	"""Router should validate synthesized recipe by dry-run before saving to store."""
	from merchant_automation.operations.router import ExecutionRouter
	from merchant_automation.operations.recipe_store import RecipeStore

	# Mock explorer to return success with valid history
	mock_explorer = MagicMock()
	mock_explorer_class.return_value = mock_explorer
	mock_explorer.explore = AsyncMock(return_value=_make_success_trace())
	mock_explorer.last_history = MagicMock()
	mock_explorer.last_history.model_actions.return_value = [
		{'navigate': {'url': 'https://example.com'}, 'interacted_element': None},
	]

	# Mock step executor for validation (dry_run succeeds)
	mock_executor = MagicMock()
	mock_step_class.return_value = mock_executor
	mock_executor.execute_sync.return_value = _make_success_trace()

	# Mock recipe store
	mock_recipe_store = MagicMock(spec=RecipeStore)
	mock_recipe_store.get_definition.return_value = None
	mock_recipe_store.get_recipe.return_value = None

	router = ExecutionRouter(
		mock_browser_session,
		mock_llm,
		recipe_store=mock_recipe_store,
		_validate_synthesized=True,
	)
	trace = await router.execute(unseeded_bound_task)

	# Should have validated with step executor
	mock_executor.execute_sync.assert_called_once()
	# Should have saved definition after successful validation
	mock_recipe_store.save_definition.assert_called_once()


# ---------- Test 13: skips saving when validation fails ----------

@pytest.mark.asyncio
@patch('merchant_automation.operations.router.AgentExplorer')
@patch('merchant_automation.operations.router.RecipeStepExecutor')
async def test_router_skips_saving_when_validation_fails(
	mock_step_class,
	mock_explorer_class,
	mock_browser_session,
	mock_llm,
	unseeded_bound_task,
):
	"""Router should NOT save definition when dry-run validation fails."""
	from merchant_automation.operations.executor import StepExecutionError
	from merchant_automation.operations.router import ExecutionRouter
	from merchant_automation.operations.recipe_store import RecipeStore

	# Mock explorer to return success with history
	mock_explorer = MagicMock()
	mock_explorer_class.return_value = mock_explorer
	mock_explorer.explore = AsyncMock(return_value=_make_success_trace())
	mock_explorer.last_history = MagicMock()
	mock_explorer.last_history.model_actions.return_value = [
		{'navigate': {'url': 'https://example.com'}, 'interacted_element': None},
	]

	# Mock step executor for validation (dry_run fails)
	mock_executor = MagicMock()
	mock_step_class.return_value = mock_executor
	failed_step = RecipeStep(action=RecipeStepAction.NAVIGATE, url='https://example.com')
	mock_executor.execute_sync.side_effect = StepExecutionError('validation failed', 0, failed_step)

	# Mock recipe store
	mock_recipe_store = MagicMock(spec=RecipeStore)
	mock_recipe_store.get_definition.return_value = None
	mock_recipe_store.get_recipe.return_value = None

	router = ExecutionRouter(
		mock_browser_session,
		mock_llm,
		recipe_store=mock_recipe_store,
		_validate_synthesized=True,
	)
	trace = await router.execute(unseeded_bound_task)

	# Should have attempted validation
	mock_executor.execute_sync.assert_called_once()
	# Should NOT have saved definition (validation failed)
	mock_recipe_store.save_definition.assert_not_called()
