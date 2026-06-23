"use strict";

const token = new URLSearchParams(window.location.hash.slice(1)).get("token") || "";

const state = {
  config: null,
  files: [],
  lastEventId: 0,
  currentApproval: null,
  busy: false,
  eventTimer: null,
};

const elements = {
  activityList: document.querySelector("#activity-list"),
  allowApproval: document.querySelector("#allow-approval-button"),
  apiKey: document.querySelector("#api-key-input"),
  approvalArguments: document.querySelector("#approval-arguments"),
  approvalModal: document.querySelector("#approval-modal"),
  approvalRisk: document.querySelector("#approval-risk"),
  approvalTool: document.querySelector("#approval-tool"),
  baseUrl: document.querySelector("#base-url-input"),
  browseFolder: document.querySelector("#browse-folder-button"),
  browseFolderLabel: document.querySelector("#browse-folder-label"),
  clearActivity: document.querySelector("#clear-activity-button"),
  closePreview: document.querySelector("#close-preview-button"),
  connection: document.querySelector("#connection-state"),
  connectionLabel: document.querySelector("#connection-label"),
  conversation: document.querySelector("#conversation-scroll"),
  denyApproval: document.querySelector("#deny-approval-button"),
  emptyState: document.querySelector("#empty-state"),
  fileCount: document.querySelector("#file-count"),
  fileList: document.querySelector("#file-list"),
  fileSearch: document.querySelector("#file-search"),
  messageList: document.querySelector("#message-list"),
  model: document.querySelector("#model-input"),
  modelOptions: document.querySelector("#provider-models"),
  modelPill: document.querySelector("#model-pill"),
  newSession: document.querySelector("#new-session-button"),
  previewBackdrop: document.querySelector("#preview-backdrop"),
  previewContent: document.querySelector("#preview-content"),
  previewDrawer: document.querySelector("#preview-drawer"),
  previewTitle: document.querySelector("#preview-title"),
  prompt: document.querySelector("#prompt-input"),
  providerDocsLink: document.querySelector("#provider-docs-link"),
  providerHelpText: document.querySelector("#provider-help-text"),
  providerHelpTitle: document.querySelector("#provider-help-title"),
  providerInputs: document.querySelectorAll('input[name="provider"]'),
  providerKeyLink: document.querySelector("#provider-key-link"),
  root: document.querySelector("#root-input"),
  send: document.querySelector("#send-button"),
  settingsButton: document.querySelector("#settings-button"),
  settingsForm: document.querySelector("#settings-form"),
  settingsModal: document.querySelector("#settings-modal"),
  snapshotDemo: document.querySelector("#snapshot-demo-button"),
  toastStack: document.querySelector("#toast-stack"),
  workspaceName: document.querySelector("#workspace-name"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-BNCT-Token": token,
      ...(options.headers || {}),
    },
  });
  let payload = {};
  try {
    payload = await response.json();
  } catch (_error) {
    payload = { error: `本地服务返回了非 JSON 响应 (${response.status})` };
  }
  if (!response.ok) {
    if (response.status === 401) {
      setConnection("offline", "会话已过期");
      throw new Error("本地会话已过期。请关闭此页面，并重新双击 Start-BNCT-Agent.cmd 打开工作台。");
    }
    throw new Error(payload.error || `请求失败 (${response.status})`);
  }
  return payload;
}

function showToast(message, kind = "info") {
  const toast = document.createElement("div");
  toast.className = `toast ${kind}`;
  toast.textContent = message;
  elements.toastStack.append(toast);
  window.setTimeout(() => toast.remove(), 4200);
}

function setConnection(mode, label) {
  elements.connection.className = `connection-state ${mode}`;
  elements.connectionLabel.textContent = label;
}

function setBusy(busy) {
  state.busy = busy;
  elements.send.disabled = busy;
  elements.prompt.disabled = busy;
  if (busy) {
    setConnection("busy", "Agent 工作中");
  } else if (state.config?.apiKeyConfigured) {
    setConnection("online", "模型已连接");
  } else {
    setConnection("offline", "离线模式");
  }
}

