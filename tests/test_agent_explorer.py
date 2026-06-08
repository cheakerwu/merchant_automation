from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merchant_automation.operations.binder import BoundOperationTask
from merchant_automation.operations.explorer import AgentExplorer
from merchant_automation.operations.preflight import PreflightResult
from merchant_automation.operations.schemas import (
	ExecutionMode,
	FailureType,
	OperationContract,
	OperationTask,
	RecipeMetadata,
	RecipeStatus,
)
from merchant_automation.operations.traces import (
	TraceOutcomeStatus,
	TraceRecorder,
	TraceStepKind,
)


@pytest.fixture
def mock_browser_session():
	session = AsyncMock()
	session.get_current_page_url.return_value = 'https://example.com/store'
	session.get_current_page_title.return_value = 'Test Store Page'
	return session


@pytest.fixture
def mock_llm():
	return MagicMock()


@pytest.fixture
def sample_operation():
	return OperationContract(
		operation_id='update_store_phone',
		title='修改门店联系电话',
		required_params=['store_id', 'phone'],
		success_criteria=['保存后重新进入页面，联系电话等于目标值'],
		forbidden_actions=['不能修改其他门店信息'],
		allow_commit=True,
	)


@pytest.fixture
def sample_bound_task():
	return BoundOperationTask(
		task=OperationTask(
			platform='meituan',
			store_id='A店',
			operation_id='update_store_phone',
			params={'phone': '13800138000'},
			mode=ExecutionMode.DRY_RUN,
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
			requested_mode=ExecutionMode.DRY_RUN,
			effective_mode=ExecutionMode.DRY_RUN,
		),
	)


@pytest.fixture
def prepare_bound_task(sample_bound_task):
	return sample_bound_task.model_copy(
		update={
			'task': sample_bound_task.task.model_copy(update={'mode': ExecutionMode.PREPARE}),
			'preflight': sample_bound_task.preflight.model_copy(
				update={
					'requested_mode': ExecutionMode.PREPARE,
					'effective_mode': ExecutionMode.PREPARE,
				}
			),
		}
	)


def test_explorer_builds_task_prompt(sample_operation):
	explorer = AgentExplorer(MagicMock(), MagicMock())
	prompt = explorer._build_task_prompt(sample_operation, {'phone': '13800138000'}, ExecutionMode.DRY_RUN)

	assert '修改门店联系电话' in prompt
	assert 'phone=13800138000' in prompt
	assert '保存后重新进入页面，联系电话等于目标值' in prompt
	assert '不能修改其他门店信息' in prompt


def test_explorer_builds_dry_run_prompt(sample_operation):
	explorer = AgentExplorer(MagicMock(), MagicMock())
	prompt = explorer._build_task_prompt(sample_operation, {}, ExecutionMode.DRY_RUN)

	assert 'dry_run' in prompt
	assert '不要修改真实数据' in prompt


def test_explorer_builds_prepare_prompt(sample_operation):
	explorer = AgentExplorer(MagicMock(), MagicMock())
	prompt = explorer._build_task_prompt(sample_operation, {}, ExecutionMode.PREPARE)

	assert 'prepare' in prompt
	assert '停在最终提交前' in prompt


def test_explorer_builds_commit_prompt(sample_operation):
	explorer = AgentExplorer(MagicMock(), MagicMock())
	prompt = explorer._build_task_prompt(sample_operation, {}, ExecutionMode.COMMIT)

	assert 'commit' in prompt
	assert '真实提交' in prompt


@patch('merchant_automation.operations.explorer.Agent')
def test_explorer_records_agent_steps(mock_agent_class, mock_browser_session, mock_llm, sample_operation, sample_bound_task):
	mock_agent = MagicMock()
	mock_agent_class.return_value = mock_agent

	async def fake_run(max_steps, on_step_end):
		await on_step_end(mock_agent)
		await on_step_end(mock_agent)
		return '探索完成'

	mock_agent.run = AsyncMock(side_effect=fake_run)

	recorder = TraceRecorder.start(sample_bound_task)
	explorer = AgentExplorer(mock_browser_session, mock_llm)

	trace = asyncio.run(
		explorer.explore(sample_operation, {'phone': '13800138000'}, recorder)
	)

	assert trace.outcome.status == TraceOutcomeStatus.SUCCESS
	assert len(trace.steps) == 2
	assert all(step.kind == TraceStepKind.MODEL_JUDGEMENT for step in trace.steps)
	assert 'Test Store Page' in trace.steps[0].message
	assert trace.steps[0].url == 'https://example.com/store'


@patch('merchant_automation.operations.explorer.Agent')
def test_explorer_records_prepare_evidence_screenshot(mock_agent_class, mock_browser_session, mock_llm, sample_operation, prepare_bound_task):
	mock_agent = MagicMock()
	mock_agent_class.return_value = mock_agent
	mock_agent.run = AsyncMock(return_value='探索完成')
	mock_browser_session.take_screenshot.return_value = b'fake-png'

	recorder = TraceRecorder.start(prepare_bound_task)
	explorer = AgentExplorer(mock_browser_session, mock_llm)

	trace = asyncio.run(
		explorer.explore(sample_operation, {'phone': '13800138000'}, recorder, mode=ExecutionMode.PREPARE)
	)

	screenshot_steps = [step for step in trace.steps if step.kind == TraceStepKind.SCREENSHOT]
	assert len(screenshot_steps) == 1
	assert screenshot_steps[0].message == 'prepare 证据截图'
	assert screenshot_steps[0].screenshot_path is not None
	assert screenshot_steps[0].screenshot_path.endswith('.png')


@patch('merchant_automation.operations.explorer.Agent')
def test_explorer_returns_success_trace(mock_agent_class, mock_browser_session, mock_llm, sample_operation, sample_bound_task):
	mock_agent = MagicMock()
	mock_agent_class.return_value = mock_agent
	mock_agent.run = AsyncMock(return_value='探索完成')

	recorder = TraceRecorder.start(sample_bound_task)
	explorer = AgentExplorer(mock_browser_session, mock_llm)

	trace = asyncio.run(
		explorer.explore(sample_operation, {'phone': '13800138000'}, recorder)
	)

	assert trace.outcome.status == TraceOutcomeStatus.SUCCESS
	assert '探索完成' in trace.outcome.message


@patch('merchant_automation.operations.explorer.Agent')
def test_explorer_returns_failure_trace_on_exception(mock_agent_class, mock_browser_session, mock_llm, sample_operation, sample_bound_task):
	mock_agent = MagicMock()
	mock_agent_class.return_value = mock_agent
	mock_agent.run = AsyncMock(side_effect=RuntimeError('browser crashed'))

	recorder = TraceRecorder.start(sample_bound_task)
	explorer = AgentExplorer(mock_browser_session, mock_llm)

	trace = asyncio.run(
		explorer.explore(sample_operation, {'phone': '13800138000'}, recorder)
	)

	assert trace.outcome.status == TraceOutcomeStatus.FAILED
	assert trace.outcome.failure_type == FailureType.SUBMIT_FAILED
	assert 'browser crashed' in trace.outcome.message
