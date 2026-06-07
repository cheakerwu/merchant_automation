from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from merchant_automation.operations.failure import FailureAnalysis
from merchant_automation.operations.schemas import ExecutionMode, FailureType
from merchant_automation.operations.service import OperationPlanningResult
from merchant_automation.operations.traces import ExecutionTrace, TraceOutcomeStatus


class PlanningRunSummary(BaseModel):
	model_config = ConfigDict(extra='forbid')

	run_id: str
	source: str
	task_count: int
	issue_count: int
	created_at: str


class TraceSummary(BaseModel):
	model_config = ConfigDict(extra='forbid')

	trace_id: str
	run_id: str | None = None
	operation_id: str
	platform: str
	store_id: str
	recipe_id: str
	mode: ExecutionMode
	outcome_status: TraceOutcomeStatus | None = None
	failure_type: FailureType | None = None
	created_at: str


class FailureAnalysisSummary(BaseModel):
	model_config = ConfigDict(extra='forbid')

	analysis_id: str
	trace_id: str
	failure_type: FailureType
	retryable: bool
	suspected_recipe_stale: bool
	created_at: str


class OperationStore:
	def __init__(self, db_path: str | Path) -> None:
		self._db_path = Path(db_path)

	def initialize(self) -> None:
		self._db_path.parent.mkdir(parents=True, exist_ok=True)
		with self._connection() as connection:
			connection.execute(
				'''
				CREATE TABLE IF NOT EXISTS planning_runs (
					run_id TEXT PRIMARY KEY,
					source TEXT NOT NULL,
					task_count INTEGER NOT NULL,
					issue_count INTEGER NOT NULL,
					payload_json TEXT NOT NULL,
					created_at TEXT NOT NULL
				)
				'''
			)
			connection.execute(
				'''
				CREATE TABLE IF NOT EXISTS traces (
					trace_id TEXT PRIMARY KEY,
					run_id TEXT,
					operation_id TEXT NOT NULL,
					platform TEXT NOT NULL,
					store_id TEXT NOT NULL,
					recipe_id TEXT NOT NULL,
					mode TEXT NOT NULL,
					outcome_status TEXT,
					failure_type TEXT,
					payload_json TEXT NOT NULL,
					created_at TEXT NOT NULL
				)
				'''
			)
			connection.execute(
				'''
				CREATE TABLE IF NOT EXISTS failure_analyses (
					analysis_id TEXT PRIMARY KEY,
					trace_id TEXT NOT NULL,
					failure_type TEXT NOT NULL,
					retryable INTEGER NOT NULL,
					suspected_recipe_stale INTEGER NOT NULL,
					payload_json TEXT NOT NULL,
					created_at TEXT NOT NULL
				)
				'''
			)

	def table_names(self) -> set[str]:
		with self._connection() as connection:
			rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
		return {row['name'] for row in rows}

	def save_planning_result(self, result: OperationPlanningResult) -> str:
		run_id = uuid4().hex
		issue_count = len(result.input_issues) + len(result.plan_issues) + len(result.binding_issues)
		with self._connection() as connection:
			connection.execute(
				'''
				INSERT INTO planning_runs (run_id, source, task_count, issue_count, payload_json, created_at)
				VALUES (?, ?, ?, ?, ?, ?)
				''',
				(
					run_id,
					result.plan.source,
					len(result.bound_tasks),
					issue_count,
					_dump_model(result),
					_now(),
				),
			)
		return run_id

	def get_planning_result(self, run_id: str) -> OperationPlanningResult | None:
		with self._connection() as connection:
			row = connection.execute(
				'SELECT payload_json FROM planning_runs WHERE run_id = ?',
				(run_id,),
			).fetchone()
		if row is None:
			return None
		return OperationPlanningResult.model_validate_json(row['payload_json'])

	def list_planning_runs(self) -> list[PlanningRunSummary]:
		with self._connection() as connection:
			rows = connection.execute(
				'''
				SELECT run_id, source, task_count, issue_count, created_at
				FROM planning_runs
				ORDER BY created_at DESC, run_id DESC
				'''
			).fetchall()
		return [PlanningRunSummary(**dict(row)) for row in rows]

	def save_trace(self, trace: ExecutionTrace, *, run_id: str | None = None) -> str:
		trace_id = uuid4().hex
		outcome_status = trace.outcome.status.value if trace.outcome else None
		failure_type = trace.outcome.failure_type.value if trace.outcome and trace.outcome.failure_type else None
		with self._connection() as connection:
			connection.execute(
				'''
				INSERT INTO traces (
					trace_id, run_id, operation_id, platform, store_id, recipe_id, mode,
					outcome_status, failure_type, payload_json, created_at
				)
				VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
				''',
				(
					trace_id,
					run_id,
					trace.operation_id,
					trace.platform,
					trace.store_id,
					trace.recipe_id,
					trace.mode.value,
					outcome_status,
					failure_type,
					_dump_model(trace),
					_now(),
				),
			)
		return trace_id

	def get_trace(self, trace_id: str) -> ExecutionTrace | None:
		with self._connection() as connection:
			row = connection.execute(
				'SELECT payload_json FROM traces WHERE trace_id = ?',
				(trace_id,),
			).fetchone()
		if row is None:
			return None
		return ExecutionTrace.model_validate_json(row['payload_json'])

	def list_traces(self, *, operation_id: str | None = None) -> list[TraceSummary]:
		sql = '''
			SELECT trace_id, run_id, operation_id, platform, store_id, recipe_id, mode,
				outcome_status, failure_type, created_at
			FROM traces
		'''
		params: tuple[str, ...] = ()
		if operation_id is not None:
			sql += ' WHERE operation_id = ?'
			params = (operation_id,)
		sql += ' ORDER BY created_at DESC, trace_id DESC'

		with self._connection() as connection:
			rows = connection.execute(sql, params).fetchall()
		return [TraceSummary(**dict(row)) for row in rows]

	def save_failure_analysis(self, analysis: FailureAnalysis, *, trace_id: str) -> str:
		analysis_id = uuid4().hex
		with self._connection() as connection:
			connection.execute(
				'''
				INSERT INTO failure_analyses (
					analysis_id, trace_id, failure_type, retryable,
					suspected_recipe_stale, payload_json, created_at
				)
				VALUES (?, ?, ?, ?, ?, ?, ?)
				''',
				(
					analysis_id,
					trace_id,
					analysis.failure_type.value,
					int(analysis.retryable),
					int(analysis.suspected_recipe_stale),
					_dump_model(analysis),
					_now(),
				),
			)
		return analysis_id

	def get_failure_analysis(self, analysis_id: str) -> FailureAnalysis | None:
		with self._connection() as connection:
			row = connection.execute(
				'SELECT payload_json FROM failure_analyses WHERE analysis_id = ?',
				(analysis_id,),
			).fetchone()
		if row is None:
			return None
		return FailureAnalysis.model_validate_json(row['payload_json'])

	def list_failure_analyses(self) -> list[FailureAnalysisSummary]:
		with self._connection() as connection:
			rows = connection.execute(
				'''
				SELECT analysis_id, trace_id, failure_type, retryable, suspected_recipe_stale, created_at
				FROM failure_analyses
				ORDER BY created_at DESC, analysis_id DESC
				'''
			).fetchall()
		return [
			FailureAnalysisSummary(
				analysis_id=row['analysis_id'],
				trace_id=row['trace_id'],
				failure_type=row['failure_type'],
				retryable=bool(row['retryable']),
				suspected_recipe_stale=bool(row['suspected_recipe_stale']),
				created_at=row['created_at'],
			)
			for row in rows
		]

	@contextmanager
	def _connection(self) -> Iterator[sqlite3.Connection]:
		connection = sqlite3.connect(self._db_path)
		connection.row_factory = sqlite3.Row
		try:
			yield connection
			connection.commit()
		finally:
			connection.close()


def _dump_model(model: BaseModel) -> str:
	return json.dumps(model.model_dump(mode='json'), ensure_ascii=False, sort_keys=True)


def _now() -> str:
	return datetime.now(timezone.utc).isoformat()

