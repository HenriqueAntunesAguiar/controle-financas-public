from __future__ import annotations

from typing import Any, Protocol

from fastapi_app.domain import ImportReceipt


class VersionPublisherPort(Protocol):
    def publish(self, payload: dict[str, Any]) -> ImportReceipt: ...
