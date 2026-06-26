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
from .office_tools import create_excel, create_powerpoint, create_word_document
from .safety import PolicyDenied, Risk, SafetyPolicy
from .skills import SkillRegistry
from .tps_tools import summarize_plan_snapshot, validate_plan_snapshot
from .web_search import fetch_url, looks_sensitive_url, looks_sensitive_web_query, web_search


ToolHandler = Callable[..., dict[str, Any]]
RiskResolver = Callable[[dict[str, Any]], Risk]
EventCallback = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    risk: Risk
    handler: ToolHandler
    risk_resolver: RiskResolver | None = None

    def risk_for(self, arguments: dict[str, Any]) -> Risk:
        if self.risk_resolver is None:
            return self.risk
        return self.risk_resolver(arguments)

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
        web_search_mode: str = "auto",
        web_search_network: str = "auto",
    ):
        self.root = root
        self.policy = policy
        self.audit = audit
        self.event_callback = event_callback
        self.skill_registry = skill_registry or SkillRegistry(root)
        self.web_search_mode = web_search_mode
        self.web_search_network = web_search_network
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
        tools = [
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
                "Create or replace a text file. Relative paths stay inside the project root; absolute paths outside the root require the same explicit human approval.",
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
                lambda _root: {"skills": self.skill_registry.public_catalog(include_background=True)},
            ),
            Tool(
                "read_agent_skill",
                "Read one local skill's SKILL.md and file list before using that skill.",
                {**object_schema, "properties": {"name": {"type": "string"}}, "required": ["name"]},
                Risk.READ,
                lambda _root, name: self.skill_registry.read_skill(name),
            ),
            Tool(
                "install_agent_skill",
                "Install a Claude-style skill from an explicit public GitHub URL into .agent/skills. Use this when the user asks to install/import a skill from a GitHub URL; do not web-search the URL first. Pass ref as an empty string to use the repository default branch.",
                {
                    **object_schema,
                    "properties": {
                        "url": {"type": "string"},
                        "ref": {"type": "string"},
                    },
                    "required": ["url", "ref"],
                },
                Risk.EXTERNAL,
                self._install_agent_skill,
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
            Tool(
                "create_word_document",
                "Create a .docx Word document in the workspace from a title and a list of paragraph strings. "
                "Prefix a paragraph with '# ' or '## ' to make it a heading. Output is standards-based OOXML; "
                "no patient identifiers or secrets may be written.",
                {
                    **object_schema,
                    "properties": {
                        "path": {"type": "string"},
                        "title": {"type": "string"},
                        "paragraphs": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["path", "title", "paragraphs"],
                },
                Risk.WRITE,
                lambda root, path, title, paragraphs: create_word_document(root, path, title, paragraphs),
            ),
            Tool(
                "create_powerpoint",
                "Create a .pptx PowerPoint deck in the workspace. Each slide is an object with a title and a list "
                "of bullet strings. Output is standards-based OOXML; no patient identifiers or secrets may be written.",
                {
                    **object_schema,
                    "properties": {
                        "path": {"type": "string"},
                        "slides": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "title": {"type": "string"},
                                    "bullets": {"type": "array", "items": {"type": "string"}},
                                },
                                "required": ["title", "bullets"],
                            },
                        },
                    },
                    "required": ["path", "slides"],
                },
                Risk.WRITE,
                lambda root, path, slides: create_powerpoint(root, path, slides),
            ),
            Tool(
                "create_excel",
                "Create a .xlsx Excel workbook in the workspace. Each sheet is an object with a name and rows; "
                "each row is a list of cell strings (numeric-looking strings become numbers). Output is "
                "standards-based OOXML; no patient identifiers or secrets may be written.",
                {
                    **object_schema,
                    "properties": {
                        "path": {"type": "string"},
                        "sheets": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "name": {"type": "string"},
                                    "rows": {
                                        "type": "array",
                                        "items": {"type": "array", "items": {"type": "string"}},
                                    },
                                },
                                "required": ["name", "rows"],
                            },
                        },
                    },
                    "required": ["path", "sheets"],
                },
                Risk.WRITE,
                lambda root, path, sheets: create_excel(root, path, sheets),
            ),
        ]
        if self.web_search_mode != "off":
            tools.append(
                Tool(
                    "fetch_url",
                    "Fetch and extract readable text from one explicit public http(s) URL. Use this instead of web_search when the user gives a specific URL to open, read, inspect, or analyze. Local/private hosts and credential-bearing URLs are blocked.",
                    {
                        **object_schema,
                        "properties": {
                            "url": {"type": "string"},
                            "max_chars": {"type": "integer"},
                        },
                        "required": ["url", "max_chars"],
                    },
                    Risk.READ,
                    lambda root, url, max_chars: fetch_url(
                        root,
                        url,
                        max_chars=max_chars,
                        network=self.web_search_network,
                    ),
                    risk_resolver=self._fetch_url_risk,
                )
            )
            tools.append(
                Tool(
                    "web_search",
                    (
                        "Search the public web for external information. Pass the query as a "
                        "complete natural-language phrase exactly as a person would type it; do "
                        "not split it into single words or characters. Set recency=true only when "
                        "the answer depends on current/changing facts (news, releases, prices, "
                        "dates, latest standards) so that fresh news sources are consulted first; "
                        "set recency=false for stable knowledge. Never include patient identifiers, "
                        "secrets, internal paths, or private code in the query."
                    ),
                    {
                        **object_schema,
                        "properties": {
                            "query": {"type": "string"},
                            "max_results": {"type": "integer"},
                            "recency": {"type": "boolean"},
                        },
                        "required": ["query", "max_results", "recency"],
                    },
                    Risk.READ,
                    lambda root, query, max_results, recency: web_search(
                        root,
                        query,
                        max_results=max_results,
                        network=self.web_search_network,
                        recency=recency,
                    ),
                    risk_resolver=self._web_search_risk,
                )
            )
        return tools

    def _install_agent_skill(self, _root: Path, url: str, ref: str) -> dict[str, Any]:
        installed = self.skill_registry.install_github_skill(url, ref=ref)
        self._emit({"type": "skill_imported", "skill": installed["name"]})
        return {
            "name": installed["name"],
            "description": installed["description"],
            "path": installed["path"],
            "trusted": installed["trusted"],
            "metadata": installed["metadata"],
            "files": installed["files"],
            "message": f"Skill {installed['name']} installed. Use read_agent_skill before relying on it.",
        }

    def _web_search_risk(self, arguments: dict[str, Any]) -> Risk:
        query = str(arguments.get("query") or "")
        if self.web_search_mode == "ask" or looks_sensitive_web_query(query):
            return Risk.EXTERNAL
        return Risk.READ

    def _fetch_url_risk(self, arguments: dict[str, Any]) -> Risk:
        url = str(arguments.get("url") or "")
        if self.web_search_mode == "ask" or looks_sensitive_url(url):
            return Risk.EXTERNAL
        return Risk.READ

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

        risk = tool.risk_for(arguments)
        serialized_arguments = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
        self.audit.record(
            "tool_requested",
            tool=name,
            risk=risk.value,
            argument_keys=sorted(arguments.keys()),
            arguments_sha256=sha256_text(serialized_arguments),
            arguments_chars=len(serialized_arguments),
        )
        self._emit({"type": "tool_started", "tool": name, "risk": risk.value})
        try:
            self.policy.require(name, risk, arguments)
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
                "risk": risk.value,
                "ok": bool(wrapped.get("ok")),
                "error_type": wrapped.get("error_type"),
            }
        )
        return wrapped
