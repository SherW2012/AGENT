"use strict";

// ---- Theme: applied first so the page never flashes the wrong colors. ----
const THEME_STORAGE_KEY = "bnct-agent-theme";
const themeMedia = window.matchMedia("(prefers-color-scheme: dark)");

function themePreference() {
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  return ["light", "dark", "auto"].includes(stored) ? stored : "light";
}

function applyTheme() {
  const preference = themePreference();
  const resolved = preference === "auto" ? (themeMedia.matches ? "dark" : "light") : preference;
  document.documentElement.dataset.theme = resolved;
}

function setThemePreference(preference) {
  window.localStorage.setItem(THEME_STORAGE_KEY, preference);
  applyTheme();
}

themeMedia.addEventListener("change", () => {
  if (themePreference() === "auto") applyTheme();
});
applyTheme();

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
const MAX_PDF_ATTACHMENT_BYTES = 10_000_000;

const state = {
  config: null,
  files: [],
  skills: [],
  sessions: [],
  currentSessionId: null,
  currentApproval: null,
  pendingAttachments: [],
  // Live runs owned by THIS tab, keyed by session id. Each run carries its
  // own stream controller and draft DOM, so parallel sessions can never write
  // into each other's conversation: sessionId -> {controller, draft, stopped}.
  runs: new Map(),
  busy: false,
  eventTimer: null,
  lastEventId: 0,
  lastSubmission: null,
  dragDepth: 0,
  selectMode: false,
  selectedSessions: new Set(),
  // Claude-style follow: keep pinned to the bottom while streaming, but stop
  // following as soon as the user scrolls up, and resume when they return.
  stickToBottom: true,
  // Tools the user chose "本轮始终允许" for; cleared when the turn ends.
  autoApproveTools: new Set(),
  approvalCard: null,
  // Calendar panel state: displayed month + entries/links from /api/personal.
  calendar: { year: new Date().getFullYear(), month: new Date().getMonth(), selected: "" },
  personal: { calendar: [], links: [] },
};

const elements = {
  appShell: document.querySelector(".app-shell"),
  apiKey: document.querySelector("#api-key-input"),
  composer: document.querySelector("#composer"),
  attachButton: document.querySelector("#attach-button"),
  attachmentInput: document.querySelector("#attachment-input"),
  attachmentList: document.querySelector("#attachment-list"),
  baseUrl: document.querySelector("#base-url-input"),
  browseFolder: document.querySelector("#browse-folder-button"),
  browseFolderLabel: document.querySelector("#browse-folder-label"),
  connection: document.querySelector("#connection-state"),
  connectionLabel: document.querySelector("#connection-label"),
  conversation: document.querySelector("#conversation-scroll"),
  emptyState: document.querySelector("#empty-state"),
  importSkill: document.querySelector("#import-skill-button"),
  messageList: document.querySelector("#message-list"),
  model: document.querySelector("#model-input"),
  modelOptions: document.querySelector("#provider-models"),
  modelPill: document.querySelector("#model-pill"),
  newSession: document.querySelector("#new-session-button"),
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
  auditTbody: document.querySelector("#audit-tbody"),
  refreshAudit: document.querySelector("#refresh-audit-button"),
  usageStats: document.querySelector("#usage-stats"),
  autoMemoryToggle: document.querySelector("#auto-memory-toggle"),
  clearAutoMemory: document.querySelector("#clear-auto-memory-button"),
  webSearchEnabledToggle: document.querySelector("#web-search-enabled-toggle"),
  workdirChip: document.querySelector("#workdir-chip"),
  workdirPath: document.querySelector("#workdir-path"),
  webSearchToggle: document.querySelector("#web-search-toggle"),
  mascot: document.querySelector("#mascot"),
  calTitle: document.querySelector("#cal-title"),
  calPrev: document.querySelector("#cal-prev"),
  calNext: document.querySelector("#cal-next"),
  calendarGrid: document.querySelector("#calendar-grid"),
  calendarEntries: document.querySelector("#calendar-entries"),
  quickLinks: document.querySelector("#quick-links"),
  addEventButton: document.querySelector("#add-event-button"),
  addLinkButton: document.querySelector("#add-link-button"),
  panelFormModal: document.querySelector("#panel-form-modal"),
  panelFormEyebrow: document.querySelector("#panel-form-eyebrow"),
  panelFormTitle: document.querySelector("#panel-form-title"),
  panelForm: document.querySelector("#panel-form"),
  panelFormFields: document.querySelector("#panel-form-fields"),
  panelFormError: document.querySelector("#panel-form-error"),
  panelFormCancel: document.querySelector("#panel-form-cancel"),
  panelFormSubmit: document.querySelector("#panel-form-submit"),
  closePanelForm: document.querySelector("#close-panel-form"),
  themeInputs: document.querySelectorAll('input[name="theme"]'),
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
  // The prompt stays usable while the agent works: Enter sends mid-task
  // guidance that the agent picks up before its next reasoning round.
  elements.prompt.placeholder = busy
    ? "任务进行中——输入补充引导，回车立即传给 Agent..."
    : "给 BNCT Agent 一个任务...";
  elements.attachButton.disabled = busy;
  if (busy) {
    setConnection("busy", "Agent 工作中");
  } else if (state.config?.apiKeyConfigured) {
    setConnection("online", "模型已连接");
  } else {
    setConnection("offline", "离线模式");
  }
  elements.mascot?.classList.toggle("working", busy);
  if (!busy) {
    state.autoApproveTools.clear();
    removeApprovalCard();
    state.currentApproval = null;
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
  elements.workdirPath.textContent = config.root;
  elements.workdirChip.title = `工作目录：${config.root}\n点击切换`;
  elements.modelPill.textContent = config.apiKeyConfigured ? `${config.providerLabel} · ${config.model}` : "未连接模型";
  elements.providerInputs.forEach((input) => { input.checked = input.value === config.provider; });
  elements.autoMemoryToggle.checked = config.autoMemory !== false;
  elements.webSearchEnabledToggle.checked = config.webSearchEnabled !== false;
  renderWebSearchToggle();
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

function renderWebSearchToggle() {
  const enabled = state.config?.webSearchEnabled !== false;
  elements.webSearchToggle.classList.toggle("on", enabled);
  const engine = state.config?.webSearchEngine === "builtin" ? "Kimi 自带搜索" : "内置搜索";
  elements.webSearchToggle.title = enabled
    ? `联网搜索已开启（${engine}）。点击关闭；与设置页同步。`
    : "联网搜索已关闭。点击开启；与设置页同步。";
}

async function toggleWebSearch() {
  if (!state.config) return;
  // Optimistic flip through the lightweight endpoint: the server only swaps
  // one flag (no runtime rebuild), so the button reacts instantly and simply
  // rolls back on failure. Safe mid-task -- the next round picks it up.
  const target = !(state.config.webSearchEnabled !== false);
  const apply = (value) => {
    state.config.webSearchEnabled = value;
    elements.webSearchEnabledToggle.checked = value;
    renderWebSearchToggle();
  };
  apply(target);
  try {
    await api("/api/web-search", {
      method: "POST",
      body: JSON.stringify({ enabled: target }),
    });
  } catch (error) {
    apply(!target);
    showToast(error.message, "error");
  }
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
  const visionNote = provider.vision === "native"
    ? "✅ 该系列模型原生支持图片识别，截图可直接发送。"
    : provider.vision === "switch"
      ? `✅ 支持图片识别：包含图片的消息会自动切换到视觉模型 ${provider.visionModel}（同一 API Key，无需手动切换）。`
      : "⚠️ 该供应商的对话接口不支持图片识别，发送的图片无法被读取。";
  elements.providerHelpText.textContent = `请在 ${provider.label} 官方平台创建密钥。环境变量名为 ${provider.keyEnv}，密钥仅保存在本次本机进程内。${visionNote}`;
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
  article.querySelector(".message-actions")?.remove();
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
    retryBtn.addEventListener("click", () => resendInterrupting(retryTask));
    row.append(retryBtn);
  }
  // User bubbles stay compact: the action row lives below the bubble (as an
  // article-level sibling) and only appears while hovering the bubble itself.
  if (article.classList.contains("user")) {
    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "msg-action-btn";
    editBtn.title = "编辑后重新提问";
    const editLabel = document.createElement("span");
    editLabel.textContent = "编辑";
    editBtn.append(svgIcon(["M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17z", "m13.5 6.5 4 4"]), editLabel);
    editBtn.addEventListener("click", () => enterUserMessageEdit(article, rawText));
    row.append(editBtn);
    article.append(row);
  } else {
    body.append(row);
  }
}

function enterUserMessageEdit(article, rawText) {
  // Kimi-style in-place edit: the bubble becomes editable with 取消/确定 below;
  // confirming re-asks the edited question in this same session.
  if (article.classList.contains("editing")) return;
  const content = article.querySelector(".message-content");
  if (!content) return;
  article.classList.add("editing");
  const editor = document.createElement("div");
  editor.className = "message-edit";
  const area = document.createElement("textarea");
  area.className = "message-edit-area";
  area.value = rawText;
  const actions = document.createElement("div");
  actions.className = "message-edit-actions";
  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "edit-btn cancel";
  cancel.textContent = "取消";
  const confirm = document.createElement("button");
  confirm.type = "button";
  confirm.className = "edit-btn confirm";
  confirm.textContent = "确定";
  const exitEdit = () => {
    editor.remove();
    content.classList.remove("hidden");
    article.classList.remove("editing");
  };
  const submit = () => {
    const text = area.value.trim();
    if (!text) return;
    exitEdit();
    // Editing during a run means "stop that answer and re-think with my new
    // wording" -- interrupt, then re-ask in this same session.
    resendInterrupting(text);
  };
  cancel.addEventListener("click", exitEdit);
  confirm.addEventListener("click", submit);
  area.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
    if (event.key === "Escape") exitEdit();
  });
  actions.append(cancel, confirm);
  editor.append(area, actions);
  content.classList.add("hidden");
  content.after(editor);
  area.style.height = "auto";
  area.style.height = `${Math.min(area.scrollHeight + 4, 300)}px`;
  area.focus();
  area.setSelectionRange(area.value.length, area.value.length);
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
    create_agent_skill: "创建 Skill",
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
    get_build_profiles: "读取编译配置",
    configure_build_profile: "保存编译配置",
    run_build: "运行编译",
    analyze_build_log: "分析编译日志",
    read_agent_memory: "读取记忆",
    append_agent_memory: "写入记忆",
    forget_agent_memory: "删除记忆",
  };
  return labels[name] || name || "工具调用";
}