function updateConfig(config) {
  state.config = config;
  const parts = config.root.replaceAll("\\", "/").split("/").filter(Boolean);
  elements.workspaceName.textContent = parts.at(-1) || config.root;
  elements.workspaceName.parentElement.title = config.root;
  elements.modelPill.textContent = config.apiKeyConfigured ? `${config.providerLabel} · ${config.model}` : "未连接模型";
  elements.providerInputs.forEach((input) => { input.checked = input.value === config.provider; });
  syncProviderFields(config.provider, false);
  elements.model.value = config.model;
  elements.baseUrl.value = config.baseUrl || "";
  elements.root.value = config.root;
  setBusy(Boolean(config.busy));
}

function providerConfig(providerId) {
  return state.config?.providers?.find((provider) => provider.id === providerId) || null;
}

function selectedProvider() {
  return Array.from(elements.providerInputs).find((input) => input.checked)?.value || "openai";
}

function syncProviderFields(providerId, resetValues) {
  const provider = providerConfig(providerId);
  if (!provider) return;
  elements.modelOptions.replaceChildren(...provider.models.map((model) => {
    const option = document.createElement("option");
    option.value = model;
    return option;
  }));
  elements.providerHelpTitle.textContent = `${provider.label} 使用独立的 API Key`;
  elements.providerHelpText.textContent = `请在 ${provider.label} 官方平台创建密钥。环境变量名为 ${provider.keyEnv}，密钥仅保存在本次本机进程内。`;
  elements.providerKeyLink.href = provider.keyUrl;
  elements.providerDocsLink.href = provider.docsUrl;
  elements.apiKey.placeholder = `${provider.keyHint}（可留空以沿用本次配置）`;
  if (resetValues) {
    elements.model.value = provider.defaultModel;
    elements.baseUrl.value = provider.baseUrl;
  }
}

function hideEmptyState() {
  elements.emptyState.classList.add("hidden");
}

function safeLinkUrl(value) {
  try {
    const url = new URL(value, window.location.href);
    return ["http:", "https:"].includes(url.protocol) ? url.href : null;
  } catch (_error) {
    return null;
  }
}

function renderInline(container, source) {
  let remaining = String(source);
  const tokenPattern = /(`[^`\n]+`|\*\*[^*\n]+\*\*|__[^_\n]+__|~~[^~\n]+~~|\[[^\]\n]+\]\([^\s)]+\)|\*[^*\n]+\*|_[^_\n]+_)/;
  while (remaining) {
    const match = remaining.match(tokenPattern);
    if (!match) {
      container.append(document.createTextNode(remaining));
      return;
    }
    if (match.index > 0) container.append(document.createTextNode(remaining.slice(0, match.index)));
    const token = match[0];
    let element;
    if (token.startsWith("`")) {
      element = document.createElement("code");
      element.textContent = token.slice(1, -1);
    } else if (token.startsWith("**") || token.startsWith("__")) {
      element = document.createElement("strong");
      renderInline(element, token.slice(2, -2));
    } else if (token.startsWith("~~")) {
      element = document.createElement("del");
      renderInline(element, token.slice(2, -2));
    } else if (token.startsWith("[")) {
      const linkMatch = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      const href = linkMatch ? safeLinkUrl(linkMatch[2]) : null;
      if (href) {
        element = document.createElement("a");
        element.href = href;
        element.target = "_blank";
        element.rel = "noreferrer noopener";
        renderInline(element, linkMatch[1]);
      } else {
        element = document.createTextNode(linkMatch ? linkMatch[1] : token);
      }
    } else {
      element = document.createElement("em");
      renderInline(element, token.slice(1, -1));
    }
    container.append(element);
    remaining = remaining.slice((match.index || 0) + token.length);
  }
}

