# Adaptive Prepare Recovery Design

- Date: 2026-06-08
- Status: approved for implementation planning
- Related files:
  - `src/merchant_automation/operations/executor.py`
  - `src/merchant_automation/operations/explorer.py`
  - `src/merchant_automation/operations/router.py`
  - `src/merchant_automation/operations/failure.py`
  - `docs/PRD-recipe-flywheel.md`
  - `docs/PLAN-recipe-flywheel.md`

## Summary

Prepare mode should keep using deterministic recipes as the preferred path, but it must stop acting like a brittle script when the merchant backend page drifts. When a recipe step encounters a recoverable page abnormality, the system should invoke a local Agent recovery routine for that step only, then return to the recipe and continue prepare execution.

The selected behavior is:

> Automatically perform local recovery and continue prepare, as long as the automation does not click save, submit, publish, confirm, or other finalizing actions.

## Problem

The current execution model has three useful pieces:

- `RecipeStepExecutor` executes deterministic `RecipeDefinition` steps.
- `ExecutionRouter` can fall back to `AgentExplorer` when recipe execution fails with `StepExecutionError`.
- `AgentExplorer` can reason over page state with LLM and browser vision.

The gap is the granularity of recovery. A recipe failure is handled at the whole-task level. If the page contains a popup, slow render, changed label, login interruption, stale DOM node, or unexpected layout variation, prepare execution can only keep following fixed recipe steps until a failure escapes. Then the router may restart via full Agent exploration. This is too mechanical for real merchant backends.

The goal is not to remove recipes. Recipes remain the fast, auditable path. The goal is to add an adaptive recovery layer around individual prepare steps.

## Goals

- Add step-level local recovery for prepare mode.
- Preserve deterministic recipe execution when pages are normal.
- Allow Agent assistance only for bounded local recovery around the failed step.
- Continue the remaining recipe steps after recovery succeeds.
- Enforce prepare safety in code, not only in prompts.
- Record recovery attempts in execution traces.
- Keep candidate recipe self-healing possible without overwriting promoted recipes.

## Non-Goals

- Do not replace `RecipeStepExecutor` with full-time Agent execution.
- Do not enable commit behavior or relax existing commit preflight gates.
- Do not auto-overwrite `prepare_ready` or `commit_ready` recipes.
- Do not introduce hard-coded selectors for specific Meituan pages as the main solution.
- Do not solve full dashboard review UX in this feature.

## Recommended Architecture

Introduce an adaptive wrapper around recipe execution:

```text
ExecutionRouter
  -> AdaptiveRecipeExecutor
      -> RecipeStepExecutor executes the next step
      -> PageStateInspector checks obvious abnormal states
      -> AdaptiveStepRecovery handles recoverable failures
      -> PrepareSafetyGuard blocks finalizing actions
      -> execution returns to recipe steps after recovery
  -> full AgentExplorer fallback only after local recovery fails
```

This keeps the existing router concept intact. The router still decides between deterministic recipe execution and full Agent exploration. The new wrapper makes recipe execution less brittle before full fallback is needed.

## Components

### AdaptiveRecipeExecutor

Responsibility: orchestrate recipe steps in prepare mode with local recovery.

Inputs:

- `RecipeDefinition`
- recipe params
- `TraceRecorder`
- `ExecutionMode`
- browser session
- optional LLM
- operation contract metadata for recovery prompts

Behavior:

1. Execute each step through existing `RecipeStepExecutor` behavior.
2. Before high-risk actions, run `PrepareSafetyGuard`.
3. If a step raises `StepExecutionError`, ask `AdaptiveStepRecovery` to repair the local page state.
4. If recovery succeeds, record a trace step and continue with the next recipe step.
5. If recovery fails, raise `StepExecutionError` so `ExecutionRouter` can perform existing full fallback.

This component should be small. It should not duplicate browser action implementations from `RecipeStepExecutor`.

### PageStateInspector

Responsibility: classify obvious page abnormalities before or after a step.

Initial checks should be intentionally lightweight:

- current URL is missing or changed to a login page
- body text contains common auth or permission prompts
- modal-like page text suggests an interruption
- page body is empty after a wait
- target page title or URL is obviously wrong for the recipe entry URL

Output:

```python
class PageState:
    status: PageStateStatus
    reason: str
    details: dict[str, object]
```

Initial statuses:

- `OK`
- `LOGIN_REQUIRED`
- `BLOCKED_BY_MODAL`
- `WRONG_PAGE`
- `EMPTY_OR_LOADING`
- `UNKNOWN_ABNORMAL`

Only abnormal statuses should trigger recovery.

### AdaptiveStepRecovery

Responsibility: invoke a bounded Agent task to repair the local page state or complete the failed step.

Recovery prompt should include:

- original user operation title
- params
- current failed step description, target, and action
- prepare safety rule
- explicit instruction to stop after the current local objective

Example prompt shape:

