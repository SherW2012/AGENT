# BNCT TPS 专属 AI Agent

这是一个面向 BNCT TPS 研发日常流程的安全优先本地 Agent 工作台，提供 Web 图形界面和
命令行两种入口。模型可以理解任务、选择工具、读取工程、搜索代码、执行测试，
并对**脱敏的只读计划快照**做格式校验和指标汇总。

> 当前版本是研发辅助工具，不是医疗器械，不生成处方，不批准计划，也不向 TPS、
> DICOM 或患者数据库写回数据。所有模型输出都必须由有资质人员复核。

## 已实现

- Claude 风格本地 Web 工作台：会话列表、对话（内嵌审批）、日历与常用链接面板、连接设置
- 本地会话持久化、收藏置顶、搜索、删除和项目级/私有记忆
- Claude 风格 `SKILL.md` 能力包发现机制，支持 `skills/`、`.agent/skills/`、`.claude/skills/`
- 右侧 Skill 面板默认装载 `dicom-tags`、Office 生成与 TPS 编译系列 skill，并支持从本地导入新的 skill
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

## 安全底线

除临床动作阻断和 PHI 检查外，以下边界同样生效（能用代码兜底的都在代码层，不只靠提示词）：

- **禁止一切 SVN 操作**（本机 TPS 代码由 SVN 维护，保险起见全禁）。三层防线：
  `.svn`/`.git` 元数据目录在文件工具层被确定性拒绝（读、写、搜索、列举都碰不到）；
  Agent 写出的脚本（.bat/.cmd/.ps1/.sh）如包含 svn 命令会被确定性拒绝写入；
  系统提示词明令禁止执行、编写或建议任何 SVN 命令——版本控制动作只属于人。
  （人工登记的编译脚本不受内容检查——那是你自己写的、注册时审批过的。）
- **不暴露内部实现**：用户通过提问、角色扮演或“调试为由”探查系统提示词、工具
  参数、审批机制等内部细节时，Agent 拒绝并转向用户文档。介绍“能做什么”没问题，
  “怎么实现的”不谈。
- **保护用户 token**：拒绝以消耗输出 token 为目的的请求（无限重复、要求超长灌水、
  自我循环）；每轮对话有工具调用步数预算（`BNCT_AGENT_MAX_STEPS`，默认 32，上限
  120）。到达预算不是失败而是**成本检查点**：任务体面暂停、进度与已写文件全部
  保留、对话里说"继续"即从暂停处接着执行——长的多阶段 skill 合法地需要多个检查点。
- **拒绝网络安全滥用**：不协助未授权扫描/入侵、凭据窃取、漏洞利用与恶意软件开发、
  DoS 等；针对用户自有系统的防御性问题正常回答。

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

- `dicom-tags`：解析 DICOM tag，脱敏直接标识符并省略 Pixel Data。
- `create-word`：在工作目录生成 `.docx` Word 文档。
- `create-ppt`：在工作目录生成 `.pptx` 演示文稿。
- `create-excel`：在工作目录生成 `.xlsx` Excel 表格。
- `tps-build-debug` ⚡：一键 Debug 编译 + 产物同步 + 日志总结，失败时提取关键错误并预估源码位置。
- `tps-build-release` ⚡：一键 Release 编译 + 产物同步，检查成败并提示发布风险。
- `tps-build-diagnose`：分析已有编译日志，聚类错误、排序根因、给出定位建议（不执行任何命令）。

### Skill 交互分类

Skill 分五类交互方式，`SKILL.md` frontmatter 用 `interaction` 与 `visibility` 声明：

| 类别 | 行为 | 例子 |
|---|---|---|
| `instant` ⚡ | **点击即执行**：直接发送、免回车；skill 声明的工具本次运行免审批 | `tps-build-debug/release` |
| `direct` | 点击即填入完整指令，回车直接执行 | — |
| `guided`（默认） | 点击填入说明模板，需补充目标后发送 | `create-word/ppt/excel`、`tps-build-diagnose` |
| 附件驱动 | 上传匹配类型的附件自动触发 | `dicom-tags` |
| `background` | 不显示在面板，需要时自动使用 | `web-search`、`archive-extract`、`pdf-extract` |