function isBlockStart(line, nextLine = "") {
  return /^\s*$/.test(line)
    || /^\s*```/.test(line)
    || /^\s{0,3}#{1,6}\s+/.test(line)
    || /^\s*>\s?/.test(line)
    || /^\s*(?:[-+*]|\d+[.)])\s+/.test(line)
    || /^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)
    || (/\|/.test(line) && /^\s*\|?\s*:?-{3,}/.test(nextLine));
}

function splitTableRow(line) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function renderMarkdown(container, text) {
  container.replaceChildren();
  container.classList.add("markdown-body");
  const lines = String(text).replace(/\r\n?/g, "\n").split("\n");
  let index = 0;
  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    const fence = line.match(/^\s*```\s*([^\s`]*)\s*$/);
    if (fence) {
      const codeLines = [];
      index += 1;
      while (index < lines.length && !/^\s*```\s*$/.test(lines[index])) {
        codeLines.push(lines[index]);
        index += 1;
      }
      if (index < lines.length) index += 1;
      const pre = document.createElement("pre");
      if (fence[1]) pre.dataset.language = fence[1];
      const code = document.createElement("code");
      code.textContent = codeLines.join("\n");
      pre.append(code);
      container.append(pre);
      continue;
    }

    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.+)$/);
    if (heading) {
      const node = document.createElement(`h${heading[1].length}`);
      renderInline(node, heading[2].replace(/\s+#+\s*$/, ""));
      container.append(node);
      index += 1;
      continue;
    }

    if (/^\s{0,3}(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      container.append(document.createElement("hr"));
      index += 1;
      continue;
    }

    if (/^\s*>\s?/.test(line)) {
      const quoted = [];
      while (index < lines.length && /^\s*>\s?/.test(lines[index])) {
        quoted.push(lines[index].replace(/^\s*>\s?/, ""));
        index += 1;
      }
      const blockquote = document.createElement("blockquote");
      renderMarkdown(blockquote, quoted.join("\n"));
      container.append(blockquote);
      continue;
    }

    const listMatch = line.match(/^\s*(?:([-+*])|(\d+)[.)])\s+(.+)$/);
    if (listMatch) {
      const ordered = Boolean(listMatch[2]);
      const list = document.createElement(ordered ? "ol" : "ul");
      if (ordered && Number(listMatch[2]) !== 1) list.start = Number(listMatch[2]);
      while (index < lines.length) {
        const itemMatch = lines[index].match(/^\s*(?:([-+*])|(\d+)[.)])\s+(.+)$/);
        if (!itemMatch || Boolean(itemMatch[2]) !== ordered) break;
        const item = document.createElement("li");
        renderInline(item, itemMatch[3]);
        list.append(item);
        index += 1;
      }
      container.append(list);
      continue;
    }

    if (/\|/.test(line) && index + 1 < lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[index + 1])) {
      const table = document.createElement("table");
      const thead = document.createElement("thead");
      const headerRow = document.createElement("tr");
      splitTableRow(line).forEach((cell) => {
        const th = document.createElement("th");
        renderInline(th, cell);
        headerRow.append(th);
      });
      thead.append(headerRow);
      table.append(thead);
      index += 2;
      const tbody = document.createElement("tbody");
      while (index < lines.length && lines[index].trim() && /\|/.test(lines[index])) {
        const row = document.createElement("tr");
        splitTableRow(lines[index]).forEach((cell) => {
          const td = document.createElement("td");
          renderInline(td, cell);
          row.append(td);
        });
        tbody.append(row);
        index += 1;
      }
      table.append(tbody);
      container.append(table);
      continue;
    }

    const paragraphLines = [line];
    index += 1;
    while (index < lines.length && !isBlockStart(lines[index], lines[index + 1] || "")) {
      paragraphLines.push(lines[index]);
      index += 1;
    }
    const paragraph = document.createElement("p");
    renderInline(paragraph, paragraphLines.join("\n"));
    container.append(paragraph);
  }
}

function appendMessage(role, text, options = {}) {
  hideEmptyState();
  const article = document.createElement("article");
  article.className = `message ${role}`;
  if (options.id) article.id = options.id;

  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.textContent = role === "user" ? "你" : role === "system" ? "!" : "B";

  const body = document.createElement("div");
  body.className = "message-body";
  const meta = document.createElement("div");
  meta.className = "message-meta";
  meta.textContent = role === "user" ? "你" : role === "system" ? "系统" : "BNCT Agent";
  const content = document.createElement("div");
  content.className = "message-content";
  renderMarkdown(content, text);
  body.append(meta, content);
  article.append(avatar, body);
  elements.messageList.append(article);
  elements.conversation.scrollTo({ top: elements.conversation.scrollHeight, behavior: "smooth" });
  return article;
}

