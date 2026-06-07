"""Recipe step definitions — independent from RecipeMetadata."""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class RecipeStepAction(str, Enum):
	"""浏览器操作类型。"""
	NAVIGATE = 'navigate'
	CLICK = 'click'
	FILL = 'fill'
	UPLOAD = 'upload'
	SCREENSHOT = 'screenshot'
	WAIT = 'wait'
	STOP_BEFORE_SUBMIT = 'stop_before_submit'
	VERIFY = 'verify'


class RecipeStep(BaseModel):
	"""Recipe 的单个执行步骤。语义描述，不是 CSS 选择器。"""
	model_config = ConfigDict(extra='forbid')

	action: RecipeStepAction
	target: str | None = None        # 语义描述: "电话输入框" / "保存按钮"
	value: str | None = None         # 填入的值，支持模板: "{phone}"
	url: str | None = None           # navigate 时的目标 URL
	timeout: float | None = None     # wait 时的超时秒数
	description: str | None = None   # 人类可读描述


class RecipeDefinition(BaseModel):
	"""Recipe 的完整执行定义。独立于 RecipeMetadata。"""
	model_config = ConfigDict(extra='forbid')

	recipe_id: str
	steps: list[RecipeStep] = Field(default_factory=list)
	entry_url: str | None = None
	verify_after_commit: list[str] = Field(default_factory=list)

