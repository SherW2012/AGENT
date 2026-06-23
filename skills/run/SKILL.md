---
name: run
description: Run the local application, approved test command, or deterministic project workflow and report the result. Use when the user asks to launch, execute, smoke test, or check whether the app works.
version: 0.1.0
display_name: "Run"
short_description: "启动或执行受控流程，并回报结果。"
default_prompt: "使用 run skill 检查当前本地 Agent 是否能正常启动，并报告健康检查、关键日志和失败点。"
---

# Run

Use existing project entrypoints before inventing new commands.

## Workflow

1. Identify the intended entrypoint from README, scripts, or package metadata.
2. Prefer fixed, approved commands such as the bundled unit test command or local start script.
3. Capture the important result: exit code, health check, visible UI status, and relevant errors.
4. Stop background services only when they belong to this project and the user asked for restart or replacement.

## Output

Report what ran, whether it passed, and what the user can rely on now.