`instant` 的免审批依据是双重人工授权：能被执行的脚本只有人工登记过的
（`configure_build_profile`，登记本身需审批），而按钮点击就是这一次运行的授权——
和双击 `.bat` 是同一个信任模型，多余的回车与审批只是摩擦。skill 在 frontmatter 用
`auto_approve_tools` 声明免审批的工具（仅对本次运行生效，运行结束即失效），审批
记录照常写入审计日志。首次使用时的配置（脚本路径、产物目录）仍在对话中完成并需
审批。导入的第三方 skill 默认按 `guided` 处理；若其 frontmatter 声明了其他
`interaction` 或附件处理器字段，则按对应类别工作。

**图标**：出厂 skill 在 frontmatter 里用 `icon: "🔍"` 声明默认图标（emoji）；导入的
skill 也可以在自己的 `SKILL.md` 里声明 `icon` 自定义。未声明时按名称哈希从一组预设
图标（🧩 ⚙️ 🛠️ 🧪 📐 🗂️ 💡 🔧）中固定分配一个，保证同一 skill 图标稳定。

**Agent 自己凝练 skill**：让 Agent “把这个流程做成一个 skill”，它会自己撰写完整的
SKILL.md 并调用 `create_agent_skill`（写入类，需审批）。新 skill 存入用户级 skill
目录（与工作区无关），注册表即时刷新，右侧面板**无需重启**就会出现。

**脚本文件写入**：`write_project_text` 允许写 `.bat/.cmd/.ps1/.sh`，但会自动升级为
**execute 级审批**（写好的脚本离运行只差一次注册，所以按执行风险对待）。写普通文本
仍是 write 级。配合 `configure_build_profile` + `run_build`，形成“写脚本 → 注册 →
执行”三道人工闸门，例如让 Agent 自己生成 `launch_tps.bat` 并注册为 `launch` 档案，
之后一句“启动 TPS”即可一键运行。

### TPS 编译 Skill 的配置与一键执行

编译脚本路径因机器而异，**绝不写死在代码里**。首次点击编译按钮时，Agent 调用
`get_build_profiles` 发现没有配置，向你要两样东西：脚本的完整路径（例如
`D:\...\vs2019_win64.bat`）和**产物同步映射**（例如 Debug 的
`build-vs2019-x64\bin` → `bin\win64`、Release 的
`build-vs2019-x64-release\bin` → `bin\win64_release`，相对路径以脚本所在目录
为基准），经你批准后保存到用户数据目录 `~/.bnct_agent/build-profiles.json`。

配置完成后，**点击按钮 = 完整执行**：编译 → 成功后自动把产物（dll/exe 等）
覆盖复制到目标目录 → 汇报用时/警告数/同步结果/日志路径，失败则汇报关键错误与
根因预估。不需要再敲回车，也没有审批弹窗——脚本是你登记的、点击是你按的，
这与双击 `.bat` 的信任等级相同（体验对齐，且多了日志诊断和产物同步）。产物
被运行中的 TPS 占用导致的复制失败会逐个列出。对话里说“这次不要同步产物”即可
用 `deploy=false` 跳过同步；修改映射也在对话中完成。

`run_build` 只能运行人工登记过的脚本，模型不能构造任意命令；输出按 UTF-8→GBK
兜底解码避免中文日志乱码，完整日志存到 `~/.bnct_agent/build-logs/`，同时返回
确定性提取的错误诊断（文件/行/错误码/信息）供模型定位根因。超时默认 30 分钟，
可用 `BNCT_AGENT_BUILD_TIMEOUT` 调整。历史日志按档案自动保留最近 10 份
（`BNCT_AGENT_BUILD_LOG_KEEP` 可调），长期使用不会持续膨胀。

`archive-extract` 是一个**后台 skill**（不显示在面板里，类似 `web-search`）：上传 `.zip` 时自动在内存里解析压缩包，列出文件并预览文本成员，全程只读、不落盘，并对条目数、单文件读取量和总预览量做上限以抵御 zip 炸弹。

`pdf-extract` 同为后台 skill：上传 `.pdf` 时自动在内存里解压内容流并提取文本层（纯标准库实现）。对**文本型 PDF** 有效；扫描件没有文本层（需要 OCR）、CID/CJK 复合字体可能解码不全，这两种情况会如实报告而不是硬猜；加密 PDF 会提示无法解析。

