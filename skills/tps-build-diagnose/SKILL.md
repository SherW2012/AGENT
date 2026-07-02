---
name: tps-build-diagnose
description: Analyze an existing build log without running a build - cluster the errors, rank probable root causes, and suggest where in the project to look. Use when the user has a build log file or pasted build output to diagnose.
version: 0.1.0
display_name: "编译日志诊断"
short_description: "分析已有编译日志，聚类错误并定位根因。"
default_prompt: "使用 tps-build-diagnose skill 分析编译日志，聚类错误、排序根因并给出定位建议。"
---

# TPS Build Diagnose

Post-mortem analysis of a build that already ran — nothing is executed.

## Input forms

- A log file path: call `analyze_build_log` with it (workspace-relative or
  absolute; `run_build` also saves logs under the user data dir and returns
  their path).
- Pasted or attached log text: read it directly from the message/attachment.

## Method

1. Get the deterministic diagnostics (`analyze_build_log` returns
   file/line/code/message and warning counts).
2. Cluster: group identical error codes and same-file errors; separate root
   errors from cascade errors (the first error in a translation unit usually
   causes the rest).
3. Rank root causes by likelihood and blast radius.
4. For each root cause, suggest the concrete place to look — file and line from
   the diagnostic, plus related symbols located with `search_project_text` when
   the sources are in the workspace.
5. Output: 错误聚类表 → 根因排序（附依据）→ 每个根因的定位建议与下一步动作。

## Guardrails

- Diagnoses are hypotheses to accelerate the developer, not verdicts.
- Do not modify code as part of this skill; propose fixes only.
