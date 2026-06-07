"""Tests for RecipeStep and RecipeDefinition models."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from merchant_automation.operations.recipe_definition import (
	RecipeDefinition,
	RecipeStep,
	RecipeStepAction,
)


class TestRecipeStepAction:
	"""Verify all enum values exist."""

	def test_recipe_step_action_values(self) -> None:
		expected = {
			'navigate',
			'click',
			'fill',
			'upload',
			'screenshot',
			'wait',
			'stop_before_submit',
			'verify',
		}
		actual = {action.value for action in RecipeStepAction}
		assert actual == expected
		assert len(RecipeStepAction) == 8


class TestRecipeStep:
	"""RecipeStep field tests."""

	def test_recipe_step_minimal(self) -> None:
		step = RecipeStep(action=RecipeStepAction.CLICK)
		assert step.action == RecipeStepAction.CLICK
		assert step.target is None
		assert step.value is None
		assert step.url is None
		assert step.timeout is None
		assert step.description is None

	def test_recipe_step_full(self) -> None:
		step = RecipeStep(
			action=RecipeStepAction.FILL,
			target='电话输入框',
			value='{phone}',
			url='https://example.com',
			timeout=10.0,
			description='填写电话号码',
		)
		assert step.action == RecipeStepAction.FILL
		assert step.target == '电话输入框'
		assert step.value == '{phone}'
		assert step.url == 'https://example.com'
		assert step.timeout == 10.0
		assert step.description == '填写电话号码'

	def test_recipe_step_value_supports_template(self) -> None:
		step = RecipeStep(action=RecipeStepAction.FILL, value='{phone}')
		assert step.value == '{phone}'


class TestRecipeDefinition:
	"""RecipeDefinition field tests."""

	def test_recipe_definition_empty_steps(self) -> None:
		defn = RecipeDefinition(recipe_id='test-001')
		assert defn.recipe_id == 'test-001'
		assert defn.steps == []
		assert defn.entry_url is None
		assert defn.verify_after_commit == []

	def test_recipe_definition_with_steps(self) -> None:
		steps = [
			RecipeStep(action=RecipeStepAction.NAVIGATE, url='https://example.com'),
			RecipeStep(action=RecipeStepAction.FILL, target='用户名', value='admin'),
			RecipeStep(action=RecipeStepAction.CLICK, target='登录按钮'),
			RecipeStep(action=RecipeStepAction.STOP_BEFORE_SUBMIT),
		]
		defn = RecipeDefinition(recipe_id='test-002', steps=steps, entry_url='https://example.com')
		assert len(defn.steps) == 4
		assert defn.steps[0].action == RecipeStepAction.NAVIGATE
		assert defn.steps[1].target == '用户名'
		assert defn.steps[2].target == '登录按钮'
		assert defn.steps[3].action == RecipeStepAction.STOP_BEFORE_SUBMIT

	def test_recipe_definition_rejects_unknown_fields(self) -> None:
		with pytest.raises(ValidationError):
			RecipeDefinition(recipe_id='test-003', unknown_field='bad')
