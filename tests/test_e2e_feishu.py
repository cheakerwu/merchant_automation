"""End-to-end test for the Feishu → merchant_automation pipeline.

Tests the full flow without requiring a real Feishu server:
Feishu message → OperationPlanningService → ExecutionRouter → trace
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from merchant_automation.operations.preflight import CommitPolicy
from merchant_automation.operations.service import OperationPlanningService
from merchant_automation.operations.storage import OperationStore


def _create_store(tmp_path: Path) -> OperationStore:
	store = OperationStore(tmp_path / 'merchant.db')
	store.initialize()
	return store


def test_e2e_planning_pipeline_from_feishu_text(tmp_path: Path):
	"""Simulate a Feishu text message going through the planning pipeline."""
	store = _create_store(tmp_path)
	service = OperationPlanningService()

	# Simulate: user sends "把美团 A店 电话改成 13800138000"
	text = '把美团 A店 电话改成 13800138000'
	result = service.plan_text(text, policy=CommitPolicy())

	# Planning should succeed
	assert len(result.input_issues) == 0
	assert len(result.plan_issues) == 0
	assert len(result.bound_tasks) == 1

	bound = result.bound_tasks[0]
	assert bound.task.platform == 'meituan'
	assert bound.task.operation_id == 'update_store_phone'
	assert bound.task.params['phone'] == '13800138000'
	assert bound.task.store_id == 'A店'

	# Save to store
	run_id = store.save_planning_result(result)
	assert run_id

	# Verify stored
	runs = store.list_planning_runs()
	assert len(runs) == 1
	assert runs[0].task_count == 1


def test_e2e_planning_pipeline_from_table(tmp_path: Path):
	"""Simulate a Feishu table upload going through the planning pipeline."""
	store = _create_store(tmp_path)
	service = OperationPlanningService()

	rows = [
		{'platform': '美团', 'store_id': 'A店', 'operation': 'update_store_phone', 'phone': '13800138000'},
		{'platform': '美团', 'store_id': 'B店', 'operation': 'change_business_hours', '营业时间': '09:00-22:00'},
	]
	result = service.plan_table_rows(rows, policy=CommitPolicy())

	assert len(result.bound_tasks) == 2
	assert result.bound_tasks[0].task.operation_id == 'update_store_phone'
	assert result.bound_tasks[1].task.operation_id == 'change_business_hours'

	run_id = store.save_planning_result(result)
	assert run_id


def test_e2e_planning_handles_invalid_input():
	"""Invalid input should produce issues, not crash."""
	service = OperationPlanningService()
	result = service.plan_text('这不是一个有效的操作指令', policy=CommitPolicy())

	# Should have input issues
	assert len(result.input_issues) > 0 or len(result.bound_tasks) == 0


def test_e2e_trace_round_trip(tmp_path: Path):
	"""Test that traces can be saved and retrieved after execution."""
	store = _create_store(tmp_path)
	service = OperationPlanningService()

	# Plan
	result = service.plan_text('把美团 A店 电话改成 13800138000', policy=CommitPolicy())
	run_id = store.save_planning_result(result)

	# Simulate a trace
	from merchant_automation.operations.traces import ExecutionTrace, TraceOutcome, TraceOutcomeStatus

	trace = ExecutionTrace(
		platform='meituan',
		store_id='A店',
		operation_id='update_store_phone',
		recipe_id='meituan.update_store_phone.v1',
		mode=result.bound_tasks[0].task.mode,
		params={'phone': '13800138000'},
		outcome=TraceOutcome(status=TraceOutcomeStatus.SUCCESS, message='执行完成'),
	)
	trace_id = store.save_trace(trace, run_id=run_id)

	# Verify
	traces = store.list_traces()
	assert len(traces) == 1
	assert traces[0].operation_id == 'update_store_phone'
	assert traces[0].outcome_status == TraceOutcomeStatus.SUCCESS
