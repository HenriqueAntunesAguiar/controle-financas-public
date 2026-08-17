"""Armazenamento privado em disco com caminhos confinados e escrita atomica."""

from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi_app.domain import ConnectionStatus, InvalidInputError, StoredDocument


MAX_PDF_BYTES = 50 * 1024 * 1024


class LocalDocumentStorage:
    component = "private_storage"

    def __init__(self, private_root: Path):
        self.private_root = private_root.resolve()
        self.private_root.mkdir(parents=True, exist_ok=True)

    def resolve(self, reference: str) -> Path:
        path = (self.private_root / reference).resolve()
        try:
            path.relative_to(self.private_root)
        except ValueError as exc:
            raise InvalidInputError("Caminho local invalido.") from exc
        return path

    def relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.private_root).as_posix()

    async def save_pdf(self, invoice_id: str, filename: str, chunks: AsyncIterator[bytes]) -> StoredDocument:
        directory = self.resolve(f"uploads/{invoice_id}")
        directory.mkdir(parents=True, exist_ok=False)
        temporary = directory / ".upload.tmp"
        final = directory / "fatura.pdf"
        size = 0
        first = True
        try:
            with temporary.open("xb") as output:
                async for chunk in chunks:
                    if first:
                        first = False
                        if not chunk.startswith(b"%PDF-"):
                            raise InvalidInputError(
                                "O arquivo nao possui assinatura PDF valida."
                            )
                    size += len(chunk)
                    if size > MAX_PDF_BYTES:
                        raise InvalidInputError("O PDF excede 50 MiB.")
                    output.write(chunk)
                if first:
                    raise InvalidInputError("O arquivo PDF esta vazio.")
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, final)
            return StoredDocument(self.relative(final), filename)
        except Exception:
            temporary.unlink(missing_ok=True)
            final.unlink(missing_ok=True)
            try:
                directory.rmdir()
            except OSError:
                pass
            raise

    def remove_pdf(self, reference: str) -> None:
        path = self.resolve(reference)
        path.unlink(missing_ok=True)
        try:
            path.parent.rmdir()
        except OSError:
            pass

    def save_payload(self, invoice_id: str, version: int, payload: dict[str, Any]) -> str:
        path = self.resolve(f"processed/{invoice_id}/version-{version}.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_name = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".version-", suffix=".tmp", dir=path.parent
            )
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
                json.dump(payload, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_name, path)
            temporary_name = None
        finally:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)
        return self.relative(path)

    def load_payload(self, reference: str) -> dict[str, Any]:
        return json.loads(self.resolve(reference).read_text(encoding="utf-8"))

    def probe(self) -> ConnectionStatus:
        started = time.perf_counter()
        temporary_name = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".health-", dir=self.private_root
            )
            os.close(descriptor)
            Path(temporary_name).unlink()
            temporary_name = None
            status, detail = "ok", "read_write_ok"
        except Exception:
            status, detail = "error", "read_write_failed"
        finally:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)
        return ConnectionStatus(
            self.component, status, round((time.perf_counter() - started) * 1000, 2), detail
        )
