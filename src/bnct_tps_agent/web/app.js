"use strict";

const token = new URLSearchParams(window.location.hash.slice(1)).get("token") || "";
const MAX_ATTACHMENTS = 5;
const MAX_ATTACHMENT_BYTES = 750_000;
const MAX_IMAGE_ATTACHMENT_BYTES = 1_500_000;
const MAX_DICOM_HEADER_BYTES = 1_500_000;
const LONG_PASTE_CHAR_THRESHOLD = 4_000;
const MAX_PASTED_TEXT_CHARS = 180_000;
const TEXT_ATTACHMENT_PATTERN = /\.(txt|md|json|csv|log|py|js|ts|tsx|html|css|xml|yaml|yml|toml|ini|cfg)$/i;
const DICOM_ATTACHMENT_PATTERN = /\.(dcm|dicom)$/i;
const ARCHIVE_ATTACHMENT_PATTERN = /\.zip$/i;
const MAX_ARCHIVE_ATTACHMENT_BYTES = 1_500_000;
const PDF_ATTACHMENT_PATTERN = /\.pdf$/i;
const MAX_PDF_ATTACHMENT_BYTES = 1_500_000;

const state = {
  config: null,
  files: [],
  skills: [],
  sessions: [],
  currentSessionId: null,
  currentApproval: null,
  pendingAttachments: [],
  activeDraft: null,
  busy: false,
  eventTimer: null,
  lastEventId: 0,
  abortController: null,
  stopped: false,
  lastSubmission: null,
  dragDepth: 0,
  selectMode: false,
  selectedSessions: new Set(),
  // Claude-style follow: keep pinned to the bottom while streaming, but stop
  // following as soon as the user scrolls up, and resume when they return.
  stickToBottom: true,
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
  settingsSections: document.querySelectorAll("[data-settings-section-panel]"),
  settingsTabs: document.querySelectorAll("[data-settings-section]"),
  sidebarExpand: document.querySelector("#sidebar-expand-button"),
  sidebarToggle: document.querySelector("#sidebar-toggle"),
  skillCount: document.querySelector("#skill-count"),
  skillList: document.querySelector("#skill-list"),
  openSkillsModal: document.querySelector("#open-skills-modal"),
  skillsModal: document.querySelector("#skills-modal"),
  skillsGrid: document.querySelector("#skills-grid"),
  sessionManage: document.querySelector("#session-manage-button"),
  sessionSelectBar: document.querySelector("#session-select-bar"),
  sessionSelectAll: document.querySelector("#session-select-all"),
  sessionDeleteSelected: document.querySelector("#session-delete-selected"),
  sessionManageDone: document.querySelector("#session-manage-done"),
  uiBlocker: document.querySelector("#ui-blocker"),
  uiBlockerLabel: document.querySelector("#ui-blocker-label"),
  toastStack: document.querySelector("#toast-stack"),
  webSearchInputs: document.querySelectorAll('input[name="web-search-mode"]'),
  webSearchNetworkInputs: document.querySelectorAll('input[name="web-search-network"]'),
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

async function streamApi(path, payload, onEvent, signal) {
  let response;
  try {
    response = await fetch(path, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-BNCT-Token": token,
      },
      body: JSON.stringify(payload),
      signal,
    });
  } catch (error) {
    if (error.name === "AbortError") throw error;
    throw new Error(`无法连接本地服务：${error.message}`);
  }
  if (!response.ok) {
    let errorPayload = {};
    try {
      errorPayload = await response.json();
    } catch (_error) {
      errorPayload = { error: `本地服务返回了非 JSON 响应 (${response.status})` };
    }
    if (response.status === 401) {
      setConnection("offline", "会话已过期");
      throw new Error("本地会话已过期。请关闭此页面，并重新双击 Start-BNCT-Agent.cmd 打开工作台。");
    }
    throw new Error(errorPayload.error || `请求失败 (${response.status})`);
  }
  if (!response.body) {
    throw new Error("当前浏览器不支持流式响应读取");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      const event = JSON.parse(trimmed);
      if (event.type === "error") {
        throw new Error(event.error || "任务失败");
      }
      onEvent(event);
    }
  }
  buffer += decoder.decode();
  const trailing = buffer.trim();
  if (trailing) {
    const event = JSON.parse(trailing);
    if (event.type === "error") {
      throw new Error(event.error || "任务失败");
    }
    onEvent(event);
  }
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
  // The send button doubles as a stop button while the agent is working, so it
  // stays enabled (clicking it interrupts) instead of being greyed out.
  elements.send.classList.toggle("is-busy", busy);
  elements.send.setAttribute("aria-label", busy ? "停止生成" : "发送任务");
  elements.send.title = busy ? "停止生成" : "";
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
  const eventScopeChanged = !state.config
    || state.config.root !== config.root
    || state.config.currentSessionId !== config.currentSessionId;
  state.config = config;
  if (eventScopeChanged) state.lastEventId = 0;
  state.skills = config.skills || [];
  state.currentSessionId = config.currentSessionId || state.currentSessionId;
  const parts = config.root.replaceAll("\\", "/").split("/").filter(Boolean);
  elements.workspaceName.textContent = parts.at(-1) || config.root;
  elements.workspacePath.textContent = config.root;
  elements.workspaceChip.title = config.root;
  elements.modelPill.textContent = config.apiKeyConfigured ? `${config.providerLabel} · ${config.model}` : "未连接模型";
  elements.providerInputs.forEach((input) => { input.checked = input.value === config.provider; });
  elements.webSearchInputs.forEach((input) => { input.checked = input.value === (config.webSearchMode || "auto"); });
  elements.webSearchNetworkInputs.forEach((input) => { input.checked = input.value === (config.webSearchNetwork || "auto"); });
  syncProviderFields(config.provider, false);
  elements.model.value = config.model;
  elements.baseUrl.value = config.baseUrl || "";
  elements.root.value = config.root;
  renderSkills();
  renderSkillsGrid();
  setBusy(Boolean(config.busy));
}

