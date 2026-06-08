# 实施计划:Recipe 确定性执行飞轮(Agent 探索自动生成)

- 文档版本:v1.0 / 2026-06-07
- 关联 PRD:`docs/PRD-recipe-flywheel.md`
- 状态:**待开发**(本文件仅为计划,本轮不执行编码)
- 方法论:严格 TDD(先红后绿),遵循仓库现有 `tmp_path` + DI + `pytest.mark.asyncio` 约定

---

## 0. 一句话目标

补上「持久化 + 加载 + Agent 历史合成 + 闭环编排 + 人审晋级」,让死掉的确定性路径 `RecipeStepExecutor` 真正上线,并由 Agent 探索自动沉淀 Recipe。

---

## 1. 现状锚点(已核实)

- 断点:`server.py:224`、`explore.py:190` 的 `recipe_defs = {}`。
- 路由:`router.py:38-89`,层 1 命中条件 `recipe_def and recipe_def.steps and recent_failures == 0`。
- 执行器:`executor.py` `RecipeStepExecutor`(语义 target + `_find_element` LLM/文本兜底,已实现)。
- 探索器:`explorer.py` `AgentExplorer.explore()` 现仅记录 url/title,**丢弃** `agent.run()` 返回的 `AgentHistoryList`。
- 存储:`recipe_store.py` 仅存 `RecipeMetadata`;`storage.py` `OperationStore` 存 trace。
- browser_use 事实:`agent.run()→AgentHistoryList`;`.model_actions()` 含 `interacted_element(ax_name/attributes/node_name/x_path)`;动作名 `navigate/click/input/upload_file/done`。

---

## 2. 分阶段任务

### 阶段 M1 — RecipeDefinition 持久化

**测试先行** `tests/test_recipe_store.py`(扩展):
- `test_initialize_creates_recipe_definitions_table`
- `test_save_and_get_definition_roundtrip`(steps 完整、source 默认 `auto`)
- `test_save_definition_upsert_overwrites`
- `test_get_definition_returns_none_when_missing`
- `test_list_definitions_returns_all`

**实现** `src/merchant_automation/operations/recipe_store.py`:
- `initialize()` 增 `CREATE TABLE IF NOT EXISTS recipe_definitions(recipe_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'auto', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)`。
- `save_definition(definition: RecipeDefinition, *, source: str = 'auto') -> None`(`INSERT ... ON CONFLICT(recipe_id) DO UPDATE`,保留 created_at)。
- `get_definition(recipe_id) -> RecipeDefinition | None`。
- `list_definitions() -> list[RecipeDefinition]`。
- import `RecipeDefinition`(来自 `operations.recipe_definition`)。

### 阶段 M2 — Agent 历史合成器(纯函数,易测)

**测试先行** `tests/test_recipe_synthesizer.py`(新):用**伪造的 history 对象**(轻量 stub,模拟 `model_actions()` 返回 list[dict],元素带 `ax_name`/`attributes`)驱动,无需 browser_use:
- `test_navigate_maps_to_navigate_step`
- `test_click_uses_ax_name_as_target`
- `test_input_parameterizes_matching_param_value`(text=门店电话 → `{phone}`)
- `test_upload_file_maps_to_upload_step`
- `test_search_scroll_done_are_skipped`
- `test_appends_stop_before_submit`
- `test_missing_interacted_element_is_skipped_gracefully`(schema 健壮性)
- `test_target_fallback_order`(ax_name→aria-label→placeholder→name→node_name)

**实现** `src/merchant_automation/operations/synthesizer.py`(新):
```
def synthesize_recipe_definition(
    history,                       # AgentHistoryList(鸭子类型: .model_actions())
    *, recipe_id: str,
    params: dict[str, object],
    entry_url: str | None = None,
) -> RecipeDefinition
```
- 遍历 `history.model_actions()`;按 §PRD 动作映射表生成 `RecipeStep`。
- `_semantic_target(interacted_element) -> str`:ax_name → attributes[aria-label/placeholder/name] → node_name。
- `_parameterize(value, params) -> str`:精确匹配入参值则替换 `{key}`。
- 末尾追加 `RecipeStep(action=STOP_BEFORE_SUBMIT)`。
- 仅在调用方确认成功后调用(合成器本身不判断成功)。
- 对缺字段/未知动作:跳过该步,不抛异常(跨版本健壮)。

### 阶段 M3 — 闭环编排 + 接线

**测试先行**
- `tests/test_execution_router.py`(扩展):
  - `test_router_uses_step_executor_when_definition_present`:注入带 steps 的 `recipe_definitions` + 替换 `router._step_executor` 为 fake,断言层 1 被调用。
  - `test_router_synthesizes_candidate_after_successful_agent`:无定义 + explorer 返回成功(其 `last_history` 为 stub)+ 注入 `RecipeStore` → 断言 `save_definition` 被调用且 metadata=candidate。
  - `test_router_does_not_overwrite_promoted_recipe`:status=prepare_ready 时不合成覆盖。
  - `test_router_falls_back_to_agent_when_no_definition`(回归)。
- `tests/test_real_backend_explore_runner.py`(扩展):`list_definitions()` 构建的 defs 正确进入默认 router 路径(helper 单测)。

**实现**
- `explorer.py`:`explore()` 内 `self.last_history = history`(保留 `agent.run()` 返回值);签名仍返回 `ExecutionTrace`(不破坏既有调用/测试)。
- `router.py`:
  - `__init__` 增 `recipe_store: RecipeStore | None = None`。
  - 层 2 成功后:`if self._recipe_store and outcome==SUCCESS:` → 取 `self._explorer.last_history` → 守卫(无定义或 status==candidate)→ `synthesize_recipe_definition(...)` → `save_definition(source='auto')` + 确保 `upsert_recipe` 存在 candidate metadata。
  - 抽 `_maybe_synthesize_recipe(...)` 私有方法便于单测。
