from __future__ import annotations

from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

SuccessRate = Annotated[float, Field(ge=0, le=1)]


class ExecutionMode(str, Enum):
	PARSE_ONLY = 'parse_only'
	DRY_RUN = 'dry_run'
	PREPARE = 'prepare'
	COMMIT = 'commit'


class RecipeStatus(str, Enum):
	CANDIDATE = 'candidate'
	PREPARE_TESTING = 'prepare_testing'
	PREPARE_READY = 'prepare_ready'
	COMMIT_TESTING = 'commit_testing'
	COMMIT_READY = 'commit_ready'
	DISABLED = 'disabled'


class FailureType(str, Enum):
	PREFLIGHT_FAILED = 'preflight_failed'
	SUBMIT_FAILED = 'submit_failed'
	VALIDATION_FAILED = 'validation_failed'
	PARTIAL_SUCCESS = 'partial_success'
	UNKNOWN_COMMIT_STATE = 'unknown_commit_state'


class OperationContract(BaseModel):
	model_config = ConfigDict(extra='forbid')

	operation_id: str
	title: str
	required_params: list[str] = Field(default_factory=list)
	success_criteria: list[str] = Field(default_factory=list)
	forbidden_actions: list[str] = Field(default_factory=list)
	allow_commit: bool = False


class RecipeMetadata(BaseModel):
	model_config = ConfigDict(extra='forbid')

	recipe_id: str
	operation_id: str
	platform: str
	version: int = Field(ge=1)
	status: RecipeStatus
	allowed_modes: set[ExecutionMode] = Field(default_factory=set)
	success_rates: dict[ExecutionMode, SuccessRate] = Field(default_factory=dict)


class OperationTask(BaseModel):
	model_config = ConfigDict(extra='forbid')

	platform: str
	store_id: str
	account_id: str | None = None
	operation_id: str
	params: dict[str, object] = Field(default_factory=dict)
	mode: ExecutionMode = ExecutionMode.PARSE_ONLY
	recipe_id: str | None = None


class JobPlan(BaseModel):
	model_config = ConfigDict(extra='forbid')

	source: str
	raw_input: str | None = None
	tasks: list[OperationTask] = Field(default_factory=list)

