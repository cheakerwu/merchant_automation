from __future__ import annotations

from pathlib import Path

import pytest

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
