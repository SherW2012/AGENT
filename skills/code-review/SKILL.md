---
name: code-review
description: Review code changes or selected project files for bugs, safety issues, regressions, and missing tests. Use when the user asks for code review, risk review, implementation critique, or pre-merge inspection.
version: 0.1.0
display_name: "Code Review"
short_description: "审查代码风险、回归和缺失测试。"
default_prompt: "使用 code-review skill 审查当前工程最近的代码改动，优先指出 bug、回归风险和缺失测试。"
---

# Code Review

Focus on actionable engineering findings before summaries.

## Workflow

1. Inspect the changed files or the files named by the user.
2. Prioritize correctness, safety boundaries, data handling, compatibility, and test gaps.
3. Report findings first, ordered by severity.
4. Include file and line references when available.
5. Keep style opinions secondary unless they hide a real maintenance risk.

## Output

- Start with issues. Say clearly if no issues are found.
- Add open questions only when they affect correctness.
- Summarize the reviewed scope and tests at the end.
