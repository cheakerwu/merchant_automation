# PRD:Recipe 确定性执行飞轮(Agent 探索自动生成)

- 文档版本:v1.0
- 日期:2026-06-07
- 状态:待评审
- 关联代码:`src/merchant_automation/operations/*`、`server.py`、`explore.py`、`dashboard/routes.py`

---

## 1. 背景与问题

`merchant_automation` 通过飞书机器人接收自然语言指令(如「把美团 江湖饭焗 电话改成 138…」),驱动浏览器在美团/饿了么/抖音商家后台完成操作。架构上设计了**三层执行模型**:

| 层 | 组件 | 定位 |
|---|---|---|
| 契约 | `OperationContract` | 操作的成功标准/禁止行为 |
| 治理 | `RecipeMetadata` + `preflight` | 状态机 + 成功率门控 commit |
| 执行 | `RecipeStepExecutor`(确定性) / `AgentExplorer`(LLM 兜底) | 真正驱动浏览器 |

**核心问题(P0):确定性执行层从未上线。**

- `server.py:224` 与 `explore.py:190` 硬编码 `recipe_defs = {}`,导致 `ExecutionRouter` 的「层 1」(`router.py:55`)永远不命中。
- `RecipeStore` 只持久化 `RecipeMetadata`(状态/成功率),从不持久化 `RecipeDefinition`(可执行步骤)——两者按 `recipe_id` 对齐但中间**没有桥**。
- 结果:**每个任务都从零跑一遍 `browser_use.Agent`(LLM + 视觉)**,慢、贵、不确定;`RecipeStatus`、`success_rates` 永远停在 `recipes.py` 的硬编码种子值;没有任何「学习」闭环把成功经验沉淀下来。

设计意图最值钱的那一半(确定性回放 + 自我沉淀)是空的。本 PRD 定义如何补上它。

### 需求决策(本轮关键变更)

**Recipe 步骤的来源 = Agent 探索自动生成,而非人工录入。**

人只负责**审核与晋级**(把 candidate 升为 commit_ready 才允许真实提交),不负责手写步骤。

---

## 2. 目标与非目标

### 2.1 目标(本期)

- **G1 持久化**:`RecipeDefinition`(步骤)可存可取,与 `RecipeMetadata` 同 `recipe_id` 对齐。
- **G2 自动生成**:一次成功的 Agent 探索后,自动把其浏览器动作历史合成为一份 `candidate` Recipe(语义步骤)。
- **G3 确定性回放**:存在可用步骤定义时,后续同类任务走 `RecipeStepExecutor`(确定性),不再调用 Agent;失败自动降级回 Agent(自愈)。
- **G4 人审晋级**:Dashboard 可查看自动生成的步骤、来源、成功率,并将状态 `candidate → prepare_ready → commit_ready`;commit 仍由 `preflight` 按状态+成功率门控。
- **G5 安全不回退**:全程不破坏现有「默认不 commit、prepare 停在提交前」的安全模型。

### 2.2 非目标(本期不做)

- 不替换正则意图解析为 LLM(单独议题)。
- 不拆分 `server.py`、不做 DI 重构。
- 不做飞书「确认提交」COMMIT 卡片(后续期)。
- 不做多租户、Dashboard 鉴权(产品化期)。
- 不做选择器(CSS/XPath)硬缓存——本期仍用语义 target + 运行时定位。

---

## 3. 用户与场景

### 3.1 用户角色

| 角色 | 描述 | 关心 |
|---|---|---|
| 运营专员(10 人小团队) | 飞书发指令改门店信息 | 快、稳、改对 |
| 运营负责人 / 技术接口人 | 在 Dashboard 审核晋级 Recipe | 哪些操作可信、能否放开 commit |
| 系统维护者 | 关注成本与可靠性 | LLM 调用量、成功率、可回放性 |

### 3.2 核心场景

1. **冷启动(无 Recipe)**:专员发「改电话」→ 系统无步骤定义 → Agent 探索完成(prepare 停在提交前)→ 自动合成 candidate Recipe → 回执成功。
2. **热路径(有 Recipe)**:另一专员发同类「改电话」(不同门店)→ 命中 candidate 步骤 → `RecipeStepExecutor` 确定性回放(参数化替换门店/电话)→ 快速完成,不调用 Agent。
3. **自愈**:后台改版导致回放失败 → 自动降级 Agent 重新探索 → 刷新 candidate 步骤。
4. **晋级**:负责人在 Dashboard 审核某 candidate 的步骤,确认无误 → 升为 `prepare_ready`;经数次验证后升 `commit_ready`,从此该操作允许真实提交(仍受 `CommitPolicy` 总开关约束)。

