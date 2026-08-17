import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


SERVICES_ROOT = Path(__file__).resolve().parents[3]
INVOICE_WEB_ROOT = SERVICES_ROOT / "invoice_web"
if str(INVOICE_WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(INVOICE_WEB_ROOT))

from fastapi_app.adapters.outbound.persistence import PostgresCashFlowRepository
from fastapi_app.application import CashFlowUseCases
from fastapi_app.infrastructure.config import PostgresSettings

from financial_data_agent.repository import PostgresConnectionSettings, PostgresFinancialDataReader


class NoOpAudit:
    def emit(self, event: str, **fields: Any) -> None:
        pass


def create_default_dependencies() -> tuple[PostgresFinancialDataReader, Callable[..., dict[str, Any]], Callable[..., dict[str, Any]], Callable[[int], None]]:
    reader = PostgresFinancialDataReader(PostgresConnectionSettings.from_environment())
    repository = PostgresCashFlowRepository(PostgresSettings.from_environment())
    cash_flow = CashFlowUseCases(repository, NoOpAudit())
    return reader, cash_flow.create_expense, cash_flow.update_expense, cash_flow.remove_expense
