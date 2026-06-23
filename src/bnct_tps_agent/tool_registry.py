from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .audit import AuditLogger, sha256_text
from .memory import append_agent_memory, read_agent_memory
from .project_tools import (
    list_project_files,
    read_project_text,
    run_unit_tests,
    search_project_text,
    write_project_text,
)
from .safety import PolicyDenied, Risk, SafetyPolicy
from .skills import SkillRegistry
from .tps_tools import summarize_plan_snapshot, validate_plan_snapshot


ToolHandler = Callable[..., dict[str, Any]]
EventCallback = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    risk: Risk
    handler: ToolHandler

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "strict": True,
        }

    def chat_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(
        self,
        root: Path,
        policy: SafetyPolicy,
        audit: AuditLogger,
        event_callback: EventCallback | None = None,
        skill_registry: SkillRegistry | None = None,
    ):
        self.root = root
        self.policy = policy
        self.audit = audit
        self.event_callback = event_callback
        self.skill_registry = skill_registry or SkillRegistry(root)
        self._tools = {tool.name: tool for tool in self._build_tools()}

    def _emit(self, event: dict[str, Any]) -> None:
        if self.event_callback is None:
            return
        try:
            self.event_callback(event)
        except Exception:
            # UI/telemetry callbacks must never change tool execution semantics.
            pass

    def _build_tools(self) -> list[Tool]:
        object_schema = {"type": "object", "additionalProperties": False}
        return [
            Tool(
                "list_project_files",
                "List files below the project root. Generated and dependency directories are excluded.",
                {**object_schema, "properties": {"pattern": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["pattern", "limit"]},
                Risk.READ,
                list_project_files,
            ),
            Tool(
                "read_project_text",
                "Read a bounded line range from a UTF-8 project text file.",
                {**object_schema, "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, "required": ["path", "start_line", "end_line"]},
                Risk.READ,
                read_project_text,
            ),
            Tool(
                "search_project_text",
                "Search text files in the project for a literal case-insensitive string.",
                {**object_schema, "properties": {"query": {"type": "string"}, "glob": {"type": "string"}}, "required": ["query", "glob"]},
                Risk.READ,
                search_project_text,
            ),
            Tool(
                "write_project_text",
                "Create or replace a project text file. Requires explicit human approval.",
                {**object_schema, "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
                Risk.WRITE,
                write_project_text,
            ),
            Tool(
                "run_unit_tests",
                "Run the fixed command: python -m unittest discover -s tests -v. Arbitrary commands are not accepted.",
                {**object_schema, "properties": {}, "required": []},
                Risk.EXECUTE,
                run_unit_tests,
            ),
            Tool(
                "read_agent_memory",
                "Read project CLAUDE.md plus the local private agent memory file.",
                {**object_schema, "properties": {}, "required": []},
                Risk.READ,
                read_agent_memory,
            ),
            Tool(
                "append_agent_memory",
                "Append a stable user preference or workflow note to the local private memory file. Use only when the user explicitly asks you to remember something.",
                {
                    **object_schema,
                    "properties": {
                        "note": {"type": "string"},
                        "category": {"type": "string"},
                    },
                    "required": ["note", "category"],
                },
                Risk.WRITE,
                append_agent_memory,
            ),
            Tool(
                "list_agent_skills",
                "List local skills discovered from skills/, .agent/skills/, and .claude/skills/.",
                {**object_schema, "properties": {}, "required": []},
                Risk.READ,
                lambda _root: {"skills": self.skill_registry.public_catalog()},
            ),
            Tool(
                "read_agent_skill",
                "Read one local skill's SKILL.md and file list before using that skill.",
                {**object_schema, "properties": {"name": {"type": "string"}}, "required": ["name"]},
                Risk.READ,
                lambda _root, name: self.skill_registry.read_skill(name),
            ),
            Tool(
                "validate_plan_snapshot",
                "Validate a de-identified read-only BNCT plan JSON snapshot without making clinical judgments.",
                {**object_schema, "properties": {"path": {"type": "string"}}, "required": ["path"]},
                Risk.READ,
                validate_plan_snapshot,
            ),
            Tool(
                "summarize_plan_snapshot",
                "Return source metadata and metric values from a valid de-identified plan JSON snapshot.",
                {**object_schema, "properties": {"path": {"type": "string"}}, "required": ["path"]},
                Risk.READ,
                summarize_plan_snapshot,
            ),
        ]

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    @property
    def chat_schemas(self) -> list[dict[str, Any]]:
        return [tool.chat_schema() for tool in self._tools.values()]

    @property
    def descriptions(self) -> list[dict[str, str]]:
        return [
            {"name": tool.name, "risk": tool.risk.value, "description": tool.description}
            for tool in self._tools.values()
        ]

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            result = {"ok": False, "error": f"未知工具: {name}"}
            self.audit.tool_result(name, result)
            return result

        serialized_arguments = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        self.audit.record(
            "tool_requested",
            tool=name,
            risk=tool.risk.value,
            argument_keys=sorted(arguments.keys()),
            arguments_sha256=sha256_text(serialized_arguments),
            arguments_chars=len(serialized_arguments),
        )
        self._emit({"type": "tool_started", "tool": name, "risk": tool.risk.value})
        try:
            self.policy.require(name, tool.risk, arguments)
            result = tool.handler(self.root, **arguments)
            wrapped = {"ok": True, "result": result}
        except (PolicyDenied, ValueError, FileNotFoundError, TimeoutError, json.JSONDecodeError) as exc:
            wrapped = {"ok": False, "error": str(exc), "error_type": type(exc).__name__}
        except Exception as exc:  # Keep model-visible errors bounded; full traceback stays out of prompts.
            wrapped = {"ok": False, "error": "工具执行失败", "error_type": type(exc).__name__}
        self.audit.tool_result(name, wrapped)
        self._emit(
            {
                "type": "tool_finished",
                "tool": name,
                "risk": tool.risk.value,
                "ok": bool(wrapped.get("ok")),
                "error_type": wrapped.get("error_type"),
            }
        )
        return wrapped
