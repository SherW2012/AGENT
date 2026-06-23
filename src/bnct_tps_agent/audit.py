from __future__ import annotations

import hashlib
import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "patient_id",
    "patient_name",
    "birth_date",
    "date_of_birth",
    "accession_number",
    "medical_record_number",
    "mrn",
}
SECRET_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b")


def redact(value: Any, key: str | None = None) -> Any:
    if key and key.lower() in SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return SECRET_PATTERN.sub("[REDACTED_API_KEY]", value)
    return value


class AuditLogger:
    def __init__(self, audit_dir: Path):
        audit_dir.mkdir(parents=True, exist_ok=True)
        date = datetime.now(UTC).strftime("%Y-%m-%d")
        self.path = audit_dir / f"events-{date}.jsonl"
        self._lock = threading.Lock()

    def record(self, event: str, **payload: Any) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": event,
            **redact(payload),
        }
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    def tool_result(self, tool: str, result: dict[str, Any]) -> None:
        serialized = json.dumps(redact(result), ensure_ascii=False, sort_keys=True)
        payload = result.get("result")
        self.record(
            "tool_result",
            tool=tool,
            sha256=hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
            ok=bool(result.get("ok")),
            error_type=result.get("error_type"),
            result_keys=sorted(payload.keys()) if isinstance(payload, dict) else [],
        )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
