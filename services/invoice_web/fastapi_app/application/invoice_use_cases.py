"""Orquestracao de faturas dependente somente das portas da aplicacao."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

from fastapi_app.application.ports import (
    AuditLogPort,
    DocumentStoragePort,
    InvoiceParserPort,
    InvoiceRepositoryPort,
    RepositoryConflict,
    VersionPublisherPort,
)
from fastapi_app.domain import (
    ConflictError,
    ImportUnavailableError,
    InvalidInputError,
    NotFoundError,
    ProcessingError,
    ProcessingSummary,
)


SAFE_NAME_RE = re.compile(r"[^\w.() -]+", re.UNICODE)
MAX_INVOICE_NAME_LENGTH = 120


class InvoiceUseCases:
    def __init__(self, repository: InvoiceRepositoryPort, storage: DocumentStoragePort, parser: InvoiceParserPort, publisher: VersionPublisherPort, audit: AuditLogPort):
        self.repository = repository
        self.storage = storage
        self.parser = parser
        self.publisher = publisher
        self.audit = audit

    def dashboard(self) -> dict[str, Any]:
        return {
            "invoices": self.repository.list_all(),
            "stats": self.repository.stats(),
        }

    @staticmethod
    def _display_name(filename: str) -> str:
        basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
        cleaned = SAFE_NAME_RE.sub("_", basename).strip(" .")
        return (cleaned or "fatura.pdf")[:180]

    @staticmethod
    def _valid_uuid(invoice_id: str) -> None:
        try:
            uuid.UUID(invoice_id)
        except ValueError as exc:
            raise InvalidInputError("Identificador invalido.") from exc

    @staticmethod
    def _invoice_name(value: str) -> str:
        name = " ".join(value.split()).strip()
        if not name:
            raise InvalidInputError("Informe um nome para a fatura.")
        if len(name) > MAX_INVOICE_NAME_LENGTH:
            raise InvalidInputError("O nome da fatura excede 120 caracteres.")
        return name

    async def register(self, name_text: str, filename: str, reference_text: str, chunks: AsyncIterator[bytes]) -> str:
        if not filename or not filename.lower().endswith(".pdf"):
            raise InvalidInputError("Selecione uma fatura PDF valida.")
        try:
            reference_date = date.fromisoformat(reference_text)
        except ValueError as exc:
            raise InvalidInputError("Informe uma data de referencia valida.") from exc
        invoice_name = self._invoice_name(name_text)

        invoice_id = str(uuid.uuid4())
        started = time.perf_counter()
        stored = None
        try:
            stored = await self.storage.save_pdf(invoice_id, filename, chunks)
            self.repository.create(
                invoice_id,
                invoice_name,
                self._display_name(stored.display_name),
                stored.reference,
                reference_date.isoformat(),
            )
        except InvalidInputError:
            self.audit.emit(
                "invoice.register", level="warning", outcome="rejected",
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            raise
        except Exception as exc:
            if stored is not None:
                self.storage.remove_pdf(stored.reference)
            self.audit.emit(
                "invoice.register", level="error", outcome="failed",
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            raise ProcessingError("Nao foi possivel registrar a fatura.") from exc
        self.audit.emit(
            "invoice.register", invoice_id=invoice_id, outcome="success",
            duration_ms=(time.perf_counter() - started) * 1000,
        )
        return invoice_id

    def process(self, invoice_id: str, password: str | None) -> ProcessingSummary:
        self._valid_uuid(invoice_id)
        if password is not None and len(password) > 256:
            raise InvalidInputError("Senha invalida.")
        started = time.perf_counter()
        try:
            pending = self.repository.begin_processing(invoice_id)
        except RepositoryConflict as exc:
            raise ConflictError("Fatura nao encontrada ou ocupada.") from exc

        try:
            payload = self.parser.parse(
                document_reference=pending["pdf_path"],
                reference_date=date.fromisoformat(pending["reference_date"]),
                document_id=invoice_id,
                version_number=pending["version_number"],
                password=password,
            )
            payload["nome"] = pending["name"]
            output_reference = self.storage.save_payload(
                invoice_id, pending["version_number"], payload
            )
            transaction_count = int(payload["resumo"]["transacoes_extraidas"])
            version_status = payload.get("qualidade", {}).get(
                "status", "needs_review"
            )
            self.repository.finish_processing(
                invoice_id,
                pending["version_number"],
                output_reference,
                payload["conteudo_hash"],
                transaction_count,
                version_status,
            )
        except Exception as exc:
            self.repository.fail_processing(invoice_id)
            self.audit.emit(
                "invoice.process", level="error", invoice_id=invoice_id,
                outcome="failed", duration_ms=(time.perf_counter() - started) * 1000,
            )
            raise ProcessingError(
                "Nao foi possivel processar o PDF. Verifique o formato ou a senha."
            ) from exc
        self.audit.emit(
            "invoice.process", invoice_id=invoice_id, outcome=version_status,
            version=pending["version_number"], transaction_count=transaction_count,
            duration_ms=(time.perf_counter() - started) * 1000,
        )
        return ProcessingSummary(
            pending["version_number"],
            transaction_count,
            requires_review=version_status == "needs_review",
        )

    def import_latest(self, invoice_id: str) -> bool:
        self._valid_uuid(invoice_id)
        version = self.repository.latest_version(invoice_id)
        if version is None:
            raise NotFoundError("Processe a fatura antes de importar.")
        if version["status"] == "needs_review":
            raise ConflictError(
                "A versao possui divergencias e precisa ser revisada antes da importacao."
            )
        started = time.perf_counter()
        try:
            payload = self.storage.load_payload(version["json_path"])
            payload["nome"] = version["invoice_name"]
            result = self.publisher.publish(payload)
            self.repository.mark_imported(
                invoice_id, version["version_number"], result.version_id
            )
        except Exception as exc:
            self.repository.mark_import_failed(invoice_id)
            self.audit.emit(
                "invoice.import", level="error", invoice_id=invoice_id,
                component="postgresql", outcome="failed",
                duration_ms=(time.perf_counter() - started) * 1000,
            )
            raise ImportUnavailableError(
                "Nao foi possivel importar. Confirme se o PostgreSQL esta ativo."
            ) from exc
        self.audit.emit(
            "invoice.import", invoice_id=invoice_id, component="postgresql",
            outcome="already_exists" if result.already_imported else "success",
            version=version["version_number"],
            duration_ms=(time.perf_counter() - started) * 1000,
        )
        return result.already_imported

    def approve_latest(self, invoice_id: str) -> None:
        self._valid_uuid(invoice_id)
        try:
            self.repository.approve_latest(invoice_id)
        except RepositoryConflict as exc:
            raise ConflictError("Nao ha uma versao pendente de revisao.") from exc
        self.audit.emit(
            "invoice.review_approved", invoice_id=invoice_id, outcome="ready"
        )