function appendTyping() {
  hideEmptyState();
  const article = document.createElement("article");
  article.className = "message assistant";
  article.id = "typing-message";
  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  avatar.textContent = "B";
  const body = document.createElement("div");
  body.className = "message-body";
  const meta = document.createElement("div");
  meta.className = "message-meta";
  meta.textContent = "BNCT Agent 正在思考";
  const typing = document.createElement("div");
  typing.className = "typing";
  typing.append(document.createElement("i"), document.createElement("i"), document.createElement("i"));
  body.append(meta, typing);
  article.append(avatar, body);
  elements.messageList.append(article);
  elements.conversation.scrollTo({ top: elements.conversation.scrollHeight, behavior: "smooth" });
}

function removeTyping() {
  document.querySelector("#typing-message")?.remove();
}

function resizePrompt() {
  elements.prompt.style.height = "auto";
  elements.prompt.style.height = `${Math.min(elements.prompt.scrollHeight, 170)}px`;
}

async function sendTask(prefilled = null) {
  const task = String(prefilled ?? elements.prompt.value).trim();
  if (!task || state.busy) return;
  if (!state.config?.apiKeyConfigured) {
    appendMessage("system", `需要先配置 ${state.config?.providerLabel || "模型供应商"} 的 API Key。请打开右上角设置，也可以切换到其他供应商。`);
    openSettings();
    return;
  }
  elements.prompt.value = "";
  resizePrompt();
  appendMessage("user", task);
  appendTyping();
  setBusy(true);
  try {
    const result = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({ task }),
    });
    removeTyping();
    appendMessage("assistant", result.answer);
  } catch (error) {
    removeTyping();
    appendMessage("system", `任务失败：${error.message}`);
  } finally {
    setBusy(false);
  }
}

function fileIcon(path) {
  const extension = path.includes(".") ? path.split(".").at(-1).toLowerCase() : "";
  if (["py", "js", "ts", "cpp", "cc", "c", "cs"].includes(extension)) return "◇";
  if (["json", "toml", "yaml", "yml", "xml"].includes(extension)) return "⌘";
  if (["md", "txt"].includes(extension)) return "≡";
  return "·";
}

function renderFiles(filter = "") {
  const needle = filter.trim().toLowerCase();
  elements.fileList.replaceChildren();
  const matching = state.files.filter((path) => path.toLowerCase().includes(needle));
  matching.forEach((path) => {
    const button = document.createElement("button");
    button.className = "file-item";
    button.type = "button";
    button.dataset.depth = String(Math.min(path.split("/").length - 1, 4));
    button.title = path;
    const icon = document.createElement("span");
    icon.className = "file-icon";
    icon.textContent = fileIcon(path);
    const name = document.createElement("span");
    name.className = "file-name";
    name.textContent = path.split("/").at(-1);
    button.append(icon, name);
    button.addEventListener("click", () => openPreview(path));
    elements.fileList.append(button);
  });
  elements.fileCount.textContent = String(matching.length);
}

async function loadFiles() {
  try {
    const result = await api("/api/files?limit=600");
    state.files = result.files || [];
    renderFiles(elements.fileSearch.value);
  } catch (error) {
    showToast(`无法读取工程文件：${error.message}`, "error");
  }
}

async function openPreview(path) {
  elements.previewTitle.textContent = path;
  elements.previewContent.textContent = "读取中...";
  elements.previewContent.classList.toggle("markdown-preview", path.toLowerCase().endsWith(".md"));
  elements.previewBackdrop.classList.remove("hidden");
  elements.previewDrawer.classList.remove("hidden");
  try {
    const result = await api(`/api/file?path=${encodeURIComponent(path)}`);
    if (path.toLowerCase().endsWith(".md")) {
      renderMarkdown(elements.previewContent, result.content);
    } else {
      elements.previewContent.classList.remove("markdown-body");
      elements.previewContent.replaceChildren();
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      code.textContent = result.content;
      pre.append(code);
      elements.previewContent.append(pre);
    }
  } catch (error) {
    elements.previewContent.textContent = `无法预览：${error.message}`;
  }
}

