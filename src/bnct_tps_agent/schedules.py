"""Scheduled agent tasks, persisted per user and executed by the web server.

Design follows Claude Code's approach: scheduling is harness infrastructure
(tools + a scheduler loop inside the running service), not a skill -- a skill is
a prompt package and has no resident process to fire timers. Schedules live in
the user data dir, so they survive workspace switches. They only fire while the
local service is running; missed occurrences are skipped, not replayed.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any


SCHEDULE_FILE = "schedules.json"
MIN_INTERVAL_MINUTES = 5
MAX_SCHEDULES = 20
MAX_PROMPT_CHARS = 2_000
_LOCK = threading.Lock()


def _path(data_dir: Path) -> Path:
    return data_dir / SCHEDULE_FILE


def _load(data_dir: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return payload if isinstance(payload, list) else []


def _save(data_dir: Path, items: list[dict[str, Any]]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    _path(data_dir).write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _next_run(schedule_type: str, interval_minutes: int, daily_time: str, now: float | None = None) -> float:
    now = time.time() if now is None else now
    if schedule_type == "interval":
        return now + interval_minutes * 60
    hour, minute = (int(part) for part in daily_time.split(":", 1))
    local = time.localtime(now)
    candidate = time.mktime((local.tm_year, local.tm_mon, local.tm_mday, hour, minute, 0, 0, 0, -1))
    if candidate <= now:
        candidate += 24 * 3600
    return candidate


def _display_time(timestamp: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


def _public(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "prompt": item["prompt"],
        "scheduleType": item["scheduleType"],
        "intervalMinutes": item.get("intervalMinutes") or 0,
        "dailyTime": item.get("dailyTime") or "",
        "nextRun": _display_time(item["nextRun"]),
        "lastRun": _display_time(item["lastRun"]) if item.get("lastRun") else "",
        "createdAt": item.get("createdAt") or "",
    }


def create_schedule(
    data_dir: Path,
    prompt: str,
    schedule_type: str,
    interval_minutes: int = 0,
    daily_time: str = "",
) -> dict[str, Any]:
    clean_prompt = str(prompt or "").strip()
    if not clean_prompt:
        raise ValueError("定时任务的内容不能为空")
    if len(clean_prompt) > MAX_PROMPT_CHARS:
        raise ValueError(f"任务内容过长，最多 {MAX_PROMPT_CHARS} 字符")
    schedule_type = str(schedule_type or "").strip().lower()
    if schedule_type == "interval":
        interval_minutes = int(interval_minutes)
        if interval_minutes < MIN_INTERVAL_MINUTES:
            raise ValueError(f"间隔至少 {MIN_INTERVAL_MINUTES} 分钟")
        daily_time = ""
    elif schedule_type == "daily":
        daily_time = str(daily_time or "").strip()
        parts = daily_time.split(":")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ValueError('daily_time 必须是 "HH:MM" 格式，例如 "09:00"')
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError("daily_time 时间超出范围")
        daily_time = f"{hour:02d}:{minute:02d}"
        interval_minutes = 0
    else:
        raise ValueError('schedule_type 只能是 "interval"（每 N 分钟）或 "daily"（每天固定时间）')

    with _LOCK:
        items = _load(data_dir)
        if len(items) >= MAX_SCHEDULES:
            raise ValueError(f"定时任务数量已达上限（{MAX_SCHEDULES} 个），请先删除不用的")
        item = {
            "id": uuid.uuid4().hex[:12],
            "prompt": clean_prompt,
            "scheduleType": schedule_type,
            "intervalMinutes": interval_minutes,
            "dailyTime": daily_time,
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "lastRun": 0,
            "nextRun": _next_run(schedule_type, interval_minutes, daily_time),
        }
        items.append(item)
        _save(data_dir, items)
    return {
        **_public(item),
        "message": "定时任务已创建。注意：只有本地服务运行时才会触发；错过的时间点不会补跑。",
    }


def list_schedules(data_dir: Path) -> dict[str, Any]:
    items = _load(data_dir)
    return {
        "schedules": [_public(item) for item in items],
        "count": len(items),
        "message": "定时任务只在本地服务运行期间触发。" if items else "当前没有定时任务。",
    }


def delete_schedule(data_dir: Path, schedule_id: str) -> dict[str, Any]:
    clean_id = str(schedule_id or "").strip()
    with _LOCK:
        items = _load(data_dir)
        remaining = [item for item in items if item.get("id") != clean_id]
        if len(remaining) == len(items):
            raise ValueError(f"定时任务不存在: {clean_id}")
        _save(data_dir, remaining)
    return {"id": clean_id, "message": "定时任务已删除。"}


def pop_due_schedules(data_dir: Path, now: float | None = None) -> list[dict[str, Any]]:
    """Return schedules that are due and advance their nextRun immediately, so a
    slow or failed run can never double-fire."""
    now = time.time() if now is None else now
    due: list[dict[str, Any]] = []
    with _LOCK:
        items = _load(data_dir)
        changed = False
        for item in items:
            if item.get("nextRun", 0) <= now:
                due.append(dict(item))
                item["lastRun"] = now
                item["nextRun"] = _next_run(
                    str(item.get("scheduleType")),
                    int(item.get("intervalMinutes") or 0),
                    str(item.get("dailyTime") or ""),
                    now,
                )
                changed = True
        if changed:
            _save(data_dir, items)
    return due
