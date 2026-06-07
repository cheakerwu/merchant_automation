from pathlib import Path

from merchant_automation.operations.preflight import CommitPolicy
from merchant_automation.operations.service import OperationPlanningService
from merchant_automation.operations.storage import OperationStore


def test_store_initializes_sqlite_tables(tmp_path: Path):
	db_path = tmp_path / 'merchant.db'
	store = OperationStore(db_path)

	store.initialize()

	assert db_path.exists()
	assert store.table_names() == {'failure_analyses', 'planning_runs', 'traces'}


def test_planning_result_round_trips(tmp_path: Path):
	store = OperationStore(tmp_path / 'merchant.db')
	store.initialize()
	result = OperationPlanningService().plan_text('把美团 A店 电话改成 13800138000', policy=CommitPolicy())

	run_id = store.save_planning_result(result)
	loaded = store.get_planning_result(run_id)

	assert loaded is not None
	assert loaded.plan.source == 'text'
	assert loaded.bound_tasks[0].task.recipe_id == 'meituan.update_store_phone.v1'
	assert loaded.bound_tasks[0].task.params == {'phone': '13800138000'}


def test_list_planning_runs_returns_dashboard_summary(tmp_path: Path):
	store = OperationStore(tmp_path / 'merchant.db')
	store.initialize()
	service = OperationPlanningService()
	success = service.plan_text('把美团 A店 电话改成 13800138000')
	failed = service.plan_text('把美团 A店 牛肉饭价格改成 19.9')

	success_id = store.save_planning_result(success)
	failed_id = store.save_planning_result(failed)

	summaries = store.list_planning_runs()

	assert [summary.run_id for summary in summaries] == [failed_id, success_id]
	assert summaries[0].source == 'text'
	assert summaries[0].task_count == 0
	assert summaries[0].issue_count == 1
	assert summaries[1].task_count == 1
	assert summaries[1].issue_count == 0
