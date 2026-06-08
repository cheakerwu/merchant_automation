from __future__ import annotations

from pathlib import Path

import pytest

from merchant_automation.operations.recipe_definition import (
	RecipeDefinition,
	RecipeStep,
	RecipeStepAction,
)
from merchant_automation.operations.schemas import (
	ExecutionMode,
	RecipeMetadata,
	RecipeStatus,
)
from merchant_automation.operations.recipe_store import RecipeStore


def _make_recipe(
	recipe_id: str = 'recipe-1',
	operation_id: str = 'op-1',
	platform: str = 'platform-a',
	version: int = 1,
	status: RecipeStatus = RecipeStatus.CANDIDATE,
	allowed_modes: set[ExecutionMode] | None = None,
	success_rates: dict[ExecutionMode, float] | None = None,
) -> RecipeMetadata:
	return RecipeMetadata(
		recipe_id=recipe_id,
		operation_id=operation_id,
		platform=platform,
		version=version,
		status=status,
		allowed_modes=allowed_modes or set(),
		success_rates=success_rates or {},
	)


@pytest.fixture
def store(tmp_path: Path) -> RecipeStore:
	db_path = tmp_path / 'recipes.db'
	s = RecipeStore(db_path)
	s.initialize()
	return s


def test_initialize_creates_recipes_table(store: RecipeStore) -> None:
	tables = store.table_names()
	assert 'recipes' in tables


def test_upsert_and_list_recipes(store: RecipeStore) -> None:
	recipe1 = _make_recipe(recipe_id='r1', platform='p1', operation_id='op1')
	recipe2 = _make_recipe(recipe_id='r2', platform='p2', operation_id='op2')

	store.upsert_recipe(recipe1)
	store.upsert_recipe(recipe2)

	results = store.list_recipes()
	assert len(results) == 2

	# Ordered by platform, operation_id
	assert results[0].recipe_id == 'r1'
	assert results[1].recipe_id == 'r2'


def test_get_recipe_returns_full_metadata(store: RecipeStore) -> None:
	recipe = _make_recipe(
		recipe_id='r-full',
		operation_id='op-full',
		platform='plat',
		version=3,
		status=RecipeStatus.PREPARE_READY,
		allowed_modes={ExecutionMode.PREPARE, ExecutionMode.COMMIT},
		success_rates={ExecutionMode.PREPARE: 0.95, ExecutionMode.COMMIT: 0.8},
	)
	store.upsert_recipe(recipe)

	loaded = store.get_recipe('r-full')
	assert loaded is not None
	assert loaded.recipe_id == 'r-full'
	assert loaded.operation_id == 'op-full'
	assert loaded.platform == 'plat'
	assert loaded.version == 3
	assert loaded.status == RecipeStatus.PREPARE_READY
	assert loaded.allowed_modes == {ExecutionMode.PREPARE, ExecutionMode.COMMIT}
	assert loaded.success_rates == {ExecutionMode.PREPARE: 0.95, ExecutionMode.COMMIT: 0.8}


def test_get_recipe_returns_none_for_missing(store: RecipeStore) -> None:
	assert store.get_recipe('nonexistent') is None


def test_update_status(store: RecipeStore) -> None:
	recipe = _make_recipe(recipe_id='r-status', status=RecipeStatus.CANDIDATE)
	store.upsert_recipe(recipe)

	updated = store.update_status('r-status', RecipeStatus.COMMIT_READY)
	assert updated is True

	loaded = store.get_recipe('r-status')
	assert loaded is not None
	assert loaded.status == RecipeStatus.COMMIT_READY


def test_update_status_returns_false_for_missing(store: RecipeStore) -> None:
	updated = store.update_status('nonexistent', RecipeStatus.DISABLED)
	assert updated is False


