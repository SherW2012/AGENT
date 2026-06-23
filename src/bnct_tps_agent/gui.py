from __future__ import annotations

import argparse
import json
import os
import queue
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .agent import AgentRuntime
from .audit import AuditLogger
from .config import Settings
from .project_tools import TEXT_SUFFIXES, list_project_files
from .safety import Risk, SafetyPolicy
from .tool_registry import ToolRegistry


COLORS = {
    "bg": "#0f1218",
    "panel": "#161b24",
    "surface": "#1d2430",
    "surface_2": "#252e3c",
    "border": "#303949",
    "text": "#eef1f5",
    "muted": "#98a2b3",
    "accent": "#d27d5f",
    "accent_hover": "#e28b6b",
    "success": "#55b88a",
    "warning": "#d9a441",
    "danger": "#df6b74",
    "user": "#263244",
    "assistant": "#1a202a",
}


@dataclass
class ApprovalRequest:
    tool_name: str
    risk: Risk
    arguments: dict[str, Any]
    event: threading.Event = field(default_factory=threading.Event)
    approved: bool = False


def format_tool_event(event: dict[str, Any]) -> str:
    now = datetime.now().strftime("%H:%M:%S")
    tool = event.get("tool", "unknown")
    if event.get("type") == "tool_started":
        return f"{now}  -> {tool}  [{event.get('risk', '?')}]"
    status = "完成" if event.get("ok") else "失败"
    return f"{now}  <- {tool}  {status}"


def compact_arguments(arguments: dict[str, Any]) -> str:
    safe: dict[str, Any] = {}
    for key, value in arguments.items():
        if key in {"content", "query"}:
            safe[key] = f"<{len(str(value))} chars>"
        else:
            safe[key] = value
    return json.dumps(safe, ensure_ascii=False, indent=2)[:1600]


