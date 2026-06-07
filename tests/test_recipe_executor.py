"""Tests for RecipeStepExecutor — TDD RED phase."""
from __future__ import annotations

import re

import pytest
import pytest_asyncio
from pytest_httpserver import HTTPServer

from browser_use.browser.profile import BrowserProfile
from browser_use.browser.session import BrowserSession
from merchant_automation.operations.recipe_definition import (
	RecipeDefinition,
	RecipeStep,
	RecipeStepAction,
)
from merchant_automation.operations.executor import RecipeStepExecutor, StepExecutionError
from merchant_automation.operations.schemas import ExecutionMode
from merchant_automation.operations.traces import ExecutionTrace, TraceRecorder, TraceStepKind


# ---------------------------------------------------------------------------
# Mock LLM
# ---------------------------------------------------------------------------


class MockLLM:
	"""Mock LLM that returns the correct element index by parsing candidates."""

	async def ainvoke(self, messages):
		prompt = messages[0].content if messages else ''

		# Extract target description from prompt
		target_match = re.search(r'找到"(.+?)"对应', prompt)
		target = target_match.group(1) if target_match else ''

		# Parse candidates and find matching index
		for line in prompt.split('\n'):
			m = re.match(r'\[(\d+)\]\s*<(\w+)>.*?(?:text|label)="([^"]*)"', line)
			if m:
				idx, tag, text_label = int(m.group(1)), m.group(2), m.group(3)
				# Match by text/label content
				if target in text_label or (tag == 'button' and target in text_label):
					return _MockResponse(str(idx))
				# Match input by label (e.g. "联系电话" for <input>)
				if tag == 'input' and target in text_label:
					return _MockResponse(str(idx))

		# Fallback: return first candidate
		first_match = re.search(r'\[(\d+)\]', prompt)
		return _MockResponse(first_match.group(1) if first_match else '0')


class _MockResponse:
	def __init__(self, content: str) -> None:
		self.content = content


class FailingMockLLM:
	"""Mock LLM that returns a non-existent element index."""

	async def ainvoke(self, messages):
		return _MockResponse('9999')


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def http_server():
	server = HTTPServer()
	server.start()
	yield server
	server.clear()
	server.stop()


@pytest.fixture
def phone_page(http_server):
	"""A page with a phone input field and save button."""
	html = '''<!DOCTYPE html><html><body>
		<h1>门店设置</h1>
		<label for="phone">联系电话</label>
		<input id="phone" name="phone" type="text" value="010-12345678" />
		<button id="save">保存</button>
	</body></html>'''
	http_server.expect_request('/store/settings').respond_with_data(
		html, content_type='text/html'
	)
	return http_server


@pytest_asyncio.fixture
async def browser_session():
	profile = BrowserProfile(headless=True)
	session = BrowserSession(browser_profile=profile)
	await session.start()
	yield session
	await session.close()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_recorder() -> TraceRecorder:
	"""Create a TraceRecorder with a minimal ExecutionTrace."""
	from merchant_automation.operations.traces import ExecutionTrace as ET

	trace = ET(
		platform='test',
		store_id='store-1',
		operation_id='test_op',
		recipe_id='test.recipe.v1',
		mode=ExecutionMode.PREPARE,
	)
	return TraceRecorder(trace)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_navigate_step(phone_page, browser_session):
	"""Navigate step records URL in trace."""
	url = phone_page.url_for('/store/settings')
	recipe = RecipeDefinition(
		recipe_id='test.recipe.v1',
		steps=[RecipeStep(action=RecipeStepAction.NAVIGATE, url=url)],
	)
	executor = RecipeStepExecutor(browser_session, llm=MockLLM())
	recorder = _make_recorder()

	trace = await executor.execute(recipe, params={}, recorder=recorder)

	assert len(trace.steps) == 1
	assert trace.steps[0].kind == TraceStepKind.PAGE
	assert url in (trace.steps[0].url or '')


@pytest.mark.asyncio
async def test_fill_step(phone_page, browser_session):
	"""Fill step finds element and records action in trace."""
	url = phone_page.url_for('/store/settings')
	recipe = RecipeDefinition(
		recipe_id='test.recipe.v1',
		steps=[
			RecipeStep(action=RecipeStepAction.NAVIGATE, url=url),
			RecipeStep(action=RecipeStepAction.WAIT, timeout=1.0),
			RecipeStep(
				action=RecipeStepAction.FILL,
				target='联系电话',
				value='13900139000',
			),
		],
	)
	executor = RecipeStepExecutor(browser_session, llm=MockLLM())
	recorder = _make_recorder()

	trace = await executor.execute(recipe, params={}, recorder=recorder)

	assert len(trace.steps) == 3
	assert trace.steps[2].kind == TraceStepKind.ACTION
	assert trace.steps[2].target == '联系电话'


