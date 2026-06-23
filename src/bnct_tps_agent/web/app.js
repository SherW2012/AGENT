"use strict";

const token = new URLSearchParams(window.location.hash.slice(1)).get("token") || "";
const MAX_ATTACHMENTS = 5;
const MAX_ATTACHMENT_BYTES = 750_000;
const MAX_DICOM_HEADER_BYTES = 1_500_000;
const TEXT_ATTACHMENT_PATTERN = /\.(txt|md|json|csv|log|py|js|ts|tsx|html|css|xml|yaml|yml|toml|ini|cfg)$/i;
const DICOM_ATTACHMENT_PATTERN = /\.(dcm|dicom)$/i;

const state = {
  config: null,
  files: [],
  skills: [],
  sessions: [],
  currentSessionId: null,
  currentApproval: null,
  pendingAttachments: [],
  busy: false,
  eventTimer: null,
};

const elements = {
  appShell: document.querySelector(".app-shell"),
  allowApproval: document.querySelector("#allow-approval-button"),
  apiKey: document.querySelector("#api-key-input"),
  approvalArguments: document.querySelector("#approval-arguments"),
  approvalModal: document.querySelector("#approval-modal"),
  approvalRisk: document.querySelector("#approval-risk"),
  approvalTool: document.querySelector("#approval-tool"),
  attachButton: document.querySelector("#attach-button"),
  attachmentInput: document.querySelector("#attachment-input"),
  attachmentList: document.querySelector("#attachment-list"),
  baseUrl: document.querySelector("#base-url-input"),
  browseFolder: document.querySelector("#browse-folder-button"),
  browseFolderLabel: document.querySelector("#browse-folder-label"),
  closePreview: document.querySelector("#close-preview-button"),
  connection: document.querySelector("#connection-state"),
  connectionLabel: document.querySelector("#connection-label"),
  conversation: document.querySelector("#conversation-scroll"),
  denyApproval: document.querySelector("#deny-approval-button"),
  emptyState: document.querySelector("#empty-state"),
  fileCount: document.querySelector("#file-count"),
  fileList: document.querySelector("#file-list"),
  fileSearch: document.querySelector("#file-search"),
  importSkill: document.querySelector("#import-skill-button"),
  memoryPill: document.querySelector("#memory-pill"),
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
  sessionCount: document.querySelector("#session-count"),
  sessionList: document.querySelector("#session-list"),
  sessionSearch: document.querySelector("#session-search"),
  settingsButton: document.querySelector("#settings-button"),
  settingsForm: document.querySelector("#settings-form"),
  settingsModal: document.querySelector("#settings-modal"),
  sidebarExpand: document.querySelector("#sidebar-expand-button"),
  sidebarToggle: document.querySelector("#sidebar-toggle"),
  skillCount: document.querySelector("#skill-count"),
  skillList: document.querySelector("#skill-list"),
  toastStack: document.querySelector("#toast-stack"),
  workspaceChip: document.querySelector("#workspace-chip"),
  workspaceName: document.querySelector("#workspace-name"),
  workspacePath: document.querySelector("#workspace-path"),
  workspaceSwitch: document.querySelector("#workspace-switch-button"),
};

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        "X-BNCT-Token": token,
        ...(options.headers || {}),
      },
    });
  } catch (error) {
    throw new Error(`无法连接本地服务。若刚上传了附件，可能是文件过大或服务正在重启：${error.message}`);
  }
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
  elements.attachButton.disabled = busy;
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
  state.skills = config.skills || [];
  state.currentSessionId = config.currentSessionId || state.currentSessionId;
  const parts = config.root.replaceAll("\\", "/").split("/").filter(Boolean);
  elements.workspaceName.textContent = parts.at(-1) || config.root;
  elements.workspacePath.textContent = config.root;
  elements.workspaceChip.title = config.root;
  elements.modelPill.textContent = config.apiKeyConfigured ? `${config.providerLabel} · ${config.model}` : "未连接模型";
  if (config.memory) {
    elements.memoryPill.title = `项目记忆：${config.memory.projectFile}\n本地记忆：${config.memory.localFile}`;
  }
  elements.providerInputs.forEach((input) => { input.checked = input.value === config.provider; });
  syncProviderFields(config.provider, false);
  elements.model.value = config.model;
  elements.baseUrl.value = config.baseUrl || "";
  elements.root.value = config.root;
  renderSkills();
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

