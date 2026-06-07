from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field
from uuid_extensions import uuid7str

from merchant_automation.operations.schemas import ExecutionMode


class AccountStatus(str, Enum):
	ACTIVE = 'active'
	DISABLED = 'disabled'
	NEEDS_LOGIN = 'needs_login'


class LoginStatus(str, Enum):
	LOGGED_IN = 'logged_in'
	EXPIRED = 'expired'
	UNKNOWN = 'unknown'


class Account(BaseModel):
	model_config = ConfigDict(extra='forbid', validate_by_name=True)

	id: str = Field(default_factory=uuid7str)
	name: str
	platform: str
	username: str | None = None
	profile_dir: str
	status: AccountStatus = AccountStatus.NEEDS_LOGIN
	created_at: datetime = Field(default_factory=datetime.now)
	last_used_at: datetime | None = None


class PlatformAccount(BaseModel):
	model_config = ConfigDict(extra='forbid')

	account_id: str
	platform: str
	username: str
	profile_path: str | None = None
	login_status: LoginStatus = LoginStatus.UNKNOWN
	default_mode: ExecutionMode = ExecutionMode.PARSE_ONLY
	commit_allowed: bool = False
	feishu_group_id: str | None = None
	last_failure_reason: str | None = None


class Store(BaseModel):
	model_config = ConfigDict(extra='forbid')

	store_id: str
	platform: str
	account_id: str
	store_name: str | None = None