function closePreview() {
  elements.previewBackdrop.classList.add("hidden");
  elements.previewDrawer.classList.add("hidden");
}

function traceDescription(event) {
  const names = {
    agent_started: ["Agent 开始处理", "正在分析任务并规划工具调用"],
    agent_finished: ["Agent 已完成", "回答已返回到对话区"],
    approval_required: [event.tool || "等待审批", `风险等级：${event.risk || "unknown"}`],
    approval_resolved: [event.approved ? "操作已批准" : "操作已拒绝", event.tool || "受控工具"],
    session_configured: ["连接已更新", event.model || "新模型设置"],
    session_started: ["新会话", "上下文已清空"],
    tool_started: [event.tool || "工具调用", `风险等级：${event.risk || "read"}`],
    tool_finished: [event.tool || "工具完成", event.ok ? "执行成功" : `执行失败：${event.error_type || "unknown"}`],
  };
  return names[event.type] || [event.type || "活动", ""];
}

function appendTrace(event) {
  elements.activityList.querySelector(".activity-empty")?.remove();
  const [title, description] = traceDescription(event);
  const item = document.createElement("div");
  let tone = "";
  if (event.type === "tool_finished") tone = event.ok ? "success" : "error";
  if (event.type?.includes("approval")) tone = "warning";
  if (event.type === "agent_finished") tone = "success";
  item.className = `trace-event ${tone}`;
  const timestamp = document.createElement("span");
  timestamp.className = "trace-time";
  timestamp.textContent = event.timestamp || "now";
  const strong = document.createElement("strong");
  strong.textContent = title;
  const p = document.createElement("p");
  p.textContent = description;
  item.append(timestamp, strong, p);
  elements.activityList.append(item);
  elements.activityList.scrollTo({ top: elements.activityList.scrollHeight, behavior: "smooth" });
}

async function pollEvents() {
  try {
    const result = await api(`/api/events?since=${state.lastEventId}`);
    for (const event of result.events || []) {
      state.lastEventId = Math.max(state.lastEventId, Number(event.id) || 0);
      appendTrace(event);
    }
    await pollApprovals();
  } catch (_error) {
    // The server can be briefly unavailable while restarting. The next poll retries.
  }
}

async function pollApprovals() {
  if (state.currentApproval) return;
  const result = await api("/api/approvals");
  const approval = (result.approvals || [])[0];
  if (!approval) return;
  state.currentApproval = approval;
  elements.approvalTool.textContent = approval.tool;
  elements.approvalRisk.textContent = approval.risk;
  elements.approvalArguments.textContent = JSON.stringify(approval.arguments, null, 2);
  elements.approvalModal.classList.remove("hidden");
}

async function resolveApproval(approved) {
  if (!state.currentApproval) return;
  const approval = state.currentApproval;
  state.currentApproval = null;
  elements.approvalModal.classList.add("hidden");
  try {
    await api("/api/approval", {
      method: "POST",
      body: JSON.stringify({ id: approval.id, approved }),
    });
  } catch (error) {
    showToast(error.message, "error");
  }
}

function openSettings() {
  if (state.config) {
    elements.providerInputs.forEach((input) => { input.checked = input.value === state.config.provider; });
    syncProviderFields(state.config.provider, false);
    elements.model.value = state.config.model;
    elements.baseUrl.value = state.config.baseUrl || "";
    elements.root.value = state.config.root;
  }
  elements.apiKey.value = "";
  elements.settingsModal.classList.remove("hidden");
  window.setTimeout(() => elements.apiKey.focus(), 50);
}

function closeSettings() {
  elements.settingsModal.classList.add("hidden");
}

