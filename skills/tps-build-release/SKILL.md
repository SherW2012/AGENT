---
name: tps-build-release
description: One-click TPS Release build - run the user's configured Release build script, sync the release artifacts (dll/exe) into their install directory, verify it completed cleanly, and flag release risks such as errors, unusual warning growth, or failed artifact copies. Use when the user asks to build/compile the TPS project in Release.
version: 0.2.0
icon: "package"
display_name: "TPS Release 编译"
short_description: "一键 Release 编译、同步产物并提示发布风险。"
default_prompt: "运行一次 TPS Release 编译（run_build，profile 为 release）：成功则同步产物并按发布视角报告；失败则提取关键错误。如果 release 档案还没配置，先向我要脚本路径和产物目录映射。"
interaction: instant
auto_approve_tools:
  - run_build
---

# TPS Release Build（一键）

Same mechanics as the Debug build, tuned for release: the goal is not just
"did it compile" but "is this build safe to hand over". One click runs the
build and syncs the artifacts; the click itself is the user's consent, so
`run_build` needs no extra approval prompt.

## First-time configuration (in conversation)

If `get_build_profiles` shows the `release` profile missing or stale, collect
from the user and call `configure_build_profile` (approval required):

1. The absolute path of their Release build script (for example a
   `vs2019_win64_release.bat`).
2. The `deploy` mappings — for the TPS project typically
   `build-vs2019-x64-release\bin` → `bin\win64_release` (relative paths
   resolve against the script's directory) — always confirm, never assume.

## One-click run

1. Call `run_build` with profile `release`; on success artifacts are synced
   automatically and reported in `deployed`.
2. Report with a release lens:
   - 失败：按 tps-build-debug 的方式提取并解释关键错误；产物未同步。
   - 成功：报告用时与警告数；报告产物同步结果（数量、目标目录、失败项——
     被占用的 dll/exe 是最常见原因，同步失败的发布包是不完整的，必须醒目提示）；
     警告数如果显著异常（例如比平时高很多），作为发布风险提示。
   - 明确说明这只是编译与产物拷贝层面的检查，不能替代测试与验证流程。

## Guardrails

- Only the human-registered script can run; never construct other commands.
- Artifact sync only copies between the human-configured directory pairs.
- Do not claim the build is "ready for clinical use" — release readiness here
  means the compile/link/copy stage only.