@pytest.mark.asyncio
async def test_click_step(phone_page, browser_session):
	"""Click step finds element and records action in trace."""
	url = phone_page.url_for('/store/settings')
	recipe = RecipeDefinition(
		recipe_id='test.recipe.v1',
		steps=[
			RecipeStep(action=RecipeStepAction.NAVIGATE, url=url),
			RecipeStep(action=RecipeStepAction.WAIT, timeout=1.0),
			RecipeStep(action=RecipeStepAction.CLICK, target='保存'),
		],
	)
	executor = RecipeStepExecutor(browser_session, llm=MockLLM())
	recorder = _make_recorder()

	trace = await executor.execute(recipe, params={}, recorder=recorder)

	assert len(trace.steps) == 3
	assert trace.steps[2].kind == TraceStepKind.ACTION
	assert trace.steps[2].target == '保存'


@pytest.mark.asyncio
async def test_screenshot_step(phone_page, browser_session):
	"""Screenshot step saves file and records path in trace."""
	url = phone_page.url_for('/store/settings')
	recipe = RecipeDefinition(
		recipe_id='test.recipe.v1',
		steps=[
			RecipeStep(action=RecipeStepAction.NAVIGATE, url=url),
			RecipeStep(
				action=RecipeStepAction.SCREENSHOT,
				description='提交前截图',
			),
		],
	)
	executor = RecipeStepExecutor(browser_session, llm=MockLLM())
	recorder = _make_recorder()

	trace = await executor.execute(recipe, params={}, recorder=recorder)

	screenshot_step = trace.steps[1]
	assert screenshot_step.kind == TraceStepKind.SCREENSHOT
	assert screenshot_step.screenshot_path is not None
	assert screenshot_step.screenshot_path.endswith('.png')


@pytest.mark.asyncio
async def test_stop_before_submit(phone_page, browser_session):
	"""Execution stops at STOP_BEFORE_SUBMIT step."""
	url = phone_page.url_for('/store/settings')
	recipe = RecipeDefinition(
		recipe_id='test.recipe.v1',
		steps=[
			RecipeStep(action=RecipeStepAction.NAVIGATE, url=url),
			RecipeStep(action=RecipeStepAction.STOP_BEFORE_SUBMIT),
			RecipeStep(action=RecipeStepAction.CLICK, target='保存'),
		],
	)
	executor = RecipeStepExecutor(browser_session, llm=MockLLM())
	recorder = _make_recorder()

	trace = await executor.execute(recipe, params={}, recorder=recorder)

	# Only navigate + stop_before_submit should execute, not the click
	assert len(trace.steps) == 2
	assert trace.steps[1].kind == TraceStepKind.ACTION
	assert '停在提交前' in trace.steps[1].message


@pytest.mark.asyncio
async def test_template_variable_resolution(phone_page, browser_session):
	"""Template {phone} resolves to params['phone']."""
	url = phone_page.url_for('/store/settings')
	recipe = RecipeDefinition(
		recipe_id='test.recipe.v1',
		steps=[
			RecipeStep(action=RecipeStepAction.NAVIGATE, url=url),
			RecipeStep(action=RecipeStepAction.WAIT, timeout=1.0),
			RecipeStep(
				action=RecipeStepAction.FILL,
				target='联系电话',
				value='{phone}',
			),
		],
	)
	executor = RecipeStepExecutor(browser_session, llm=MockLLM())
	recorder = _make_recorder()

	trace = await executor.execute(
		recipe, params={'phone': '13800138000'}, recorder=recorder
	)

	fill_step = trace.steps[2]
	assert fill_step.input_value == '13800138000'


@pytest.mark.asyncio
async def test_step_execution_error_on_missing_element(phone_page, browser_session):
	"""StepExecutionError raised when element not found."""
	url = phone_page.url_for('/store/settings')
	recipe = RecipeDefinition(
		recipe_id='test.recipe.v1',
		steps=[
			RecipeStep(action=RecipeStepAction.NAVIGATE, url=url),
			RecipeStep(action=RecipeStepAction.WAIT, timeout=1.0),
			RecipeStep(action=RecipeStepAction.CLICK, target='不存在的元素'),
		],
	)
	executor = RecipeStepExecutor(browser_session, llm=FailingMockLLM())
	recorder = _make_recorder()

	with pytest.raises(StepExecutionError) as exc_info:
		await executor.execute(recipe, params={}, recorder=recorder)

	assert '不存在的元素' in str(exc_info.value)
