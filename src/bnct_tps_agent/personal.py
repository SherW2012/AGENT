"""Personal calendar entries and quick links, stored in the user data dir.

These are passive records: nothing fires, polls, or consumes tokens by itself
(unlike the removed scheduled-tasks feature). The panel renders them; the
conversation can add/remove them on explicit user request, which is why the
tools are read-risk -- the user's request IS the consent, like memory writes.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


CALENDAR_FILE = "calendar.json"
LINKS_FILE = "quick-links.json"
MAX_CALENDAR_ENTRIES = 200
MAX_QUICK_LINKS = 30
MAX_TEXT_CHARS = 200
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}$")
_LOCK = threading.Lock()


def _load(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def _save(path: Path, items: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _validate_date(value: str) -> str:
    value = str(value or "").strip()
    if not DATE_RE.match(value):
        raise ValueError('date 必须是 "YYYY-MM-DD" 格式，例如 "2026-07-08"')
    try:
        time.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"日期无效: {value}") from exc
    return value


def add_calendar_entry(data_dir: Path, date: str, text: str, time_of_day: str = "") -> dict[str, Any]:
    clean_date = _validate_date(date)
    clean_text = str(text or "").strip()
    if not clean_text:
        raise ValueError("日程内容不能为空")
    if len(clean_text) > MAX_TEXT_CHARS:
        raise ValueError(f"日程内容最多 {MAX_TEXT_CHARS} 字符")
    clean_time = str(time_of_day or "").strip()
    if clean_time and not TIME_RE.match(clean_time):
        raise ValueError('time 必须是 "HH:MM" 格式或留空')
    with _LOCK:
        items = _load(data_dir / CALENDAR_FILE)
        if len(items) >= MAX_CALENDAR_ENTRIES:
            raise ValueError(f"日程数量已达上限（{MAX_CALENDAR_ENTRIES} 条），请先清理")
        entry = {
            "id": uuid.uuid4().hex[:12],
            "date": clean_date,
            "time": clean_time,
            "text": clean_text,
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        items.append(entry)
        items.sort(key=lambda item: (str(item.get("date")), str(item.get("time"))))
        _save(data_dir / CALENDAR_FILE, items)
    return {**entry, "message": "日程已记录。"}


def list_calendar_entries(data_dir: Path) -> dict[str, Any]:
    items = _load(data_dir / CALENDAR_FILE)
    return {"entries": items, "count": len(items)}


def delete_calendar_entry(data_dir: Path, entry_id: str = "", match: str = "") -> dict[str, Any]:
    clean_id = str(entry_id or "").strip()
    clean_match = str(match or "").strip()
    if not clean_id and len(clean_match) < 2:
        raise ValueError("请提供日程 id，或至少 2 个字符的内容片段用于匹配")
    with _LOCK:
        items = _load(data_dir / CALENDAR_FILE)
        if clean_id:
            remaining = [item for item in items if item.get("id") != clean_id]
        else:
            remaining = [item for item in items if clean_match not in str(item.get("text") or "")]
        removed = len(items) - len(remaining)
        if not removed:
            raise ValueError("没有找到匹配的日程")
        _save(data_dir / CALENDAR_FILE, remaining)
    return {"removed": removed, "message": f"已删除 {removed} 条日程。"}


def _validate_link_url(url: str) -> str:
    clean = str(url or "").strip()
    parsed = urlparse(clean)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("链接必须是完整的 http(s) 地址")
    return clean


def add_quick_link(data_dir: Path, name: str, url: str) -> dict[str, Any]:
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("链接名称不能为空")
    if len(clean_name) > 40:
        raise ValueError("链接名称最多 40 字符")
    clean_url = _validate_link_url(url)
    with _LOCK:
        items = _load(data_dir / LINKS_FILE)
        # Same name replaces (rename-in-place is the intuitive behavior).
        items = [item for item in items if str(item.get("name")) != clean_name]
        if len(items) >= MAX_QUICK_LINKS:
            raise ValueError(f"常用链接已达上限（{MAX_QUICK_LINKS} 个），请先删除不用的")
        entry = {"name": clean_name, "url": clean_url, "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
        items.append(entry)
        _save(data_dir / LINKS_FILE, items)
    return {**entry, "message": "常用链接已保存。"}


def list_quick_links(data_dir: Path) -> dict[str, Any]:
    items = _load(data_dir / LINKS_FILE)
    return {"links": items, "count": len(items)}


def delete_quick_link(data_dir: Path, name: str) -> dict[str, Any]:
    clean_name = str(name or "").strip()
    with _LOCK:
        items = _load(data_dir / LINKS_FILE)
        remaining = [item for item in items if str(item.get("name")) != clean_name]
        if len(remaining) == len(items):
            raise ValueError(f"常用链接不存在: {clean_name}")
        _save(data_dir / LINKS_FILE, remaining)
    return {"name": clean_name, "message": "常用链接已删除。"}


def resolve_quick_link(data_dir: Path, name: str) -> dict[str, Any]:
    """Find a link by (fuzzy) name for "打开 xxx"; exact match wins."""
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("请提供要打开的链接名称")
    items = _load(data_dir / LINKS_FILE)
    exact = [item for item in items if str(item.get("name")) == clean_name]
    fuzzy = [item for item in items if clean_name in str(item.get("name") or "")]
    match = (exact or fuzzy or [None])[0]
    if match is None:
        known = ", ".join(str(item.get("name")) for item in items) or "（空）"
        raise ValueError(f"没有叫「{clean_name}」的常用链接。已保存的链接: {known}")
    return {"name": match["name"], "url": match["url"], "message": f"已在浏览器中打开 {match['name']}。"}
