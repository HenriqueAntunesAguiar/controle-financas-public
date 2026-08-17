"""Nucleo de dominio, sem dependencias de framework ou banco de dados."""

from .entities import ConnectionStatus, ImportReceipt, ProcessingSummary, StoredDocument
from .errors import (
    ApplicationError,
    ConflictError,
    ForbiddenError,
    ImportUnavailableError,
    InvalidInputError,
    NotFoundError,
    ProcessingError,
)

__all__ = [
    "ApplicationError",
    "ConflictError",
    "ConnectionStatus",
    "ForbiddenError",
    "ImportReceipt",
    "ImportUnavailableError",
    "InvalidInputError",
    "NotFoundError",
    "ProcessingError",
    "ProcessingSummary",
    "StoredDocument",
]
