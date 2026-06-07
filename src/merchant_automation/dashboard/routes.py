from __future__ import annotations

from html import escape

from fastapi import APIRouter, FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from merchant_automation.accounts.store import AccountStore
from merchant_automation.operations.recipe_store import RecipeStore
from merchant_automation.operations.schemas import ExecutionMode, RecipeStatus
from merchant_automation.operations.storage import OperationStore


def create_dashboard_app(
	store: OperationStore,
	recipe_store: RecipeStore | None = None,
	account_store: AccountStore | None = None,
) -> FastAPI:
	app = FastAPI(title='Merchant Automation Dashboard')
	app.include_router(create_dashboard_router(store, recipe_store=recipe_store, account_store=account_store))
	return app


def create_dashboard_router(
	store: OperationStore,
	recipe_store: RecipeStore | None = None,
	account_store: AccountStore | None = None,
) -> APIRouter:
	router = APIRouter(prefix='/dashboard', tags=['dashboard'])

	@router.get('', response_class=HTMLResponse)
	def dashboard_home() -> HTMLResponse:
		rows = ''.join(
			_table_row(
				summary.run_id,
				summary.source,
				str(summary.task_count),
				str(summary.issue_count),
				summary.created_at,
			)
			for summary in store.list_planning_runs()
		)
		return HTMLResponse(
			_page(
				'任务中心',
				_table(['Run ID', '来源', '任务数', '问题数', '创建时间'], rows),
			)
		)

	@router.get('/traces', response_class=HTMLResponse)
	def dashboard_traces() -> HTMLResponse:
		rows = ''.join(
			_table_row(
				summary.trace_id,
				summary.operation_id,
				summary.platform,
				summary.store_id,
				summary.recipe_id,
				summary.mode.value,
				summary.outcome_status.value if summary.outcome_status else '-',
				summary.failure_type.value if summary.failure_type else '-',
			)
			for summary in store.list_traces()
		)
		return HTMLResponse(
			_page(
				'轨迹中心',
				_table(['Trace ID', 'Operation', '平台', '门店', 'Recipe', 'Mode', '结果', '失败类型'], rows),
			)
		)

	@router.get('/failures', response_class=HTMLResponse)
	def dashboard_failures() -> HTMLResponse:
		rows = ''.join(
			_table_row(
				summary.analysis_id,
				summary.trace_id,
				summary.failure_type.value,
				'可重试' if summary.retryable else '不可重试',
				'疑似过期' if summary.suspected_recipe_stale else '正常',
				summary.created_at,
			)
			for summary in store.list_failure_analyses()
		)
		return HTMLResponse(
			_page(
				'失败分析',
				_table(['Analysis ID', 'Trace ID', '失败类型', '重试', 'Recipe 状态', '创建时间'], rows),
			)
		)

	# ------------------------------------------------------------------
	# Recipe Console
	# ------------------------------------------------------------------

	@router.get('/recipes', response_class=HTMLResponse)
	def recipe_list() -> HTMLResponse:
		if recipe_store is None:
			return HTMLResponse(_page('Recipe 控制台', '<p>Recipe Store 未配置</p>'))
		rows = ''.join(
			_table_row(
				summary.recipe_id,
				summary.operation_id,
				summary.platform,
				str(summary.version),
				summary.status.value,
				_format_rate(summary.success_rates.get(ExecutionMode.PREPARE)),
				_format_rate(summary.success_rates.get(ExecutionMode.COMMIT)),
				', '.join(sorted(m.value for m in summary.allowed_modes)),
			)
			for summary in recipe_store.list_recipes()
		)
		return HTMLResponse(
			_page(
				'Recipe 控制台',
				_table(
					['Recipe ID', 'Operation', '平台', '版本', '状态', 'prepare 成功率', 'commit 成功率', '允许 Mode'],
					rows,
				),
			)
		)

	@router.get('/recipes/{recipe_id}', response_class=HTMLResponse)
	def recipe_detail(recipe_id: str) -> HTMLResponse:
		if recipe_store is None:
			return HTMLResponse(_page('Recipe 详情', '<p>Recipe Store 未配置</p>'), status_code=404)
		recipe = recipe_store.get_recipe(recipe_id)
		if recipe is None:
			return HTMLResponse(_page('Recipe 详情', f'<p>未找到 Recipe: {escape(recipe_id)}</p>'), status_code=404)

		allowed_modes = ', '.join(sorted(m.value for m in recipe.allowed_modes))
		success_rows = ''.join(
			_table_row(mode.value, _format_rate(rate))
			for mode, rate in sorted(recipe.success_rates.items(), key=lambda item: item[0].value)
		)
		success_table = _table(['Mode', '成功率'], success_rows)

		status_options = ''.join(
			f'<option value="{escape(s.value)}"{" selected" if s == recipe.status else ""}>{escape(s.value)}</option>'
			for s in RecipeStatus
		)
		status_form = f'''<h2>切换状态</h2>
<form method="post" action="/dashboard/recipes/{escape(recipe_id)}/status">
	<select name="new_status">{status_options}</select>
	<button type="submit">切换状态</button>
</form>'''

		detail_table = _table(
			['字段', '值'],
			''.join(
				_table_row(field, value)
				for field, value in [
					('Recipe ID', recipe.recipe_id),
					('Operation', recipe.operation_id),
					('平台', recipe.platform),
					('版本', str(recipe.version)),
					('状态', recipe.status.value),
					('允许 Mode', allowed_modes),
				]
			),
		)
		return HTMLResponse(
			_page(
				f'Recipe: {recipe.recipe_id}',
				detail_table + '<h2>成功率</h2>' + success_table + status_form,
			)
		)

	@router.post('/recipes/{recipe_id}/status')
	def recipe_status_toggle(recipe_id: str, new_status: str = Form(...)) -> RedirectResponse:
		if recipe_store is None:
			return RedirectResponse(url='/dashboard/recipes', status_code=307)
		try:
			status_enum = RecipeStatus(new_status)
		except ValueError:
			return RedirectResponse(url=f'/dashboard/recipes/{recipe_id}', status_code=307)
		recipe_store.update_status(recipe_id, status_enum)
		return RedirectResponse(url=f'/dashboard/recipes/{recipe_id}', status_code=307)

	# ------------------------------------------------------------------
	# Account & Store Center
	# ------------------------------------------------------------------

	@router.get('/accounts', response_class=HTMLResponse)
	def account_list() -> HTMLResponse:
		if account_store is None:
			return HTMLResponse(_page('账号门店', '<p>Account Store 未配置</p>'))
		rows = ''.join(
			_table_row(
				summary.account_id,
				summary.platform,
				summary.username,
				summary.login_status.value,
				summary.default_mode.value,
				'是' if summary.commit_allowed else '否',
			)
			for summary in account_store.list_accounts()
		)
		return HTMLResponse(
			_page(
				'账号门店',
				_table(
					['Account ID', '平台', '用户名', '登录状态', '默认 Mode', '允许 Commit'],
					rows,
				),
			)
		)

	@router.get('/accounts/{account_id}', response_class=HTMLResponse)
	def account_detail(account_id: str) -> HTMLResponse:
		if account_store is None:
			return HTMLResponse(_page('账号详情', '<p>Account Store 未配置</p>'), status_code=404)
		account = account_store.get_account(account_id)
		if account is None:
			return HTMLResponse(_page('账号详情', f'<p>未找到账号: {escape(account_id)}</p>'), status_code=404)

		detail_table = _table(
			['字段', '值'],
			''.join(
				_table_row(field, value)
				for field, value in [
					('Account ID', account.account_id),
					('平台', account.platform),
					('用户名', account.username),
					('Profile Path', account.profile_path or '-'),
					('登录状态', account.login_status.value),
					('默认 Mode', account.default_mode.value),
					('允许 Commit', '是' if account.commit_allowed else '否'),
					('飞书群 ID', account.feishu_group_id or '-'),
					('最近失败原因', account.last_failure_reason or '-'),
				]
			),
		)

		stores = account_store.list_stores(account_id=account_id)
		store_rows = ''.join(
			_table_row(
				s.store_id,
				s.platform,
				s.account_id,
				s.store_name or '-',
			)
			for s in stores
		)
		store_table = _table(['Store ID', '平台', 'Account ID', '门店名称'], store_rows)

		return HTMLResponse(
			_page(
				f'账号: {account.username}',
				detail_table + '<h2>绑定门店</h2>' + store_table,
			)
		)

	@router.get('/stores', response_class=HTMLResponse)
	def store_list() -> HTMLResponse:
		if account_store is None:
			return HTMLResponse(_page('门店列表', '<p>Account Store 未配置</p>'))
		rows = ''.join(
			_table_row(
				s.store_id,
				s.platform,
				s.account_id,
				s.store_name or '-',
			)
			for s in account_store.list_stores()
		)
		return HTMLResponse(
			_page(
				'门店列表',
				_table(['Store ID', '平台', 'Account ID', '门店名称'], rows),
			)
		)

	return router


