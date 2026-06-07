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


# ---------- Test 3: routes to agent explorer when no steps ----------

@pytest.mark.asyncio
@patch('merchant_automation.operations.router.RecipeStepExecutor')
@patch('merchant_automation.operations.router.AgentExplorer')
async def test_routes_to_agent_explorer_when_no_steps(
	mock_explorer_class,
	mock_step_class,
	mock_browser_session,
	mock_llm,
	sample_bound_task,
):
	"""When no RecipeDefinition is found, ExecutionRouter should fall back to AgentExplorer."""
	from merchant_automation.operations.router import ExecutionRouter

	mock_explorer = MagicMock()
	mock_explorer_class.return_value = mock_explorer
	mock_explorer.explore = AsyncMock(return_value=_make_success_trace())

	router = ExecutionRouter(mock_browser_session, mock_llm)
	trace = await router.execute(sample_bound_task)

	mock_explorer.explore.assert_called_once()


# ---------- Test 3.1: forwards max_steps to explorer ----------

@pytest.mark.asyncio
@patch('merchant_automation.operations.router.AgentExplorer')
async def test_forwards_max_steps_to_agent_explorer(
	mock_explorer_class,
	mock_browser_session,
	mock_llm,
	sample_bound_task,
):
	mock_explorer = MagicMock()
	mock_explorer_class.return_value = mock_explorer
	mock_explorer.explore = AsyncMock(return_value=_make_success_trace())

	router = ExecutionRouter(
		browser_session=mock_browser_session,
		llm=mock_llm,
		recipe_definitions={},
	)

	trace = await router.execute(sample_bound_task, raw_input='test input', max_steps=12)

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
	sample_bound_task,
):
	"""When no RecipeDefinition exists and no LLM is configured, ExecutionRouter should fail."""
	from merchant_automation.operations.router import ExecutionRouter

	router = ExecutionRouter(mock_browser_session, llm=None)
	trace = await router.execute(sample_bound_task)

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
	from merchant_automation.operations.router import ExecutionRouter
	from merchant_automation.operations.storage import TraceSummary

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
			created_at='2026-01-01T00:00:00Z',
		),
		TraceSummary(
			trace_id='t2',
			operation_id='update_store_phone',
			platform='meituan',
			store_id='A店',
			recipe_id='meituan.update_store_phone.v1',
			mode=ExecutionMode.PREPARE,
			outcome_status=TraceOutcomeStatus.FAILED,
			created_at='2026-01-01T00:00:00Z',
		),
		TraceSummary(
			trace_id='t3',
			operation_id='update_store_phone',
			platform='meituan',
			store_id='A店',
			recipe_id='meituan.update_store_phone.v1',
			mode=ExecutionMode.PREPARE,
			outcome_status=TraceOutcomeStatus.SUCCESS,
			created_at='2026-01-01T00:00:00Z',
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
	from merchant_automation.operations.router import ExecutionRouter
	from merchant_automation.operations.storage import TraceSummary

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
			created_at='2026-01-01T00:00:00Z',
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
