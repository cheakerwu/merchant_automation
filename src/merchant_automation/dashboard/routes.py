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

		# Build definition info map: recipe_id -> (step_count, source)
		defn_info: dict[str, tuple[int, str]] = {}
		for defn in recipe_store.list_definitions():
			defn_info[defn.recipe_id] = (len(defn.steps), 'auto')

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
				str(defn_info.get(summary.recipe_id, (0, '-'))[0]) if summary.recipe_id in defn_info else '-',
				defn_info.get(summary.recipe_id, (0, '-'))[1],
			)
			for summary in recipe_store.list_recipes()
		)
		return HTMLResponse(
			_page(
				'Recipe 控制台',
				_table(
					['Recipe ID', 'Operation', '平台', '版本', '状态', 'prepare 成功率', 'commit 成功率', '允许 Mode', '步骤数', '来源'],
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

		# Definition section
		defn_section = ''
		defn = recipe_store.get_definition(recipe_id)
		if defn:
			# Entry URL
			entry_url_html = f'<p><strong>入口 URL:</strong> {escape(defn.entry_url or "-")}</p>' if defn.entry_url else ''

			# Steps table
			step_rows = ''.join(
				_table_row(
					escape(step.action.value),
					escape(step.target or '-'),
					escape(step.value or '-'),
					escape(step.url or '-'),
				)
				for step in defn.steps
			)
			steps_table = _table(['操作', '目标', '值', 'URL'], step_rows)
			defn_section = f'<h2>执行步骤</h2>{entry_url_html}{steps_table}'

		return HTMLResponse(
			_page(
				f'Recipe: {recipe.recipe_id}',
				detail_table + '<h2>成功率</h2>' + success_table + defn_section + status_form,
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
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title>{escape(title)}</title>
	<style>
		* {{ margin: 0; padding: 0; box-sizing: border-box; }}
		body {{
			font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Microsoft YaHei", sans-serif;
			background: #f8fafc;
			color: #1e293b;
			line-height: 1.6;
		}}
		.container {{ max-width: 1200px; margin: 0 auto; padding: 0 24px; }}
		nav {{
			background: #ffffff;
			border-bottom: 1px solid #e2e8f0;
			padding: 16px 0;
			margin-bottom: 32px;
			box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
		}}
		nav .container {{ display: flex; align-items: center; gap: 32px; }}
		nav .logo {{ font-size: 20px; font-weight: 700; color: #0f172a; text-decoration: none; }}
		nav a {{
			color: #64748b;
			text-decoration: none;
			font-size: 14px;
			font-weight: 500;
			padding: 8px 12px;
			border-radius: 6px;
			transition: all 0.2s;
		}}
		nav a:hover {{ background: #f1f5f9; color: #0f172a; }}
		nav a.active {{ background: #0f172a; color: #ffffff; }}
		h1 {{
			font-size: 28px;
			font-weight: 700;
			color: #0f172a;
			margin-bottom: 24px;
		}}
		.card {{
			background: #ffffff;
			border-radius: 12px;
			box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
			padding: 24px;
			margin-bottom: 24px;
		}}
		table {{ border-collapse: collapse; width: 100%; }}
		th, td {{ padding: 12px 16px; text-align: left; border-bottom: 1px solid #f1f5f9; }}
		th {{
			background: #f8fafc;
			font-weight: 600;
			color: #475569;
			font-size: 13px;
			text-transform: uppercase;
			letter-spacing: 0.05em;
		}}
		tr:hover {{ background: #f8fafc; }}
		.badge {{
			display: inline-block;
			padding: 4px 10px;
			border-radius: 20px;
			font-size: 12px;
			font-weight: 600;
		}}
		.badge-success {{ background: #dcfce7; color: #166534; }}
		.badge-warning {{ background: #fef3c7; color: #92400e; }}
		.badge-danger {{ background: #fee2e2; color: #991b1b; }}
		.badge-info {{ background: #dbeafe; color: #1e40af; }}
		.btn {{
			display: inline-block;
			padding: 8px 16px;
			border-radius: 6px;
			font-size: 14px;
			font-weight: 500;
			text-decoration: none;
			cursor: pointer;
			border: none;
			transition: all 0.2s;
		}}
		.btn-primary {{ background: #0f172a; color: #ffffff; }}
		.btn-primary:hover {{ background: #1e293b; }}
		.btn-secondary {{ background: #f1f5f9; color: #475569; }}
		.btn-secondary:hover {{ background: #e2e8f0; }}
		.empty-state {{
			text-align: center;
			padding: 48px 24px;
			color: #94a3b8;
		}}
		.empty-state svg {{ margin-bottom: 16px; }}
	</style>
</head>
<body>
	<nav>
		<div class="container">
			<a href="/dashboard" class="logo">🤖 商家助手</a>
			<a href="/dashboard" class="{'active' if title == '任务中心' else ''}">任务中心</a>
			<a href="/dashboard/traces" class="{'active' if title == '轨迹中心' else ''}">轨迹中心</a>
			<a href="/dashboard/failures" class="{'active' if title == '失败分析' else ''}">失败分析</a>
			<a href="/dashboard/recipes" class="{'active' if title == 'Recipe 控制台' else ''}">Recipe 控制台</a>
			<a href="/dashboard/accounts" class="{'active' if '账号' in title or '门店' in title else ''}">账号门店</a>
		</div>
	</nav>
	<div class="container">
		<h1>{escape(title)}</h1>
		<div class="card">
			{body}
		</div>
	</div>
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