def _page(title: str, body: str) -> str:
	return f'''<!doctype html>
<html lang="zh-CN">
<head>
	<meta charset="utf-8">
	<title>{escape(title)}</title>
	<style>
		body {{ font-family: Arial, "Microsoft YaHei", sans-serif; margin: 24px; color: #1f2937; }}
		nav a {{ margin-right: 16px; color: #0f766e; }}
		table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
		th, td {{ border-bottom: 1px solid #e5e7eb; padding: 8px 10px; text-align: left; }}
		th {{ background: #f9fafb; }}
	</style>
</head>
<body>
	<nav>
		<a href="/dashboard">任务中心</a>
		<a href="/dashboard/traces">轨迹中心</a>
		<a href="/dashboard/failures">失败分析</a>
		<a href="/dashboard/recipes">Recipe 控制台</a>
		<a href="/dashboard/accounts">账号门店</a>
	</nav>
	<h1>{escape(title)}</h1>
	{body}
</body>
</html>'''


def _table(headers: list[str], rows: str) -> str:
	head = ''.join(f'<th>{escape(header)}</th>' for header in headers)
	body = rows or f'<tr><td colspan="{len(headers)}">暂无数据</td></tr>'
	return f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def _table_row(*values: str) -> str:
	cells = ''.join(f'<td>{escape(value)}</td>' for value in values)
	return f'<tr>{cells}</tr>'


def _format_rate(rate: float | None) -> str:
	if rate is None:
		return '-'
	return f'{rate:.0%}'

