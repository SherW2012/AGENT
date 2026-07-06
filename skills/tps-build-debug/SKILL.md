---
name: tps-build-debug
description: One-click TPS Debug build - run the user's configured Debug build script, sync the build artifacts (dll/exe) into their install directory, summarize the log, and on failure extract the real errors and estimate where in the project each error originates. Use when the user asks to build/compile the TPS project in Debug.
version: 0.2.0
icon: "hammer"
display_name: "TPS Debug 编译"
short_description: "一键 Debug 编译、同步产物并定位错误。"
default_prompt: "运行一次 TPS Debug 编译（run_build，profile 为 debug）：成功则同步产物并报告用时/警告数/同步结果；失败则提取关键错误并预估源码位置。如果 debug 档案还没配置，先向我要脚本路径和产物目录映射。"
interaction: instant
auto_approve_tools:
  - run_build
---

# TPS Debug Build（一键）

Run the user's own Debug build script, sync the artifacts, and turn the raw log
into an actionable diagnosis — all from ONE click on the skill button. The
click itself is the user's consent, so `run_build` runs without an extra
approval prompt. The script path and artifact directories differ per machine
and are NEVER hardcoded or guessed.

## First-time configuration (in conversation)

If `get_build_profiles` shows the `debug` profile missing or its script gone,
collect from the user, then call `configure_build_profile` (this write DOES
require approval — configuration changes what the one-click button will do):

1. The full absolute path of their Debug build script (for example a
   `vs2019_win64.bat`).
2. The artifact sync mappings (`deploy`): where the build outputs land and
   where they must be copied to. For the TPS project this is typically
   `build-vs2019-x64\bin` → `bin\win64` (relative paths resolve against the
   script's directory) — but always confirm with the user, never assume.

Configuration is stored in the per-user data dir and survives workspace
switches. To change mappings later, the user just says so in conversation.

## One-click run

1. Call `run_build` with profile `debug`. On success the harness automatically
   copies every file under each deploy source dir over its target dir and
   returns the result in `deployed`.
2. Report concisely: 成败、用时、警告数 → 产物同步（复制了多少个文件、到哪些
   目录、有没有失败——目标 dll/exe 被运行中的程序占用是最常见的失败原因，提醒
   用户关掉正在运行的 TPS 再试）→ 日志路径。
3. On failure, read the returned `errors` list (deterministically extracted
   file/line/code/message diagnostics) and the `logTail`:
   - Ignore warning noise; focus on the FIRST real errors — later ones are often
     cascades of the first.
   - Group repeated error codes, and for each root cause estimate which module
     or source area of the project it comes from (use `search_project_text`
     to locate symbols when the workspace contains the TPS sources).
   - Report: 概要 → 关键错误（文件:行, 代码, 信息）→ 初步根因判断与建议的
     排查位置。产物不会同步（只在成功时同步），说明这一点。

## Guardrails

- Only the human-registered script can run; never construct other commands.
- Artifact sync only copies between the human-configured directory pairs.
- Estimates of error locations are hypotheses to speed up the developer, not
  verdicts — say so.