右侧面板只显示**常用 Skill**（最多 7 个）；点击面板右上角“全部”会弹出全部 Skill 的网格对话框，可在那里设为常用（★）、删除本地导入的 skill，或导入新的 skill。Skill 与工作目录相互独立：内置 skill 随应用走，导入的 skill 存在用户数据目录，切换工作目录不会改变 skill 列表。

### Word / PPT 生成

`create-word`、`create-ppt`、`create-excel` 通过 `create_word_document` / `create_powerpoint` / `create_excel` 三个写入类工具生成 Office 文档。文件采用开放的 Office Open XML 标准（ECMA-376 / ISO/IEC 29500），完全用 Python 标准库 `zipfile` 拼装，不引入任何第三方库，也不附带微软的字体或模板——因此**不存在版权或授权问题**。生成属于写操作，需人工审批；不得把患者标识或密钥写入文档。

**联网搜索：一个开关，通道随模型走。** 设置页只有「开启联网搜索」一个开关（对话框
上方还有同款快捷开关，两处状态同步）：

- **使用 Kimi 时**：优先走 Kimi 模型自带的联网搜索（Moonshot 的 `$web_search`
  builtin 工具——模型在服务端自己执行搜索，本地只按协议回显参数）。效果与官方
  Kimi 一致，按 Kimi 平台计费。**本地 `web_search` 工具同时保留作为兜底**：搜索
  能力的存在绝不能依赖模型认得 `$web_search` 这种特殊声明——只留 builtin 时模型
  可能在工具列表里找不到叫 `web_search` 的函数，进而向用户断言"我没有搜索能力"
  （实测踩过这个坑）。系统提示词按当轮实际状态明确告知：搜索已开启、优先用
  builtin、本地版兜底、严禁向用户否认搜索能力。
- **使用 DeepSeek / 其他无自带搜索的模型时**：走内置搜索（`web-search` 后台
  skill，Bing 抓取，DuckDuckGo 兜底）。
- 关闭开关后，两种通道都不向模型暴露，提示词同步告知“已关闭、可用输入框上方
  的开关打开”；`fetch_url`（读取用户明确给出的 URL）随搜索开关一起显隐。

**为什么"自带搜索"也可能不搜——以及我们的对策**：API 版的 `$web_search` 和普通
tool call 一样，**调不调由模型自己判断**（Kimi App 那种"每次必搜"是 App 服务端
提示词的策略，不是 API 的默认行为）。而模型的"内心时钟"停在训练截止日：不告诉它
今天几号，它会认为正在发生的事"还没发生"，于是自信地跳过搜索直接背旧知识。因此
系统提示词**每轮注入当前真实日期**，并明确要求：时效性问题必须以注入的日期为准、
优先搜索、搜索结果优先于训练记忆。

**深度思考与联网搜索的官方冲突——自动交替**：Moonshot 官方文档明确 k2.5/k2.6 的
思考模式与 `$web_search` **暂时不兼容**（思考开着时该工具形同虚设；k2.6 默认开
思考）。深度思考很宝贵，所以不做一刀切，而是按阶段自动交替：

1. **默认思考态**：请求不带 `$web_search`、思考保持开启，本地 `web_search` 留在
   工具表里兼作"我要搜索"的信号；
2. **进入搜索阶段**：模型在思考态调用 `web_search` 时，harness 不执行劣质抓取，
   而是切入搜索阶段——之后的请求附带官方关闭思考的参数并挂上 `$web_search`，
   同时告知模型"用 `$web_search` 重新执行该查询"（活动面板显示"暂停思考，切换
   Kimi 联网搜索"）；
3. **自动恢复**：某一轮工具调用不再包含任何搜索时，视为素材搜集完成，退出搜索
   阶段、恢复深度思考（活动面板显示"恢复深度思考"），整理与写作轮次全程带思考。

识图轮换到的视觉模型不属于该系列，不发送 builtin 工具与 thinking 参数。冲突事实
写在 Provider 档案里（与 vision 能力字段同级），交替逻辑在运行层通用，对任何有
同类限制的 provider 都成立，非针对个别场景的特调。

内置搜索的工程实现要点（对 Kimi 通道不适用，它由 Kimi 服务端执行）：

