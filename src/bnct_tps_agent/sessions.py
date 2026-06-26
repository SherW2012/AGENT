from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any


MAX_TITLE_CHARS = 34


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def display_time(value: str) -> str:
    try:
        return value.replace("T", " ")
    except Exception:
        return value


class SessionStore:
    def __init__(self, data_dir: Path):
        # data_dir is a stable per-user location (see config.user_data_dir), not
        # the project root, so conversations persist across working-directory
        # switches instead of being scoped to whatever folder is open.
        self.base = data_dir.resolve()
        self.sessions_dir = self.base / "sessions"
        self.current_path = self.base / "current-session"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        if not session_id or any(ch not in "0123456789abcdef" for ch in session_id):
            raise ValueError("会话 ID 无效")
        return self.sessions_dir / f"{session_id}.json"

    def _write(self, session: dict[str, Any]) -> None:
        path = self._path(str(session["id"]))
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)

    def _read(self, path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or not payload.get("id"):
            return None
        payload.setdefault("title", "未命名会话")
        payload.setdefault("createdAt", now_iso())
        payload.setdefault("updatedAt", payload["createdAt"])
        payload.setdefault("favorite", False)
        payload.setdefault("messages", [])
        return payload

    def all_sessions(self) -> list[dict[str, Any]]:
        sessions = [item for path in self.sessions_dir.glob("*.json") if (item := self._read(path))]
        sessions.sort(key=lambda item: (not bool(item.get("favorite")), item.get("updatedAt", "")), reverse=False)
        favorite = sorted([item for item in sessions if item.get("favorite")], key=lambda item: item.get("updatedAt", ""), reverse=True)
        normal = sorted([item for item in sessions if not item.get("favorite")], key=lambda item: item.get("updatedAt", ""), reverse=True)
        return favorite + normal

    def list(self, query: str = "") -> list[dict[str, Any]]:
        needle = query.strip().casefold()
        result = []
        for session in self.all_sessions():
            messages = session.get("messages", [])
            haystack = " ".join(
                [str(session.get("title", ""))]
                + [str(message.get("content", "")) for message in messages[-8:]]
            ).casefold()
            if needle and needle not in haystack:
                continue
            result.append(
                {
                    "id": session["id"],
                    "title": session.get("title") or "未命名会话",
                    "favorite": bool(session.get("favorite")),
                    "createdAt": session.get("createdAt"),
                    "updatedAt": session.get("updatedAt"),
                    "displayTime": display_time(str(session.get("updatedAt", ""))),
                    "messageCount": len(messages),
                    "preview": self._preview(messages),
                }
            )
        return result

    def _preview(self, messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            content = str(message.get("content") or "").strip()
            if content:
                return content.replace("\n", " ")[:80]
        return "空会话"

    def current_id(self) -> str:
        try:
            current = self.current_path.read_text(encoding="utf-8").strip()
            if current and self._path(current).is_file():
                return current
        except OSError:
            pass
        session = self.create("新会话")
        return str(session["id"])

    def set_current(self, session_id: str) -> dict[str, Any]:
        session = self.get(session_id)
        self.current_path.parent.mkdir(parents=True, exist_ok=True)
        self.current_path.write_text(session_id, encoding="utf-8")
        return session

    def get(self, session_id: str | None = None) -> dict[str, Any]:
        session_id = session_id or self.current_id()
        session = self._read(self._path(session_id))
        if session is None:
            raise FileNotFoundError("会话不存在")
        return session

    def create(self, title: str = "新会话") -> dict[str, Any]:
        timestamp = now_iso()
        session = {
            "id": uuid.uuid4().hex,
            "title": title,
            "createdAt": timestamp,
            "updatedAt": timestamp,
            "favorite": False,
            "messages": [],
        }
        self._write(session)
        self.set_current(str(session["id"]))
        return session

    def delete(self, session_id: str) -> str:
        path = self._path(session_id)
        if path.exists():
            path.unlink()
        remaining = self.all_sessions()
        if not remaining:
            return str(self.create("新会话")["id"])
        current = remaining[0]["id"]
        self.set_current(str(current))
        return str(current)

    def set_favorite(self, session_id: str, favorite: bool) -> dict[str, Any]:
        session = self.get(session_id)
        session["favorite"] = bool(favorite)
        session["updatedAt"] = now_iso()
        self._write(session)
        return session

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        session = self.get(session_id)
        message = {
            "id": uuid.uuid4().hex,
            "role": role,
            "content": content,
            "createdAt": now_iso(),
            "attachments": attachments or [],
        }
        session["messages"].append(message)
        session["updatedAt"] = message["createdAt"]
        if role == "user" and (not session.get("title") or session.get("title") == "新会话"):
            compact = " ".join(content.strip().split())
            session["title"] = compact[:MAX_TITLE_CHARS] or "新会话"
        self._write(session)
        return message

    def recent_context(self, session_id: str, limit: int = 8) -> str:
        session = self.get(session_id)
        messages = session.get("messages", [])[-limit:]
        lines = []
        for message in messages:
            role = {"user": "用户", "assistant": "Agent", "system": "系统"}.get(str(message.get("role")), str(message.get("role")))
            content = str(message.get("content") or "").strip()
            if content:
                lines.append(f"{role}: {content[:1600]}")
        return "\n\n".join(lines)
