---
name: tps-build-debug
description: Run the user's configured TPS Debug build script, watch the log, extract the real errors from the warning noise, and estimate where in the project each error originates. Use when the user asks to build/compile the TPS project in Debug.
version: 0.1.0
display_name: "TPS Debug 编译"
short_description: "一键 Debug 编译并定位错误。"
default_prompt: "运行一次 TPS Debug 编译，失败时提取关键错误并预估源码位置。"
interaction: direct
---

# TPS Debug Build

Run the user's own Debug build script and turn the raw log into an actionable
diagnosis. The script path differs per machine and is NEVER hardcoded or
guessed.

## Workflow

1. Call `get_build_profiles`. If the `debug` profile is missing or its script no
   longer exists, ask the user for the full absolute path of their Debug build
   script (for example a `vs2019_win64.bat`), then call
   `configure_build_profile` with profile `debug`. Configuration is stored in
   the per-user data dir and survives workspace switches.
2. Call `run_build` with profile `debug`. Execution always requires human
   approval; do not try to bypass it.
3. On failure, read the returned `errors` list (deterministically extracted
   file/line/code/message diagnostics) and the `logTail`:
   - Ignore warning noise; focus on the FIRST real errors — later ones are often
     cascades of the first.
   - Group repeated error codes, and for each root cause estimate which module
     or source area of the project it comes from (use `search_project_text`
     to locate symbols when the workspace contains the TPS sources).
   - Report: 概要（成败、用时、警告数）→ 关键错误（文件:行, 代码, 信息）→
     初步根因判断与建议的排查位置。完整日志路径一并给出。
4. On success, report duration and warning count, and mention the log path.

## Guardrails

- Only the human-registered script can run; never construct other commands.
- Estimates of error locations are hypotheses to speed up the developer, not
  verdicts — say so.
