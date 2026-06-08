# Merchant Automation

外卖商家后台自动化系统 — 基于 Operation + Recipe 架构，支持多平台、多店铺的标准后台操作自动化。

## Mac 部署指南

### 1. 环境要求

- Python 3.11+
- Conda 或 venv（推荐 Conda）
- Chrome 浏览器（用于 browser_use 自动化）

### 2. 克隆项目

```bash
git clone <repository-url>
cd merchant_automation
```

### 3. 创建 Python 环境

**使用 Conda（推荐）：**

```bash
# 创建独立环境
conda create -n merchant_automation python=3.11 -y

# 激活环境
conda activate merchant_automation
```

**使用 venv：**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 4. 安装依赖

```bash
# 安装项目及所有依赖（editable 模式）
pip install -e .

# 安装测试依赖
pip install pytest pytest-asyncio pytest-httpserver
```

### 5. 配置环境变量

```bash
# 复制示例配置
cp .env.example .env

# 编辑 .env 文件，填入必要配置
nano .env
```

**必需配置项：**

```env
# LLM 配置（用于 Agent 探索）
LLM_MODEL=gpt-4o
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-your-api-key-here

# 浏览器配置
BROWSER_HEADLESS=false
BROWSER_USER_DATA_DIR=./profiles

# 飞书机器人（可选，用于接收指令）
FEISHU_APP_ID=
FEISHU_APP_SECRET=
```

### 6. 初始化数据库

```bash
# 数据库会在首次运行时自动创建
# 包括：merchant.db, recipe.db, tasks.db, account.db
```

### 7. 运行测试

```bash
# 运行全部测试
pytest tests/ -v

# 运行特定测试
pytest tests/test_recipe_store.py -v

# 查看测试覆盖率
pytest tests/ --cov=src --cov-report=term-missing
```

### 8. 启动服务

**启动 Dashboard（管理后台）：**

```bash
# 启动 FastAPI Dashboard
uvicorn merchant_automation.server:app --reload --host 0.0.0.0 --port 8000

# 访问 http://localhost:8000/dashboard
```

**启动飞书机器人（可选）：**

```bash
# 启动飞书消息接收服务
python -m merchant_automation.server
```

**本地探索模式（测试用）：**

```bash
# 使用 merchant-explore CLI 探索商家后台
merchant-explore --instruction "把美团 江湖饭焗 电话改成 13800138000" \
                 --account "江湖饭焗" \
                 --platform meituan \
                 --mode prepare
```

### 9. 目录结构

```
merchant_automation/
├── src/
│   └── merchant_automation/
│       ├── operations/      # 规划与执行管道
│       ├── accounts/        # 账号门店管理
│       └── dashboard/       # 管理后台
├── tests/                   # 测试套件
├── docs/                    # PRD 和 PLAN 文档
├── profiles/                # 浏览器用户数据（自动生成）
├── .env                     # 环境变量配置
├── pyproject.toml           # 项目配置
└── README.md
```

### 10. 常见问题

**Q: 浏览器启动失败？**

```bash
# 确保 Chrome 已安装
# 检查 Chrome 版本
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --version

# 如果使用 headless 模式，可能需要安装 chromium
brew install --cask chromium
```

**Q: LLM API 调用失败？**

```bash
# 检查 API Key 是否正确
echo $LLM_API_KEY

# 测试 API 连接
curl -H "Authorization: Bearer $LLM_API_KEY" $LLM_BASE_URL/models
```

**Q: 测试失败？**

```bash
# 确保所有依赖已安装
pip install -e .

# 清理缓存
rm -rf .pytest_cache __pycache__
pytest tests/ -v --tb=short
```

---

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
