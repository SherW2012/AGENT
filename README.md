# BNCT TPS 专属 AI Agent

这是一个面向 BNCT TPS 研发日常流程的安全优先本地 Agent 工作台，提供 Web 图形界面和
命令行两种入口。模型可以理解任务、选择工具、读取工程、搜索代码、执行测试，
并对**脱敏的只读计划快照**做格式校验和指标汇总。

> 当前版本是研发辅助工具，不是医疗器械，不生成处方，不批准计划，也不向 TPS、
> DICOM 或患者数据库写回数据。所有模型输出都必须由有资质人员复核。

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

联网搜索的工程实现要点：

- **查询整句送出**：查询词以完整自然语言原样发送给搜索引擎，绝不在代码里把句子拆成单字或零散关键词。
- **主引擎为 Bing**：Bing 对中文等非拉丁语种的自然语言查询排序更好，且在中国大陆无需 VPN 即可访问；DuckDuckGo 仅作为兜底，不再作为主入口。
- **时效性由模型判断**：是否需要最新信息由模型阅读问题后通过 `web_search` 的 `recency` 参数决定，再据此优先查询新闻源——代码里没有任何“最新/前沿”之类的时效性关键词白名单。每个人表达“我要最新信息”的说法都不同，硬编码白名单既脆弱又不准确。
- **隐私边界仍是确定性代码**：会拦截患者标识、密钥、内部路径等敏感内容进入查询，这是安全边界，与“猜测用户意图”无关。

联网搜索不得携带患者标识、API Key、内部路径、私有主机名、私有代码或公司机密内容。答案使用搜索结果时需要给出来源标题和 URL。

## 会话与 Skill 的存储位置

会话历史和导入的 skill 保存在与工作目录**无关**的用户级数据目录（默认 `~/.bnct_agent`，可用环境变量 `BNCT_AGENT_DATA_DIR` 覆盖）。因此切换工作目录不会丢失会话或已导入的 skill。项目内置 skill 仍随各自仓库的 `skills/` 目录走。右侧 Skill 面板对可移除的本地 skill 提供删除按钮；项目内置 skill 需在代码仓库中处理。

## 关于 VPN / 网络

和模型对话本身只访问所选供应商的 API 域名：DeepSeek、Kimi/Moonshot 在中国大陆通常无需 VPN；OpenAI 一般需要。换言之，不用 VPN 时，把供应商切到 DeepSeek 或 Kimi 即可正常对话。联网搜索默认走 Bing，同样无需 VPN；若本机配置了代理（如对话用的 VPN 代理）导致搜索异常，可在设置页把“网络通道”切到 `Direct` 绕过本机代理。

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

### 命令行（保留）

PowerShell 不会自动读取 `.env`，运行前设置环境变量：

```powershell
$env:DEEPSEEK_API_KEY = "你的 DeepSeek 密钥"
bnct-agent chat --provider deepseek --root .

$env:MOONSHOT_API_KEY = "你的 Kimi 密钥"
bnct-agent chat --provider kimi --model kimi-k2.6 --root .

$env:OPENAI_API_KEY = "你的 OpenAI 密钥"
bnct-agent chat --provider openai --root .
```

不连接模型即可验证安全工具链：

```powershell
bnct-agent demo --root .
python -m unittest discover -s tests -v
```

也可执行一次性任务：

```powershell
bnct-agent ask --root D:\path\to\tps-repo "定位剂量计算模块并总结测试覆盖"
```

## 计划快照接口

当前版本不直接连接临床 TPS。TPS 先导出只读、脱敏 JSON，例如
`sample_data/deidentified_case.json`。Agent 只确认结构、数值类型和单位是否存在，
不会判断计划是否临床可接受，也不会重算剂量。

接入真实 TPS 时建议增加一个独立的 `tps-adapter` 服务：

1. 只读 API 首先上线，只暴露脱敏病例元数据、结构列表、DVH/剂量指标和计算日志。
2. API 使用短期身份凭证、最小权限、病例级访问控制和完整审计。
3. Agent 工具使用 JSON Schema，并给每个返回值附带来源、软件版本、算法版本和单位。
4. 所有写操作进入“变更草稿 -> 人工评审 -> TPS 原生验证 -> 双人确认”流程。
5. 计划批准、处方修改、照射参数下发和患者数据写回始终留在 TPS 的受控界面。

## 推荐开发路线

### Phase 1：研发助手（当前版本）

- 代码问答、日志分析、测试执行、需求追踪、测试用例草拟
- 脱敏计划快照读取和数据完整性检查
- 建立 20-50 个真实日常任务的回归评测集

### Phase 2：TPS 只读 Copilot

- 对接内部只读 REST/gRPC/MCP Adapter
- 增加 DICOM-RT/私有格式解析器，但只输出脱敏摘要
- 绑定算法版本、数据库版本、材料和截面数据版本
- 用金标准病例验证引用准确性、单位一致性和拒答行为

### Phase 3：受控工作流自动化

- 允许创建工单、测试报告、变更草稿和 QA 清单
- 引入角色权限、电子签名、双人审批与不可篡改审计
- 按医疗软件质量体系做风险管理、验证确认和变更控制

### Phase 4：临床决策支持（独立项目）

这一阶段不应由通用 Agent 直接演进而来。需要单独的医疗器械合规、临床验证、
网络安全、可用性工程和上市后监测方案，并明确人机职责。

## 数据与部署建议

- 不要把 PHI、原始 DICOM 或可回溯患者身份的数据发送到未经批准的云端。
- 生产环境优先使用组织批准的企业端点，确认数据保留、训练使用和地域策略。
- API Key 放入密钥管理系统，不放入 `.env`、日志、提示词或代码仓库。
- 审计日志位于 `<root>/.bnct_agent/audit/`；正式环境应转存到受控审计系统。
- 为每个工具设置超时、输出上限、速率限制和授权范围。

## 下一步要补的业务信息

要把它变成真正贴合你日常工作的 Agent，需要把每天的任务拆成一张清单：输入、
输出、当前软件、是否含 PHI、允许自动化程度、审批人、失败回退方式。优先选择
高频、低风险、结果易验证的任务，不要从自动优化或自动批准计划开始。