function providerConfig(providerId) {
  return state.config?.providers?.find((provider) => provider.id === providerId) || null;
}

function selectedProvider() {
  return Array.from(elements.providerInputs).find((input) => input.checked)?.value || "openai";
}

function selectedWebSearchMode() {
  return Array.from(elements.webSearchInputs).find((input) => input.checked)?.value || "auto";
}

function selectedWebSearchNetwork() {
  return Array.from(elements.webSearchNetworkInputs).find((input) => input.checked)?.value || "auto";
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

// Lightweight, dependency-free syntax highlighter. The page runs under a strict
// CSP (script-src 'self'), so we cannot pull in a CDN highlighter; this keeps an
// IDE-like feel using token classes styled in styles.css. It never uses
// innerHTML — every token becomes a textContent span, so it is XSS-safe.
const HL_KEYWORDS = new Set([
  "abstract", "and", "as", "async", "await", "break", "case", "catch", "class",
  "const", "continue", "def", "default", "del", "do", "elif", "else", "enum",
  "except", "export", "extends", "final", "finally", "fn", "for", "from", "func",
  "function", "global", "if", "impl", "import", "in", "instanceof", "interface",
  "is", "lambda", "let", "match", "mut", "new", "nonlocal", "not", "or", "package",
  "pass", "private", "protected", "pub", "public", "raise", "return", "static",
  "struct", "super", "switch", "this", "throw", "trait", "try", "type", "typeof",
  "use", "var", "void", "while", "with", "yield", "where", "select", "from",
  "go", "defer", "chan", "map", "range", "module", "namespace", "using", "include",
]);
const HL_LITERALS = new Set([
  "true", "false", "null", "nil", "none", "undefined", "True", "False", "None",
  "self", "NaN", "Infinity",
]);
const HL_TOKEN_RE = /(\/\*[\s\S]*?\*\/|\/\/[^\n]*|#[^\n]*)|("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|(\b\d[\d_]*(?:\.\d+)?(?:[eE][+-]?\d+)?\b)|([A-Za-z_$][\w$]*)|([\s\S])/g;

function appendTokenSpan(parent, className, text) {
  const span = document.createElement("span");
  span.className = className;
  span.textContent = text;
  parent.append(span);
}

function highlightInto(codeElement, source) {
  codeElement.replaceChildren();
  const text = String(source);
  HL_TOKEN_RE.lastIndex = 0;
  let match;
  while ((match = HL_TOKEN_RE.exec(text)) !== null) {
    const full = match[0];
    if (match[1] !== undefined) {
      appendTokenSpan(codeElement, "hl-com", full);
    } else if (match[2] !== undefined) {
      appendTokenSpan(codeElement, "hl-str", full);
    } else if (match[3] !== undefined) {
      appendTokenSpan(codeElement, "hl-num", full);
    } else if (match[4] !== undefined) {
      if (HL_KEYWORDS.has(full)) {
        appendTokenSpan(codeElement, "hl-kw", full);
      } else if (HL_LITERALS.has(full)) {
        appendTokenSpan(codeElement, "hl-lit", full);
      } else if (/^\s*\(/.test(text.slice(HL_TOKEN_RE.lastIndex))) {
        appendTokenSpan(codeElement, "hl-fn", full);
      } else {
        codeElement.append(document.createTextNode(full));
      }
    } else {
      codeElement.append(document.createTextNode(full));
    }
  }
}

function fallbackCopy(text) {
  const area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.append(area);
  area.select();
  try {
    document.execCommand("copy");
  } finally {
    area.remove();
  }
}

async function copyText(text, button) {
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      fallbackCopy(text);
    }
    if (button) {
      const original = button.dataset.label || button.textContent;
      button.dataset.label = original;
      button.textContent = "已复制";
      button.classList.add("copied");
      window.setTimeout(() => {
        button.textContent = original;
        button.classList.remove("copied");
      }, 1400);
    } else {
      showToast("已复制");
    }
  } catch (error) {
    showToast(`复制失败：${error.message}`, "error");
  }
}

function makeCodeBlock(codeText, language) {
  const wrap = document.createElement("div");
  wrap.className = "code-block";
  const pre = document.createElement("pre");
  if (language) pre.dataset.language = language;
  const code = document.createElement("code");
  highlightInto(code, codeText);
  pre.append(code);
  const copyButton = document.createElement("button");
  copyButton.type = "button";
  copyButton.className = "code-copy-btn";
  copyButton.title = "复制代码";
  copyButton.textContent = "复制";
  copyButton.addEventListener("click", (event) => {
    event.stopPropagation();
    copyText(codeText, copyButton);
  });
  wrap.append(copyButton, pre);
  return wrap;
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
      container.append(makeCodeBlock(codeLines.join("\n"), fence[1] || ""));
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

function attachmentKindLabel(item) {
  return {
    dicom: "DICOM",
    image: "图片",
    binary: "文件",
    archive: "压缩包",
    pdf: "PDF",
    pasted: "粘贴文本",
    text: "文本",
  }[item.kind] || "文本";
}

function attachmentSizeText(item) {
  const size = Number(item.size || item.originalSize || 0);
  return size >= 1024 ? `${Math.round(size / 1024)} KB` : `${size} B`;
}

function attachmentExt(item) {
  const name = String(item.name || "");
  const dot = name.lastIndexOf(".");
  if (dot >= 0 && dot < name.length - 1) return name.slice(dot + 1).toUpperCase().slice(0, 4);
  return { image: "IMG", archive: "ZIP", dicom: "DCM", binary: "BIN", pasted: "TXT" }[item.kind] || "TXT";
}

function attachmentLabel(item) {
  return `${item.name || "附件"} · ${attachmentKindLabel(item)} · ${attachmentSizeText(item)}`;
}

function buildAttachmentCard(item, onRemove) {
  const card = document.createElement("div");
  card.className = "attachment-card";
  card.title = attachmentLabel(item);

  const thumb = document.createElement("div");
  thumb.className = "attachment-thumb";
  if (item.kind === "image" && item.content && item.encoding === "base64") {
    const img = document.createElement("img");
    img.src = `data:${item.type || "image/png"};base64,${item.content}`;
    img.alt = item.name || "image";
    thumb.classList.add("is-image");
    thumb.append(img);
  } else {
    thumb.classList.add(`kind-${item.kind || "text"}`);
    thumb.textContent = attachmentExt(item);
  }

  const meta = document.createElement("div");
  meta.className = "attachment-meta";
  const name = document.createElement("div");
  name.className = "attachment-cardname";
  name.textContent = item.name || "附件";
  const sub = document.createElement("div");
  sub.className = "attachment-sub";
  sub.textContent = `${attachmentKindLabel(item)} · ${attachmentSizeText(item)}`;
  meta.append(name, sub);
  card.append(thumb, meta);

  if (onRemove) {
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "attachment-remove";
    remove.title = "移除附件";
    remove.textContent = "×";
    remove.addEventListener("click", onRemove);
    card.append(remove);
  }
  return card;
}

function renderMessageAttachments(container, attachments = []) {
  if (!attachments.length) return;
  const wrap = document.createElement("div");
  wrap.className = "message-attachments";
  attachments.forEach((item) => wrap.append(buildAttachmentCard(item, null)));
  container.append(wrap);
}

function svgIcon(paths) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  (Array.isArray(paths) ? paths : [paths]).forEach((d) => {
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", d);
    svg.append(path);
  });
  return svg;
}

function addMessageActions(article, rawText, retryTask) {
  const body = article.querySelector(".message-body");
  if (!body) return;
  body.querySelector(".message-actions")?.remove();
  const row = document.createElement("div");
  row.className = "message-actions";

  const copyBtn = document.createElement("button");
  copyBtn.type = "button";
  copyBtn.className = "msg-action-btn";
  copyBtn.title = "复制回答";
  const copyLabel = document.createElement("span");
  copyLabel.textContent = "复制";
  copyBtn.append(svgIcon(["M9 9h9v11H9z", "M6 15H5V4h10v2"]), copyLabel);
  copyBtn.addEventListener("click", () => copyText(rawText, copyLabel));
  row.append(copyBtn);

  if (retryTask) {
    const retryBtn = document.createElement("button");
    retryBtn.type = "button";
    retryBtn.className = "msg-action-btn";
    retryBtn.title = "用同一问题重新生成";
    const retryLabel = document.createElement("span");
    retryLabel.textContent = "重试";
    retryBtn.append(svgIcon(["M20 11a8 8 0 1 0-2.1 5.4", "M20 5v6h-6"]), retryLabel);
    retryBtn.addEventListener("click", () => {
      if (state.busy) {
        showToast("当前任务仍在执行", "error");
        return;
      }
      sendTask(retryTask);
    });
    row.append(retryBtn);
  }
  body.append(row);
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
  // Must run after the body is attached to the article so the action row can
  // find ".message-body"; otherwise re-rendered history loses copy/retry.
  if (options.withActions) addMessageActions(article, text, options.retryTask);
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

function toolDisplayName(name) {
  const labels = {
    fetch_url: "读取网页",
    web_search: "联网搜索",
    install_agent_skill: "安装 Skill",
    list_agent_skills: "读取 Skill 列表",
    read_agent_skill: "读取 Skill",
    list_project_files: "浏览工作区",
    read_project_text: "读取文件",
    search_project_text: "搜索文件",
    write_project_text: "写入文件",
    run_unit_tests: "运行测试",
    validate_plan_snapshot: "校验计划快照",
    summarize_plan_snapshot: "摘要计划快照",
    create_word_document: "生成 Word 文档",
    create_powerpoint: "生成 PPT",
    create_excel: "生成 Excel",
    read_agent_memory: "读取记忆",
    append_agent_memory: "写入记忆",
  };
  return labels[name] || name || "工具调用";
}

function appendAssistantDraft() {
  const article = appendMessage("assistant", "", { id: "streaming-message" });
  const meta = article.querySelector(".message-meta");
  const content = article.querySelector(".message-content");
  meta.textContent = "BNCT Agent 正在处理";

  const activity = document.createElement("div");
  activity.className = "activity-panel";
  const title = document.createElement("div");
  title.className = "activity-title";
  const titleDot = document.createElement("span");
  const titleText = document.createElement("strong");
  titleText.textContent = "正在理解任务";
  title.append(titleDot, titleText);
  const list = document.createElement("div");
  list.className = "activity-list";
  activity.append(title, list);
  article.querySelector(".message-body").append(activity);

  state.activeDraft = {
    article,
    meta,
    content,
    activity,
    activityTitle: titleText,
    activityList: list,
    activities: [],
  };
  setActivity("agent", "正在理解任务", "active");
  return article;
}

function setDraftText(text) {
  if (!state.activeDraft) return;
  renderMarkdown(state.activeDraft.content, text);
  // Only auto-follow while the user is at the bottom; if they scrolled up to
  // read something, leave their viewport alone.
  if (state.stickToBottom) {
    elements.conversation.scrollTo({ top: elements.conversation.scrollHeight });
  }
}

function setActivity(key, label, status = "active", detail = "") {
  if (!state.activeDraft) return;
  const existing = state.activeDraft.activities.find((item) => item.key === key);
  const item = existing || { key, label, status, detail };
  item.label = label;
  item.status = status;
  item.detail = detail;
  if (!existing) state.activeDraft.activities.push(item);
  renderActivity();
}

function renderActivity() {
  if (!state.activeDraft) return;
  const active = state.activeDraft.activities.find((item) => item.status === "active");
  const waiting = state.activeDraft.activities.find((item) => item.status === "waiting");
  const current = waiting || active || state.activeDraft.activities.at(-1);
  state.activeDraft.activityTitle.textContent = current?.label || "正在处理";
  state.activeDraft.activityList.replaceChildren();
  const history = state.activeDraft.activities.filter((item) => item !== current).slice(-5);
  state.activeDraft.activityList.classList.toggle("hidden", history.length === 0);
  history.forEach((item) => {
    const row = document.createElement("div");
    row.className = `activity-item ${item.status}`;
    const dot = document.createElement("span");
    dot.className = "activity-dot";
    const text = document.createElement("span");
    text.textContent = item.detail ? `${item.label}：${item.detail}` : item.label;
    row.append(dot, text);
    state.activeDraft.activityList.append(row);
  });
}

function finalizeAssistantDraft(rawText = "", options = {}) {
  if (!state.activeDraft) return;
  const draft = state.activeDraft;
  draft.meta.textContent = options.stopped ? "BNCT Agent · 已停止" : "BNCT Agent";
  setActivity("agent", options.stopped ? "已停止" : "已完成", options.stopped ? "failed" : "done");
  draft.activity.classList.add("done");
  if (options.stopped) draft.activity.classList.add("failed");
  draft.article.removeAttribute("id");
  addMessageActions(draft.article, rawText, draft.task || "");
  state.activeDraft = null;
}

function failAssistantDraft(message) {
  if (!state.activeDraft) return;
  state.activeDraft.meta.textContent = "BNCT Agent 已中断";
  setActivity("agent", "任务失败", "failed", message);
  state.activeDraft.activity.classList.add("failed");
  state.activeDraft.article.removeAttribute("id");
  state.activeDraft = null;
}

function resizePrompt() {
  elements.prompt.style.height = "auto";
  elements.prompt.style.height = `${Math.min(elements.prompt.scrollHeight, 190)}px`;
}

function updateSessionSelectBar() {
  elements.sessionSelectBar.classList.toggle("hidden", !state.selectMode);
  elements.sessionManage.classList.toggle("active", state.selectMode);
  elements.sessionManage.textContent = state.selectMode ? "取消" : "管理";
  const total = state.sessions.length;
  const selected = state.sessions.filter((session) => state.selectedSessions.has(session.id)).length;
  elements.sessionDeleteSelected.disabled = selected === 0;
  elements.sessionDeleteSelected.textContent = selected ? `删除 (${selected})` : "删除";
  elements.sessionSelectAll.checked = total > 0 && selected === total;
  elements.sessionSelectAll.indeterminate = selected > 0 && selected < total;
}

function renderSessionList() {
  elements.sessionList.replaceChildren();
  elements.sessionList.classList.toggle("select-mode", state.selectMode);
  elements.sessionCount.textContent = String(state.sessions.length);
  // Drop selections that no longer exist (e.g. after a search filter).
  const ids = new Set(state.sessions.map((session) => session.id));
  state.selectedSessions.forEach((id) => {
    if (!ids.has(id)) state.selectedSessions.delete(id);
  });
  updateSessionSelectBar();
  if (!state.sessions.length) {
    const empty = document.createElement("div");
    empty.className = "session-empty";
    empty.textContent = "暂无会话";
    elements.sessionList.append(empty);
    return;
  }

  state.sessions.forEach((session) => {
    const item = document.createElement(state.selectMode ? "div" : "button");
    const checked = state.selectMode && state.selectedSessions.has(session.id);
    const active = !state.selectMode && session.id === state.currentSessionId;
    item.className = `session-item ${active ? "active" : ""} ${checked ? "checked" : ""}`;
    if (!state.selectMode) item.type = "button";
    item.title = session.title;

    if (state.selectMode) {
      const box = document.createElement("input");
      box.type = "checkbox";
      box.className = "session-check";
      box.checked = checked;
      box.addEventListener("click", (event) => {
        event.stopPropagation();
        toggleSessionSelected(session.id, box.checked);
      });
      item.append(box);
    }

    const main = document.createElement("span");
    main.className = "session-main";
    const title = document.createElement("strong");
    title.textContent = `${session.favorite ? "★ " : ""}${session.title || "未命名会话"}`;
    const preview = document.createElement("small");
    preview.textContent = session.preview || session.displayTime || "";
    main.append(title, preview);
    item.append(main);

    if (!state.selectMode) {
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
      item.append(actions);
      item.addEventListener("click", () => selectSession(session.id));
    } else {
      item.addEventListener("click", () => toggleSessionSelected(session.id, !state.selectedSessions.has(session.id)));
    }
    elements.sessionList.append(item);
  });
}

function setSessionSelectMode(on) {
  state.selectMode = Boolean(on);
  state.selectedSessions.clear();
  renderSessionList();
}

function toggleSessionSelected(id, on) {
  if (on) state.selectedSessions.add(id);
  else state.selectedSessions.delete(id);
  renderSessionList();
}

function toggleSelectAllSessions(on) {
  state.selectedSessions = new Set(on ? state.sessions.map((session) => session.id) : []);
  renderSessionList();
}

async function deleteSelectedSessions() {
  const ids = state.sessions.filter((session) => state.selectedSessions.has(session.id)).map((session) => session.id);
  if (!ids.length) return;
  if (!window.confirm(`删除选中的 ${ids.length} 个会话？`)) return;
  setUiBlocked(true, "正在删除会话…");
  try {
    const result = await api("/api/session/delete-batch", {
      method: "POST",
      body: JSON.stringify({ ids }),
    });
    updateConfig(result.config);
    state.sessions = result.sessions || [];
    setSessionSelectMode(false);
    await loadCurrentSession(result.currentSessionId);
    showToast(`已删除 ${ids.length} 个会话`);
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setUiBlocked(false);
  }
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
    messages.forEach((message, idx) => {
      const isAssistant = message.role === "assistant";
      let retryTask = "";
      if (isAssistant) {
        for (let i = idx - 1; i >= 0; i -= 1) {
          if (messages[i].role === "user") {
            retryTask = messages[i].content || "";
            break;
          }
        }
      }
      appendMessage(message.role, message.content || "", {
        id: message.id,
        attachments: message.attachments || [],
        scroll: false,
        withActions: isAssistant || message.role === "user",
        retryTask,
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

function setUiBlocked(blocked, label = "处理中…") {
  elements.uiBlockerLabel.textContent = label;
  elements.uiBlocker.classList.toggle("hidden", !blocked);
}

async function selectSession(sessionId) {
  if (sessionId === state.currentSessionId || state.busy) return;
  // Switching rebuilds the runtime server-side and re-renders the whole
  // conversation (markdown + highlighting) client-side, which can take a
  // moment on long sessions — gray the UI out so it reads as busy, not stuck.
  setUiBlocked(true, "正在切换会话…");
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
  } finally {
    setUiBlocked(false);
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
  setUiBlocked(true, "正在删除会话…");
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
  } finally {
    setUiBlocked(false);
  }
}

async function newSession() {
  if (state.busy) {
    showToast("当前任务仍在执行", "error");
    return;
  }
  setUiBlocked(true, "正在创建新会话…");
  try {
    const result = await api("/api/sessions", { method: "POST", body: "{}" });
    updateConfig(result.config);
    renderConversation(result.session);
    await loadSessions();
    showToast("已开始新会话");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    setUiBlocked(false);
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

function stageSkillPrompt(skill) {
  const displayName = skill.displayName || skill.name || "skill";
  const defaultPrompt = skill.defaultPrompt || `请读取并使用 ${skill.name} skill。`;
  const scaffold = [
    `使用 ${displayName} skill。`,
    "",
    defaultPrompt,
    "",
    "请补充具体目标、对象、文件或约束：",
  ].join("\n");
  const current = elements.prompt.value.trim();
  elements.prompt.value = current ? `${current}\n\n${scaffold}` : scaffold;
  resizePrompt();
  elements.prompt.focus();
  showToast(`已将 ${displayName} 的使用说明放入输入框，请补充目标后发送。`);
}

function skillSubtitle(skill) {
  const text = String(skill.shortDescription || skill.description || "").trim();
  if (!text) return "本地 skill";
  // One concise sentence; the panel keeps subtitles to a single line.
  const firstSentence = text.split(/(?<=[。.!?！？])\s*/)[0].trim() || text;
  return firstSentence.length > 40 ? `${firstSentence.slice(0, 40)}…` : firstSentence;
}

function buildSkillRow(skill, index) {
  const row = document.createElement("div");
  row.className = "skill-row";
  const button = document.createElement("button");
  button.className = "skill-action";
  button.type = "button";
  button.title = `${skill.displayName || skill.name}\n${skill.description || ""}`;
  const icon = document.createElement("span");
  icon.className = `skill-icon ${skillTone(skill, index)}`;
  icon.textContent = skillInitial(skill);
  const copy = document.createElement("span");
  copy.className = "skill-copy";
  const title = document.createElement("strong");
  title.textContent = skill.displayName || skill.name;
  const subtitle = document.createElement("small");
  subtitle.textContent = skillSubtitle(skill);
  copy.append(title, subtitle);
  button.append(icon, copy);
  button.addEventListener("click", () => stageSkillPrompt(skill));
  row.append(button);
  if (skill.removable) {
    const remove = document.createElement("button");
    remove.className = "skill-delete";
    remove.type = "button";
    remove.title = "删除该 skill";
    remove.textContent = "×";
    remove.addEventListener("click", (event) => {
      event.stopPropagation();
      deleteSkillUi(skill.name);
    });
    row.append(remove);
  }
  return row;
}

function renderSkills() {
  elements.skillList.replaceChildren();
  const all = state.skills || [];
  elements.skillCount.textContent = String(all.length);
  const favorites = all.filter((skill) => skill.favorite);
  if (!favorites.length) {
    const hint = document.createElement("button");
    hint.type = "button";
    hint.className = "skill-empty-hint";
    hint.textContent = all.length ? "未设置常用 Skill，点这里从“全部”里选择" : "暂无 skill";
    if (all.length) hint.addEventListener("click", openSkillsModal);
    elements.skillList.append(hint);
    return;
  }
  favorites.forEach((skill, index) => elements.skillList.append(buildSkillRow(skill, index)));
}

function renderSkillsGrid() {
  if (!elements.skillsGrid) return;
  elements.skillsGrid.replaceChildren();
  const all = state.skills || [];
  if (!all.length) {
    const empty = document.createElement("div");
    empty.className = "session-empty";
    empty.textContent = "暂无 skill";
    elements.skillsGrid.append(empty);
    return;
  }
  all.forEach((skill, index) => {
    const wrap = document.createElement("div");
    wrap.className = `skill-tile-wrap ${skill.favorite ? "is-fav" : ""}`;
    const tile = document.createElement("button");
    tile.type = "button";
    tile.className = "skill-tile";
    tile.title = `${skill.displayName || skill.name}\n${skill.description || ""}`;
    const icon = document.createElement("span");
    icon.className = `skill-tile-icon ${skillTone(skill, index)}`;
    icon.textContent = skillInitial(skill);
    const name = document.createElement("span");
    name.className = "skill-tile-name";
    name.textContent = skill.displayName || skill.name;
    tile.append(icon, name);
    tile.addEventListener("click", () => {
      stageSkillPrompt(skill);
      closeSkillsModal();
    });

    const star = document.createElement("button");
    star.type = "button";
    star.className = `skill-star ${skill.favorite ? "on" : ""}`;
    star.title = skill.favorite ? "取消常用" : "设为常用";
    star.textContent = skill.favorite ? "★" : "☆";
    star.addEventListener("click", (event) => {
      event.stopPropagation();
      toggleFavoriteSkill(skill.name);
    });
    wrap.append(tile, star);

    if (skill.removable) {
      const del = document.createElement("button");
      del.type = "button";
      del.className = "skill-tile-del";
      del.title = "删除该 skill";
      del.textContent = "×";
      del.addEventListener("click", (event) => {
        event.stopPropagation();
        deleteSkillUi(skill.name);
      });
      wrap.append(del);
    }
    elements.skillsGrid.append(wrap);
  });
}

async function toggleFavoriteSkill(name) {
  const current = (state.skills || []).filter((skill) => skill.favorite).map((skill) => skill.name);
  let next;
  if (current.includes(name)) {
    next = current.filter((item) => item !== name);
  } else {
    if (current.length >= 7) {
      showToast("常用 Skill 最多 7 个，请先取消一个", "error");
      return;
    }
    next = [...current, name];
  }
  try {
    const result = await api("/api/skill/favorites", {
      method: "POST",
      body: JSON.stringify({ names: next }),
    });
    updateConfig(result.config);
  } catch (error) {
    showToast(error.message, "error");
  }
}

function openSkillsModal() {
  renderSkillsGrid();
  elements.skillsModal.classList.remove("hidden");
}

function closeSkillsModal() {
  elements.skillsModal.classList.add("hidden");
}

async function deleteSkillUi(name) {
  if (state.busy) {
    showToast("当前任务仍在执行，请稍后再删除 skill", "error");
    return;
  }
  if (!window.confirm(`删除 skill「${name}」？这会移除本地 skill 文件。`)) return;
  try {
    const result = await api("/api/delete-skill", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    updateConfig(result.config);
    showToast(`已删除 skill：${name}`);
  } catch (error) {
    showToast(error.message, "error");
  }
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
      highlightInto(code, result.content);
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

function estimateTextBytes(text) {
  return new TextEncoder().encode(text).length;
}

function pastedAttachmentName() {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  return `pasted-${stamp}.txt`;
}

function pastedFileName(mediaType = "application/octet-stream") {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const extension = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "text/plain": "txt",
    "text/markdown": "md",
  }[mediaType] || "bin";
  return `pasted-${stamp}.${extension}`;
}

function fileDisplayName(file) {
  return file.name || pastedFileName(file.type);
}

function clipboardFiles(clipboard) {
  const files = [];
  const seen = new Set();
  const addFile = (file) => {
    if (!file) return;
    const key = `${file.name}|${file.type}|${file.size}|${file.lastModified}`;
    if (seen.has(key)) return;
    seen.add(key);
    files.push(file);
  };
  Array.from(clipboard.files || []).forEach(addFile);
  Array.from(clipboard.items || []).forEach((item) => {
    if (item.kind === "file") addFile(item.getAsFile());
  });
  return files;
}

function addPastedTextAttachment(text) {
  if (state.pendingAttachments.length >= MAX_ATTACHMENTS) {
    showToast(`一次最多上传 ${MAX_ATTACHMENTS} 个附件`, "error");
    return false;
  }
  const normalized = String(text).replace(/\r\n?/g, "\n");
  const truncated = normalized.length > MAX_PASTED_TEXT_CHARS;
  const content = truncated ? normalized.slice(0, MAX_PASTED_TEXT_CHARS) : normalized;
  const size = estimateTextBytes(content);
  state.pendingAttachments.push({
    name: pastedAttachmentName(),
    type: "text/plain",
    size,
    originalSize: estimateTextBytes(normalized),
    encoding: "text",
    kind: "pasted",
    content,
  });
  renderPendingAttachments();
  if (truncated) {
    showToast("粘贴内容过长，已作为 txt 附件加入并按上限截断。", "error");
  } else {
    showToast("长文本已作为临时 txt 附件加入。");
  }
  return true;
}

async function handlePromptPaste(event) {
  const clipboard = event.clipboardData;
  if (!clipboard) return;
  const files = clipboardFiles(clipboard);
  if (files.length) {
    event.preventDefault();
    await addAttachments(files);
    return;
  }
  const text = clipboard.getData("text/plain");
  if (!text || text.length < LONG_PASTE_CHAR_THRESHOLD) return;
  event.preventDefault();
  addPastedTextAttachment(text);
}

function renderPendingAttachments() {
  elements.attachmentList.replaceChildren();
  elements.attachmentList.classList.toggle("hidden", state.pendingAttachments.length === 0);
  state.pendingAttachments.forEach((item, index) => {
    const card = buildAttachmentCard(item, () => {
      state.pendingAttachments.splice(index, 1);
      renderPendingAttachments();
    });
    elements.attachmentList.append(card);
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
  return DICOM_ATTACHMENT_PATTERN.test(fileDisplayName(file)) || ["application/dicom", "application/x-dicom"].includes(file.type);
}

function isTextFile(file) {
  return file.type.startsWith("text/") || TEXT_ATTACHMENT_PATTERN.test(fileDisplayName(file));
}

function isImageFile(file) {
  return file.type.startsWith("image/");
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
  const name = fileDisplayName(file);
  if (isDicomFile(file)) {
    const slice = file.slice(0, Math.min(file.size, MAX_DICOM_HEADER_BYTES));
    const content = arrayBufferToBase64(await slice.arrayBuffer());
    return {
      name,
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
      name,
      type: file.type || "text/plain",
      size: file.size,
      encoding: "text",
      kind: "text",
      content: await file.text(),
    };
  }
  if (isImageFile(file)) {
    if (file.size > MAX_IMAGE_ATTACHMENT_BYTES) {
      throw new Error(`图片附件超过 ${Math.round(MAX_IMAGE_ATTACHMENT_BYTES / 1024)} KB`);
    }
    return {
      name,
      type: file.type || "application/octet-stream",
      size: file.size,
      originalSize: file.size,
      encoding: "base64",
      kind: "image",
      content: arrayBufferToBase64(await file.arrayBuffer()),
    };
  }
  if (PDF_ATTACHMENT_PATTERN.test(name) || file.type === "application/pdf") {
    if (file.size > MAX_PDF_ATTACHMENT_BYTES) {
      throw new Error(`PDF 附件超过 ${Math.round(MAX_PDF_ATTACHMENT_BYTES / 1024)} KB`);
    }
    return {
      name,
      type: file.type || "application/pdf",
      size: file.size,
      originalSize: file.size,
      encoding: "base64",
      kind: "pdf",
      content: arrayBufferToBase64(await file.arrayBuffer()),
    };
  }
  if (ARCHIVE_ATTACHMENT_PATTERN.test(name) || ["application/zip", "application/x-zip-compressed"].includes(file.type)) {
    if (file.size > MAX_ARCHIVE_ATTACHMENT_BYTES) {
      throw new Error(`压缩包附件超过 ${Math.round(MAX_ARCHIVE_ATTACHMENT_BYTES / 1024)} KB`);
    }
    return {
      name,
      type: file.type || "application/zip",
      size: file.size,
      originalSize: file.size,
      encoding: "base64",
      kind: "archive",
      content: arrayBufferToBase64(await file.arrayBuffer()),
    };
  }
  if (file.size > MAX_ATTACHMENT_BYTES) {
    throw new Error(`二进制附件超过 ${Math.round(MAX_ATTACHMENT_BYTES / 1024)} KB`);
  }
  return {
    name,
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
  const attachments = [...state.pendingAttachments];
  const typedTask = String(prefilled ?? elements.prompt.value).trim();
  const task = typedTask || (attachments.length ? "请阅读附件内容。" : "");
  if (!task || state.busy) return;
  if (!state.config?.apiKeyConfigured) {
    appendMessage("system", `需要先配置 ${state.config?.providerLabel || "模型供应商"} 的 API Key。请打开左下角设置，也可以切换到其他供应商。`);
    openSettings();
    return;
  }
  const attachmentMetadata = storedAttachmentMetadata(attachments);
  state.pendingAttachments = [];
  renderPendingAttachments();
  elements.prompt.value = "";
  resizePrompt();
  // Remember the submission so a Stop can restore it for editing and resending.
  state.lastSubmission = { typed: typedTask, prefilled, attachments };
  state.stickToBottom = true;
  appendMessage("user", task, { attachments: attachmentMetadata, withActions: true });
  appendAssistantDraft();
  if (state.activeDraft) state.activeDraft.task = task;
  state.abortController = new AbortController();
  state.stopped = false;
  setBusy(true);
  let answerText = "";
  let completed = false;
  try {
    await streamApi(
      "/api/chat-stream",
      {
        sessionId: state.currentSessionId,
        task,
        attachments,
      },
      (event) => {
        if (event.type === "delta") {
          answerText += event.text || "";
          setDraftText(answerText);
        } else if (event.type === "done") {
          completed = true;
          const stopped = Boolean(event.stopped) || state.stopped;
          answerText = event.answer || answerText || "模型未返回文本结果。";
          setDraftText(answerText);
          if (event.session) {
            state.currentSessionId = event.session.id;
          }
          finalizeAssistantDraft(answerText, { stopped });
          if (stopped) restoreLastSubmission();
        }
      },
      state.abortController.signal,
    );
    if (!completed) {
      setDraftText(answerText || "模型未返回文本结果。");
      finalizeAssistantDraft(answerText);
    }
    await loadSessions();
  } catch (error) {
    if (error.name === "AbortError" || state.stopped) {
      finalizeAssistantDraft(answerText, { stopped: true });
      restoreLastSubmission();
      showToast("已停止。可以编辑问题后重新发送。");
      try {
        await loadSessions();
      } catch (_error) {
        // Listing can briefly fail right after a stop; the next poll recovers.
      }
    } else {
      failAssistantDraft(error.message);
      appendMessage("system", `任务失败：${error.message}`);
    }
  } finally {
    state.abortController = null;
    setBusy(false);
  }
}

function stopTask() {
  if (!state.busy) return;
  state.stopped = true;
  if (state.abortController) {
    try {
      state.abortController.abort();
    } catch (_error) {
      // Ignore: the fetch may have already settled.
    }
  }
  api("/api/chat/stop", { method: "POST", body: "{}" }).catch(() => {});
}

function restoreLastSubmission() {
  const submission = state.lastSubmission;
  if (!submission) return;
  const text = submission.prefilled != null ? String(submission.prefilled) : submission.typed;
  if (text) elements.prompt.value = text;
  if (Array.isArray(submission.attachments) && submission.attachments.length) {
    state.pendingAttachments = submission.attachments.slice(0, MAX_ATTACHMENTS);
    renderPendingAttachments();
  }
  resizePrompt();
  elements.prompt.focus();
}

function handleServerEvent(event) {
  state.lastEventId = Math.max(state.lastEventId, Number(event.id || 0));
  if (event.type === "agent_started") {
    setActivity("agent", "正在理解任务", "active");
  }
  if (event.type === "approval_required") {
    setActivity(`approval:${event.tool}`, "等待人工批准", "waiting", toolDisplayName(event.tool));
  }
  if (event.type === "approval_resolved") {
    setActivity(`approval:${event.tool}`, event.approved ? "审批已通过" : "审批已拒绝", event.approved ? "done" : "failed", toolDisplayName(event.tool));
  }
  if (event.type === "tool_started") {
    setActivity(`tool:${event.tool}`, toolDisplayName(event.tool), "active");
  }
  if (event.type === "tool_finished") {
    setActivity(`tool:${event.tool}`, toolDisplayName(event.tool), event.ok ? "done" : "failed", event.ok ? "完成" : (event.error_type || "失败"));
  }
  if (event.type === "agent_finished") {
    setActivity("agent", "正在整理答案", "done");
  }
  if (event.type === "agent_failed") {
    setActivity("agent", "任务失败", "failed");
  }
  if (event.type === "agent_stopped") {
    setActivity("agent", "已停止", "failed");
  }
  if (event.type === "tool_started" && event.tool === "web_search") {
    showToast("正在联网搜索公开资料...");
  }
  if (event.type === "tool_finished" && event.tool === "web_search") {
    showToast(event.ok ? "联网搜索完成" : "联网搜索失败", event.ok ? "info" : "error");
  }
  if (event.type === "tool_started" && event.tool === "fetch_url") {
    showToast("正在读取网页...");
  }
  if (event.type === "tool_finished" && event.tool === "fetch_url") {
    showToast(event.ok ? "网页读取完成" : "网页读取失败", event.ok ? "info" : "error");
  }
}

async function pollEvents() {
  try {
    const payload = await api(`/api/events?since=${state.lastEventId}`);
    (payload.events || []).forEach(handleServerEvent);
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

function switchSettingsSection(section) {
  const target = section || "connection";
  elements.settingsTabs.forEach((tab) => {
    tab.classList.toggle("is-active", tab.dataset.settingsSection === target);
  });
  elements.settingsSections.forEach((panel) => {
    panel.classList.toggle("is-active", panel.dataset.settingsSectionPanel === target);
  });
}

function openSettings(section = "connection") {
  if (state.config) {
    elements.providerInputs.forEach((input) => { input.checked = input.value === state.config.provider; });
    syncProviderFields(state.config.provider, false);
    elements.model.value = state.config.model;
    elements.baseUrl.value = state.config.baseUrl || "";
    elements.root.value = state.config.root;
    elements.webSearchInputs.forEach((input) => { input.checked = input.value === (state.config.webSearchMode || "auto"); });
    elements.webSearchNetworkInputs.forEach((input) => { input.checked = input.value === (state.config.webSearchNetwork || "auto"); });
  }
  switchSettingsSection(section);
  elements.apiKey.value = "";
  elements.settingsModal.classList.remove("hidden");
  window.setTimeout(() => {
    if (section === "connection") elements.apiKey.focus();
  }, 50);
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
    webSearchMode: selectedWebSearchMode(),
    webSearchNetwork: selectedWebSearchNetwork(),
  };
  try {
    const config = await api("/api/config", { method: "POST", body: JSON.stringify(payload) });
    updateConfig(config);
    closeSettings();
    await loadFiles();
    await loadSessions();
    await loadCurrentSession(config.currentSessionId);
    appendMessage("system", "设置已更新。API Key 仅保存在当前本机进程内。关闭服务后需要重新输入。");
    showToast("设置已保存");
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
  setUiBlocked(true, "正在切换工作目录…");
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
        webSearchMode: state.config.webSearchMode || "auto",
        webSearchNetwork: state.config.webSearchNetwork || "auto",
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
    setUiBlocked(false);
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

function bindDragAndDrop() {
  const dropZone = document.querySelector(".conversation-panel");
  if (!dropZone) return;
  const hasFiles = (event) => Array.from(event.dataTransfer?.types || []).includes("Files");
  const clearDrag = () => {
    state.dragDepth = 0;
    dropZone.classList.remove("drag-over");
  };
  dropZone.addEventListener("dragenter", (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    state.dragDepth += 1;
    dropZone.classList.add("drag-over");
  });
  dropZone.addEventListener("dragover", (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
  });
  dropZone.addEventListener("dragleave", (event) => {
    if (!hasFiles(event)) return;
    state.dragDepth -= 1;
    if (state.dragDepth <= 0) clearDrag();
  });
  dropZone.addEventListener("drop", (event) => {
    if (!hasFiles(event)) return;
    event.preventDefault();
    clearDrag();
    if (state.busy) {
      showToast("当前任务仍在执行，请稍后再添加附件", "error");
      return;
    }
    const files = event.dataTransfer?.files;
    if (files && files.length) addAttachments(files);
  });
}

function bindEvents() {
  elements.send.addEventListener("click", () => {
    if (state.busy) stopTask();
    else sendTask();
  });
  elements.prompt.addEventListener("input", resizePrompt);
  elements.prompt.addEventListener("paste", handlePromptPaste);
  elements.conversation.addEventListener("scroll", () => {
    const el = elements.conversation;
    state.stickToBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
  });
  bindDragAndDrop();
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
  elements.settingsButton.addEventListener("click", () => openSettings());
  elements.settingsTabs.forEach((tab) => {
    tab.addEventListener("click", () => switchSettingsSection(tab.dataset.settingsSection));
  });
  elements.browseFolder.addEventListener("click", pickProjectFolder);
  elements.providerInputs.forEach((input) => input.addEventListener("change", () => {
    if (input.checked) syncProviderFields(input.value, true);
  }));
  elements.settingsForm.addEventListener("submit", saveSettings);
  document.querySelectorAll(".close-modal").forEach((button) => button.addEventListener("click", closeSettings));
  elements.newSession.addEventListener("click", newSession);
  elements.importSkill.addEventListener("click", importSkill);
  elements.openSkillsModal.addEventListener("click", openSkillsModal);
  document.querySelectorAll(".close-skills-modal").forEach((button) => button.addEventListener("click", closeSkillsModal));
  elements.skillsModal.addEventListener("click", (event) => {
    if (event.target === elements.skillsModal) closeSkillsModal();
  });
  elements.sessionManage.addEventListener("click", () => setSessionSelectMode(!state.selectMode));
  elements.sessionManageDone.addEventListener("click", () => setSessionSelectMode(false));
  elements.sessionSelectAll.addEventListener("change", (event) => toggleSelectAllSessions(event.target.checked));
  elements.sessionDeleteSelected.addEventListener("click", deleteSelectedSessions);
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
      if (!elements.skillsModal.classList.contains("hidden")) closeSkillsModal();
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