function showEmptyState() {
  elements.emptyState.classList.remove("hidden");
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
    const tokenText = match[0];
    let element;
    if (tokenText.startsWith("`")) {
      element = document.createElement("code");
      element.textContent = tokenText.slice(1, -1);
    } else if (tokenText.startsWith("**") || tokenText.startsWith("__")) {
      element = document.createElement("strong");
      renderInline(element, tokenText.slice(2, -2));
    } else if (tokenText.startsWith("~~")) {
      element = document.createElement("del");
      renderInline(element, tokenText.slice(2, -2));
    } else if (tokenText.startsWith("[")) {
      const linkMatch = tokenText.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      const href = linkMatch ? safeLinkUrl(linkMatch[2]) : null;
      if (href) {
        element = document.createElement("a");
        element.href = href;
        element.target = "_blank";
        element.rel = "noreferrer noopener";
        renderInline(element, linkMatch[1]);
      } else {
        element = document.createTextNode(linkMatch ? linkMatch[1] : tokenText);
      }
    } else {
      element = document.createElement("em");
      renderInline(element, tokenText.slice(1, -1));
    }
    container.append(element);
    remaining = remaining.slice((match.index || 0) + tokenText.length);
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

function attachmentLabel(item) {
  const size = Number(item.size || 0);
  const kind = item.kind === "dicom" ? "DICOM" : item.kind === "binary" ? "Binary" : "Text";
  const sizeText = size > 1024 ? `${Math.round(size / 1024)} KB` : `${size} B`;
  return `${item.name || "附件"} · ${kind} · ${sizeText}`;
}

function renderMessageAttachments(container, attachments = []) {
  if (!attachments.length) return;
  const wrap = document.createElement("div");
  wrap.className = "message-attachments";
  attachments.forEach((item) => {
    const chip = document.createElement("span");
    chip.className = "message-attachment";
    chip.textContent = attachmentLabel(item);
    wrap.append(chip);
  });
  container.append(wrap);
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
  renderMessageAttachments(body, options.attachments || []);
  article.append(avatar, body);
  elements.messageList.append(article);
  if (options.scroll !== false) {
    elements.conversation.scrollTo({ top: elements.conversation.scrollHeight, behavior: "smooth" });
  }
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
  elements.prompt.style.height = `${Math.min(elements.prompt.scrollHeight, 190)}px`;
}

function renderSessionList() {
  elements.sessionList.replaceChildren();
  elements.sessionCount.textContent = String(state.sessions.length);
  if (!state.sessions.length) {
    const empty = document.createElement("div");
    empty.className = "session-empty";
    empty.textContent = "暂无会话";
    elements.sessionList.append(empty);
    return;
  }

  state.sessions.forEach((session) => {
    const item = document.createElement("button");
    item.className = `session-item ${session.id === state.currentSessionId ? "active" : ""}`;
    item.type = "button";
    item.title = session.title;

    const main = document.createElement("span");
    main.className = "session-main";
    const title = document.createElement("strong");
    title.textContent = session.title || "未命名会话";
    const preview = document.createElement("small");
    preview.textContent = session.preview || session.displayTime || "";
    main.append(title, preview);

    const actions = document.createElement("span");
    actions.className = "session-item-actions";
    const favorite = document.createElement("button");
    favorite.className = `session-mini-button ${session.favorite ? "favorited" : ""}`;
    favorite.type = "button";
    favorite.title = session.favorite ? "取消置顶" : "收藏置顶";
    favorite.textContent = session.favorite ? "★" : "☆";
    favorite.addEventListener("click", (event) => {
      event.stopPropagation();
      setSessionFavorite(session.id, !session.favorite);
    });
    const remove = document.createElement("button");
    remove.className = "session-mini-button";
    remove.type = "button";
    remove.title = "删除会话";
    remove.textContent = "×";
    remove.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteSession(session.id, session.title);
    });
    actions.append(favorite, remove);

    item.append(main, actions);
    item.addEventListener("click", () => selectSession(session.id));
    elements.sessionList.append(item);
  });
}

