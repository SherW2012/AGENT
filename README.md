# AI Agent

本地 Agent 工作台，提供 Web 图形界面和
命令行两种入口。模型可以理解任务、选择工具、读取工程、搜索代码、执行测试，
并对**脱敏的只读计划快照**做格式校验和指标汇总。


## 已实现

- Claude 风格本地 Web 工作台：会话列表、对话、工作区、文件预览、连接设置、审批弹窗
- 本地会话持久化、收藏置顶、搜索、删除和项目级/私有记忆
- Claude 风格 `SKILL.md` 能力包发现机制，支持 `skills/`、`.agent/skills/`、`.claude/skills/`
- 右侧 Skill 面板默认装载 `code-review`、`debug`、`run`、`verify`、`dicom-tags`，并支持从本地导入新的 skill
- 后台 `web-search` skill：支持 `auto`/`ask`/`off` 三种联网搜索模式，默认在需要最新公开知识时自动搜索
- 支持 OpenAI、DeepSeek、Kimi 三种供应商和各自独立的 Key、模型、Base URL
- OpenAI Responses API 与兼容 Chat Completions 的多轮工具调用循环
- 工程文件列举、读取、搜索和经审批的文本写入；绝对路径写入可在人工批准后落到工作区外
- 经审批的单元测试执行，拒绝任意 shell 命令
- BNCT 计划 JSON 快照的脱敏检查、字段校验与原值汇总
- `dicom-tags` skill：对上传的 DICOM 附件做本地 tag 解析、Pixel Data 省略、直接标识符脱敏
- 代码层风险分级：`read`、`write`、`execute`、`clinical`
- `write`/`execute` 人工确认，`clinical` 无条件阻断
- `web-search` 默认只用于公开资料；敏感查询或 `ask` 模式会进入人工审批，`off` 模式完全不暴露联网搜索工具
- JSONL 审计日志，敏感字段脱敏，工具结果只保留摘要和哈希
- 无 API Key 的离线演示及单元测试

## 架构

```text
用户 Web / CLI
   |
   v
Provider Adapter (OpenAI Responses / Compatible Chat Completions)
   |
   +--> Tool Registry --> Safety Policy --> Human Approval
   |                             |
   |                             +--> Audit JSONL
   |
   +--> Project Tools (read/search/write/test)
   +--> TPS Snapshot Tools (validate/summarize, read-only)
   +--> Skill Registry (SKILL.md + scripts/templates/examples)
```

模型只负责规划和解释；路径约束、审批、PHI 检查、命令白名单和临床动作阻断均由
本地确定性代码执行。

## Skill 系统

Skill 是可拆卸能力包，不是模型微调。一个 skill 通常由 `SKILL.md`、可选脚本、
模板、示例组成。Agent 会先发现 skill，再在需要时读取 `SKILL.md` 或调用受信任的
本地处理器。

当前支持三类目录：

| 目录 | 用途 | Git 行为 |
|---|---|---|
| `skills/<name>/` | 项目内置、建议提交的 skill | 纳入版本管理 |
| `.agent/skills/<name>/` | 本机私有 skill | 默认被 `.gitignore` 忽略 |
| `.claude/skills/<name>/` | 兼容 Claude 风格 skill 的导入位置 | 可按团队策略决定是否提交 |

典型结构：

```text
skills/dicom-tags/
  SKILL.md
  scripts/
    parse_dicom.py
```

`SKILL.md` 使用轻量 frontmatter：

```markdown
---
name: dicom-tags
description: Parse DICOM attachments into de-identified tag metadata summaries.
trusted: true
attachment_extensions: [".dcm", ".dicom"]
attachment_mime_types: ["application/dicom", "application/x-dicom"]
processor: "scripts/parse_dicom.py:process_attachment"
---

# DICOM Tags

Use this skill when the user uploads DICOM images and asks for tag metadata.
```

兼容边界：

- 可直接兼容大多数 prompt-only 的 Claude 风格 `SKILL.md`。
- 当前已支持 Python 附件处理器：`relative/path.py:function`。
- 脚本处理器必须显式 `trusted: true`，因为执行本地代码天然有权限风险。
- Claude Code 的高级字段、hook、工具白名单和运行时上下文不会假装完全兼容，后续会逐步补。

启停方式很朴素：放入上述目录即加载；移走目录或在 frontmatter 中设置
`enabled: false` 即卸载。新增 PPT、PDF、Excel、DICOM-RT 等垂直能力时，优先做成
skill，而不是改核心 Agent 代码。

