"""Composition root: unico ponto que conecta portas a adaptadores."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi_app.adapters.outbound.ai import LangGraphAssistant
from fastapi_app.adapters.outbound.filesystem import LocalDocumentStorage
from fastapi_app.adapters.outbound.observability import JsonAuditLog
from fastapi_app.adapters.outbound.pdf import PdfPlumberInvoiceParser
from fastapi_app.adapters.outbound.persistence import (
    PostgresVersionPublisher,
    PostgresCategorizationRepository,
    PostgresCashFlowRepository,
    SQLiteInvoiceRepository,
)
from fastapi_app.application import CashFlowUseCases, CategorizationUseCases, DiagnosticsUseCase, InvoiceUseCases
from fastapi_app.application.ports import AssistantPort
from fastapi_app.infrastructure.config import PostgresSettings


@dataclass(frozen=True)
class ApplicationContainer:
    assistant: AssistantPort
    invoices: InvoiceUseCases
    categorization: CategorizationUseCases
    cash_flow: CashFlowUseCases
    diagnostics: DiagnosticsUseCase
    repository: SQLiteInvoiceRepository
    storage: LocalDocumentStorage
    publisher: PostgresVersionPublisher
    audit: JsonAuditLog


def build_container(private_root: Path, categorization_repository: Any | None = None, cash_flow_repository: Any | None = None, assistant: AssistantPort | None = None) -> ApplicationContainer:
    repository = SQLiteInvoiceRepository(private_root / "invoice-registry.sqlite3")
    storage = LocalDocumentStorage(private_root)
    parser = PdfPlumberInvoiceParser(private_root)
    postgres_settings = PostgresSettings.from_environment()
    publisher = PostgresVersionPublisher(postgres_settings)
    selected_categorization_repository = (
        categorization_repository
        if categorization_repository is not None
        else PostgresCategorizationRepository(postgres_settings)
    )
    selected_cash_flow_repository = (
        cash_flow_repository
        if cash_flow_repository is not None
        else PostgresCashFlowRepository(postgres_settings)
    )
    audit = JsonAuditLog(private_root / "logs" / "application.jsonl")
    invoices = InvoiceUseCases(repository, storage, parser, publisher, audit)
    categorization = CategorizationUseCases(selected_categorization_repository, audit)
    cash_flow = CashFlowUseCases(selected_cash_flow_repository, audit)
    diagnostics = DiagnosticsUseCase([repository, storage, publisher], audit)
    return ApplicationContainer(
        assistant=assistant or LangGraphAssistant(),
        invoices=invoices,
        categorization=categorization,
        cash_flow=cash_flow,
        diagnostics=diagnostics,
        repository=repository,
        storage=storage,
        publisher=publisher,
        audit=audit,
    )