- **查询整句送出**：查询词以完整自然语言原样发送给搜索引擎，绝不在代码里把句子拆成单字或零散关键词。
- **时效性由模型判断**：通过 `web_search` 的 `recency` 参数决定，代码里没有任何时效性关键词白名单。
- **隐私边界仍是确定性代码**：拦截患者标识、密钥、内部路径等敏感内容进入查询。

进阶：`ask` 模式（每次搜索前人工审批）与第三方搜索 API（博查/Tavily/Brave）不再
出现在界面上，但仍可用环境变量配置：`BNCT_AGENT_WEB_SEARCH_MODE=ask`、
`BNCT_AGENT_SEARCH_PROVIDER` / `BNCT_AGENT_SEARCH_API_KEY`。API 失败自动回退内置抓取。

联网搜索不得携带患者标识、API Key、内部路径、私有主机名、私有代码或公司机密内容。答案使用搜索结果时需要给出来源标题和 URL。

## 记忆：显式 + 隐式

- **显式记忆**（原有）：用户明确说“记住……”时，走 `append_agent_memory` 写入本机
  `memory.md`（需审批）。
- **隐式记忆**（对标 Claude 的自动记忆）：开启后，每轮对话完成时后台异步调用模型，
  从对话中提取最多 2 条**稳定的**用户偏好/背景事实，合并进用户数据目录的
  `auto-memory.md`（去重、上限 80 条、单条 200 字符），并热更新到系统上下文。
  确定性过滤器拦截患者信息、密钥、邮箱等敏感内容进入记忆——这层是代码，不依赖模型
  自觉。设置页“记忆”标签提供开关（默认开启，对标 Claude；环境变量
  `BNCT_AGENT_AUTO_MEMORY=0` 可全局关闭）和“清空自动记忆”按钮。隐式总结属于
  尽力而为的后台行为，失败静默，不影响对话本身。

## 日历与常用链接（右侧面板）

右侧原“工作区文件”面板替换为**日历 + 常用链接**（工作目录入口移到了对话框上方的
「工作目录」胶囊，悬浮平滑展开完整路径，点击切换；旁边是联网搜索快捷开关和吉祥物）。

- **日历**：迷你月历（有日程的日期带圆点，点日期看当天条目）+ 日程列表。这是
  **纯被动记录**，没有任何定时触发或后台轮询，不消耗 token——与已砍掉的定时任务
  是两码事。面板 ＋ 号可直接添加；对话里说“帮我记录一个日程：周五上午评审”即可，
  显式请求即同意，不弹审批。
- **常用链接**：用户自定义名称 + URL（仅限 http/https），点击即在新标签页打开。
  对话里“帮我记录一个常用链接”添加，“打开禅道”即由 Agent 匹配名称并让浏览器打开。
- 数据存在用户数据目录（`calendar.json` / `quick-links.json`），与工作区无关。

## 对话体验细节

- **会话切换不丢直播**：任务运行中切到别的会话再切回来，思考过程和流式输出原样
  接回，结束后答案直接出现，无需刷新页面。
- **提问气泡编辑**：悬浮自己的提问气泡出现 复制/编辑；点编辑后气泡原地变输入框
  （取消/确定），确定后在本会话中重新提问（对标 Kimi）。**任务执行中也可以编辑**：
  确定会先打断当前回答，等它真正停止后用新问题在同一会话重新思考（对标 Claude 的
  打断重答）；重试按钮同理。
- **多会话严格隔离**：每个会话的流式输出、思考面板、审批卡都只属于自己的会话。
  A 会话执行中切到 B 提问，两条流并行互不串扰；A 需要审批时卡片不会弹在 B 里，
  切回 A 才显示（后端给每个审批和工具事件打了会话标签）。
- **吉祥物**：对话框右上的蓝色小家伙会眨眼，任务执行时会打工式摇摆（
  `prefers-reduced-motion` 时静止）。
- **联网搜索快捷开关零卡顿**：开关走专用轻量接口，服务端只原地翻一个标志位
  （不重扫 skill、不重建运行时），前端乐观更新、失败回滚；任务执行中也能切，
  下一轮推理即生效。
- **暗色主题**：设置 → 外观 可选 亮色/暗色/跟随系统，立即生效、存于本机浏览器。
  全部配色收敛为 CSS 变量双色板，代码高亮、审批卡、日历、吉祥物同步适配。