function appendAssistantDraft(sessionId) {
  const article = appendMessage("assistant", "", {});
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

  const draft = {
    article,
    meta,
    content,
    activity,
    activityTitle: titleText,
    activityList: list,
    activities: [],
    // Which session this stream belongs to: switching away detaches the
    // article, switching back re-attaches it so live output is never lost.
    session: sessionId,
  };
  setActivity(draft, "agent", "正在理解任务", "active");
  return draft;
}

function setDraftText(draft, text) {
  if (!draft) return;
  renderMarkdown(draft.content, text);
  // Only auto-follow while the user is at the bottom AND actually viewing this
  // draft's session; never scroll someone reading another conversation.
  if (state.stickToBottom && draft.session === state.currentSessionId) {
    elements.conversation.scrollTo({ top: elements.conversation.scrollHeight });
  }
}

function setActivity(draft, key, label, status = "active", detail = "") {
  if (!draft) return;
  const existing = draft.activities.find((item) => item.key === key);
  const item = existing || { key, label, status, detail };
  item.label = label;
  item.status = status;
  item.detail = detail;
  if (!existing) draft.activities.push(item);
  renderActivity(draft);
}

function renderActivity(draft) {
  if (!draft) return;
  const active = draft.activities.find((item) => item.status === "active");
  const waiting = draft.activities.find((item) => item.status === "waiting");
  const current = waiting || active || draft.activities.at(-1);
  draft.activityTitle.textContent = current?.label || "正在处理";
  draft.activityList.replaceChildren();
  const history = draft.activities.filter((item) => item !== current).slice(-5);
  draft.activityList.classList.toggle("hidden", history.length === 0);
  history.forEach((item) => {
    const row = document.createElement("div");
    row.className = `activity-item ${item.status}`;
    const dot = document.createElement("span");
    dot.className = "activity-dot";
    const text = document.createElement("span");
    text.textContent = item.detail ? `${item.label}：${item.detail}` : item.label;
    row.append(dot, text);
    draft.activityList.append(row);
  });
}

function finalizeAssistantDraft(draft, rawText = "", options = {}) {
  if (!draft || draft.finalized) return;
  draft.finalized = true;
  let metaText = options.stopped ? "BNCT Agent · 已停止" : "BNCT Agent";
  const usage = options.usage;
  if (usage && (usage.promptTokens || usage.completionTokens)) {
    metaText += ` · ↑${usage.promptTokens} ↓${usage.completionTokens} tokens`;
  }
  draft.meta.textContent = metaText;
  setActivity(draft, "agent", options.stopped ? "已停止" : "已完成", options.stopped ? "failed" : "done");
  draft.activity.classList.add("done");
  if (options.stopped) draft.activity.classList.add("failed");
  addMessageActions(draft.article, rawText, draft.task || "");
}

