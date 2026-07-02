"""Run user-configured build scripts and analyze their logs.

Design constraints:
- No hardcoded paths. The build script location differs per machine, so each
  profile (debug/release/...) is configured once by the human and stored in the
  per-user data dir (~/.bnct_agent/build-profiles.json). The model can only
  trigger a script the human already registered -- it cannot invent commands,
  which preserves the "no arbitrary shell" guarantee.
- Configuration is WRITE risk and every run is EXECUTE risk, so both go through
  human approval.
- Build output on Chinese Windows is usually GBK; decode utf-8 first and fall
  back to gbk so logs don't turn into mojibake.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any


PROFILE_FILE = "build-profiles.json"
ALLOWED_SCRIPT_SUFFIXES = {".bat", ".cmd", ".sh", ".ps1"}
PROFILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
DEFAULT_TIMEOUT_SECONDS = 1800
MAX_LOG_BYTES = 8_000_000
MAX_TAIL_CHARS = 6_000
MAX_ERRORS = 40
MAX_LOG_FILE_CHARS = 2_000_000

# MSVC / MSBuild / CMake / GCC-style diagnostics.
_ERROR_PATTERNS = [
    # D:\path\Dose.cpp(245): error C2065: 'x': undeclared identifier
    re.compile(r"^(?P<file>[^\s(][^(\n]*)\((?P<line>\d+)(?:,\d+)?\)\s*:\s*(?:fatal\s+)?error\s+(?P<code>[A-Z]+\d+)\s*:\s*(?P<message>.+)$", re.IGNORECASE),
    # main.obj : error LNK2019: unresolved external symbol ...
    re.compile(r"^(?P<file>\S[^:\n]*?)\s*:\s*(?:fatal\s+)?error\s+(?P<code>LNK\d+|MSB\d+)\s*:\s*(?P<message>.+)$", re.IGNORECASE),
    # src/dose.cpp:245:10: error: 'x' was not declared
    re.compile(r"^(?P<file>[^\s:][^:\n]*):(?P<line>\d+)(?::\d+)?:\s*(?:fatal\s+)?error:\s*(?P<message>.+)$", re.IGNORECASE),
    # CMake Error at CMakeLists.txt:12 (message): ...
    re.compile(r"^CMake Error(?: at (?P<file>[^:\n]+):(?P<line>\d+))?(?: \([^)]*\))?:\s*(?P<message>.*)$"),
]
_WARNING_RE = re.compile(r"\bwarning\b\s*[A-Z]*\d*\s*:", re.IGNORECASE)


def decode_build_output(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return raw.decode("gbk")
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="replace")


def extract_build_errors(text: str) -> list[dict[str, Any]]:
    """Deterministically pull error diagnostics out of a build log."""
    errors: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for line in text.splitlines():
        if len(errors) >= MAX_ERRORS:
            break
        line = line.strip()
        if not line:
            continue
        for pattern in _ERROR_PATTERNS:
            match = pattern.match(line)
            if not match:
                continue
            groups = match.groupdict()
            item = {
                "file": (groups.get("file") or "").strip(),
                "line": int(groups["line"]) if groups.get("line") else None,
                "code": (groups.get("code") or "").upper(),
                "message": (groups.get("message") or "").strip()[:400],
            }
            key = (item["file"], str(item["line"]), item["code"] + item["message"][:80])
            if key not in seen:
                seen.add(key)
                errors.append(item)
            break
    return errors


def _profiles_path(data_dir: Path) -> Path:
    return data_dir / PROFILE_FILE


def load_build_profiles(data_dir: Path) -> dict[str, Any]:
    try:
        payload = json.loads(_profiles_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_build_profiles(data_dir: Path, profiles: dict[str, Any]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    _profiles_path(data_dir).write_text(
        json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_build_profiles(_root: Path, data_dir: Path) -> dict[str, Any]:
    profiles = load_build_profiles(data_dir)
    public = {}
    for name, item in profiles.items():
        if isinstance(item, dict):
            public[name] = {
                "script": item.get("script"),
                "cwd": item.get("cwd"),
                "configuredAt": item.get("configuredAt"),
                "scriptExists": bool(item.get("script")) and Path(str(item.get("script"))).is_file(),
            }
    return {
        "profiles": public,
        "message": (
            "没有已配置的编译档案。请让用户提供编译脚本的完整路径，然后调用 configure_build_profile。"
            if not public else "调用 run_build 前请确认档案的 scriptExists 为 true。"
        ),
    }


def configure_build_profile(_root: Path, data_dir: Path, profile: str, script_path: str) -> dict[str, Any]:
    name = str(profile or "").strip().lower()
    if not PROFILE_NAME_RE.match(name):
        raise ValueError("profile 只能使用小写字母、数字、下划线或短横线（例如 debug、release）")
    script = Path(str(script_path or "").strip().strip('"')).expanduser()
    if not script.is_absolute():
        raise ValueError("请提供编译脚本的完整绝对路径（每台机器路径不同，不能猜测）")
    if not script.is_file():
        raise FileNotFoundError(f"编译脚本不存在: {script}")
    if script.suffix.lower() not in ALLOWED_SCRIPT_SUFFIXES:
        raise ValueError(f"只支持这些脚本类型: {', '.join(sorted(ALLOWED_SCRIPT_SUFFIXES))}")
    profiles = load_build_profiles(data_dir)
    profiles[name] = {
        "script": str(script.resolve()),
        "cwd": str(script.resolve().parent),
        "configuredAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    _save_build_profiles(data_dir, profiles)
    return {
        "profile": name,
        "script": profiles[name]["script"],
        "cwd": profiles[name]["cwd"],
        "message": f"编译档案 {name} 已保存（存储于用户数据目录，与工作区无关）。",
    }


def _build_command(script: Path) -> list[str]:
    suffix = script.suffix.lower()
    if suffix in {".bat", ".cmd"}:
        return ["cmd.exe", "/d", "/c", str(script)]
    if suffix == ".ps1":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
    return ["bash", str(script)] if os.name != "nt" else ["cmd.exe", "/d", "/c", str(script)]


def run_build(_root: Path, data_dir: Path, profile: str) -> dict[str, Any]:
    name = str(profile or "").strip().lower()
    profiles = load_build_profiles(data_dir)
    entry = profiles.get(name)
    if not isinstance(entry, dict) or not entry.get("script"):
        raise ValueError(
            f"编译档案 {name} 尚未配置。请让用户提供编译脚本路径，先调用 configure_build_profile。"
        )
    script = Path(str(entry["script"]))
    if not script.is_file():
        raise FileNotFoundError(f"已配置的编译脚本不存在: {script}（可能已移动，请重新配置）")

    timeout = int(os.getenv("BNCT_AGENT_BUILD_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS)))
    started = time.monotonic()
    try:
        completed = subprocess.run(
            _build_command(script),
            cwd=entry.get("cwd") or str(script.parent),
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(f"编译超过 {timeout} 秒仍未结束，已终止。可用 BNCT_AGENT_BUILD_TIMEOUT 调整。") from exc
    duration = round(time.monotonic() - started, 1)

    raw = (completed.stdout or b"") + b"\n" + (completed.stderr or b"")
    raw = raw[-MAX_LOG_BYTES:]
    text = decode_build_output(raw)

    logs_dir = data_dir / "build-logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}.log"
    log_path.write_text(text, encoding="utf-8")

    errors = extract_build_errors(text)
    warnings = len(_WARNING_RE.findall(text))
    tail = text[-MAX_TAIL_CHARS:]
    return {
        "profile": name,
        "script": str(script),
        "exitCode": completed.returncode,
        "success": completed.returncode == 0,
        "durationSeconds": duration,
        "warningCount": warnings,
        "errors": errors,
        "logPath": str(log_path),
        "logTail": tail,
        "message": (
            "编译成功。" if completed.returncode == 0
            else f"编译失败（退出码 {completed.returncode}）。errors 字段是确定性提取的诊断，请据此定位并解释根因。"
        ),
    }


def analyze_build_log(root: Path, path: str) -> dict[str, Any]:
    """Extract diagnostics from an existing build log (workspace file or absolute path)."""
    raw_path = str(path or "").strip().strip('"')
    if not raw_path:
        raise ValueError("path 不能为空")
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = (root / raw_path).resolve()
    if not candidate.is_file():
        raise FileNotFoundError(f"日志文件不存在: {candidate}")
    data = candidate.read_bytes()[: MAX_LOG_FILE_CHARS * 2]
    text = decode_build_output(data)[:MAX_LOG_FILE_CHARS]
    errors = extract_build_errors(text)
    warnings = len(_WARNING_RE.findall(text))
    return {
        "path": str(candidate),
        "chars": len(text),
        "warningCount": warnings,
        "errorCount": len(errors),
        "errors": errors,
        "message": "errors 为确定性提取结果；请聚类相同代码的错误、按根因排序，并给出最可能的源码位置。",
    }
