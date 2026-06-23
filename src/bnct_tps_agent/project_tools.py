from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any


IGNORED_PARTS = {".git", ".venv", "node_modules", "__pycache__", ".bnct_agent"}
TEXT_SUFFIXES = {
    ".c",
    ".cc",
    ".cpp",
    ".cs",
    ".h",
    ".hpp",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
MAX_READ_BYTES = 1_000_000
MAX_WRITE_BYTES = 1_000_000


def resolve_inside(root: Path, relative_path: str) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ValueError("只允许相对于工程根目录的路径")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("路径越过工程根目录") from exc
    return resolved


def _is_ignored(path: Path, root: Path) -> bool:
    return bool(IGNORED_PARTS.intersection(path.relative_to(root).parts))


def list_project_files(root: Path, pattern: str = "*", limit: int = 200) -> dict[str, Any]:
    if not 1 <= limit <= 1000:
        raise ValueError("limit 必须在 1 到 1000 之间")
    files: list[str] = []
    for path in root.rglob(pattern):
        if path.is_file() and not _is_ignored(path, root):
            files.append(path.relative_to(root).as_posix())
            if len(files) >= limit:
                break
    return {"files": files, "count": len(files), "limited": len(files) == limit}


def read_project_text(root: Path, path: str, start_line: int = 1, end_line: int = 400) -> dict[str, Any]:
    target = resolve_inside(root, path)
    if not target.is_file():
        raise FileNotFoundError(path)
    if target.stat().st_size > MAX_READ_BYTES:
        raise ValueError("文件超过 1 MB 读取上限")
    if not 1 <= start_line <= end_line or end_line - start_line > 1000:
        raise ValueError("行号范围无效或超过 1000 行")
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    selected = lines[start_line - 1 : end_line]
    return {
        "path": target.relative_to(root).as_posix(),
        "start_line": start_line,
        "end_line": start_line + max(len(selected) - 1, 0),
        "total_lines": len(lines),
        "content": "\n".join(selected),
    }


def search_project_text(root: Path, query: str, glob: str = "*") -> dict[str, Any]:
    if not query or len(query) > 200:
        raise ValueError("query 必须为 1 到 200 个字符")
    needle = query.casefold()
    matches: list[dict[str, Any]] = []
    for path in root.rglob(glob):
        if not path.is_file() or _is_ignored(path, root) or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if path.stat().st_size > MAX_READ_BYTES:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if needle in line.casefold():
                matches.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "line": number,
                        "text": line[:300],
                    }
                )
                if len(matches) >= 100:
                    return {"matches": matches, "limited": True}
    return {"matches": matches, "limited": False}


def write_project_text(root: Path, path: str, content: str) -> dict[str, Any]:
    target = resolve_inside(root, path)
    if target.suffix.lower() not in TEXT_SUFFIXES:
        raise ValueError("MVP 仅允许写入常见文本源文件")
    encoded = content.encode("utf-8")
    if len(encoded) > MAX_WRITE_BYTES:
        raise ValueError("写入内容超过 1 MB 上限")
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists()
    target.write_bytes(encoded)
    return {
        "path": target.relative_to(root).as_posix(),
        "bytes": len(encoded),
        "operation": "updated" if existed else "created",
    }


def run_unit_tests(root: Path) -> dict[str, Any]:
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    completed = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    output = (completed.stdout + "\n" + completed.stderr).strip()
    output = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[REDACTED_API_KEY]", output)
    return {
        "exit_code": completed.returncode,
        "passed": completed.returncode == 0,
        "output": output[-20_000:],
        "truncated": len(output) > 20_000,
    }