class BNCTAgentApp:
    def __init__(self, window: tk.Tk, project_root: Path):
        self.window = window
        self.project_root = project_root.resolve()
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.runtime: AgentRuntime | None = None
        self.registry: ToolRegistry | None = None
        self.audit: AuditLogger | None = None
        self.busy = False

        self.window.title("BNCT TPS Agent")
        self.window.geometry("1420x860")
        self.window.minsize(1080, 680)
        self.window.configure(bg=COLORS["bg"])
        self.window.protocol("WM_DELETE_WINDOW", self._on_close)

        self._configure_styles()
        self._build_ui()
        self._initialize_agent()
        self._populate_tree()
        self._append_message(
            "system",
            "桌面工作区已就绪。Agent 仅用于研发辅助；计划批准、处方修改和患者数据写回始终被阻断。",
        )
        self.window.after(80, self._drain_events)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.window)
        style.theme_use("clam")
        style.configure("TFrame", background=COLORS["bg"])
        style.configure("Panel.TFrame", background=COLORS["panel"])
        style.configure("Surface.TFrame", background=COLORS["surface"])
        style.configure(
            "TLabel",
            background=COLORS["bg"],
            foreground=COLORS["text"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "Muted.TLabel",
            background=COLORS["panel"],
            foreground=COLORS["muted"],
            font=("Segoe UI", 9),
        )
        style.configure(
            "Title.TLabel",
            background=COLORS["panel"],
            foreground=COLORS["text"],
            font=("Segoe UI Semibold", 15),
        )
        style.configure(
            "Status.TLabel",
            background=COLORS["surface_2"],
            foreground=COLORS["success"],
            padding=(10, 5),
            font=("Segoe UI Semibold", 9),
        )
        style.configure(
            "TButton",
            background=COLORS["surface_2"],
            foreground=COLORS["text"],
            borderwidth=0,
            padding=(12, 8),
            font=("Segoe UI", 9),
        )
        style.map("TButton", background=[("active", COLORS["border"]), ("disabled", COLORS["surface"])])
        style.configure(
            "Accent.TButton",
            background=COLORS["accent"],
            foreground="#ffffff",
            padding=(18, 9),
            font=("Segoe UI Semibold", 10),
        )
        style.map("Accent.TButton", background=[("active", COLORS["accent_hover"]), ("disabled", COLORS["border"])])
        style.configure(
            "Treeview",
            background=COLORS["panel"],
            fieldbackground=COLORS["panel"],
            foreground=COLORS["text"],
            borderwidth=0,
            rowheight=27,
            font=("Segoe UI", 9),
        )
        style.map("Treeview", background=[("selected", COLORS["surface_2"])])
        style.configure("Treeview.Heading", background=COLORS["surface"], foreground=COLORS["muted"])
        style.configure(
            "TNotebook",
            background=COLORS["panel"],
            borderwidth=0,
        )
        style.configure(
            "TNotebook.Tab",
            background=COLORS["panel"],
            foreground=COLORS["muted"],
            padding=(12, 7),
        )
        style.map("TNotebook.Tab", background=[("selected", COLORS["surface"])], foreground=[("selected", COLORS["text"])])

    def _build_ui(self) -> None:
        self._build_header()
        body = ttk.Panedwindow(self.window, orient=tk.HORIZONTAL)
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))

        left = ttk.Frame(body, style="Panel.TFrame", width=260)
        center = ttk.Frame(body, style="Panel.TFrame")
        right = ttk.Frame(body, style="Panel.TFrame", width=310)
        body.add(left, weight=0)
        body.add(center, weight=1)
        body.add(right, weight=0)

        self._build_workspace(left)
        self._build_chat(center)
        self._build_inspector(right)

    def _build_header(self) -> None:
        header = ttk.Frame(self.window, style="Panel.TFrame")
        header.pack(fill=tk.X, padx=12, pady=12)
        title_block = ttk.Frame(header, style="Panel.TFrame")
        title_block.pack(side=tk.LEFT, padx=14, pady=10)
        ttk.Label(title_block, text="BNCT TPS Agent", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(title_block, text="研发工作台 · 人工审批 · 全程审计", style="Muted.TLabel").pack(anchor=tk.W, pady=(2, 0))

        self.status_label = ttk.Label(header, text="● 就绪", style="Status.TLabel")
        self.status_label.pack(side=tk.RIGHT, padx=(6, 14))
        ttk.Button(header, text="设置", command=self._open_settings).pack(side=tk.RIGHT, padx=4)
        ttk.Button(header, text="新会话", command=self._new_session).pack(side=tk.RIGHT, padx=4)

    def _build_workspace(self, parent: ttk.Frame) -> None:
        toolbar = ttk.Frame(parent, style="Panel.TFrame")
        toolbar.pack(fill=tk.X, padx=12, pady=(12, 8))
        ttk.Label(toolbar, text="工程文件", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Button(toolbar, text="更换", command=self._choose_workspace).pack(side=tk.RIGHT)

        self.path_label = ttk.Label(parent, text=str(self.project_root), style="Muted.TLabel", wraplength=230)
        self.path_label.pack(fill=tk.X, padx=12, pady=(0, 8))

        tree_frame = ttk.Frame(parent, style="Panel.TFrame")
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        self.file_tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse")
        tree_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.file_tree.yview)
        self.file_tree.configure(yscrollcommand=tree_scroll.set)
        self.file_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_tree.bind("<<TreeviewSelect>>", self._preview_selected_file)

        quick = ttk.Frame(parent, style="Panel.TFrame")
        quick.pack(fill=tk.X, padx=12, pady=(0, 12))
        ttk.Label(quick, text="快捷任务", style="Muted.TLabel").pack(anchor=tk.W, pady=(0, 6))
        ttk.Button(quick, text="分析当前工程", command=lambda: self._submit_task("分析当前工程结构，指出主要模块和测试入口。"), width=24).pack(fill=tk.X, pady=2)
        ttk.Button(quick, text="校验示例快照", command=self._offline_snapshot_demo, width=24).pack(fill=tk.X, pady=2)

    def _build_chat(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        chat_header = ttk.Frame(parent, style="Panel.TFrame")
        chat_header.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))
        ttk.Label(chat_header, text="Agent 对话", style="Title.TLabel").pack(side=tk.LEFT)
        self.model_label = ttk.Label(chat_header, text="模型未连接", style="Muted.TLabel")
        self.model_label.pack(side=tk.RIGHT)

        transcript_frame = ttk.Frame(parent, style="Surface.TFrame")
        transcript_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 10))
        self.transcript = tk.Text(
            transcript_frame,
            bg=COLORS["surface"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief=tk.FLAT,
            borderwidth=0,
            wrap=tk.WORD,
            padx=20,
            pady=16,
            font=("Segoe UI", 10),
            spacing1=2,
            spacing3=8,
            state=tk.DISABLED,
        )
        transcript_scroll = ttk.Scrollbar(transcript_frame, orient=tk.VERTICAL, command=self.transcript.yview)
        self.transcript.configure(yscrollcommand=transcript_scroll.set)
        self.transcript.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        transcript_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.transcript.tag_configure("user_header", foreground="#8fb8ff", font=("Segoe UI Semibold", 10), spacing1=10)
        self.transcript.tag_configure("assistant_header", foreground=COLORS["accent_hover"], font=("Segoe UI Semibold", 10), spacing1=10)
        self.transcript.tag_configure("system_header", foreground=COLORS["warning"], font=("Segoe UI Semibold", 9), spacing1=8)
        self.transcript.tag_configure("body", foreground=COLORS["text"], lmargin1=4, lmargin2=4, spacing3=10)
        self.transcript.tag_configure("system_body", foreground=COLORS["muted"], lmargin1=4, lmargin2=4, spacing3=10)

        composer = ttk.Frame(parent, style="Panel.TFrame")
        composer.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.prompt = tk.Text(
            composer,
            height=4,
            bg=COLORS["surface_2"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            selectbackground=COLORS["accent"],
            relief=tk.FLAT,
            borderwidth=0,
            wrap=tk.WORD,
            padx=12,
            pady=10,
            font=("Segoe UI", 10),
        )
        self.prompt.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.prompt.bind("<Control-Return>", self._send_shortcut)
        self.prompt.bind("<Control-KP_Enter>", self._send_shortcut)
        self.send_button = ttk.Button(composer, text="发送\nCtrl+Enter", style="Accent.TButton", command=self._send)
        self.send_button.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))

    def _build_inspector(self, parent: ttk.Frame) -> None:
        notebook = ttk.Notebook(parent)
        notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        activity_tab = ttk.Frame(notebook, style="Panel.TFrame")
        preview_tab = ttk.Frame(notebook, style="Panel.TFrame")
        notebook.add(activity_tab, text="活动")
        notebook.add(preview_tab, text="预览")

        self.activity = tk.Listbox(
            activity_tab,
            width=36,
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            selectbackground=COLORS["surface_2"],
            selectforeground=COLORS["text"],
            relief=tk.FLAT,
            borderwidth=0,
            font=("Cascadia Mono", 9),
            activestyle="none",
        )
        self.activity.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.activity.insert(tk.END, "等待工具调用...")

        self.preview_title = ttk.Label(preview_tab, text="选择左侧文本文件", style="Muted.TLabel")
        self.preview_title.pack(fill=tk.X, padx=8, pady=8)
        self.preview = tk.Text(
            preview_tab,
            width=36,
            bg=COLORS["panel"],
            fg="#c9d2df",
            relief=tk.FLAT,
            borderwidth=0,
            wrap=tk.NONE,
            padx=10,
            pady=8,
            font=("Cascadia Mono", 9),
            state=tk.DISABLED,
        )
        self.preview.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

    def _initialize_agent(self) -> None:
        try:
            settings = Settings.load(self.project_root, interactive=True)
            self.audit = AuditLogger(settings.audit_dir)
            policy = SafetyPolicy(self._request_approval_from_worker)
            self.registry = ToolRegistry(
                settings.root,
                policy,
                self.audit,
                event_callback=lambda event: self.events.put(("tool_event", event)),
            )
            if settings.api_key:
                self.runtime = AgentRuntime(settings, self.registry, self.audit)
                self.model_label.configure(text=settings.model)
            else:
                self.runtime = None
                self.model_label.configure(text="未配置 API Key · 离线可用")
        except Exception as exc:
            self.runtime = None
            self.registry = None
            self.model_label.configure(text="初始化失败")
            self._append_message("system", f"初始化失败：{exc}")

    def _populate_tree(self) -> None:
        self.file_tree.delete(*self.file_tree.get_children())
        self.path_label.configure(text=str(self.project_root))
        try:
            result = list_project_files(self.project_root, "*", 600)
        except Exception as exc:
            self._append_message("system", f"无法读取工程树：{exc}")
            return

        nodes: dict[str, str] = {"": ""}
        for relative in sorted(result["files"]):
            parts = relative.split("/")
            parent_key = ""
            for index, part in enumerate(parts):
                key = "/".join(parts[: index + 1])
                if key in nodes:
                    parent_key = key
                    continue
                is_file = index == len(parts) - 1
                label = part if is_file else f"{part}/"
                self.file_tree.insert(nodes[parent_key], tk.END, iid=key, text=label, open=index < 1)
                nodes[key] = key
                parent_key = key

    def _preview_selected_file(self, _event: tk.Event | None = None) -> None:
        selected = self.file_tree.selection()
        if not selected:
            return
        relative = selected[0]
        target = (self.project_root / relative).resolve()
        if not target.is_file() or target.suffix.lower() not in TEXT_SUFFIXES:
            return
        try:
            content = target.read_text(encoding="utf-8", errors="replace")[:30_000]
        except OSError as exc:
            content = f"无法预览：{exc}"
        self.preview_title.configure(text=relative)
        self.preview.configure(state=tk.NORMAL)
        self.preview.delete("1.0", tk.END)
        self.preview.insert("1.0", content)
        self.preview.configure(state=tk.DISABLED)

    def _append_message(self, role: str, text: str) -> None:
        labels = {"user": "你", "assistant": "BNCT Agent", "system": "系统"}
        header_tags = {"user": "user_header", "assistant": "assistant_header", "system": "system_header"}
        body_tag = "system_body" if role == "system" else "body"
        self.transcript.configure(state=tk.NORMAL)
        self.transcript.insert(tk.END, labels[role] + "\n", header_tags[role])
        self.transcript.insert(tk.END, text.strip() + "\n", body_tag)
        self.transcript.configure(state=tk.DISABLED)
        self.transcript.see(tk.END)

    def _send_shortcut(self, _event: tk.Event) -> str:
        self._send()
        return "break"

    def _send(self) -> None:
        task = self.prompt.get("1.0", tk.END).strip()
        self._submit_task(task)

    def _submit_task(self, task: str) -> None:
        if not task or self.busy:
            return
        if self.runtime is None:
            self._append_message("system", "尚未连接模型。点击右上角“设置”填入本次会话的 API Key，或使用“校验示例快照”离线体验。")
            self._open_settings()
            return
        self.prompt.delete("1.0", tk.END)
        self._append_message("user", task)
        self._set_busy(True)
        threading.Thread(target=self._run_agent, args=(task,), daemon=True).start()

    def _run_agent(self, task: str) -> None:
        try:
            assert self.runtime is not None
            answer = self.runtime.run(task)
            self.events.put(("assistant", answer))
        except Exception as exc:
            self.events.put(("error", str(exc)))
        finally:
            self.events.put(("idle", None))

    def _offline_snapshot_demo(self) -> None:
        if self.registry is None or self.busy:
            return
        result = self.registry.execute("validate_plan_snapshot", {"path": "sample_data/deidentified_case.json"})
        summary = self.registry.execute("summarize_plan_snapshot", {"path": "sample_data/deidentified_case.json"})
        text = "离线校验结果：\n" + json.dumps(result, ensure_ascii=False, indent=2)
        text += "\n\n源指标摘要：\n" + json.dumps(summary, ensure_ascii=False, indent=2)
        self._append_message("assistant", text)

    def _request_approval_from_worker(self, tool_name: str, risk: Risk, arguments: dict) -> bool:
        request = ApprovalRequest(tool_name, risk, arguments)
        self.events.put(("approval", request))
        if not request.event.wait(timeout=600):
            return False
        return request.approved

    def _show_approval(self, request: ApprovalRequest) -> None:
        details = compact_arguments(request.arguments)
        request.approved = messagebox.askyesno(
            "需要人工批准",
            f"工具：{request.tool_name}\n风险：{request.risk.value}\n\n参数摘要：\n{details}\n\n是否允许本次执行？",
            parent=self.window,
        )
        request.event.set()

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "assistant":
                    self._append_message("assistant", str(payload))
                elif kind == "error":
                    self._append_message("system", f"执行失败：{payload}")
                elif kind == "idle":
                    self._set_busy(False)
                elif kind == "approval":
                    self._show_approval(payload)
                elif kind == "tool_event":
                    if self.activity.size() == 1 and self.activity.get(0) == "等待工具调用...":
                        self.activity.delete(0)
                    self.activity.insert(tk.END, format_tool_event(payload))
                    self.activity.see(tk.END)
        except queue.Empty:
            pass
        self.window.after(80, self._drain_events)

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        self.send_button.configure(state=tk.DISABLED if busy else tk.NORMAL)
        self.status_label.configure(text="● 工作中" if busy else "● 就绪")

    def _choose_workspace(self) -> None:
        selected = filedialog.askdirectory(initialdir=self.project_root, parent=self.window)
        if not selected:
            return
        self.project_root = Path(selected).resolve()
        self._new_session(announce=False)
        self._populate_tree()
        self._append_message("system", f"已切换工程：{self.project_root}")

    def _new_session(self, announce: bool = True) -> None:
        if self.busy:
            messagebox.showwarning("任务进行中", "请等待当前任务完成后再新建会话。", parent=self.window)
            return
        self._initialize_agent()
        self.activity.delete(0, tk.END)
        self.activity.insert(tk.END, "新会话，等待工具调用...")
        if announce:
            self._append_message("system", "已开始新会话。")

    def _open_settings(self) -> None:
        dialog = tk.Toplevel(self.window)
        dialog.title("Agent 设置")
        dialog.geometry("520x330")
        dialog.resizable(False, False)
        dialog.configure(bg=COLORS["panel"])
        dialog.transient(self.window)
        dialog.grab_set()

        frame = ttk.Frame(dialog, style="Panel.TFrame")
        frame.pack(fill=tk.BOTH, expand=True, padx=22, pady=18)
        ttk.Label(frame, text="连接设置", style="Title.TLabel").pack(anchor=tk.W, pady=(0, 14))

        ttk.Label(frame, text="API Key（仅保存在当前进程内）", style="Muted.TLabel").pack(anchor=tk.W)
        key_entry = tk.Entry(frame, show="●", bg=COLORS["surface_2"], fg=COLORS["text"], insertbackground=COLORS["text"], relief=tk.FLAT, font=("Segoe UI", 10))
        key_entry.pack(fill=tk.X, ipady=8, pady=(4, 10))

        ttk.Label(frame, text="模型", style="Muted.TLabel").pack(anchor=tk.W)
        model_entry = tk.Entry(frame, bg=COLORS["surface_2"], fg=COLORS["text"], insertbackground=COLORS["text"], relief=tk.FLAT, font=("Segoe UI", 10))
        model_entry.insert(0, os.getenv("OPENAI_MODEL", "gpt-5.4-mini"))
        model_entry.pack(fill=tk.X, ipady=8, pady=(4, 10))

        ttk.Label(frame, text="Base URL（可选，企业网关）", style="Muted.TLabel").pack(anchor=tk.W)
        base_entry = tk.Entry(frame, bg=COLORS["surface_2"], fg=COLORS["text"], insertbackground=COLORS["text"], relief=tk.FLAT, font=("Segoe UI", 10))
        base_entry.insert(0, os.getenv("OPENAI_BASE_URL", ""))
        base_entry.pack(fill=tk.X, ipady=8, pady=(4, 14))

        def save() -> None:
            key = key_entry.get().strip()
            model = model_entry.get().strip()
            base_url = base_entry.get().strip()
            if key:
                os.environ["OPENAI_API_KEY"] = key
            if model:
                os.environ["OPENAI_MODEL"] = model
            if base_url:
                os.environ["OPENAI_BASE_URL"] = base_url
            else:
                os.environ.pop("OPENAI_BASE_URL", None)
            dialog.destroy()
            self._new_session(announce=False)
            if self.runtime is not None:
                self._append_message("system", "模型连接已更新。API Key 未写入磁盘。")

        ttk.Button(frame, text="保存并连接", style="Accent.TButton", command=save).pack(side=tk.RIGHT)
        ttk.Button(frame, text="取消", command=dialog.destroy).pack(side=tk.RIGHT, padx=8)

    def _on_close(self) -> None:
        if self.busy and not messagebox.askyesno("退出", "当前任务仍在执行，确定退出吗？", parent=self.window):
            return
        self.window.destroy()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BNCT TPS Agent desktop GUI")
    parser.add_argument("--root", default=".", help="初始工程目录")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    project_root = Path(args.root).expanduser().resolve()
    if not project_root.is_dir():
        raise SystemExit(f"工程目录不存在: {project_root}")
    window = tk.Tk()
    BNCTAgentApp(window, project_root)
    window.mainloop()


if __name__ == "__main__":
    main()
