from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent import AgentRuntime
from .audit import AuditLogger
from .config import Settings
from .safety import Risk, SafetyPolicy
from .tool_registry import ToolRegistry


def _approval(tool_name: str, risk: Risk, arguments: dict) -> bool:
    print("\n[需要人工批准]", file=sys.stderr)
    print(f"工具: {tool_name}", file=sys.stderr)
    print(f"风险: {risk.value}", file=sys.stderr)
    preview = json.dumps(arguments, ensure_ascii=False, indent=2)
    print(preview[:2000], file=sys.stderr)
    answer = input("输入 approve 执行，其它输入均拒绝: ").strip().lower()
    return answer == "approve"


def _runtime(args: argparse.Namespace) -> tuple[Settings, ToolRegistry, AuditLogger]:
    interactive = not getattr(args, "non_interactive", False)
    settings = Settings.load(
        args.root,
        provider=getattr(args, "provider", None),
        model=getattr(args, "model", None),
        interactive=interactive,
    )
    audit = AuditLogger(settings.audit_dir)
    policy = SafetyPolicy(_approval if interactive else None)
    registry = ToolRegistry(settings.root, policy, audit)
    return settings, registry, audit


def _run_ask(args: argparse.Namespace) -> int:
    settings, registry, audit = _runtime(args)
    runtime = AgentRuntime(settings, registry, audit)
    print(runtime.run(args.task))
    return 0


def _run_chat(args: argparse.Namespace) -> int:
    settings, registry, audit = _runtime(args)
    runtime = AgentRuntime(settings, registry, audit)
    print("BNCT TPS Agent。输入 exit/quit 退出。")
    while True:
        try:
            task = input("\nbnct> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if task.lower() in {"exit", "quit"}:
            return 0
        if not task:
            continue
        try:
            print(runtime.run(task))
        except Exception as exc:
            print(f"错误: {exc}", file=sys.stderr)


def _run_demo(args: argparse.Namespace) -> int:
    _, registry, audit = _runtime(args)
    print("1) 列出工程文件")
    print(json.dumps(registry.execute("list_project_files", {"pattern": "*", "limit": 10}), ensure_ascii=False, indent=2))
    sample = "sample_data/deidentified_case.json"
    sample_path = Path(args.root).resolve() / sample
    if sample_path.exists():
        print("\n2) 校验脱敏计划快照")
        print(json.dumps(registry.execute("validate_plan_snapshot", {"path": sample}), ensure_ascii=False, indent=2))
        print("\n3) 汇总源快照指标")
        print(json.dumps(registry.execute("summarize_plan_snapshot", {"path": sample}), ensure_ascii=False, indent=2))
    print(f"\n审计日志: {audit.path}")
    print("离线演示完成；没有做临床判断，也没有写回 TPS。")
    return 0


def _run_tools(args: argparse.Namespace) -> int:
    _, registry, _ = _runtime(args)
    print(json.dumps(registry.descriptions, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="BNCT TPS 安全优先工程 Agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def common(subparser: argparse.ArgumentParser, *, model: bool = False) -> None:
        subparser.add_argument("--root", default=".", help="Agent 可访问的工程根目录")
        subparser.add_argument("--non-interactive", action="store_true", help="拒绝所有需要人工批准的动作")
        if model:
            subparser.add_argument("--provider", choices=("openai", "deepseek", "kimi"), help="模型供应商")
            subparser.add_argument("--model", help="覆盖供应商的默认模型")

    ask = subparsers.add_parser("ask", help="执行一次任务")
    common(ask, model=True)
    ask.add_argument("task")
    ask.set_defaults(func=_run_ask)

    chat = subparsers.add_parser("chat", help="启动交互会话")
    common(chat, model=True)
    chat.set_defaults(func=_run_chat)

    demo = subparsers.add_parser("demo", help="离线演示工具和安全策略")
    common(demo)
    demo.set_defaults(func=_run_demo)

    tools = subparsers.add_parser("tools", help="列出工具及风险等级")
    common(tools)
    tools.set_defaults(func=_run_tools)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        raise SystemExit(args.func(args))
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
