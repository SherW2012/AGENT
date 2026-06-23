---
name: verify
description: Verify that a change works end-to-end through tests, browser checks, API health checks, or focused manual inspection. Use after code changes, UI changes, bug fixes, or skill imports.
version: 0.1.0
display_name: "Verify"
short_description: "用测试、接口和界面检查确认改动有效。"
default_prompt: "使用 verify skill 验证当前改动：运行相关测试，检查本地 Web 服务健康状态，并说明还剩哪些风险。"
---

# Verify

Verification should match the risk of the change.

## Workflow

1. Pick the smallest checks that cover the touched behavior.
2. For UI changes, include a browser or static asset check when possible.
3. For backend changes, run focused unit tests and API health checks.
4. For skill changes, confirm the skill appears in the catalog and can be read.
5. Report skipped checks explicitly.

## Output

List checks run, pass/fail status, and residual risk.