- `server.py`:`_execute_bound_task` 用 `self._recipe_store.get_definition(bound_task.recipe.recipe_id)` 构建 recipe_defs;构造 `ExecutionRouter(..., recipe_store=self._recipe_store)`;替换 `{} # TODO`;import `RecipeDefinition`。
- `explore.py`:`run_exploration` 建 `RecipeStore(db_path.parent/'recipe.db').initialize()`;`recipe_defs={d.recipe_id:d for d in list_definitions()}`;默认 `_default_router_factory` 增第 4 参 `recipe_definitions`(默认 `{}`)并传 `recipe_store`;注入式 `router_factory` 保持 3 参(测试用)。

### 阶段 M4 — Dashboard 审核与晋级

**测试先行** `tests/test_dashboard_routes.py`(扩展,沿用 `TestClient`):
- `test_recipe_list_shows_step_count_and_source`
- `test_recipe_detail_renders_synthesized_steps`
- `test_recipe_status_promotion_via_form`(candidate→prepare_ready,沿用已存在的 `recipe_status_toggle`)
- (可选)`test_recipe_definition_manual_edit_saves`(JSON 纠错入口)

**实现** `dashboard/routes.py`:
- `recipe_list`:用 `list_definitions()` 建 `{recipe_id: (len(steps), source)}`,加「步骤数」「来源」列。
- `recipe_detail`:展示 `entry_url` + 步骤表(action/target/value);保留状态切换表单。
- (可选)`POST /recipes/{id}/definition`:`json.loads`→ 强制 `recipe_id`→ `RecipeDefinition.model_validate`→ `save_definition(source='manual')`;异常重定向 `?error=1`。imports:`json`、`RecipeDefinition`、`pydantic.ValidationError`。

---

## 3. 文件改动清单

| 文件 | 改动 | 阶段 |
|---|---|---|
| `operations/recipe_store.py` | +表 +save/get/list_definition | M1 |
| `operations/synthesizer.py`(新) | 历史→RecipeDefinition | M2 |
| `operations/explorer.py` | 保留 `last_history` | M3 |
| `operations/router.py` | +recipe_store +合成闭环 | M3 |
| `server.py` | 加载 defs + 接 recipe_store | M3 |
| `explore.py` | 加载 defs + recipe_store | M3 |
| `dashboard/routes.py` | 步骤数/来源/详情/(可选编辑) | M4 |
| `tests/test_recipe_store.py` | +定义持久化用例 | M1 |
| `tests/test_recipe_synthesizer.py`(新) | 合成器用例 | M2 |
| `tests/test_execution_router.py` | +层1命中/合成闭环/不覆盖 | M3 |
| `tests/test_real_backend_explore_runner.py` | +defs 加载 | M3 |
| `tests/test_dashboard_routes.py` | +审核晋级 UI | M4 |

> 不改:`recipes` 表结构、`preflight` commit 门控逻辑、`schemas.py`、`binder.py`、`parser.py`。

---

## 4. 动作映射表(合成器实现依据)

| browser_use(`model_actions()` 键) | params | → RecipeStepAction | target | value |
|---|---|---|---|---|
| `navigate` | `{url}` | NAVIGATE | — | url |
| `click` | `{index}` | CLICK | interacted_element 语义 | — |
| `input` | `{index, text}` | FILL | 同上 | `_parameterize(text)` |
| `upload_file` | `{path}` | UPLOAD | 同上 | `_parameterize(path)` |
| `search`/`scroll`/`done`/`extract_*` | — | 跳过 | — | — |
| 末尾追加 | — | STOP_BEFORE_SUBMIT | — | — |

target 兜底顺序:`ax_name` → `attributes.aria-label` → `attributes.placeholder` → `attributes.name` → `node_name`。

---

## 5. 验证方式

- **单元/集成**:`pytest`(全绿;新增覆盖 M1-M4 四层)。
- **确定性回放端到端**:`tests/test_recipe_executor.py` 既有本地 `HTTPServer` 模式扩展一例——存定义→经 router 加载→层 1 在本地页面跑通(证明机器闭环,不依赖真实美团)。
- **真实后台**:`merchant-explore` CLI 灰度(prepare 模式)人工观测,不纳入 CI。
- 覆盖率目标 ≥ 80%(仓库规则)。

---

## 6. 回滚

- 各阶段独立提交(feat: M1…M4)。
- 出问题回滚到「`recipe_defs = {}`」等价行为:`get_definition` 恒返回空 / router 不传 recipe_store,即退回纯 Agent 现状,无数据迁移负担(新表独立)。

---

## 7. 已知缺陷(随本期一并标注,择机修)

- `router._count_recent_failures`(`router.py:91`):按 `recipe_id` 统计**全部历史**失败,任一历史失败即永久跳过层 1,会架空刚沉淀的 Recipe。建议改为「按 recipe 版本 / 时间窗口」计数,或仅计 `updated_at` 之后的失败。**本期不改,列为紧邻后续项。**
- 合成步骤噪声:本期靠人审 + 回放失败降级兜底;后续可加「回放验证后再落库」。

---

## 8. 后续路线(本期外)

1. candidate 连续 N 次回放成功 → 自动晋级 prepare_ready。
2. 飞书「确认提交」卡片解锁高频操作 COMMIT(按门店灰度)。
3. 正则意图解析 → LLM 结构化输出。
4. `server.py` 拆分 + DI;多租户 + Dashboard 鉴权(产品化)。
5. 选择器缓存,让层 1 热路径彻底脱离 LLM(成本护城河)。
