"""Convert browser_use AgentHistoryList to RecipeDefinition."""
from __future__ import annotations

import logging
from ipaddress import ip_address
from typing import Any, Protocol
from urllib.parse import urlparse

from merchant_automation.operations.recipe_definition import (
	RecipeDefinition,
	RecipeStep,
	RecipeStepAction,
)

logger = logging.getLogger(__name__)

# Actions we convert; everything else is skipped as noise.
_ACTION_MAP: dict[str, RecipeStepAction] = {
	'navigate': RecipeStepAction.NAVIGATE,
	'click': RecipeStepAction.CLICK,
	'input': RecipeStepAction.FILL,
	'upload_file': RecipeStepAction.UPLOAD,
}

_MEITUAN_MERCHANT_HOME = 'https://e.waimai.meituan.com/'
_UNSTABLE_MEITUAN_DEEP_LINK_PREFIXES = (
	'/new_fe/shop/',
)


def _is_generated_local_host(hostname: str | None) -> bool:
	if hostname is None:
		return False
	if hostname.lower() == 'localhost':
		return True
	try:
		address = ip_address(hostname)
	except ValueError:
		return False
	return address.is_loopback or address.is_unspecified


class _InteractedElement(Protocol):
	ax_name: str | None
	attributes: dict[str, str]
	node_name: str | None


class _History(Protocol):
	def model_actions(self) -> list[dict[str, Any]]: ...


def _semantic_target(element: _InteractedElement | None) -> str | None:
	"""Extract human-readable target from interacted element.

	Fallback order: ax_name → aria-label → placeholder → name → node_name
	"""
	if element is None:
		return None

	if element.ax_name:
		return element.ax_name

	attrs = element.attributes
	for key in ('aria-label', 'placeholder', 'name'):
		val = attrs.get(key)
		if val:
			return val

	return element.node_name


def _parameterize(value: str, params: dict[str, object]) -> str:
	"""Replace value with {key} if it exactly matches a param value."""
	for key, param_val in params.items():
		if value == str(param_val):
			return f'{{{key}}}'
	return value


def _safe_navigate_url(url: str) -> str | None:
	"""Normalize generated navigation URLs; return None when the URL is unsafe."""
	parsed = urlparse(url)
	if _is_generated_local_host(parsed.hostname):
		logger.warning('Skipping generated localhost navigation URL: %s', url)
		return None
	if (
		parsed.hostname == 'e.waimai.meituan.com'
		and any(parsed.path.startswith(prefix) for prefix in _UNSTABLE_MEITUAN_DEEP_LINK_PREFIXES)
	):
		logger.info('Replacing generated Meituan deep link with merchant home: %s', url)
		return _MEITUAN_MERCHANT_HOME
	return url


def synthesize_recipe_definition(
	history: _History,
	*,
	recipe_id: str,
	params: dict[str, object],
	entry_url: str | None = None,
) -> RecipeDefinition:
	"""Convert browser_use action history into a RecipeDefinition.

	Args:
		history: AgentHistoryList (duck-typed: must have .model_actions()).
		recipe_id: Target recipe identifier.
		params: Operation parameters for value parameterization.
		entry_url: Optional entry URL for the definition.

	Returns:
		RecipeDefinition with synthesized steps, ending with STOP_BEFORE_SUBMIT.
	"""
	steps: list[RecipeStep] = []

	for action_dict in history.model_actions():
		# Each dict has one action key + 'interacted_element'
		element = action_dict.get('interacted_element')

		for action_name, action_params in action_dict.items():
			if action_name == 'interacted_element':
				continue

			step_action = _ACTION_MAP.get(action_name)
			if step_action is None:
				logger.debug('Skipping unknown action: %s', action_name)
				continue

			step = _build_step(step_action, action_params, element, params)
			if step is not None:
				steps.append(step)

	# Always end with STOP_BEFORE_SUBMIT
	steps.append(RecipeStep(action=RecipeStepAction.STOP_BEFORE_SUBMIT))

	return RecipeDefinition(
		recipe_id=recipe_id,
		steps=steps,
		entry_url=_safe_navigate_url(entry_url) if entry_url else entry_url,
	)


def _build_step(
	action: RecipeStepAction,
	params: dict[str, Any],
	element: _InteractedElement | None,
	recipe_params: dict[str, object],
) -> RecipeStep | None:
	"""Build a RecipeStep from a browser_use action. Returns None to skip."""
	if action == RecipeStepAction.NAVIGATE:
		url = _safe_navigate_url(params.get('url', ''))
		if not url:
			return None
		return RecipeStep(action=action, url=url, value=url)

	if action in (RecipeStepAction.CLICK, RecipeStepAction.FILL, RecipeStepAction.UPLOAD):
		target = _semantic_target(element)
		if target is None:
			logger.debug('Skipping %s: no interacted element', action.value)
			return None

		value: str | None = None
		if action == RecipeStepAction.FILL:
			raw = params.get('text', '')
			value = _parameterize(raw, recipe_params)
		elif action == RecipeStepAction.UPLOAD:
			raw = params.get('path', '')
			value = _parameterize(raw, recipe_params)

		return RecipeStep(action=action, target=target, value=value)

	return None