---

## 4. 功能需求

### FR-1 RecipeDefinition 持久化
- `RecipeStore` 新增独立表 `recipe_definitions`(不改动现有 `recipes` 表)。
- 提供 `save_definition`(upsert)、`get_definition(recipe_id)`、`list_definitions()`。
- 步骤模型复用现有 `RecipeDefinition`/`RecipeStep`(`operations/recipe_definition.py`,已存在),不新造结构。

### FR-2 步骤加载入执行链
- `server.py`(`MerchantTaskExecutor`)与 `explore.py`(本地 runner)在构造 `ExecutionRouter` 时,从 `RecipeStore` 加载步骤定义填入 `recipe_definitions`,替换 `{}`。
- 命中条件沿用 `router.py:55`:`recipe_def 有 steps 且最近无失败` → 走层 1。

### FR-3 Agent 动作历史 → Recipe 合成(本期核心)
- 新增**合成器**:输入 `browser_use` 的 `AgentHistoryList` + 操作参数 + `recipe_id`,输出 `RecipeDefinition`。
- 动作映射(键来自 `AgentHistoryList.model_actions()`,每项附带 `interacted_element`):

  | browser_use 动作 | RecipeStepAction | target 来源 | value 来源 |
  |---|---|---|---|
  | `navigate` | `NAVIGATE` | — | `url` |
  | `click` | `CLICK` | `interacted_element.ax_name` → attributes(aria-label/placeholder/name)→ node_name | — |
  | `input` | `FILL` | 同上 | `text`(命中入参值则参数化为 `{key}`) |
  | `upload_file` | `UPLOAD` | 同上 | `path`(参数化) |
  | `search`/`scroll`/`done`/extract 等 | 跳过 | — | — |

- **语义 target**:不存 browser_use 的临时 `index`(每次渲染都会变),改存可见文本/标签;回放时 `RecipeStepExecutor._find_element` 用语义 target + LLM/文本匹配重新定位(已实现)。
- **参数化**:`input.text`/`upload.path` 与入参值精确匹配时替换为 `{param_key}`,使 Recipe 可跨门店/取值复用。
- **安全收尾**:合成的步骤末尾追加 `STOP_BEFORE_SUBMIT`,与 prepare 语义一致。
- 仅当 Agent 本次探索**成功**时合成(`history.is_successful()` / trace outcome=SUCCESS)。

### FR-4 飞轮闭环(Router 编排)
- `ExecutionRouter` 持有可选 `RecipeStore`。当走层 2(Agent)且**成功**时:
  - 若该 `recipe_id` **无定义** 或 现有 `RecipeMetadata.status == candidate`(未经人审)→ 合成并 `save_definition`,并保证 `RecipeMetadata` 存在且为 `candidate`。
  - **绝不覆盖**已晋级(`prepare_ready` 及以上)的人审 Recipe。
- 下一次同类任务即可命中层 1。形成:首跑 Agent(慢)→ 沉淀 candidate → 后续确定性回放(快)。

### FR-5 Dashboard 审核与晋级
- Recipe 列表:增加「步骤数」「来源(auto/manual)」列,便于判断可否晋级。
- Recipe 详情:展示 `entry_url` + 步骤表(action/target/value)+ 当前状态;保留状态切换表单(已实现 `recipe_status_toggle`)实现晋级/禁用。
- (可选)提供步骤 JSON 只读查看 + 纠错编辑入口,供人工微调自动生成的步骤。
- commit 门控不变:`preflight.evaluate_preflight` 已要求 `status == COMMIT_READY` 且成功率达标,本期不改其逻辑。

---

## 5. 架构与数据流

### 5.1 执行链(目标态)

```
飞书文本
  → OperationPlanningService(parser→planner→binder→preflight)
  → BoundOperationTask
  → ExecutionRouter.execute
      ├─ 层1 命中(有 steps & 近期无失败): RecipeStepExecutor 确定性回放  ← 新增加载
      │       └─ 失败 → 降级 ─┐
      └─ 层2 AgentExplorer(LLM 探索) ←───────────┘
              └─ 成功 → [合成器] AgentHistoryList → RecipeDefinition(candidate) → RecipeStore.save_definition  ← 新增闭环
  → ExecutionTrace 持久化(OperationStore)
  → 飞书回执 / Dashboard 可见
```

### 5.2 数据模型(新增)

`recipe_definitions` 表(SQLite,`recipe.db`):

