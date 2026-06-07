# Merchant Automation

外卖商家后台自动化系统 — 基于 Operation + Recipe 架构，支持多平台、多店铺的标准后台操作自动化。

## 架构概览

```
用户输入 (自然语言/表格)
    → 解析 (OperationParser / JobPlanner)
    → 绑定 (JobPlanBinder + Preflight 检查)
    → 执行 (RecipeStepExecutor / AgentExplorer)
    → 追踪 (TraceRecorder)
    → 存储 (OperationStore / RecipeStore / AccountStore)
    → 展示 (FastAPI Dashboard)
```

## 核心模块

### operations/ — 规划与执行管道

| 模块 | 职责 |
|------|------|
| `schemas.py` | 核心类型定义 (ExecutionMode, RecipeStatus, FailureType, OperationTask, JobPlan) |
| `catalog.py` | Operation 注册表 — 定义每个操作的参数、成功标准、禁止行为 |
| `recipes.py` | Recipe 注册表 — 按平台+操作查找执行配方 |
| `recipe_definition.py` | Recipe 步骤定义 (RecipeStep, RecipeDefinition) |
| `recipe_store.py` | Recipe 持久化 (SQLite) |
| `parser.py` | 自然语言 → OperationTask |
| `planner.py` | 表格行 → JobPlan |
| `service.py` | 规划编排 (OperationPlanningService) |
| `binder.py` | Recipe 绑定 + Preflight 检查 |
| `preflight.py` | 提交前安全检查 (6 项) |
| `executor.py` | RecipeStepExecutor — 按步骤执行 Recipe |
| `explorer.py` | AgentExplorer — browser_use.Agent 探索封装 |
| `router.py` | ExecutionRouter — 分层执行入口 |
| `traces.py` | 执行轨迹录制 |
| `failure.py` | 失败归因 + Recipe 过期检测 |
| `storage.py` | OperationStore (SQLite 持久化) |

### accounts/ — 账号与门店管理

| 模块 | 职责 |
|------|------|
| `models.py` | PlatformAccount, Store, LoginStatus 模型 |
| `store.py` | AccountStore (SQLite 持久化) |

### dashboard/ — 管理后台

| 路由 | 功能 |
|------|------|
| `GET /dashboard` | 任务中心 |
| `GET /dashboard/traces` | 轨迹中心 |
| `GET /dashboard/failures` | 失败分析 |
| `GET /dashboard/recipes` | Recipe 控制台 |
| `GET /dashboard/recipes/{id}` | Recipe 详情 + 状态切换 |
| `GET /dashboard/accounts` | 账号列表 |
| `GET /dashboard/accounts/{id}` | 账号详情 + 绑定门店 |
| `GET /dashboard/stores` | 门店列表 |

## 执行策略

分层执行，逐级降级：

1. **Recipe 步骤执行** — 有具体步骤 + 最近没失败 → 按步骤驱动浏览器
2. **LLM 辅助定位** — Recipe 步骤里的语义描述找不到元素时 → LLM 在 DOM 里匹配
3. **Agent 探索** — 没有步骤 / 步骤失败 → browser_use.Agent 自由探索
4. **人工介入** — Agent 也搞不定 → 通知飞书

## 快速开始

```bash
# 安装依赖
pip install pydantic fastapi uvicorn

# 运行测试
PYTHONPATH=src pytest tests -v

# 编译检查
python -m compileall -q src tests
```

## 项目结构

```
merchant_automation/
├── src/
│   └── merchant_automation/
│       ├── operations/      # 规划与执行管道
│       ├── accounts/        # 账号门店管理
│       └── dashboard/       # 管理后台
├── tests/                   # 测试 (106 个)
└── pyproject.toml
```

## 技术栈

- Python 3.11+
- Pydantic v2 — 数据模型
- FastAPI — Dashboard
- SQLite — 持久化
- browser_use — 浏览器自动化 (Agent + BrowserSession)