function failAssistantDraft(draft, message) {
  if (!draft || draft.finalized) return;
  draft.finalized = true;
  draft.meta.textContent = "BNCT Agent 已中断";
  setActivity(draft, "agent", "任务失败", "failed", message);
  draft.activity.classList.add("failed");
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
  // A live stream owned by this tab for THIS session: re-attach its draft
  // article so switching away and back keeps showing thinking + output live
  // (the stream keeps writing into the same DOM node while detached).
  const liveDraft = state.runs.get(session.id)?.draft || null;
  const messages = session.messages || [];
  if (!messages.length && !liveDraft) {
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
  if (liveDraft) {
    // The just-sent user message is already in the stored history; only the
    // in-flight assistant draft is missing. Same node, still stream-updated.
    hideEmptyState();
    elements.messageList.append(liveDraft.article);
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

let uiBlockerTimer = null;

function setUiBlocked(blocked, label = "处理中…") {
  // Show the overlay only if the operation is actually slow; fast session
  // switches finish inside the delay and never flash the screen.
  window.clearTimeout(uiBlockerTimer);
  uiBlockerTimer = null;
  if (blocked) {
    uiBlockerTimer = window.setTimeout(() => {
      elements.uiBlockerLabel.textContent = label;
      elements.uiBlocker.classList.remove("hidden");
    }, 300);
  } else {
    elements.uiBlocker.classList.add("hidden");
  }
}

async function selectSession(sessionId) {
  if (sessionId === state.currentSessionId) return;
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

// ---------- Calendar + quick links panel (replaces the old file browser) ----------

function isoDate(year, month, day) {
  return `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function todayIso() {
  const now = new Date();
  return isoDate(now.getFullYear(), now.getMonth(), now.getDate());
}

async function loadPersonal() {
  try {
    const result = await api("/api/personal");
    state.personal = { calendar: result.calendar || [], links: result.links || [] };
    renderCalendar();
    renderQuickLinks();
  } catch (_error) {
    // Panel data is non-critical; the next refresh recovers.
  }
}

function shiftCalendarMonth(delta) {
  const base = new Date(state.calendar.year, state.calendar.month + delta, 1);
  state.calendar.year = base.getFullYear();
  state.calendar.month = base.getMonth();
  renderCalendar();
}

function renderCalendar() {
  const { year, month } = state.calendar;
  if (!state.calendar.selected) state.calendar.selected = todayIso();
  elements.calTitle.textContent = `${year} 年 ${month + 1} 月`;
  const eventDates = new Set(state.personal.calendar.map((item) => item.date));
  const grid = elements.calendarGrid;
  grid.replaceChildren();
  "一二三四五六日".split("").forEach((label) => {
    const head = document.createElement("span");
    head.className = "cal-dow";
    head.textContent = label;
    grid.append(head);
  });
  const first = new Date(year, month, 1);
  const leading = (first.getDay() + 6) % 7; // Monday-first grid
  const days = new Date(year, month + 1, 0).getDate();
  for (let i = 0; i < leading; i += 1) grid.append(document.createElement("span"));
  const today = todayIso();
  for (let day = 1; day <= days; day += 1) {
    const iso = isoDate(year, month, day);
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "cal-day";
    if (iso === today) cell.classList.add("is-today");
    if (iso === state.calendar.selected) cell.classList.add("is-selected");
    if (eventDates.has(iso)) cell.classList.add("has-events");
    cell.textContent = String(day);
    cell.addEventListener("click", () => {
      state.calendar.selected = iso;
      renderCalendar();
    });
    grid.append(cell);
  }
  renderCalendarEntries();
}

function renderCalendarEntries() {
  const selected = state.calendar.selected || todayIso();
  const today = todayIso();
  const wrap = elements.calendarEntries;
  wrap.replaceChildren();
  // Selected day's entries first, then the next few upcoming ones.
  const ofDay = state.personal.calendar.filter((item) => item.date === selected);
  const upcoming = state.personal.calendar
    .filter((item) => item.date !== selected && item.date >= today)
    .slice(0, 4);
  const sections = [
    [selected === today ? "今天" : selected, ofDay, true],
    ["接下来", upcoming, false],
  ];
  sections.forEach(([label, items, showEmpty]) => {
    if (!items.length && !showEmpty) return;
    const head = document.createElement("div");
    head.className = "cal-entries-label";
    head.textContent = label;
    wrap.append(head);
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "cal-entry-empty";
      empty.textContent = "没有日程。对话框里说“帮我记录一个日程”即可添加。";
      wrap.append(empty);
      return;
    }
    items.forEach((item) => {
      const row = document.createElement("div");
      row.className = "cal-entry";
      const text = document.createElement("span");
      text.className = "cal-entry-text";
      text.textContent = `${item.date === selected ? "" : `${item.date.slice(5)} `}${item.time ? `${item.time} ` : ""}${item.text}`;
      text.title = `${item.date} ${item.time || ""} ${item.text}`;
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "cal-entry-del";
      remove.title = "删除日程";
      remove.textContent = "×";
      remove.addEventListener("click", async () => {
        try {
          await api("/api/personal/delete-event", { method: "POST", body: JSON.stringify({ id: item.id }) });
          await loadPersonal();
        } catch (error) {
          showToast(error.message, "error");
        }
      });
      row.append(text, remove);
      wrap.append(row);
    });
  });
}

function renderQuickLinks() {
  const wrap = elements.quickLinks;
  wrap.replaceChildren();
  if (!state.personal.links.length) {
    const empty = document.createElement("div");
    empty.className = "cal-entry-empty";
    empty.textContent = "还没有常用链接。可以点 ＋ 添加，或在对话框里说“帮我记录一个常用链接”。";
    wrap.append(empty);
    return;
  }
  state.personal.links.forEach((item) => {
    const row = document.createElement("div");
    row.className = "quick-link-row";
    const open = document.createElement("a");
    open.className = "quick-link";
    const href = safeLinkUrl(item.url);
    if (!href) return;
    open.href = href;
    open.target = "_blank";
    open.rel = "noreferrer noopener";
    open.title = item.url;
    const icon = document.createElement("span");
    icon.className = "quick-link-icon";
    icon.textContent = (item.name || "?").slice(0, 1).toUpperCase();
    const name = document.createElement("span");
    name.textContent = item.name;
    open.append(icon, name);
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "cal-entry-del";
    remove.title = "删除链接";
    remove.textContent = "×";
    remove.addEventListener("click", async () => {
      try {
        await api("/api/personal/delete-link", { method: "POST", body: JSON.stringify({ name: item.name }) });
        await loadPersonal();
      } catch (error) {
        showToast(error.message, "error");
      }
    });
    row.append(open, remove);
    wrap.append(row);
  });
}

// ---------- Styled in-app form dialog (calendar entries & quick links) ----------

let panelFormSession = null;

function closePanelForm() {
  elements.panelFormModal.classList.add("hidden");
  panelFormSession = null;
}

function openPanelForm({ eyebrow, title, submitLabel, fields, onSubmit }) {
  elements.panelFormEyebrow.textContent = eyebrow;
  elements.panelFormTitle.textContent = title;
  elements.panelFormSubmit.textContent = submitLabel || "保存";
  elements.panelFormError.classList.add("hidden");
  elements.panelFormFields.replaceChildren();
  const inputs = new Map();
  fields.forEach((field) => {
    const label = document.createElement("label");
    label.className = "panel-form-field";
    const caption = document.createElement("span");
    caption.textContent = field.label;
    if (field.optional) {
      const hint = document.createElement("em");
      hint.textContent = "可选";
      caption.append(hint);
    }
    const input = document.createElement("input");
    input.type = field.type || "text";
    if (field.placeholder) input.placeholder = field.placeholder;
    if (field.value) input.value = field.value;
    if (field.maxLength) input.maxLength = field.maxLength;
    input.autocomplete = "off";
    inputs.set(field.key, input);
    label.append(caption, input);
    elements.panelFormFields.append(label);
  });
  panelFormSession = { onSubmit, inputs };
  elements.panelFormModal.classList.remove("hidden");
  const first = inputs.values().next().value;
  window.setTimeout(() => first?.focus(), 30);
}

async function submitPanelForm(event) {
  event.preventDefault();
  if (!panelFormSession) return;
  const values = {};
  panelFormSession.inputs.forEach((input, key) => {
    values[key] = input.value.trim();
  });
  elements.panelFormSubmit.disabled = true;
  try {
    await panelFormSession.onSubmit(values);
    closePanelForm();
  } catch (error) {
    elements.panelFormError.textContent = error.message;
    elements.panelFormError.classList.remove("hidden");
  } finally {
    elements.panelFormSubmit.disabled = false;
  }
}

function addCalendarEventFromPanel() {
  openPanelForm({
    eyebrow: "CALENDAR",
    title: "记录日程",
    submitLabel: "记录",
    fields: [
      { key: "date", label: "日期", type: "date", value: state.calendar.selected || todayIso() },
      { key: "time", label: "时间", type: "time", optional: true },
      { key: "text", label: "内容", type: "text", placeholder: "例如：评审剂量模块", maxLength: 200 },
    ],
    onSubmit: async (values) => {
      if (!values.date) throw new Error("请选择日期");
      if (!values.text) throw new Error("请填写日程内容");
      await api("/api/personal/add-event", {
        method: "POST",
        body: JSON.stringify({ date: values.date, text: values.text, time: values.time || "" }),
      });
      state.calendar.selected = values.date;
      const parts = values.date.split("-");
      state.calendar.year = Number(parts[0]);
      state.calendar.month = Number(parts[1]) - 1;
      await loadPersonal();
      showToast("日程已记录");
    },
  });
}

function addQuickLinkFromPanel() {
  openPanelForm({
    eyebrow: "LINKS",
    title: "添加常用链接",
    submitLabel: "保存",
    fields: [
      { key: "name", label: "名称", type: "text", placeholder: "例如：禅道", maxLength: 40 },
      { key: "url", label: "地址", type: "url", placeholder: "https://…" },
    ],
    onSubmit: async (values) => {
      if (!values.name) throw new Error("请填写链接名称");
      if (!values.url) throw new Error("请填写链接地址");
      await api("/api/personal/add-link", {
        method: "POST",
        body: JSON.stringify({ name: values.name, url: values.url }),
      });
      await loadPersonal();
      showToast("常用链接已保存");
    },
  });
}

function skillTone(skill, index) {
  if (skill.hasProcessor) return "amber";
  if (skill.trusted) return "green";
  return ["violet", "green", "accent", "red"][index % 4];
}

// Claude-style minimal line icons (24x24 stroke paths, currentColor). A skill's
// `icon:` frontmatter can name one of these presets; an emoji still works as a
// custom escape hatch; skills with neither get a stable preset by name hash.
const SKILL_ICON_PATHS = {
  doc: ["M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z", "M14 3v5h5", "M9 13h6", "M9 17h4"],
  table: ["M4 5.5h16v13H4z", "M4 10h16", "M10.5 10v8.5"],
  slides: ["M3.5 4.5h17v11h-17z", "M12 15.5V19", "M8 19.5h8", "m8 12 2.5-3 2 2L16 7.5"],
  hammer: ["m15 12-8.4 8.4a2.1 2.1 0 0 1-3-3L12 9", "m18 15 4-4", "m21.5 11.5-1.9-1.9A2 2 0 0 1 19 8.2V7l-2.3-2.3a6 6 0 0 0-4.2-1.7L9 3l.9.8A6.2 6.2 0 0 1 12 8.4V10l2 2h1.2a2 2 0 0 1 1.4.6l1.9 1.9"],
  package: ["M21 8a2 2 0 0 0-1-1.7l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.7l7 4a2 2 0 0 0 2 0l7-4a2 2 0 0 0 1-1.7Z", "m3.3 7 8.7 5 8.7-5", "M12 22V12"],
  diagnose: ["M11 17a6 6 0 1 0 0-12 6 6 0 0 0 0 12Z", "m16 16 4.5 4.5", "M8.5 11h1.2l.9-1.8 1.4 3.6.9-1.8h1.6"],
  scan: ["M4 5h16a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1Z", "M6.5 12h3l1.5-3 2 6 1.5-3h3"],
  gear: ["M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z", "M12 2v3", "M12 19v3", "M2 12h3", "M19 12h3", "m4.9 4.9 2.1 2.1", "m17 17 2.1 2.1", "m4.9 19.1 2.1-2.1", "m17 7 2.1-2.1"],
  bolt: ["M13 2 4.5 13.5h6L11 22l8.5-11.5h-6L13 2Z"],
  flask: ["M9 3h6", "M10 3v6L4.7 18a2 2 0 0 0 1.8 3h11a2 2 0 0 0 1.8-3L14 9V3", "M7.5 15h9"],
  ruler: ["M3 17 17 3l4 4L7 21l-4-4Z", "m8 16 1.5 1.5", "m11 13 1.5 1.5", "m14 10 1.5 1.5"],
  bulb: ["M9 18h6", "M10 21h4", "M12 3a6 6 0 0 0-3.5 10.9c.7.5 1.2 1.3 1.4 2.1h4.2c.2-.8.7-1.6 1.4-2.1A6 6 0 0 0 12 3Z"],
  folder: ["M3.5 6.5h6l2 2h9v10h-17z"],
};
const SKILL_FALLBACK_ICONS = ["gear", "bolt", "flask", "ruler", "bulb", "folder"];

function skillIconElement(skill) {
  const custom = String(skill.icon || "").trim();
  if (custom && SKILL_ICON_PATHS[custom]) {
    return svgIcon(SKILL_ICON_PATHS[custom]);
  }
  if (custom && !/^[a-z][a-z0-9-]*$/.test(custom)) {
    // Emoji or other literal glyph declared by the skill author.
    return document.createTextNode(custom);
  }
  const name = String(skill.name || "?");
  let hash = 0;
  for (let i = 0; i < name.length; i += 1) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  return svgIcon(SKILL_ICON_PATHS[SKILL_FALLBACK_ICONS[hash % SKILL_FALLBACK_ICONS.length]]);
}

function stageSkillPrompt(skill) {
  const displayName = skill.displayName || skill.name || "skill";
  const defaultPrompt = skill.defaultPrompt || `请读取并使用 ${skill.name} skill。`;
  if (skill.interaction === "instant") {
    // One-click skill: the click IS the send AND the consent. The skill's
    // declared tools are pre-approved for this run only (the set is cleared
    // when the run ends), so a configured action runs like double-clicking
    // the .bat -- no extra Enter, no approval dialog. First-time setup
    // (script path, artifact dirs) still happens in conversation.
    if (state.busy) {
      showToast("当前有任务进行中，稍后再点。", "error");
      return;
    }
    (skill.autoApproveTools || []).forEach((tool) => state.autoApproveTools.add(tool));
    sendTask(defaultPrompt);
    if (state.busy) {
      showToast(`${displayName} 已启动。`);
    } else {
      // The launch was rejected (e.g. missing API key): the pre-approval must
      // not linger and silently apply to the next unrelated task.
      state.autoApproveTools.clear();
    }
    return;
  }
  if (skill.interaction === "direct") {
    // Fixed-action skill: the default prompt is complete, nothing to fill in.
    // Stage it ready to send -- one Enter runs it (execution still goes through
    // the normal approval flow).
    elements.prompt.value = defaultPrompt;
    resizePrompt();
    elements.prompt.focus();
    showToast(`已填入 ${displayName} 指令，按 Enter 直接执行。`);
    return;
  }
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
  // One concise sentence. Split only on CJK/full sentence enders -- a plain
  // Latin "." must NOT split, or "生成 .xlsx 表格" collapses to "生成 .".
  const firstSentence = text.split(/(?<=[。！？!?])\s*/)[0].trim() || text;
  return firstSentence.length > 40 ? `${firstSentence.slice(0, 40)}…` : firstSentence;
}

function buildSkillRow(skill, index) {
  // Panel rows are launch-only; deletion lives in the "全部" grid dialog to
  // keep a single management entry point.
  const row = document.createElement("div");
  row.className = "skill-row";
  const button = document.createElement("button");
  button.className = "skill-action";
  button.type = "button";
  button.title = `${skill.displayName || skill.name}\n${skill.description || ""}`;
  // The favorites panel keeps one calm, unified tone; per-skill colors live
  // only in the "全部" grid.
  const icon = document.createElement("span");
  icon.className = "skill-icon neutral";
  icon.replaceChildren(skillIconElement(skill));
  const copy = document.createElement("span");
  copy.className = "skill-copy";
  const title = document.createElement("strong");
  title.textContent = (skill.displayName || skill.name) + (skill.interaction === "instant" ? " ⚡" : "");
  const subtitle = document.createElement("small");
  const subtitleText = skillSubtitle(skill);
  subtitle.textContent = subtitleText;
  subtitle.title = String(skill.shortDescription || skill.description || subtitleText);
  copy.append(title, subtitle);
  button.append(icon, copy);
  button.addEventListener("click", () => stageSkillPrompt(skill));
  row.append(button);
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
    icon.replaceChildren(skillIconElement(skill));
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
  let addedImage = false;
  for (const file of selected) {
    try {
      const attachment = await readAttachment(file);
      state.pendingAttachments.push(attachment);
      if (attachment.kind === "image") addedImage = true;
    } catch (_error) {
      showToast(`${file.name} 无法读取：${_error.message}`, "error");
    }
  }
  elements.attachmentInput.value = "";
  renderPendingAttachments();
  if (addedImage) {
    const provider = providerConfig(state.config?.provider);
    if (provider && provider.vision === "none") {
      showToast(`${provider.label} 的对话接口不支持图片识别，建议在设置中切换到支持识图的供应商（如 Kimi）。`, "error");
    }
  }
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
      throw new Error(`PDF 附件超过 ${Math.round(MAX_PDF_ATTACHMENT_BYTES / 1_000_000)} MB 上限`);
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
  const sessionId = state.currentSessionId;
  const attachments = [...state.pendingAttachments];
  const typedTask = String(prefilled ?? elements.prompt.value).trim();
  const task = typedTask || (attachments.length ? "请阅读附件内容。" : "");
  if (!task || state.busy || state.runs.has(sessionId)) return;
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
  const draft = appendAssistantDraft(sessionId);
  draft.task = task;
  const runState = { controller: new AbortController(), draft, stopped: false };
  state.runs.set(sessionId, runState);
  setBusy(true);
  // Everything below writes through THIS run's draft, never a global one:
  // the user may switch sessions (and even start a second run there) while
  // this stream is still arriving.
  const viewingThisRun = () => state.currentSessionId === sessionId;
  let answerText = "";
  let completed = false;
  // Smooth typewriter: providers like Kimi emit bursty chunks with long gaps,
  // which looks like stuttering. Buffer arrivals and drain at a steady cadence
  // (draining faster when the backlog grows so we never fall behind).
  let displayedText = "";
  let pendingText = "";
  const smoothTimer = window.setInterval(() => {
    if (!pendingText) return;
    const step = Math.max(4, Math.ceil(pendingText.length / 10));
    displayedText += pendingText.slice(0, step);
    pendingText = pendingText.slice(step);
    setDraftText(draft, displayedText);
  }, 33);
  const flushSmooth = () => {
    displayedText += pendingText;
    pendingText = "";
  };
  try {
    await streamApi(
      "/api/chat-stream",
      {
        sessionId,
        task,
        attachments,
      },
      (event) => {
        if (event.type === "delta") {
          answerText += event.text || "";
          pendingText += event.text || "";
        } else if (event.type === "activity") {
          // Provider-side actions (e.g. Kimi builtin web search) that have no
          // local tool events still surface in the activity panel.
          setActivity(draft, event.key || "activity", event.label || "处理中", "active");
        } else if (event.type === "notice") {
          if (viewingThisRun()) showToast(event.message || "任务提示", "error");
          setActivity(draft, "notice", event.message || "任务提示", "failed");
        } else if (event.type === "done") {
          completed = true;
          flushSmooth();
          const stopped = Boolean(event.stopped) || runState.stopped;
          answerText = event.answer || answerText || "模型未返回文本结果。";
          setDraftText(draft, answerText);
          finalizeAssistantDraft(draft, answerText, { stopped, usage: event.usage });
          if (stopped && viewingThisRun()) restoreLastSubmission();
        }
      },
      runState.controller.signal,
    );
    if (!completed) {
      flushSmooth();
      setDraftText(draft, answerText || "模型未返回文本结果。");
      finalizeAssistantDraft(draft, answerText);
    }
    await loadSessions();
  } catch (error) {
    flushSmooth();
    if (answerText) setDraftText(draft, answerText);
    if (error.name === "AbortError" || runState.stopped) {
      finalizeAssistantDraft(draft, answerText, { stopped: true });
      if (viewingThisRun()) {
        restoreLastSubmission();
        showToast("已停止。可以编辑问题后重新发送。");
      }
      try {
        await loadSessions();
      } catch (_error) {
        // Listing can briefly fail right after a stop; the next poll recovers.
      }
    } else {
      failAssistantDraft(draft, error.message);
      if (viewingThisRun()) {
        appendMessage("system", `任务失败：${error.message}`);
      } else {
        showToast(`后台会话任务失败：${error.message}`, "error");
      }
    }
  } finally {
    window.clearInterval(smoothTimer);
    state.runs.delete(sessionId);
    // Only reset the composer/busy state if the user is still looking at this
    // run's session; another session may have its own run in flight.
    if (viewingThisRun()) setBusy(false);
  }
}

async function sendSteer() {
  const text = elements.prompt.value.trim();
  if (!text || !state.busy) return;
  elements.prompt.value = "";
  resizePrompt();
  appendMessage("user", text, { withActions: true });
  try {
    await api("/api/chat/steer", {
      method: "POST",
      body: JSON.stringify({ text, sessionId: state.currentSessionId }),
    });
    showToast("已把补充引导交给正在执行的任务，将在下一轮生效。");
  } catch (error) {
    showToast(error.message, "error");
  }
}

function stopTask() {
  const run = state.runs.get(state.currentSessionId);
  if (!run && !state.busy) return;
  if (run) {
    run.stopped = true;
    try {
      run.controller.abort();
    } catch (_error) {
      // Ignore: the fetch may have already settled.
    }
  }
  api("/api/chat/stop", {
    method: "POST",
    body: JSON.stringify({ sessionId: state.currentSessionId }),
  }).catch(() => {});
}

async function waitForSessionIdle(sessionId, timeoutMs = 10000) {
  // "Idle" needs BOTH sides: our stream handler finished (runs map cleared)
  // and the server released the session lock, or an immediate re-send 409s.
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!state.runs.has(sessionId)) {
      try {
        const config = await api("/api/config");
        if (!(config.busySessions || []).includes(sessionId)) return true;
      } catch (_error) {
        // Transient; retry until the deadline.
      }
    }
    await new Promise((resolve) => window.setTimeout(resolve, 250));
  }
  return false;
}

async function resendInterrupting(text) {
  // Claude-style edit/retry mid-run: interrupt the current answer for this
  // session, wait for it to actually stop, then re-ask in the SAME session.
  const sessionId = state.currentSessionId;
  if (state.runs.has(sessionId) || state.busy) {
    showToast("正在停止当前回答，随后重新提问…");
    stopTask();
    const idle = await waitForSessionIdle(sessionId);
    if (!idle) {
      showToast("当前任务未能及时停止，请稍后再试", "error");
      return;
    }
    if (state.currentSessionId !== sessionId) return;
  }
  // The stop above restored the previous submission into the composer; the
  // edited question replaces it entirely.
  state.pendingAttachments = [];
  renderPendingAttachments();
  elements.prompt.value = "";
  resizePrompt();
  sendTask(text);
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

function draftForEvent(event) {
  // Route server events to the draft of the session that emitted them; events
  // without a session tag fall back to the currently viewed session's run.
  const sid = event.session || state.currentSessionId;
  return state.runs.get(sid)?.draft || null;
}

function handleServerEvent(event) {
  state.lastEventId = Math.max(state.lastEventId, Number(event.id || 0));
  const draft = draftForEvent(event);
  if (event.type === "agent_started") {
    setActivity(draft, "agent", "正在理解任务", "active");
  }
  if (event.type === "approval_required") {
    setActivity(draft, `approval:${event.tool}`, "等待人工批准", "waiting", toolDisplayName(event.tool));
  }
  if (event.type === "approval_resolved") {
    setActivity(draft, `approval:${event.tool}`, event.approved ? "审批已通过" : "审批已拒绝", event.approved ? "done" : "failed", toolDisplayName(event.tool));
  }
  if (event.type === "tool_started") {
    setActivity(draft, `tool:${event.tool}`, toolDisplayName(event.tool), "active");
  }
  if (event.type === "tool_finished") {
    setActivity(draft, `tool:${event.tool}`, toolDisplayName(event.tool), event.ok ? "done" : "failed", event.ok ? "完成" : (event.error_type || "失败"));
  }
  if (event.type === "agent_finished") {
    setActivity(draft, "agent", "正在整理答案", "done");
  }
  if (event.type === "agent_failed") {
    setActivity(draft, "agent", "任务失败", "failed");
  }
  if (event.type === "agent_stopped") {
    setActivity(draft, "agent", "已停止", "failed");
  }
  if ((event.type === "agent_finished" || event.type === "agent_stopped" || event.type === "agent_failed")
      && event.session && event.session === state.currentSessionId
      && state.busy && !state.runs.has(event.session)) {
    // A run in this session finished on the server while we were not the
    // stream owner (e.g. another tab started it): clear busy, show the answer.
    setBusy(false);
    loadCurrentSession(state.currentSessionId).catch(() => {});
  }
  if (event.type === "steer_received") {
    setActivity(draft, "steer", "已收到补充引导，下一轮生效", "done");
  }
  if (event.type === "open_link") {
    const href = safeLinkUrl(event.url || "");
    if (href) {
      const opened = window.open(href, "_blank", "noopener");
      if (!opened) showToast(`浏览器拦截了弹出窗口，请手动打开：${event.name || href}`, "error");
    }
  }
  if (event.type === "tool_finished" && event.ok
      && ["add_calendar_entry", "delete_calendar_entry", "add_quick_link", "delete_quick_link"].includes(event.tool)) {
    // The agent changed panel data mid-conversation: refresh calendar/links.
    loadPersonal().catch(() => {});
  }
  if (event.type === "skill_imported" || event.type === "skill_deleted") {
    // A skill was created/installed/removed mid-session (possibly by the agent
    // itself): refresh the catalog so the panel updates without a restart.
    api("/api/config").then(updateConfig).catch(() => {});
    if (event.type === "skill_imported" && event.skill) {
      showToast(`新 skill 已加入面板：${event.skill}`);
    }
  }
  // Toasts about another session's tools would just confuse; activity panels
  // already carry them inside their own conversation.
  const eventIsForViewedSession = !event.session || event.session === state.currentSessionId;
  if (eventIsForViewedSession) {
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

const RISK_LABELS = { read: "读取", write: "写入", execute: "执行", external: "外部访问", clinical: "临床（禁止）" };

function describeApproval(tool, args = {}) {
  const text = (value, cap = 90) => {
    const s = String(value ?? "");
    return s.length > cap ? s.slice(0, cap) + "…" : s;
  };
  const contentPreview = (value) => {
    const s = String(value ?? "");
    const lines = s.split("\n");
    return `${lines.length} 行 · ${text(lines[0], 60) || "(空行)"}`;
  };
  switch (tool) {
    case "write_project_text":
      return { title: `写入文件 ${text(args.path)}`, rows: [["内容", contentPreview(args.content)]] };
    case "run_build":
      return { title: `运行编译/脚本档案「${text(args.profile)}」`, rows: [] };
    case "configure_build_profile":
      return { title: `登记编译档案「${text(args.profile)}」`, rows: [["脚本", text(args.script_path, 120)]] };
    case "web_search":
      return { title: "联网搜索（含敏感词，需确认）", rows: [["查询", text(args.query, 120)]] };
    case "fetch_url":
      return { title: "读取网页（需确认）", rows: [["地址", text(args.url, 120)]] };
    case "append_agent_memory":
      return { title: "写入一条记忆", rows: [["内容", text(args.note, 120)], ["分类", text(args.category)]] };
    case "forget_agent_memory":
      return { title: `删除包含「${text(args.match)}」的记忆`, rows: [] };
    case "create_agent_skill":
      return { title: "创建一个新 Skill", rows: [["定义", contentPreview(args.skill_md)]] };
    case "install_agent_skill":
      return { title: "从 GitHub 安装 Skill", rows: [["地址", text(args.url, 120)]] };
    case "create_word_document":
      return { title: `生成 Word 文档 ${text(args.path)}`, rows: [["标题", text(args.title)]] };
    case "create_powerpoint":
      return { title: `生成 PPT ${text(args.path)}`, rows: [["页数", Array.isArray(args.slides) ? args.slides.length : "?"]] };
    case "create_excel":
      return { title: `生成 Excel ${text(args.path)}`, rows: [["工作表", Array.isArray(args.sheets) ? args.sheets.length : "?"]] };
    case "run_unit_tests":
      return { title: "运行项目单元测试", rows: [] };
    default: {
      const rows = Object.entries(args || {}).slice(0, 4).map(([key, value]) => [key, text(
        typeof value === "string" ? value : JSON.stringify(value), 100)]);
      return { title: `${toolDisplayName(tool)}`, rows };
    }
  }
}

function removeApprovalCard() {
  state.approvalCard?.remove();
  state.approvalCard = null;
  elements.composer.classList.remove("approval-active");
}

function renderApprovalCard(approval) {
  removeApprovalCard();
  const described = describeApproval(approval.tool, approval.arguments || {});
  const card = document.createElement("div");
  card.className = "approval-embed";

  const head = document.createElement("div");
  head.className = "approval-inline-head";
  const badge = document.createElement("span");
  badge.className = `approval-risk-badge risk-${approval.risk}`;
  badge.textContent = RISK_LABELS[approval.risk] || approval.risk;
  const title = document.createElement("strong");
  title.textContent = described.title;
  head.append(badge, title);
  card.append(head);

  if (described.rows.length) {
    const details = document.createElement("div");
    details.className = "approval-inline-details";
    described.rows.forEach(([label, value]) => {
      const row = document.createElement("div");
      const key = document.createElement("span");
      key.textContent = label;
      const val = document.createElement("code");
      val.textContent = String(value);
      row.append(key, val);
      details.append(row);
    });
    card.append(details);
  }

  const actions = document.createElement("div");
  actions.className = "approval-inline-actions";
  const allow = document.createElement("button");
  allow.type = "button";
  allow.className = "approval-btn allow";
  allow.textContent = "允许";
  allow.addEventListener("click", () => resolveApproval(true, false));
  const always = document.createElement("button");
  always.type = "button";
  always.className = "approval-btn always";
  always.textContent = "本轮始终允许";
  always.title = "本次任务结束前，同类操作不再询问";
  always.addEventListener("click", () => resolveApproval(true, true));
  const deny = document.createElement("button");
  deny.type = "button";
  deny.className = "approval-btn deny";
  deny.textContent = "拒绝";
  deny.addEventListener("click", () => resolveApproval(false, false));
  actions.append(allow, always, deny);
  card.append(actions);

  // The approval is part of the SAME composer dialog: the buttons grow inside
  // it while the textarea stays usable, so the user can still type steering
  // guidance (Enter sends it to the running task) instead of only clicking.
  elements.composer.prepend(card);
  elements.composer.classList.add("approval-active");
  state.approvalCard = card;
  elements.prompt.focus();
}

async function pollApprovals() {
  // A pending card that belongs to a session we navigated away from must not
  // keep squatting in this session's composer.
  if (state.currentApproval && state.currentApproval.session
      && state.currentApproval.session !== state.currentSessionId) {
    removeApprovalCard();
    state.currentApproval = null;
  }
  if (state.currentApproval) return;
  const result = await api("/api/approvals");
  // Only surface approvals belonging to the session on screen; a blocked run
  // in another session shows its card when the user switches back to it.
  const approval = (result.approvals || []).find(
    (item) => !item.session || item.session === state.currentSessionId,
  );
  if (!approval) return;
  state.currentApproval = approval;
  // "本轮始终允许" auto-resolves same-tool requests without re-asking.
  if (state.autoApproveTools.has(approval.tool)) {
    const current = approval;
    state.currentApproval = null;
    try {
      await api("/api/approval", { method: "POST", body: JSON.stringify({ id: current.id, approved: true }) });
    } catch (_error) {
      // The request may have timed out server-side; the next poll recovers.
    }
    return;
  }
  renderApprovalCard(approval);
}

async function resolveApproval(approved, always) {
  if (!state.currentApproval) return;
  const approval = state.currentApproval;
  state.currentApproval = null;
  if (approved && always) state.autoApproveTools.add(approval.tool);
  removeApprovalCard();
  try {
    await api("/api/approval", {
      method: "POST",
      body: JSON.stringify({ id: approval.id, approved }),
    });
  } catch (error) {
    showToast(error.message, "error");
  }
}

function renderUsageTotals() {
  const totals = state.config?.usageTotals;
  if (!totals) return;
  elements.usageStats.textContent =
    `累计用量：输入 ${totals.promptTokens.toLocaleString()} · 输出 ${totals.completionTokens.toLocaleString()} tokens · ${totals.turns} 轮`;
}

async function loadAudit() {
  elements.auditTbody.replaceChildren();
  try {
    const result = await api("/api/audit?limit=200");
    (result.entries || []).forEach((entry) => {
      const row = document.createElement("tr");
      const cells = [
        String(entry.timestamp || "").slice(0, 19).replace("T", " "),
        String(entry.event || ""),
        String(entry.tool || ""),
        String(entry.risk || ""),
        entry.ok === false ? (entry.error_type || "失败") : entry.ok === true ? "成功" : "",
      ];
      cells.forEach((text) => {
        const td = document.createElement("td");
        td.textContent = text;
        row.append(td);
      });
      elements.auditTbody.append(row);
    });
    renderUsageTotals();
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
  if (target === "audit") loadAudit();
}

function openSettings(section = "connection") {
  if (state.config) {
    elements.providerInputs.forEach((input) => { input.checked = input.value === state.config.provider; });
    syncProviderFields(state.config.provider, false);
    elements.model.value = state.config.model;
    elements.baseUrl.value = state.config.baseUrl || "";
    elements.root.value = state.config.root;
    elements.webSearchEnabledToggle.checked = state.config.webSearchEnabled !== false;
    elements.autoMemoryToggle.checked = state.config.autoMemory !== false;
  }
  const themePref = themePreference();
  elements.themeInputs.forEach((input) => { input.checked = input.value === themePref; });
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
    webSearchEnabled: elements.webSearchEnabledToggle.checked,
    autoMemory: elements.autoMemoryToggle.checked,
  };
  try {
    const config = await api("/api/config", { method: "POST", body: JSON.stringify(payload) });
    updateConfig(config);
    closeSettings();
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
  elements.workdirChip.disabled = true;
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
    await loadSessions();
    await loadCurrentSession(config.currentSessionId);
    appendMessage("system", `工作目录已切换到：\`${picked.path}\``);
    showToast("工作目录已切换");
  } catch (error) {
    showToast(error.message, "error");
  } finally {
    elements.workdirChip.disabled = false;
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
      if (state.busy) sendSteer();
      else sendTask();
    }
  });
  elements.attachButton.addEventListener("click", () => elements.attachmentInput.click());
  elements.attachmentInput.addEventListener("change", () => addAttachments(elements.attachmentInput.files));
  elements.sessionSearch.addEventListener("input", () => loadSessions(elements.sessionSearch.value));
  elements.settingsButton.addEventListener("click", () => openSettings());
  elements.refreshAudit.addEventListener("click", loadAudit);
  elements.clearAutoMemory.addEventListener("click", async () => {
    if (!window.confirm("清空自动总结的隐式记忆？显式记忆不受影响。")) return;
    try {
      await api("/api/memory/clear-auto", { method: "POST", body: "{}" });
      showToast("自动记忆已清空");
    } catch (error) {
      showToast(error.message, "error");
    }
  });
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
  elements.workdirChip.addEventListener("click", switchWorkspaceFolder);
  elements.webSearchToggle.addEventListener("click", toggleWebSearch);
  elements.calPrev.addEventListener("click", () => shiftCalendarMonth(-1));
  elements.calNext.addEventListener("click", () => shiftCalendarMonth(1));
  elements.addEventButton.addEventListener("click", addCalendarEventFromPanel);
  elements.addLinkButton.addEventListener("click", addQuickLinkFromPanel);
  elements.panelForm.addEventListener("submit", submitPanelForm);
  elements.panelFormCancel.addEventListener("click", closePanelForm);
  elements.closePanelForm.addEventListener("click", closePanelForm);
  elements.panelFormModal.addEventListener("click", (event) => {
    if (event.target === elements.panelFormModal) closePanelForm();
  });
  // Theme radios apply instantly and persist locally; no server round-trip.
  elements.themeInputs.forEach((input) => input.addEventListener("change", () => {
    if (input.checked) setThemePreference(input.value);
  }));
  elements.sidebarToggle.addEventListener("click", () => toggleSidebar(true));
  elements.sidebarExpand.addEventListener("click", () => toggleSidebar(false));
  document.querySelectorAll("[data-task]").forEach((button) => {
    button.addEventListener("click", () => sendTask(button.dataset.task));
  });
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (!elements.settingsModal.classList.contains("hidden")) closeSettings();
      if (!elements.skillsModal.classList.contains("hidden")) closeSkillsModal();
      if (!elements.panelFormModal.classList.contains("hidden")) closePanelForm();
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
    await Promise.all([loadPersonal(), loadSessions()]);
    await loadCurrentSession(config.currentSessionId);
    state.eventTimer = window.setInterval(pollEvents, 650);
    pollEvents();
  } catch (error) {
    appendMessage("system", `无法连接本地 Agent 服务：${error.message}`);
    setConnection("offline", "服务不可用");
  }
}

initialize();