async function saveSettings(event) {
  event.preventDefault();
  const payload = {
    provider: selectedProvider(),
    apiKey: elements.apiKey.value.trim(),
    model: elements.model.value.trim(),
    baseUrl: elements.baseUrl.value.trim(),
    root: elements.root.value.trim(),
  };
  try {
    const config = await api("/api/config", { method: "POST", body: JSON.stringify(payload) });
    updateConfig(config);
    closeSettings();
    await loadFiles();
    appendMessage("system", "连接设置已更新。API Key 仅保存在当前本机进程内。关闭服务后需要重新输入。 ");
    showToast("连接设置已保存");
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function pickProjectFolder() {
  if (state.busy) {
    showToast("当前任务仍在执行，请稍后选择工程目录", "error");
    return;
  }
  elements.browseFolder.disabled = true;
  elements.browseFolderLabel.textContent = "等待选择...";
  try {
    const result = await api("/api/pick-folder", {
      method: "POST",
      body: JSON.stringify({ initial: elements.root.value.trim() }),
    });
    if (result.path) {
      elements.root.value = result.path;
      showToast("已选择工程目录，点击保存后生效");
    }
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    elements.browseFolder.disabled = false;
    elements.browseFolderLabel.textContent = "打开文件夹";
  }
}

async function newSession() {
  if (state.busy) {
    showToast("当前任务仍在执行", "error");
    return;
  }
  try {
    const config = await api("/api/new-session", { method: "POST", body: "{}" });
    updateConfig(config);
    state.lastEventId = 0;
    elements.messageList.replaceChildren();
    elements.emptyState.classList.remove("hidden");
    elements.activityList.innerHTML = '<div class="activity-empty"><div class="pulse-ring"></div><strong>等待任务</strong><span>工具调用与审批会显示在这里</span></div>';
    showToast("已开始新会话");
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function offlineDemo() {
  if (state.busy) return;
  setBusy(true);
  appendMessage("user", "校验示例脱敏计划快照（离线）");
  appendTyping();
  try {
    const result = await api("/api/offline-demo", { method: "POST", body: "{}" });
    removeTyping();
    appendMessage("assistant", `离线校验完成。\n\n\`\`\`json\n${JSON.stringify(result, null, 2)}\n\`\`\``);
  } catch (error) {
    removeTyping();
    appendMessage("system", `离线校验失败：${error.message}`);
  } finally {
    setBusy(false);
  }
}

function bindEvents() {
  elements.send.addEventListener("click", () => sendTask());
  elements.prompt.addEventListener("input", resizePrompt);
  elements.prompt.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      sendTask();
    }
  });
  elements.fileSearch.addEventListener("input", () => renderFiles(elements.fileSearch.value));
  elements.settingsButton.addEventListener("click", openSettings);
  elements.browseFolder.addEventListener("click", pickProjectFolder);
  elements.providerInputs.forEach((input) => input.addEventListener("change", () => {
    if (input.checked) syncProviderFields(input.value, true);
  }));
  elements.settingsForm.addEventListener("submit", saveSettings);
  document.querySelectorAll(".close-modal").forEach((button) => button.addEventListener("click", closeSettings));
  elements.newSession.addEventListener("click", newSession);
  elements.snapshotDemo.addEventListener("click", offlineDemo);
  elements.clearActivity.addEventListener("click", () => elements.activityList.replaceChildren());
  elements.closePreview.addEventListener("click", closePreview);
  elements.previewBackdrop.addEventListener("click", closePreview);
  elements.allowApproval.addEventListener("click", () => resolveApproval(true));
  elements.denyApproval.addEventListener("click", () => resolveApproval(false));
  document.querySelectorAll("[data-task]").forEach((button) => {
    button.addEventListener("click", () => sendTask(button.dataset.task));
  });
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closePreview();
      if (!elements.settingsModal.classList.contains("hidden")) closeSettings();
    }
  });
}

async function initialize() {
  bindEvents();
  if (!token) {
    appendMessage("system", "缺少本地会话令牌。请通过 Start-BNCT-Agent.cmd 重新打开工作台。 ");
    setConnection("offline", "未授权");
    return;
  }
  try {
    const config = await api("/api/config");
    updateConfig(config);
    await loadFiles();
    state.eventTimer = window.setInterval(pollEvents, 650);
    pollEvents();
  } catch (error) {
    appendMessage("system", `无法连接本地 Agent 服务：${error.message}`);
    setConnection("offline", "服务不可用");
  }
}

initialize();
