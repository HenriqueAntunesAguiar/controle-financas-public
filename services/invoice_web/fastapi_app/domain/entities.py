"""Objetos imutaveis compartilhados pelos casos de uso e adaptadores."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class StoredDocument:
    reference: str
    display_name: str


@dataclass(frozen=True)
class ProcessingSummary:
    version: int
    transactions: int
    requires_review: bool = False


@dataclass(frozen=True)
class ImportReceipt:
    version_id: int
    already_imported: bool


@dataclass(frozen=True)
class ConnectionStatus:
    component: str
    status: str
    latency_ms: float
    detail: str

    def as_dict(self) -> dict[str, str | float]:
        return asdict(self)
