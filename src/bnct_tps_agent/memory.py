from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any


PROJECT_MEMORY_FILE = "CLAUDE.md"
LOCAL_MEMORY_FILE = ".bnct_agent/memory.md"
AUTO_MEMORY_FILE = "auto-memory.md"
MAX_MEMORY_CHARS = 24_000
MAX_NOTE_CHARS = 4_000
MAX_AUTO_MEMORY_LINES = 80
MAX_AUTO_LINE_CHARS = 200

# Implicit memory must never absorb identifiers or secrets, whatever the
# summarizer produces. Deterministic gate, mirroring the web-search guard.
_AUTO_MEMORY_BLOCKLIST = [
    re.compile(r"(?i)\b(sk-[A-Za-z0-9_-]{12,}|api[_ -]?key|secret|token|password|bearer)\b"),
    re.compile(r"(?i)\b(patient|mrn|medical record|accession number)\b"),
    re.compile(r"(患者|身份证|住院号|病历号|病案号|手机号|出生日期|床号)"),
    re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
]


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


def _auto_memory_path(data_dir: Path) -> Path:
    return data_dir / AUTO_MEMORY_FILE


def read_auto_memory(data_dir: Path) -> str:
    return _read_bounded(_auto_memory_path(data_dir), limit=12_000).strip()


def sanitize_auto_memory_lines(lines: list[str]) -> list[str]:
    """Keep only short, plain preference bullets; drop anything sensitive."""
    cleaned: list[str] = []
    for raw in lines:
        line = str(raw).strip().lstrip("-•").strip()
        if not line or line.upper() == "NONE":
            continue
        if len(line) > MAX_AUTO_LINE_CHARS:
            line = line[:MAX_AUTO_LINE_CHARS]
        if any(pattern.search(line) for pattern in _AUTO_MEMORY_BLOCKLIST):
            continue
        cleaned.append(line)
    return cleaned


def merge_auto_memory(data_dir: Path, lines: list[str]) -> int:
    """Append new de-duplicated bullets to the implicit memory file, keeping the
    newest MAX_AUTO_MEMORY_LINES entries. Returns how many were added."""
    candidates = sanitize_auto_memory_lines(lines)
    if not candidates:
        return 0
    path = _auto_memory_path(data_dir)
    existing: list[str] = []
    try:
        existing = [
            line[2:].strip()
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.startswith("- ")
        ]
    except FileNotFoundError:
        pass
    known = {line.casefold() for line in existing}
    added: list[str] = []
    for line in candidates:
        key = line.casefold()
        if key not in known:
            known.add(key)  # also de-dupe within the incoming batch
            added.append(line)
    if not added:
        return 0
    merged = (existing + added)[-MAX_AUTO_MEMORY_LINES:]
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "# Auto Memory (隐式记忆)\n\n自动从日常对话总结，可在设置中关闭或清空。\n\n" + "\n".join(
        f"- {line}" for line in merged
    ) + "\n"
    path.write_text(body, encoding="utf-8")
    return len(added)


def clear_auto_memory(data_dir: Path) -> None:
    try:
        _auto_memory_path(data_dir).unlink()
    except FileNotFoundError:
        pass


def append_agent_memory(root: Path, note: str, category: str = "Preference") -> dict[str, Any]:
    note = note.strip()
    category = (category or "Preference").strip()[:80]
    if not note:
        raise ValueError("记忆内容不能为空")
    if len(note) > MAX_NOTE_CHARS:
        raise ValueError(f"记忆内容不能超过 {MAX_NOTE_CHARS} 个字符")
    paths = ensure_memory_files(root)
    target = root / paths["local"]
    existing = _read_bounded(target)
    if note in existing:
        return {
            "path": paths["local"],
            "category": category,
            "chars": len(note),
            "duplicate": True,
            "message": "相同内容已在记忆中，未重复写入。",
        }
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    block = f"\n\n## {category}\n\n- {timestamp}: {note}\n"
    with target.open("a", encoding="utf-8") as handle:
        handle.write(block)
    return {
        "path": paths["local"],
        "category": category,
        "chars": len(note),
    }


def forget_agent_memory(root: Path, data_dir: Path, match: str) -> dict[str, Any]:
    """Delete memory entries containing `match` from both the explicit local
    memory file and the implicit auto-memory file. Deterministic substring
    matching on bullet lines only — headers and defaults stay intact."""
    needle = str(match or "").strip()
    if len(needle) < 2:
        raise ValueError("请提供至少 2 个字符的匹配内容，避免误删")
    removed = {"explicit": 0, "implicit": 0}
    folded = needle.casefold()

    paths = ensure_memory_files(root)
    local_path = root / paths["local"]
    try:
        lines = local_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        lines = []
    kept = []
    for line in lines:
        if line.lstrip().startswith("- ") and folded in line.casefold():
            removed["explicit"] += 1
            continue
        kept.append(line)
    if removed["explicit"]:
        local_path.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")

    auto_path = _auto_memory_path(data_dir)
    try:
        auto_lines = auto_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except FileNotFoundError:
        auto_lines = []
    kept_auto = []
    for line in auto_lines:
        if line.startswith("- ") and folded in line.casefold():
            removed["implicit"] += 1
            continue
        kept_auto.append(line)
    if removed["implicit"]:
        auto_path.write_text("\n".join(kept_auto).rstrip() + "\n", encoding="utf-8")

    total = removed["explicit"] + removed["implicit"]
    return {
        "match": needle,
        "removedExplicit": removed["explicit"],
        "removedImplicit": removed["implicit"],
        "message": (
            f"已删除 {removed['explicit']} 条显式记忆、{removed['implicit']} 条隐式记忆。"
            if total else "没有找到匹配的记忆条目。"
        ),
    }
