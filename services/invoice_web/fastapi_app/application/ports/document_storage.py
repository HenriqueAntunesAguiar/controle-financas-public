from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

from fastapi_app.domain import StoredDocument


class DocumentStoragePort(Protocol):
    async def save_pdf(self, invoice_id: str, filename: str, chunks: AsyncIterator[bytes]) -> StoredDocument: ...

    def remove_pdf(self, reference: str) -> None: ...

    def save_payload(self, invoice_id: str, version: int, payload: dict[str, Any]) -> str: ...

    def load_payload(self, reference: str) -> dict[str, Any]: ...
