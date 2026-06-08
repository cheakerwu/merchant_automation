"""Tests for recipe synthesizer — converts browser_use history to RecipeDefinition."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from merchant_automation.operations.recipe_definition import (
	RecipeStepAction,
)
from merchant_automation.operations.synthesizer import synthesize_recipe_definition


# ---------------------------------------------------------------------------
# Lightweight stubs mimicking browser_use types (no import needed)
# ---------------------------------------------------------------------------

@dataclass
class StubInteractedElement:
	ax_name: str | None = None
	attributes: dict[str, str] = field(default_factory=dict)
	node_name: str | None = None
	x_path: str | None = None


@dataclass
class StubAction:
	action_name: str
	params: dict[str, Any]
	interacted_element: StubInteractedElement | None = None


class StubHistory:
	"""Mimics AgentHistoryList.model_actions()."""

	def __init__(self, actions: list[StubAction]) -> None:
		self._actions = actions

	def model_actions(self) -> list[dict[str, Any]]:
		return [
			{
				a.action_name: a.params,
				'interacted_element': a.interacted_element,
			}
			for a in self._actions
		]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_navigate_maps_to_navigate_step() -> None:
	history = StubHistory([
		StubAction('navigate', {'url': 'https://example.com'}),
	])

	defn = synthesize_recipe_definition(
		history,
		recipe_id='r1',
		params={},
		entry_url='https://example.com',
	)

	assert len(defn.steps) == 2  # navigate + stop_before_submit
	assert defn.steps[0].action == RecipeStepAction.NAVIGATE
	assert defn.steps[0].url == 'https://example.com'
	assert defn.steps[0].value == 'https://example.com'


def test_click_uses_ax_name_as_target() -> None:
	history = StubHistory([
		StubAction(
			'click',
			{'index': 5},
			interacted_element=StubInteractedElement(ax_name='保存按钮'),
		),
	])

	defn = synthesize_recipe_definition(history, recipe_id='r1', params={})

	assert len(defn.steps) == 2  # click + stop
	assert defn.steps[0].action == RecipeStepAction.CLICK
	assert defn.steps[0].target == '保存按钮'


def test_input_parameterizes_matching_param_value() -> None:
	history = StubHistory([
		StubAction(
			'input',
			{'index': 3, 'text': '13800138000'},
			interacted_element=StubInteractedElement(ax_name='电话输入框'),
		),
	])

	defn = synthesize_recipe_definition(
		history,
		recipe_id='r1',
		params={'phone': '13800138000'},
	)

	assert len(defn.steps) == 2  # fill + stop
	assert defn.steps[0].action == RecipeStepAction.FILL
	assert defn.steps[0].target == '电话输入框'
	assert defn.steps[0].value == '{phone}'


def test_input_keeps_value_when_no_param_match() -> None:
	history = StubHistory([
		StubAction(
			'input',
			{'index': 3, 'text': 'some text'},
			interacted_element=StubInteractedElement(ax_name='输入框'),
		),
	])

	defn = synthesize_recipe_definition(history, recipe_id='r1', params={'phone': '138'})

	assert defn.steps[0].value == 'some text'


def test_upload_file_maps_to_upload_step() -> None:
	history = StubHistory([
		StubAction(
			'upload_file',
			{'path': '/tmp/营业执照.jpg'},
			interacted_element=StubInteractedElement(ax_name='上传按钮'),
		),
	])

	defn = synthesize_recipe_definition(
		history,
		recipe_id='r1',
		params={'license_path': '/tmp/营业执照.jpg'},
	)

	assert len(defn.steps) == 2  # upload + stop
	assert defn.steps[0].action == RecipeStepAction.UPLOAD
	assert defn.steps[0].target == '上传按钮'
	assert defn.steps[0].value == '{license_path}'


def test_search_scroll_done_are_skipped() -> None:
	history = StubHistory([
		StubAction('navigate', {'url': 'https://example.com'}),
		StubAction('search', {'query': 'test'}),
		StubAction('scroll', {'direction': 'down'}),
		StubAction('done', {'text': '完成'}),
	])

	defn = synthesize_recipe_definition(history, recipe_id='r1', params={})

	# Only navigate + stop_before_submit
	assert len(defn.steps) == 2
	assert defn.steps[0].action == RecipeStepAction.NAVIGATE


def test_appends_stop_before_submit() -> None:
	history = StubHistory([
		StubAction('navigate', {'url': 'https://example.com'}),
	])

	defn = synthesize_recipe_definition(history, recipe_id='r1', params={})

	assert defn.steps[-1].action == RecipeStepAction.STOP_BEFORE_SUBMIT


def test_missing_interacted_element_is_skipped_gracefully() -> None:
	history = StubHistory([
		StubAction('click', {'index': 5}, interacted_element=None),
		StubAction('navigate', {'url': 'https://example.com'}),
	])

	defn = synthesize_recipe_definition(history, recipe_id='r1', params={})

	# click skipped (no element), navigate + stop
	assert len(defn.steps) == 2
	assert defn.steps[0].action == RecipeStepAction.NAVIGATE


def test_target_fallback_order() -> None:
	# ax_name → aria-label → placeholder → name → node_name
	history = StubHistory([
		StubAction(
			'click',
			{'index': 1},
			interacted_element=StubInteractedElement(
				ax_name=None,
				attributes={'aria-label': '提交按钮', 'placeholder': 'p', 'name': 'n'},
				node_name='BUTTON',
			),
		),
	])

	defn = synthesize_recipe_definition(history, recipe_id='r1', params={})
	assert defn.steps[0].target == '提交按钮'


def test_target_fallback_to_placeholder() -> None:
	history = StubHistory([
		StubAction(
			'click',
			{'index': 1},
			interacted_element=StubInteractedElement(
				ax_name=None,
				attributes={'placeholder': '请输入电话'},
				node_name='INPUT',
			),
		),
	])

	defn = synthesize_recipe_definition(history, recipe_id='r1', params={})
	assert defn.steps[0].target == '请输入电话'


def test_target_fallback_to_node_name() -> None:
	history = StubHistory([
		StubAction(
			'click',
			{'index': 1},
			interacted_element=StubInteractedElement(
				ax_name=None,
				attributes={},
				node_name='BUTTON',
			),
		),
	])

	defn = synthesize_recipe_definition(history, recipe_id='r1', params={})
	assert defn.steps[0].target == 'BUTTON'


def test_entry_url_preserved() -> None:
	history = StubHistory([
		StubAction('navigate', {'url': 'https://example.com'}),
	])

	defn = synthesize_recipe_definition(
		history,
		recipe_id='r1',
		params={},
		entry_url='https://example.com/login',
	)

	assert defn.entry_url == 'https://example.com/login'
