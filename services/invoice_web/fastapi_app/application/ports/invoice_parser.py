from __future__ import annotations

from datetime import date
from typing import Any, Protocol


class InvoiceParserPort(Protocol):
    def parse(self, document_reference: str, reference_date: date, document_id: str, version_number: int, password: str | None) -> dict[str, Any]: ...
