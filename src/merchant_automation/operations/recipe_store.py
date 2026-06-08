from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from pydantic import BaseModel, ConfigDict

from merchant_automation.operations.recipe_definition import RecipeDefinition
from merchant_automation.operations.schemas import (
	ExecutionMode,
	RecipeMetadata,
	RecipeStatus,
)


class RecipeSummary(BaseModel):
	"""Lightweight summary for list views."""

	model_config = ConfigDict(extra='forbid')

	recipe_id: str
	operation_id: str
	platform: str
	version: int
	status: RecipeStatus
	allowed_modes: set[ExecutionMode]
	success_rates: dict[ExecutionMode, float]


class RecipeStore:
	def __init__(self, db_path: str | Path) -> None:
		self._db_path = Path(db_path)

	def initialize(self) -> None:
		self._db_path.parent.mkdir(parents=True, exist_ok=True)
		with self._connection() as connection:
			connection.execute(
				'''
				CREATE TABLE IF NOT EXISTS recipes (
					recipe_id TEXT PRIMARY KEY,
					operation_id TEXT NOT NULL,
					platform TEXT NOT NULL,
					version INTEGER NOT NULL,
					status TEXT NOT NULL,
					allowed_modes_json TEXT NOT NULL,
					success_rates_json TEXT NOT NULL,
					created_at TEXT NOT NULL,
					updated_at TEXT NOT NULL,
					payload_json TEXT NOT NULL
				)
				'''
			)
			connection.execute(
				'''
				CREATE TABLE IF NOT EXISTS recipe_definitions (
					recipe_id TEXT PRIMARY KEY,
					payload_json TEXT NOT NULL,
					source TEXT NOT NULL DEFAULT 'auto',
					created_at TEXT NOT NULL,
					updated_at TEXT NOT NULL
				)
				'''
			)

	def table_names(self) -> set[str]:
		with self._connection() as connection:
			rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
		return {row['name'] for row in rows}

	def list_recipes(self) -> list[RecipeSummary]:
		with self._connection() as connection:
			rows = connection.execute(
				'''
				SELECT recipe_id, operation_id, platform, version, status,
					allowed_modes_json, success_rates_json
				FROM recipes
				ORDER BY platform, operation_id
				'''
			).fetchall()
		return [
			RecipeSummary(
				recipe_id=row['recipe_id'],
				operation_id=row['operation_id'],
				platform=row['platform'],
				version=row['version'],
				status=RecipeStatus(row['status']),
				allowed_modes={ExecutionMode(m) for m in json.loads(row['allowed_modes_json'])},
				success_rates={ExecutionMode(k): v for k, v in json.loads(row['success_rates_json']).items()},
			)
			for row in rows
		]

	def get_recipe(self, recipe_id: str) -> RecipeMetadata | None:
		with self._connection() as connection:
			row = connection.execute(
				'SELECT payload_json FROM recipes WHERE recipe_id = ?',
				(recipe_id,),
			).fetchone()
		if row is None:
			return None
		return RecipeMetadata.model_validate_json(row['payload_json'])

	def upsert_recipe(self, recipe: RecipeMetadata) -> None:
		now = _now()
		with self._connection() as connection:
			connection.execute(
				'''
				INSERT INTO recipes (
					recipe_id, operation_id, platform, version, status,
					allowed_modes_json, success_rates_json, created_at, updated_at, payload_json
				) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
				ON CONFLICT(recipe_id) DO UPDATE SET
					operation_id = excluded.operation_id,
					platform = excluded.platform,
					version = excluded.version,
					status = excluded.status,
					allowed_modes_json = excluded.allowed_modes_json,
					success_rates_json = excluded.success_rates_json,
					updated_at = excluded.updated_at,
					payload_json = excluded.payload_json
				''',
				(
					recipe.recipe_id,
					recipe.operation_id,
					recipe.platform,
					recipe.version,
					recipe.status.value,
					json.dumps([m.value for m in sorted(recipe.allowed_modes, key=lambda m: m.value)]),
					json.dumps({k.value: v for k, v in sorted(recipe.success_rates.items(), key=lambda item: item[0].value)}),
					now,
					now,
					_dump_model(recipe),
				),
			)

	def save_definition(self, definition: RecipeDefinition, *, source: str = 'auto') -> None:
		now = _now()
		with self._connection() as connection:
			# Preserve created_at on update
			existing = connection.execute(
				'SELECT created_at FROM recipe_definitions WHERE recipe_id = ?',
				(definition.recipe_id,),
			).fetchone()
			created_at = existing['created_at'] if existing else now

			connection.execute(
				'''
				INSERT INTO recipe_definitions (
					recipe_id, payload_json, source, created_at, updated_at
				) VALUES (?, ?, ?, ?, ?)
				ON CONFLICT(recipe_id) DO UPDATE SET
					payload_json = excluded.payload_json,
					source = excluded.source,
					updated_at = excluded.updated_at
				''',
				(definition.recipe_id, _dump_model(definition), source, created_at, now),
			)

	def get_definition(self, recipe_id: str) -> RecipeDefinition | None:
		with self._connection() as connection:
			row = connection.execute(
				'SELECT payload_json FROM recipe_definitions WHERE recipe_id = ?',
				(recipe_id,),
			).fetchone()
		if row is None:
			return None
		return RecipeDefinition.model_validate_json(row['payload_json'])

	def list_definitions(self) -> list[RecipeDefinition]:
		with self._connection() as connection:
			rows = connection.execute(
				'SELECT payload_json FROM recipe_definitions ORDER BY recipe_id'
			).fetchall()
		return [RecipeDefinition.model_validate_json(row['payload_json']) for row in rows]

	def update_status(self, recipe_id: str, new_status: RecipeStatus) -> bool:
		now = _now()
		with self._connection() as connection:
			# First get the existing payload
			row = connection.execute(
				'SELECT payload_json FROM recipes WHERE recipe_id = ?',
				(recipe_id,),
			).fetchone()
			if row is None:
				return False

			# Update the payload with new status
			payload = json.loads(row['payload_json'])
			payload['status'] = new_status.value
			new_payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=True)

			connection.execute(
				'UPDATE recipes SET status = ?, updated_at = ?, payload_json = ? WHERE recipe_id = ?',
				(new_status.value, now, new_payload_json, recipe_id),
			)
		return True

	@contextmanager
	def _connection(self) -> Iterator[sqlite3.Connection]:
		connection = sqlite3.connect(self._db_path)
		connection.row_factory = sqlite3.Row
		try:
			yield connection
			connection.commit()
		finally:
			connection.close()


def _dump_model(model: BaseModel) -> str:
	return json.dumps(model.model_dump(mode='json'), ensure_ascii=False, sort_keys=True)


def _now() -> str:
	return datetime.now(timezone.utc).isoformat()