Web 右侧 Skill 面板会显示当前已发现的 skill。点击虚线加号可以选择一个包含
`SKILL.md` 的文件夹，导入后会复制到 `.agent/skills/<name>`，因此默认只在本机生效，
不会自动进入 Git。项目内置的默认 skill 位于 `skills/`，包括：

- `code-review`：审查代码风险、回归和缺失测试。
- `debug`：定位失败原因并收敛到最小修复。
- `run`：启动或执行受控流程，并报告结果。
- `verify`：用测试、健康检查和界面检查验证改动。
- `dicom-tags`：解析 DICOM tag，脱敏直接标识符并省略 Pixel Data。

`web-search` 是一个特殊的后台 skill，不显示在右侧 Skill 面板里。用户通常不需要手动点它；Agent 会在问题依赖最新公开知识时自动调用。设置页提供三种模式：

- `Auto`：默认模式；公开、非敏感的最新知识查询可自动搜索。
- `Ask`：每次搜索前都弹出人工审批。
- `Off`：不向模型暴露联网搜索工具。

联网搜索不得携带患者标识、API Key、内部路径、私有主机名、私有代码或公司机密内容。答案使用搜索结果时需要给出来源标题和 URL。

## 快速开始

```powershell
cd D:\wsr\code\project\agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
Copy-Item .env.example .env
```

### Web 图形界面（推荐）

安装完成后双击 `Start-BNCT-Agent.cmd`。它会在本机 `127.0.0.1` 启动服务并自动打开
浏览器。也可以手动运行：

```powershell
bnct-agent-web --root D:\wsr\code\project\agent --open-browser
```

Web 工作台可以预览文件、配置本次会话的 API Key、发送任务，并在写文件或运行测试
前通过弹窗审批。服务只监听本机地址，接口由随机会话令牌保护，API Key 不写入磁盘。

旧的 Tk 桌面入口 `bnct-agent-gui` 仍保留作为离线备用入口。

## 模型供应商与 API Key

三家服务独立开户、独立创建 Key、独立计费。无需先拥有 OpenAI API，直接在网页设置里
选择你能使用的供应商即可。未设置 `BNCT_AGENT_PROVIDER` 时默认选择 DeepSeek。

| 供应商 | Key 环境变量 | 默认 Base URL | 默认模型 | 官方入口 |
|---|---|---|---|---|
| OpenAI / GPT | `OPENAI_API_KEY` | SDK 默认地址 | `gpt-5.4-mini` | [创建 Key](https://platform.openai.com/api-keys) |
| DeepSeek | `DEEPSEEK_API_KEY` | `https://api.deepseek.com` | `deepseek-v4-pro` | [创建 Key](https://platform.deepseek.com/api_keys) |
| Kimi / Moonshot | `MOONSHOT_API_KEY` | `https://api.moonshot.cn/v1` | `kimi-k2.6` | [用户中心](https://platform.kimi.com/console/account) |

DeepSeek 和 Kimi 官方都提供 OpenAI SDK 兼容的 Chat Completions 接口，但模型 ID、
Base URL 和 Key 不能混用。当前 DeepSeek 文档推荐 V4 模型；旧的 `deepseek-chat` 和
`deepseek-reasoner` 已进入弃用流程。本项目因此使用 `deepseek-v4-pro` / `flash`。

参考：[DeepSeek 接入文档](https://api-docs.deepseek.com/)、
[DeepSeek Tool Calls](https://api-docs.deepseek.com/guides/tool_calls)、
[Kimi 快速开始](https://platform.kimi.com/docs/api/quickstart)、
[Kimi 模型列表](https://platform.kimi.com/docs/models)、
[Kimi Tool Use](https://platform.kimi.com/docs/api/tool-use)。

### OpenAI 账号说明

ChatGPT Plus、Pro 或 Team 订阅不会自动生成一个可读取的 API Key，ChatGPT 与 API
平台也分别计费。操作步骤：

1. 登录 [OpenAI Platform API Keys](https://platform.openai.com/api-keys)。
2. 点击创建新的 Secret Key，并在创建时立即保存；之后通常只能看到掩码，无法再次
   查看完整密钥，遗失时应创建新 Key 并撤销旧 Key。
3. 在 [API Billing](https://platform.openai.com/settings/organization/billing/overview)
   配置 API 计费或余额。
4. 打开本项目右上角“设置”，把 Key 填入 API Key 输入框。不要把 Key 发到聊天消息、
   工单或代码仓库中。

本地工作台只把 Key 保存在当前服务进程内存中；关闭服务后需要重新输入。

