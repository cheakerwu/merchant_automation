from __future__ import annotations

import tempfile
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from merchant_automation.operations.binder import BoundOperationTask
from merchant_automation.operations.schemas import ExecutionMode, FailureType


class TraceStepKind(str, Enum):
	PAGE = 'page'
	ACTION = 'action'
	NETWORK = 'network'
	SCREENSHOT = 'screenshot'
	MODEL_JUDGEMENT = 'model_judgement'
	VALIDATION = 'validation'


class TraceOutcomeStatus(str, Enum):
	SUCCESS = 'success'
	FAILED = 'failed'


class TraceStep(BaseModel):
	model_config = ConfigDict(extra='forbid')

	step_number: int
	kind: TraceStepKind
	message: str
	url: str | None = None
	page_title: str | None = None
	target: str | None = None
	input_value: str | None = None
	screenshot_path: str | None = None
	network_hint: str | None = None
	details: dict[str, object] = Field(default_factory=dict)


class TraceOutcome(BaseModel):
	model_config = ConfigDict(extra='forbid')

	status: TraceOutcomeStatus
	message: str
	failure_type: FailureType | None = None
	failed_step_number: int | None = None


class ExecutionTrace(BaseModel):
	model_config = ConfigDict(extra='forbid')

	platform: str
	store_id: str
	operation_id: str
	recipe_id: str
	mode: ExecutionMode
	params: dict[str, object] = Field(default_factory=dict)
	raw_input: str | None = None
	steps: list[TraceStep] = Field(default_factory=list)
	outcome: TraceOutcome | None = None


class TraceRecorder:
	def __init__(self, trace: ExecutionTrace) -> None:
		self.trace = trace

	@classmethod
	def start(cls, bound_task: BoundOperationTask, *, raw_input: str | None = None) -> TraceRecorder:
		return cls(
			ExecutionTrace(
				platform=bound_task.task.platform,
				store_id=bound_task.task.store_id,
				operation_id=bound_task.task.operation_id,
				recipe_id=bound_task.recipe.recipe_id,
				mode=bound_task.task.mode,
				params=bound_task.task.params,
				raw_input=raw_input,
			)
		)

	def record_step(
		self,
		kind: TraceStepKind,
		message: str,
		**kwargs: object,
	) -> TraceStep:
		step = TraceStep(step_number=len(self.trace.steps) + 1, kind=kind, message=message, **kwargs)
		self.trace.steps.append(step)
		return step

	def complete(self, message: str) -> ExecutionTrace:
		self.trace.outcome = TraceOutcome(status=TraceOutcomeStatus.SUCCESS, message=message)
		return self.trace

	def fail(self, *, failure_type: FailureType, message: str, failed_step_number: int | None = None) -> ExecutionTrace:
		self.trace.outcome = TraceOutcome(
			status=TraceOutcomeStatus.FAILED,
			message=message,
			failure_type=failure_type,
			failed_step_number=failed_step_number,
		)
		return self.trace


def record_screenshot_bytes(
	recorder: TraceRecorder,
	message: str,
	screenshot_bytes: bytes,
) -> TraceStep:
	tmp = tempfile.NamedTemporaryFile(
		suffix='.png', delete=False, prefix='recipe_'
	)
	tmp.write(screenshot_bytes)
	tmp.close()
	return recorder.record_step(
		TraceStepKind.SCREENSHOT,
		message,
		screenshot_path=tmp.name,
	)


def trace_screenshot_paths(trace: ExecutionTrace) -> list[str]:
	return [
		step.screenshot_path
		for step in trace.steps
		if step.kind == TraceStepKind.SCREENSHOT and step.screenshot_path
	]