```text
当前是 prepare 模式。你正在执行「修改门店联系电话」任务。
当前局部目标：点击电话号码区域进入编辑状态。
页面可能出现弹窗、加载异常、布局变化或入口文案变化。
请只完成这个局部目标，完成后停止。
禁止点击保存、提交、确认、发布、立即生效、完成修改等最终提交动作。
```

Recovery should use `browser_use.Agent` with a small step limit, for example 5 to 8 steps. It should not run a full 30-step exploration unless the router falls back to `AgentExplorer`.

### PrepareSafetyGuard

Responsibility: block finalizing actions in prepare mode.

The guard should inspect recipe step targets and Agent action targets before execution where possible. It should block text patterns such as:

- 保存
- 提交
- 确认
- 发布
- 立即生效
- 完成修改
- 删除
- 支付
- 结算
- 下架

The first version can use normalized target text matching. It should fail closed for obvious finalizing actions in prepare mode. Commit mode should continue to rely on preflight and recipe status gates.

## Data Flow

Normal prepare execution:

```text
Recipe step -> safety check -> browser action -> trace step -> next recipe step
```

Recoverable prepare failure:

```text
Recipe step fails
  -> record recovery start
  -> inspect page state
  -> run AdaptiveStepRecovery
  -> record recovery outcome
  -> continue next recipe step
```

Unrecoverable prepare failure:

```text
Recipe step fails
  -> local recovery fails
  -> raise StepExecutionError
  -> ExecutionRouter full fallback to AgentExplorer
```

Candidate self-healing:

```text
Local recovery succeeds
  -> recovery history is available
  -> if recipe status is candidate, allow future task to refresh candidate definition
  -> if recipe status is prepare_ready or commit_ready, only mark suspected stale
```

The first implementation may record recovery history and stale signals without immediately replacing definitions. Candidate update can be a follow-up task if needed.

## Safety Rules

Prepare mode may:

- navigate
- close blocking popups
- click edit entrances
- fill fields
- upload files
- wait
- take screenshots

Prepare mode must not:

- save
- submit
- confirm final changes
- publish
- immediately apply changes
- delete data
- pay, settle, or perform financial actions
- take product or store destructive actions

Safety must exist as code. Prompt wording is a second layer, not the main protection.

## Trace Requirements

Trace output should make recovery visible:

- record the failed step number
- record page abnormality reason if available
- record recovery start
- record recovery success or failure
- record whether execution continued recipe replay or fell back to full Agent exploration

This matters because operators need to understand why a prepare task took the adaptive path.

## Error Handling

- Browser transient errors, stale DOM nodes, and missing semantic targets should become `StepExecutionError`.
- Local recovery should catch Agent exceptions and return a failed recovery result.
- If recovery fails, the router's existing full fallback path remains the final recovery layer.
- Unknown commit state should not be created in prepare mode because finalizing actions are blocked.
- Login-required states should be reported clearly and should not loop through repeated recovery attempts.

## Testing Strategy

Use TDD for implementation. The first tests should avoid real merchant backends.

Required tests:

1. A recipe click failure invokes local recovery in prepare mode.
2. Local recovery success allows the recipe to continue subsequent steps.
3. Local recovery failure raises `StepExecutionError` for router fallback.
4. `PrepareSafetyGuard` blocks save and submit targets in prepare mode.
5. `PrepareSafetyGuard` allows edit, fill, wait, upload, and screenshot actions.
6. Recovery prompt includes the failed step target and prepare safety rule.
7. Page state inspector classifies empty page, wrong page, login page, and normal page.
8. Recovery trace steps are recorded.
9. Promoted recipes are not automatically overwritten by recovery output.

Targeted verification commands:

```bash
pytest tests/test_recipe_executor.py tests/test_execution_router.py -q
pytest tests/test_adaptive_prepare_recovery.py -q
```

Some existing tests bind local HTTP servers and may require running outside the managed sandbox.

## Rollout

Implement in small slices:

1. Normalize browser action failures into `StepExecutionError`.
2. Add `PrepareSafetyGuard`.
3. Add `PageStateInspector`.
4. Add `AdaptiveStepRecovery` with mocked Agent tests.
5. Add adaptive orchestration around prepare recipe execution.
6. Connect adaptive path in `ExecutionRouter`.
7. Add trace visibility.

The first production behavior should be conservative: one local recovery attempt per failed step, small Agent step limit, and full fallback only after local recovery fails.

## Acceptance Criteria

- Prepare mode no longer crashes or gives up immediately on recoverable recipe step failures.
- A failed prepare step can be locally recovered by Agent and then continue the remaining recipe.
- Save and submit actions are blocked during prepare, including inside recovery.
- Existing deterministic recipe tests continue to pass.
- Existing router fallback tests continue to pass.
- Recovery events are visible in traces.
- No promoted recipe is automatically overwritten.

## Open Decisions

- Maximum local recovery attempts per task: choose 1 per failed step for the first implementation.
- Recovery Agent max steps: choose 6 for the first implementation.
- Candidate recipe rewriting after recovery: record enough history first; automatic replacement can be added after trace evidence proves it is reliable.