| 字段 | 类型 | 说明 |
|---|---|---|
| recipe_id | TEXT PK | 与 `recipes` 表/`RecipeMetadata` 对齐 |
| payload_json | TEXT | `RecipeDefinition` 的 JSON |
| source | TEXT | `auto`(合成)/ `manual`(人工纠错) |
| created_at | TEXT | ISO8601 |
| updated_at | TEXT | ISO8601 |

> `RecipeMetadata`(治理:status/success_rates)仍在 `recipes` 表;两表按 `recipe_id` 一对一。

### 5.3 关键外部依赖事实(已核实 `browser-use-main` 源码)

- `agent.run(...)` 返回 `AgentHistoryList`(`agent/service.py:2489,2641`)。
- `AgentHistoryList.model_actions()`(`agent/views.py:823`)返回每个动作 `{action_name:{params}, 'interacted_element': DOMInteractedElement|None}`。
- `DOMInteractedElement`(`dom/views.py:976`)含 `ax_name`(可见文本)、`attributes`、`node_name`、`x_path` —— 足以生成语义 target。
- 动作名:`navigate`/`click`/`input`/`upload_file`/`search`/`done`(`tools/service.py`)。
- 佐证:库内 `save_as_playwright_script` / `PlaywrightScriptGenerator`(已注释)证明历史本就含可回放信息。

> 风险:browser_use 未锁版本,history schema 跨版本可能变。合成器须对缺失字段健壮(降级跳过该步),并集中在单一模块以便适配。

---

## 6. 里程碑

| 阶段 | 内容 | 产出 |
|---|---|---|
| M1 持久化 | FR-1 + FR-2 | RecipeStepExecutor 可被真实加载触发(本地 HTTPServer 验证) |
| M2 合成器 | FR-3(纯函数,离线用 fixture 历史驱动) | AgentHistory→RecipeDefinition |
| M3 闭环 | FR-4 Router 编排 + server/explore 接线 | 首跑沉淀、二跑命中 |
| M4 Dashboard | FR-5 审核晋级可见性 | 步骤数/来源/详情/晋级 |

---

## 7. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| browser_use history schema 跨版本变动 | 合成器失效 | 合成器单模块隔离 + 字段缺失健壮降级 + 单测用固定 fixture |
| 自动步骤含探索噪声(误点/滚动) | 回放脆弱 | 仅取 navigate/click/input/upload;candidate 必经人审才放 commit;回放失败自动降级 Agent |
| `router._count_recent_failures`(`router.py:91`)按 recipe_id 任意历史失败即跳过层 1 | 刚沉淀的 Recipe 被旧失败永久旁路 | 标注为已知缺陷;计划文档列入「按时间窗口/版本计数」修正 |
| 真实美团 target/entry_url 无法离线核实 | 端到端不可离线证 | 用本地 HTTPServer 证明机器可跑通(同 `test_recipe_executor.py`);真实后台由灰度验证 |
| 语义 target 在不同门店后台细微差异 | 定位失败 | `_find_element` 已有 LLM + 文本兜底;失败降级 Agent 重探 |

---

## 8. 成功指标(上线后观测)

- **LLM 调用下降**:高频操作命中层 1 的比例 ≥ 70%(沉淀后)。
- **时延下降**:命中层 1 的任务平均耗时显著低于 Agent 路径。
- **沉淀率**:成功 Agent 探索生成 candidate 的比例 ≥ 95%。
- **可靠性**:层 1 回放成功率 ≥ 90%;失败均能自动降级,无任务因此卡死。

---

## 9. 验收标准(DoD)

- `pytest` 全绿(现 28 个测试文件 + 新增三层用例)。
- 存在步骤定义时,`ExecutionRouter` 走层 1(单测断言,无需真实浏览器)。
- 成功 Agent 探索后,`RecipeStore` 出现对应 `candidate` 定义(合成器 + 闭环单测)。
- 已晋级 Recipe 不被自动合成覆盖(单测)。
- Dashboard 展示步骤数/来源,并可切换状态完成晋级(TestClient 用例)。
- 安全模型不变:无 `commit_ready` + 总开关关闭时,绝不真实提交(沿用 `preflight` 用例)。

---

## 10. 开放问题

1. candidate 自动晋级到 `prepare_ready` 是否要「连续 N 次回放成功」自动化?(本期人审,自动晋级列为后续)
2. 合成噪声是否需要一个「回放验证」二次确认步骤再落库?(本期靠人审,后续可加)
3. 多门店语义 target 差异是否需要按 `platform` 维度多版本 Recipe?(`RecipeMetadata.version` 已预留)
