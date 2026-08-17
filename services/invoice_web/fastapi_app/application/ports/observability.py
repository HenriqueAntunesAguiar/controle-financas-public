from __future__ import annotations

from typing import Any, Protocol

from fastapi_app.domain import ConnectionStatus


class AuditLogPort(Protocol):
    def emit(self, event: str, level: str = "info", **fields: Any) -> None: ...

    def recent(self, limit: int = 50) -> list[dict[str, Any]]: ...


class HealthProbePort(Protocol):
    @property
    def component(self) -> str: ...

    def probe(self) -> ConnectionStatus: ...
