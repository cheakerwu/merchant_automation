from merchant_automation.operations.binder import JobPlanBinder
from merchant_automation.operations.catalog import OperationCatalog
from merchant_automation.operations.preflight import CommitPolicy
from merchant_automation.operations.recipes import RecipeRegistry
from merchant_automation.operations.schemas import (
	ExecutionMode,
	JobPlan,
	OperationTask,
	RecipeMetadata,
	RecipeStatus,
)


def test_binder_fills_recipe_id_and_keeps_prepare_mode():
	plan = JobPlan(
		source='test',
		tasks=[
			OperationTask(
				platform='meituan',
				store_id='A店',
				operation_id='update_store_phone',
				params={'phone': '13800138000'},
				mode=ExecutionMode.PREPARE,
			)
		],
	)

	result = JobPlanBinder().bind(plan, policy=CommitPolicy())

	assert result.issues == []
	assert len(result.bound_tasks) == 1
	bound = result.bound_tasks[0]
	assert bound.task.recipe_id == 'meituan.update_store_phone.v1'
	assert bound.task.mode == ExecutionMode.PREPARE
	assert bound.preflight.effective_mode == ExecutionMode.PREPARE


def test_binder_downgrades_commit_when_recipe_is_not_commit_ready():
	plan = JobPlan(
		source='test',
		tasks=[
			OperationTask(
				platform='meituan',
				store_id='A店',
				operation_id='update_store_phone',
				params={'phone': '13800138000'},
				mode=ExecutionMode.COMMIT,
			)
		],
	)

	result = JobPlanBinder().bind(
		plan,
		policy=CommitPolicy(global_commit_enabled=True, account_commit_allowed=True, store_commit_allowed=True),
	)

	assert result.issues == []
	bound = result.bound_tasks[0]
	assert bound.task.mode == ExecutionMode.PREPARE
	assert bound.preflight.requested_mode == ExecutionMode.COMMIT
	assert 'recipe_not_commit_ready' in bound.preflight.reasons


def test_missing_recipe_becomes_issue_without_stopping_other_tasks():
	plan = JobPlan(
		source='test',
		tasks=[
			OperationTask(platform='eleme', store_id='A店', operation_id='update_store_phone', params={'phone': '13800138000'}),
			OperationTask(platform='meituan', store_id='B店', operation_id='update_store_phone', params={'phone': '13900139000'}),
		],
	)

	result = JobPlanBinder().bind(plan, policy=CommitPolicy())

	assert len(result.bound_tasks) == 1
	assert result.bound_tasks[0].task.store_id == 'B店'
	assert len(result.issues) == 1
	assert result.issues[0].task_index == 0
	assert result.issues[0].reason == 'recipe_not_found: No recipe for eleme/update_store_phone'


def test_disabled_recipe_blocks_task_with_preflight_issue():
	disabled_recipe = RecipeMetadata(
		recipe_id='meituan.update_store_phone.disabled',
		operation_id='update_store_phone',
		platform='meituan',
		version=1,
		status=RecipeStatus.DISABLED,
		allowed_modes={ExecutionMode.PARSE_ONLY, ExecutionMode.PREPARE},
	)
	registry = RecipeRegistry(recipes=[disabled_recipe])
	plan = JobPlan(
		source='test',
		tasks=[
			OperationTask(
				platform='meituan',
				store_id='A店',
				operation_id='update_store_phone',
				params={'phone': '13800138000'},
				mode=ExecutionMode.PREPARE,
			)
		],
	)

	result = JobPlanBinder(registry=registry, catalog=OperationCatalog.default()).bind(plan, policy=CommitPolicy())

	assert result.bound_tasks == []
	assert len(result.issues) == 1
	assert result.issues[0].reason == 'preflight_failed: recipe_disabled'
