"""Local runner for exploring real merchant backends in prepare mode."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any, Callable, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from merchant_automation.accounts.manager import AccountManager
from merchant_automation.accounts.models import AccountStatus
from merchant_automation.config import get_config
from merchant_automation.operations.preflight import CommitPolicy
from merchant_automation.operations.recipe_store import RecipeStore
from merchant_automation.operations.router import ExecutionRouter
from merchant_automation.operations.schemas import ExecutionMode
from merchant_automation.operations.service import OperationPlanningService
from merchant_automation.operations.storage import OperationStore


class ExplorationRunError(RuntimeError):
	"""Raised when a local backend exploration cannot start or complete."""


class ExplorationRequest(BaseModel):
	model_config = ConfigDict(extra="forbid")

	instruction: str
	account_keyword: str
	platform: str = "meituan"
	mode: ExecutionMode = ExecutionMode.PREPARE
	db_path: str = "tasks.db"
	profiles_dir: str | None = None
	headless: bool = False
	keep_open: bool = False
	max_steps: int = Field(default=30, ge=1, le=100)
	start_url: str | None = None

	@field_validator("mode")
	@classmethod
	def _reject_commit_mode(cls, value: ExecutionMode) -> ExecutionMode:
		if value == ExecutionMode.COMMIT:
			raise ValueError("The local exploration runner does not allow commit mode")
		if value == ExecutionMode.PARSE_ONLY:
			raise ValueError("The local exploration runner must use dry_run or prepare mode")
		return value


class ExplorationResult(BaseModel):
	model_config = ConfigDict(extra="forbid")

	run_id: str
	trace_id: str
	status: str
	message: str | None = None
	account_id: str
	account_name: str
	recipe_id: str
	mode: ExecutionMode
	trace_steps: int


class BrowserSessionLike(Protocol):
	async def start(self) -> None:
		"""Start the browser session."""

	async def navigate_to(self, url: str) -> None:
		"""Navigate to a URL."""

	async def close(self) -> None:
		"""Close the browser session."""


BrowserSessionFactory = Callable[[Any], BrowserSessionLike]
LLMFactory = Callable[[], Any]
RouterFactory = Callable[[BrowserSessionLike, Any, OperationStore], Any]


async def run_exploration(
	request: ExplorationRequest,
	*,
	browser_session_factory: BrowserSessionFactory | None = None,
	llm_factory: LLMFactory | None = None,
	router_factory: RouterFactory | None = None,
) -> ExplorationResult:
	"""Run one real-backend Agent exploration with a saved account profile."""
	db_path = Path(request.db_path)
	account_manager = AccountManager(db_path=str(db_path), profiles_base_dir=request.profiles_dir)
	await account_manager.start()
	try:
		accounts = await account_manager.find_account_for_message(request.account_keyword, platform=request.platform)
		if not accounts:
			raise ExplorationRunError(
				f"No account found for platform={request.platform}, keyword={request.account_keyword}. "
				f"Log in first with: 登录 {request.platform} {request.account_keyword}"
			)

		account = accounts[0]
		if account.status != AccountStatus.ACTIVE:
			raise ExplorationRunError(
				f"Account {account.name} is not active. Current status={account.status.value}. "
				f"Log in first with: 登录 {request.platform} {account.name}"
			)

		store = OperationStore(db_path.parent / "merchant.db")
		store.initialize()

		recipe_store = RecipeStore(db_path.parent / "recipe.db")
		recipe_store.initialize()
		recipe_store.seed_default_definitions()

		planning_service = OperationPlanningService()
		planning = planning_service.plan_text(
			request.instruction,
			mode=request.mode,
			policy=CommitPolicy(),
		)
		run_id = store.save_planning_result(planning)
		if planning.input_issues or planning.plan_issues or planning.binding_issues or not planning.bound_tasks:
			reasons = [issue.reason for issue in planning.input_issues]
			reasons.extend(issue.reason for issue in planning.plan_issues)
			reasons.extend(issue.reason for issue in planning.binding_issues)
			raise ExplorationRunError("Planning failed: " + "; ".join(reasons or ["no bound tasks"]))

		bound_task = planning.bound_tasks[0]
		operation_task = bound_task.task.model_copy(update={"account_id": account.id})
		bound_task = bound_task.model_copy(update={"task": operation_task})

		profile = _build_browser_profile(account.profile_dir, headless=request.headless)
		session_factory = browser_session_factory or _default_browser_session_factory
		session = session_factory(profile)

		try:
			await session.start()
			await session.navigate_to(request.start_url or _merchant_home_url(request.platform))
			llm = (llm_factory or _default_llm_factory)()
			recipe_defs = {d.recipe_id: d for d in recipe_store.list_definitions()}
			router = (router_factory or _default_router_factory)(session, llm, store, recipe_defs, recipe_store)
			trace = await router.execute(bound_task, raw_input=request.instruction, max_steps=request.max_steps)
			trace_id = store.save_trace(trace, run_id=run_id)
			await account_manager.touch(account.id)

			return ExplorationResult(
				run_id=run_id,
				trace_id=trace_id,
				status=trace.outcome.status.value if trace.outcome else "unknown",
				message=trace.outcome.message if trace.outcome else None,
				account_id=account.id,
				account_name=account.name,
				recipe_id=bound_task.recipe.recipe_id,
				mode=bound_task.task.mode,
				trace_steps=len(trace.steps),
			)
		finally:
			if not request.keep_open:
				await session.close()
	finally:
		await account_manager.close()


def _build_browser_profile(profile_dir: str, *, headless: bool) -> Any:
	from browser_use.browser.profile import BrowserProfile

	return BrowserProfile(
		headless=headless,
		user_data_dir=profile_dir,
		window_size={"width": 1280, "height": 900},
	)


def _default_browser_session_factory(profile: Any) -> BrowserSessionLike:
	from browser_use import BrowserSession

	return BrowserSession(browser_profile=profile)


def _default_llm_factory() -> Any:
	from browser_use.llm.openai.chat import ChatOpenAI

	config = get_config()
	return ChatOpenAI(
		model=config.LLM_MODEL,
		base_url=config.LLM_BASE_URL,
		api_key=config.LLM_API_KEY,
	)


def _default_router_factory(
	browser_session: BrowserSessionLike,
	llm: Any,
	store: OperationStore,
	recipe_definitions: dict | None = None,
	recipe_store: RecipeStore | None = None,
) -> ExecutionRouter:
	return ExecutionRouter(
		browser_session=browser_session,
		llm=llm,
		store=store,
		recipe_definitions=recipe_definitions or {},
		recipe_store=recipe_store,
	)


def _merchant_home_url(platform: str) -> str:
	return {
		"meituan": "https://e.waimai.meituan.com/",
		"eleme": "https://shop.ele.me/",
		"douyin": "https://life.douyin.com/",
	}.get(platform, "https://e.waimai.meituan.com/")


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(description="Explore a real merchant backend with Agent in dry_run/prepare mode.")
	parser.add_argument("--instruction", required=True, help="Natural language operation instruction.")
	parser.add_argument("--account", required=True, dest="account_keyword", help="Account/store keyword to reuse profile.")
	parser.add_argument("--platform", default="meituan", choices=["meituan", "eleme", "douyin"])
	parser.add_argument("--mode", default="prepare", choices=["dry_run", "prepare"])
	parser.add_argument("--db-path", default="tasks.db")
	parser.add_argument("--profiles-dir", default=None)
	parser.add_argument("--headless", action="store_true")
	parser.add_argument("--keep-open", action="store_true")
	parser.add_argument("--max-steps", default=30, type=int)
	parser.add_argument("--start-url", default=None)
	args = parser.parse_args(argv)

	request = ExplorationRequest(
		instruction=args.instruction,
		account_keyword=args.account_keyword,
		platform=args.platform,
		mode=ExecutionMode(args.mode),
		db_path=args.db_path,
		profiles_dir=args.profiles_dir,
		headless=args.headless,
		keep_open=args.keep_open,
		max_steps=args.max_steps,
		start_url=args.start_url,
	)

	try:
		result = asyncio.run(run_exploration(request))
	except Exception as exc:
		print(json.dumps({"status": "failed", "message": str(exc)}, ensure_ascii=False))
		return 1

	print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
