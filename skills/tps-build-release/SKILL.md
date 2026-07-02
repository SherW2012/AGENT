---
name: tps-build-release
description: Run the user's configured TPS Release build script, verify it completed cleanly, and flag release risks such as errors, unusual warning growth, or missing artifacts. Use when the user asks to build/compile the TPS project in Release.
version: 0.1.0
display_name: "TPS Release 编译"
short_description: "一键 Release 编译并提示发布风险。"
default_prompt: "运行一次 TPS Release 编译，检查是否成功并提示发布相关风险。"
interaction: direct
---

# TPS Release Build

Same mechanics as the Debug build, tuned for release: the goal is not just
"did it compile" but "is this build safe to hand over".

## Workflow

1. Call `get_build_profiles`. If the `release` profile is missing or stale, ask
   the user for the absolute path of their Release build script (for example a
   `vs2019_win64_release.bat`) and call `configure_build_profile` with profile
   `release`.
2. Call `run_build` with profile `release` (human approval required).
3. Report with a release lens:
   - 失败：按 tps-build-debug 的方式提取并解释关键错误。
   - 成功：报告用时与警告数；如果日志尾部提示了产物输出路径或安装包步骤，
     核对其是否出现；警告数如果显著异常（例如比平时高很多），作为发布风险提示。
   - 明确说明这只是编译层面的检查，不能替代测试与验证流程。

## Guardrails

- Only the human-registered script can run; never construct other commands.
- Do not claim the build is "ready for clinical use" — release readiness here
  means the compile/link stage only.