def test_upsert_overwrites_existing(store: RecipeStore) -> None:
	recipe_v1 = _make_recipe(recipe_id='r-overwrite', status=RecipeStatus.CANDIDATE)
	store.upsert_recipe(recipe_v1)

	recipe_v2 = _make_recipe(recipe_id='r-overwrite', status=RecipeStatus.DISABLED, version=2)
	store.upsert_recipe(recipe_v2)

	results = store.list_recipes()
	assert len(results) == 1
	assert results[0].status == RecipeStatus.DISABLED
	assert results[0].version == 2

	loaded = store.get_recipe('r-overwrite')
	assert loaded is not None
	assert loaded.status == RecipeStatus.DISABLED
	assert loaded.version == 2


def _make_definition(
	recipe_id: str = 'recipe-1',
	steps: list[RecipeStep] | None = None,
	entry_url: str | None = None,
) -> RecipeDefinition:
	return RecipeDefinition(
		recipe_id=recipe_id,
		steps=steps or [],
		entry_url=entry_url,
	)


def test_initialize_creates_recipe_definitions_table(store: RecipeStore) -> None:
	tables = store.table_names()
	assert 'recipe_definitions' in tables


def test_save_and_get_definition_roundtrip(store: RecipeStore) -> None:
	defn = _make_definition(
		recipe_id='r-def-1',
		steps=[
			RecipeStep(action=RecipeStepAction.NAVIGATE, url='https://example.com'),
			RecipeStep(action=RecipeStepAction.CLICK, target='保存按钮'),
			RecipeStep(action=RecipeStepAction.STOP_BEFORE_SUBMIT),
		],
		entry_url='https://example.com',
	)
	store.save_definition(defn)

	loaded = store.get_definition('r-def-1')
	assert loaded is not None
	assert loaded.recipe_id == 'r-def-1'
	assert len(loaded.steps) == 3
	assert loaded.steps[0].action == RecipeStepAction.NAVIGATE
	assert loaded.steps[0].url == 'https://example.com'
	assert loaded.steps[1].action == RecipeStepAction.CLICK
	assert loaded.steps[1].target == '保存按钮'
	assert loaded.steps[2].action == RecipeStepAction.STOP_BEFORE_SUBMIT
	assert loaded.entry_url == 'https://example.com'


def test_save_definition_upsert_overwrites(store: RecipeStore) -> None:
	defn_v1 = _make_definition(
		recipe_id='r-upsert',
		steps=[RecipeStep(action=RecipeStepAction.NAVIGATE, url='https://v1.com')],
	)
	store.save_definition(defn_v1)

	defn_v2 = _make_definition(
		recipe_id='r-upsert',
		steps=[
			RecipeStep(action=RecipeStepAction.NAVIGATE, url='https://v2.com'),
			RecipeStep(action=RecipeStepAction.CLICK, target='按钮'),
		],
		entry_url='https://v2.com',
	)
	store.save_definition(defn_v2)

	loaded = store.get_definition('r-upsert')
	assert loaded is not None
	assert len(loaded.steps) == 2
	assert loaded.steps[0].url == 'https://v2.com'
	assert loaded.entry_url == 'https://v2.com'

	results = store.list_definitions()
	assert len(results) == 1


def test_get_definition_returns_none_when_missing(store: RecipeStore) -> None:
	assert store.get_definition('nonexistent') is None


def test_list_definitions_returns_all(store: RecipeStore) -> None:
	defn1 = _make_definition(recipe_id='r-list-1', steps=[RecipeStep(action=RecipeStepAction.NAVIGATE)])
	defn2 = _make_definition(recipe_id='r-list-2', steps=[RecipeStep(action=RecipeStepAction.CLICK)])
	defn3 = _make_definition(recipe_id='r-list-3', steps=[RecipeStep(action=RecipeStepAction.FILL)])

	store.save_definition(defn1)
	store.save_definition(defn2)
	store.save_definition(defn3)

	results = store.list_definitions()
	assert len(results) == 3
	recipe_ids = {d.recipe_id for d in results}
	assert recipe_ids == {'r-list-1', 'r-list-2', 'r-list-3'}