async function loadSessions(query = elements.sessionSearch.value) {
  const result = await api(`/api/sessions?query=${encodeURIComponent(query || "")}`);
  state.sessions = result.sessions || [];
  state.currentSessionId = result.currentSessionId || state.currentSessionId;
  renderSessionList();
}

function renderConversation(session) {
  state.currentSessionId = session.id;
  elements.messageList.replaceChildren();
  const messages = session.messages || [];
  if (!messages.length) {
    showEmptyState();
  } else {
    hideEmptyState();
    messages.forEach((message) => {
      appendMessage(message.role, message.content || "", {
        id: message.id,
        attachments: message.attachments || [],
        scroll: false,
      });
    });
    window.setTimeout(() => {
      elements.conversation.scrollTo({ top: elements.conversation.scrollHeight });
    }, 0);
  }
  renderSessionList();
}

async function loadCurrentSession(sessionId = state.currentSessionId) {
  const query = sessionId ? `?id=${encodeURIComponent(sessionId)}` : "";
  const result = await api(`/api/session${query}`);
  state.currentSessionId = result.currentSessionId || result.session?.id;
  renderConversation(result.session);
}

async function selectSession(sessionId) {
  if (sessionId === state.currentSessionId || state.busy) return;
  try {
    const result = await api("/api/session/select", {
      method: "POST",
      body: JSON.stringify({ id: sessionId }),
    });
    updateConfig(result.config);
    renderConversation(result.session);
    await loadSessions();
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function setSessionFavorite(sessionId, favorite) {
  try {
    const result = await api("/api/session/favorite", {
      method: "POST",
      body: JSON.stringify({ id: sessionId, favorite }),
    });
    state.sessions = result.sessions || [];
    renderSessionList();
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function deleteSession(sessionId, title) {
  if (!window.confirm(`删除会话「${title || "未命名会话"}」？`)) return;
  try {
    const result = await api("/api/session/delete", {
      method: "POST",
      body: JSON.stringify({ id: sessionId }),
    });
    updateConfig(result.config);
    state.sessions = result.sessions || [];
    renderSessionList();
    await loadCurrentSession(result.currentSessionId);
    showToast("会话已删除");
  } catch (error) {
    showToast(error.message, "error");
  }
}

async function newSession() {
  if (state.busy) {
    showToast("当前任务仍在执行", "error");
    return;
  }
  try {
    const result = await api("/api/sessions", { method: "POST", body: "{}" });
    updateConfig(result.config);
    renderConversation(result.session);
    await loadSessions();
    showToast("已开始新会话");
  } catch (error) {
    showToast(error.message, "error");
  }
}

function fileIcon(path) {
  const extension = path.includes(".") ? path.split(".").at(-1).toLowerCase() : "";
  if (["py", "js", "ts", "cpp", "cc", "c", "cs"].includes(extension)) return "◇";
  if (["json", "toml", "yaml", "yml", "xml"].includes(extension)) return "⌘";
  if (["md", "txt", "log", "csv"].includes(extension)) return "≡";
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

function skillTone(skill, index) {
  if (skill.hasProcessor) return "amber";
  if (skill.trusted) return "green";
  return ["violet", "green", "accent", "red"][index % 4];
}

function skillInitial(skill) {
  const name = String(skill.displayName || skill.name || "?").trim();
  return (name[0] || "?").toUpperCase();
}

function renderSkills() {
  elements.skillList.replaceChildren();
  const skills = state.skills || [];
  elements.skillCount.textContent = String(skills.length);
  if (!skills.length) {
    const empty = document.createElement("div");
    empty.className = "session-empty";
    empty.textContent = "暂无 skill";
    elements.skillList.append(empty);
    return;
  }
  skills.forEach((skill, index) => {
    const button = document.createElement("button");
    button.className = "skill-action";
    button.type = "button";
    button.title = `${skill.name}\n${skill.description || ""}`;
    const icon = document.createElement("span");
    icon.className = `skill-icon ${skillTone(skill, index)}`;
    icon.textContent = skillInitial(skill);
    const copy = document.createElement("span");
    const title = document.createElement("strong");
    title.textContent = skill.displayName || skill.name;
    const subtitle = document.createElement("small");
    subtitle.textContent = skill.shortDescription || skill.description || skill.path;
    copy.append(title, subtitle);
    button.append(icon, copy);
    button.addEventListener("click", () => {
      const prompt = skill.defaultPrompt || `请读取并使用 ${skill.name} skill 处理当前任务。`;
      sendTask(prompt);
    });
    elements.skillList.append(button);
  });
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

function renderPendingAttachments() {
  elements.attachmentList.replaceChildren();
  elements.attachmentList.classList.toggle("hidden", state.pendingAttachments.length === 0);
  state.pendingAttachments.forEach((item, index) => {
    const chip = document.createElement("span");
    chip.className = "attachment-chip";
    const label = document.createElement("span");
    label.textContent = attachmentLabel(item);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.title = "移除附件";
    remove.addEventListener("click", () => {
      state.pendingAttachments.splice(index, 1);
      renderPendingAttachments();
    });
    chip.append(label, remove);
    elements.attachmentList.append(chip);
  });
}

async function addAttachments(files) {
  const selected = Array.from(files || []);
  if (state.pendingAttachments.length + selected.length > MAX_ATTACHMENTS) {
    showToast(`一次最多上传 ${MAX_ATTACHMENTS} 个附件`, "error");
    return;
  }
  for (const file of selected) {
    try {
      const attachment = await readAttachment(file);
      state.pendingAttachments.push(attachment);
    } catch (_error) {
      showToast(`${file.name} 无法读取：${_error.message}`, "error");
    }
  }
  elements.attachmentInput.value = "";
  renderPendingAttachments();
}

function isDicomFile(file) {
  return DICOM_ATTACHMENT_PATTERN.test(file.name) || ["application/dicom", "application/x-dicom"].includes(file.type);
}

function isTextFile(file) {
  return file.type.startsWith("text/") || TEXT_ATTACHMENT_PATTERN.test(file.name);
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    const chunk = bytes.subarray(offset, offset + chunkSize);
    binary += String.fromCharCode(...chunk);
  }
  return window.btoa(binary);
}

async function readAttachment(file) {
  if (isDicomFile(file)) {
    const slice = file.slice(0, Math.min(file.size, MAX_DICOM_HEADER_BYTES));
    const content = arrayBufferToBase64(await slice.arrayBuffer());
    return {
      name: file.name,
      type: file.type || "application/dicom",
      size: slice.size,
      originalSize: file.size,
      encoding: "base64",
      kind: "dicom",
      content,
    };
  }
  if (isTextFile(file)) {
    if (file.size > MAX_ATTACHMENT_BYTES) {
      throw new Error(`文本附件超过 ${Math.round(MAX_ATTACHMENT_BYTES / 1024)} KB`);
    }
    return {
      name: file.name,
      type: file.type || "text/plain",
      size: file.size,
      encoding: "text",
      kind: "text",
      content: await file.text(),
    };
  }
  if (file.size > MAX_ATTACHMENT_BYTES) {
    throw new Error(`二进制附件超过 ${Math.round(MAX_ATTACHMENT_BYTES / 1024)} KB`);
  }
  return {
    name: file.name,
    type: file.type || "application/octet-stream",
    size: file.size,
    originalSize: file.size,
    encoding: "base64",
    kind: "binary",
    content: arrayBufferToBase64(await file.arrayBuffer()),
  };
}

function storedAttachmentMetadata(items) {
  return items.map((item) => ({
    name: item.name,
    type: item.type,
    size: item.originalSize || item.size,
    chars: String(item.content || "").length,
    kind: item.kind || "text",
  }));
}

async function sendTask(prefilled = null) {
  const task = String(prefilled ?? elements.prompt.value).trim();
  if (!task || state.busy) return;
  if (!state.config?.apiKeyConfigured) {
    appendMessage("system", `需要先配置 ${state.config?.providerLabel || "模型供应商"} 的 API Key。请打开左侧连接设置，也可以切换到其他供应商。`);
    openSettings();
    return;
  }
  const attachments = [...state.pendingAttachments];
  const attachmentMetadata = storedAttachmentMetadata(attachments);
  state.pendingAttachments = [];
  renderPendingAttachments();
  elements.prompt.value = "";
  resizePrompt();
  appendMessage("user", task, { attachments: attachmentMetadata });
  appendTyping();
  setBusy(true);
  try {
    const result = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        sessionId: state.currentSessionId,
        task,
        attachments,
      }),
    });
    removeTyping();
    appendMessage("assistant", result.answer);
    if (result.session) {
      state.currentSessionId = result.session.id;
    }
    await loadSessions();
  } catch (error) {
    removeTyping();
    appendMessage("system", `任务失败：${error.message}`);
  } finally {
    setBusy(false);
  }
}

async function pollEvents() {
  try {
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
    await loadSessions();
    await loadCurrentSession(config.currentSessionId);
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

async function switchWorkspaceFolder() {
  if (state.busy) {
    showToast("当前任务仍在执行，请稍后切换工作目录", "error");
    return;
  }
  if (!state.config) return;
  elements.workspaceSwitch.disabled = true;
  try {
    const picked = await api("/api/pick-folder", {
      method: "POST",
      body: JSON.stringify({ initial: state.config.root, title: "切换 BNCT Agent 工作目录" }),
    });
    if (!picked.path) return;
    const config = await api("/api/config", {
      method: "POST",
      body: JSON.stringify({
        provider: state.config.provider,
        model: state.config.model,
        baseUrl: state.config.baseUrl || "",
        apiKey: "",
        root: picked.path,
      }),
    });
    updateConfig(config);
    await loadFiles();
    await loadSessions();
    await loadCurrentSession(config.currentSessionId);
    appendMessage("system", `工作目录已切换到：\`${picked.path}\``);
    showToast("工作目录已切换");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    elements.workspaceSwitch.disabled = false;
  }
}

async function importSkill() {
  if (state.busy) {
    showToast("当前任务仍在执行，请稍后导入 skill", "error");
    return;
  }
  elements.importSkill.disabled = true;
  try {
    const result = await api("/api/import-skill", {
      method: "POST",
      body: JSON.stringify({ initial: state.config?.root || "" }),
    });
    if (result.cancelled) {
      showToast("已取消导入");
      return;
    }
    updateConfig(result.config);
    showToast(`已导入 skill：${result.skill.name}`);
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    elements.importSkill.disabled = false;
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

function toggleSidebar(collapsed) {
  elements.appShell.classList.toggle("sidebar-collapsed", collapsed);
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
  elements.attachButton.addEventListener("click", () => elements.attachmentInput.click());
  elements.attachmentInput.addEventListener("change", () => addAttachments(elements.attachmentInput.files));
  elements.fileSearch.addEventListener("input", () => renderFiles(elements.fileSearch.value));
  elements.sessionSearch.addEventListener("input", () => loadSessions(elements.sessionSearch.value));
  elements.settingsButton.addEventListener("click", openSettings);
  elements.browseFolder.addEventListener("click", pickProjectFolder);
  elements.providerInputs.forEach((input) => input.addEventListener("change", () => {
    if (input.checked) syncProviderFields(input.value, true);
  }));
  elements.settingsForm.addEventListener("submit", saveSettings);
  document.querySelectorAll(".close-modal").forEach((button) => button.addEventListener("click", closeSettings));
  elements.newSession.addEventListener("click", newSession);
  elements.importSkill.addEventListener("click", importSkill);
  elements.workspaceSwitch.addEventListener("click", switchWorkspaceFolder);
  elements.closePreview.addEventListener("click", closePreview);
  elements.previewBackdrop.addEventListener("click", closePreview);
  elements.allowApproval.addEventListener("click", () => resolveApproval(true));
  elements.denyApproval.addEventListener("click", () => resolveApproval(false));
  elements.sidebarToggle.addEventListener("click", () => toggleSidebar(true));
  elements.sidebarExpand.addEventListener("click", () => toggleSidebar(false));
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
    await Promise.all([loadFiles(), loadSessions()]);
    await loadCurrentSession(config.currentSessionId);
    state.eventTimer = window.setInterval(pollEvents, 650);
    pollEvents();
  } catch (error) {
    appendMessage("system", `无法连接本地 Agent 服务：${error.message}`);
    setConnection("offline", "服务不可用");
  }
}

initialize();
