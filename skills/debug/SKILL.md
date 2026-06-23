---
name: debug
description: Investigate failures, exceptions, broken UI flows, failed tests, or confusing runtime behavior. Use when the user reports something is broken, stuck, failing, or inconsistent.
version: 0.1.0
display_name: "Debug"
short_description: "定位失败原因，给出最小修复路径。"
default_prompt: "使用 debug skill 分析当前失败现象，先定位最可能的原因，再给出可验证的最小修复方案。"
---

# Debug

Debug from evidence instead of guessing.

## Workflow

1. Reproduce or inspect the exact failure message.
2. Read the narrowest relevant code path.
3. Form one or two concrete hypotheses.
4. Verify hypotheses with focused commands, logs, or tests.
5. Apply the smallest fix that matches the local architecture.

## Guardrails

- Do not hide uncertainty. Name what is confirmed and what is inferred.
- Prefer focused tests over broad, slow validation unless the blast radius is wide.
- Keep user data and secrets out of logs and prompts.