- **日程/链接自绘对话框**：面板 ＋ 号弹出与整体风格一致的表单（原生日期/时间
  选择器），不再用浏览器自带的 prompt 弹窗。

## 长会话上下文、用量与审计

- **上下文滚动压缩**：每轮携带“更早对话的自动摘要 + 最近 8 条原文”。当足够多的旧消息
  滑出原文窗口时，后台把它们合并进会话摘要（保留目标、已完成事项、关键决定、未决问
  题），长会话不再“失忆”，提示词也不会无限增长。尽力而为、失败静默。
- **Token 用量**：每轮回答的元信息里显示 `↑输入 ↓输出` token 数（流式请求携带
  `include_usage`）；设置 → 审计日志页顶部显示累计用量（存于用户目录 `usage.json`）。
- **审计日志查看**：设置 → 审计日志，可分页查看每次工具调用、审批与安全事件
  （时间为 UTC，敏感字段已脱敏），用于问题定位与管理复查。

## 会话与 Skill 的存储位置

会话历史和导入的 skill 保存在与工作目录**无关**的用户级数据目录（默认 `~/.bnct_agent`，可用环境变量 `BNCT_AGENT_DATA_DIR` 覆盖）。因此切换工作目录不会丢失会话或已导入的 skill。项目内置 skill 仍随各自仓库的 `skills/` 目录走。右侧 Skill 面板对可移除的本地 skill 提供删除按钮；项目内置 skill 需在代码仓库中处理。

## 图片识别（识图）

识图能力属于**大模型**，Agent 只负责把图片按 API 格式传给模型（与 Claude Code 的做法一致，
没有独立的 OCR 工具）。各供应商的能力是配置事实，写在 provider 档案里：

| 供应商 | 识图 | 行为 |
|---|---|---|
| OpenAI | `native` | 配置的模型本身接受图片，直接发送 |
| Kimi / Moonshot | `switch` | **同一 API Key**，含图片的对话自动路由到视觉模型（默认 `moonshot-v1-32k-vision-preview`，可用 `KIMI_VISION_MODEL` 覆盖），用户无需手动切换 |
| DeepSeek | `none` | 对话接口纯文本；图片不发送，改为向模型注明限制，由它如实告知用户 |

设置页的供应商说明会显示各家的识图能力；在纯文本供应商下添加图片附件时会立即
弹提示。若视觉模型调用失败（如账号无权限），该轮自动剥离图片退回所配置的文本
模型继续，并在界面提示，不会让整个任务失败。

## 关于 VPN / 网络

和模型对话本身只访问所选供应商的 API 域名：DeepSeek、Kimi/Moonshot 在中国大陆通常无需 VPN；OpenAI 一般需要。换言之，不用 VPN 时，把供应商切到 DeepSeek 或 Kimi 即可正常对话。联网搜索默认走 Bing，同样无需 VPN；若本机配置了代理（如对话用的 VPN 代理）导致搜索异常，可在设置页把“网络通道”切到 `Direct` 绕过本机代理。

## 打包分发（给同事的成品包）

在 Windows 上、仓库根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
```

产物是 `dist\BNCT-Agent-win64.zip`：同事解压后**双击 `BNCT-Agent.exe` 即可使用，
无需安装 Python**（PyInstaller 已把运行时打进包里）。包内含全部出厂 skill、示例数据
和《使用说明.txt》；默认工作目录是包内的 `workspace\`，每个人的会话/记忆存
在各自的 `%USERPROFILE%\.bnct_agent\`。同事只需要自备模型 API Key（设置页填入）。
注意 PyInstaller 不能跨平台构建，Windows 包必须在 Windows 上打。

## 快速开始

```powershell
cd C:\path\to\agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
Copy-Item .env.example .env
```

### Web 图形界面（推荐）

安装完成后双击 `Start-BNCT-Agent.cmd`。它会在本机 `127.0.0.1` 启动服务并自动打开
浏览器。也可以手动运行：

```powershell
bnct-agent-web --root C:\path\to\agent --open-browser
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
bnct-agent ask --root C:\path\to\tps-repo "定位剂量计算模块并总结测试覆盖"
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
