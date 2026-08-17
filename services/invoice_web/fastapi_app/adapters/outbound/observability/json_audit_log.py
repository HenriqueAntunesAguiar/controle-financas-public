"""Log JSON local com lista fechada de campos para evitar vazamento de dados."""

from __future__ import annotations

import json
import os
import threading
from collections import deque
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SAFE_FIELDS = {
    "component",
    "duration_ms",
    "http_status",
    "invoice_id",
    "method",
    "outcome",
    "request_id",
    "route",
    "transaction_count",
    "version",
}
SAFE_LEVELS = {"debug", "info", "warning", "error"}
REQUEST_ID_CONTEXT: ContextVar[str | None] = ContextVar("request_id", default=None)


class JsonAuditLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def bind_request(self, request_id: str) -> Token:
        return REQUEST_ID_CONTEXT.set(request_id)

    def reset_request(self, token: Token) -> None:
        REQUEST_ID_CONTEXT.reset(token)

    def emit(self, event: str, level: str = "info", **fields: Any) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level if level in SAFE_LEVELS else "info",
            "event": event[:80],
        }
        fields.setdefault("request_id", REQUEST_ID_CONTEXT.get())
        for name, value in fields.items():
            if name in SAFE_FIELDS and value is not None:
                record[name] = round(value, 2) if isinstance(value, float) else value
        serialized = json.dumps(record, ensure_ascii=True, separators=(",", ":"))
        with self._lock:
            with self.path.open("a", encoding="utf-8", newline="\n") as output:
                output.write(serialized + "\n")
                output.flush()
                os.fsync(output.fileno())

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self._lock:
            with self.path.open("r", encoding="utf-8") as source:
                lines = deque(source, maxlen=max(1, min(limit, 200)))
        records = []
        for line in lines:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return list(reversed(records))
