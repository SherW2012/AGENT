from __future__ import annotations

import time
from pathlib import Path
from typing import Any


PROJECT_MEMORY_FILE = "CLAUDE.md"
LOCAL_MEMORY_FILE = ".bnct_agent/memory.md"
MAX_MEMORY_CHARS = 24_000
MAX_NOTE_CHARS = 4_000


DEFAULT_PROJECT_MEMORY = """# BNCT TPS Agent Memory

This file plays the same role as a project-level CLAUDE.md: it tells the local
agent how to work inside this repository.

## Working Style

- Prefer small, reviewable changes.
- Use existing project patterns before adding new abstractions.
- Run focused tests after code changes.
- Do not make clinical judgments or treatment decisions.
- Treat de-identified BNCT plan snapshots as engineering data only.

## Domain Guardrails

- Never request, store, or expose direct patient identifiers.
- Clinical approval, prescription changes, patient data write-back, and beam
  delivery remain outside this agent.
"""


DEFAULT_LOCAL_MEMORY = """# Local Agent Memory

This file is private to this machine and is ignored by Git through `.bnct_agent/`.
Use it for stable preferences, workflow notes, and project habits that should be
available in future sessions.

## Notes

- No local notes yet.
"""


def _read_bounded(path: Path, limit: int = MAX_MEMORY_CHARS) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n...[truncated {len(text) - limit} chars]"


def ensure_memory_files(root: Path) -> dict[str, str]:
    root = root.resolve()
    project_path = root / PROJECT_MEMORY_FILE
    local_path = root / LOCAL_MEMORY_FILE
    if not project_path.exists():
        project_path.write_text(DEFAULT_PROJECT_MEMORY, encoding="utf-8")
    local_path.parent.mkdir(parents=True, exist_ok=True)
    if not local_path.exists():
        local_path.write_text(DEFAULT_LOCAL_MEMORY, encoding="utf-8")
    return {
        "project": project_path.relative_to(root).as_posix(),
        "local": local_path.relative_to(root).as_posix(),
    }


def read_memory_context(root: Path) -> str:
    paths = ensure_memory_files(root)
    sections: list[str] = []
    for label, relative in (("Project CLAUDE.md", paths["project"]), ("Local private memory", paths["local"])):
        path = root / relative
        content = _read_bounded(path).strip()
        if content:
            sections.append(f"## {label}\nPath: {relative}\n\n{content}")
    return "\n\n---\n\n".join(sections)


def memory_summary(root: Path) -> dict[str, Any]:
    paths = ensure_memory_files(root)
    return {
        "projectFile": paths["project"],
        "localFile": paths["local"],
        "projectChars": len(_read_bounded(root / paths["project"])),
        "localChars": len(_read_bounded(root / paths["local"])),
    }


def read_agent_memory(root: Path) -> dict[str, Any]:
    paths = ensure_memory_files(root)
    return {
        "files": paths,
        "content": read_memory_context(root),
    }


def append_agent_memory(root: Path, note: str, category: str = "Preference") -> dict[str, Any]:
    note = note.strip()
    category = (category or "Preference").strip()[:80]
    if not note:
        raise ValueError("记忆内容不能为空")
    if len(note) > MAX_NOTE_CHARS:
        raise ValueError(f"记忆内容不能超过 {MAX_NOTE_CHARS} 个字符")
    paths = ensure_memory_files(root)
    target = root / paths["local"]
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    block = f"\n\n## {category}\n\n- {timestamp}: {note}\n"
    with target.open("a", encoding="utf-8") as handle:
        handle.write(block)
    return {
        "path": paths["local"],
        "category": category,
        "chars": len(note),
    }
