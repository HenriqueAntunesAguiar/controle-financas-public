"""Smoke test com dados ficticios; nenhuma fatura local e consultada."""

from decimal import Decimal

from dotenv import load_dotenv

from ..agent import FinancialDataAgent
from ..tools import DataKind


class FakeMonthlyValuesReader:
    reference_month = "2026-07"
    _values = {
        "actual": {
            "2026-07": {
                "credit_card": {
                    "supermercado": Decimal("1200.00"),
                    "transporte": Decimal("600.00"),
                },
                "other_transactions": {"gasolina": Decimal("200.00")},
            },
        },
        "projected": {
            "2026-08": {
                "credit_card": {"supermercado": Decimal("1500.00")},
                "other_transactions": {"transporte": Decimal("300.00")},
            },
        },
    }

    def get_expense_by_id(self, expense_id: int) -> dict | None:
        if expense_id != 42:
            return None
        return {
            "id": 42,
            "month": "2026-07",
            "description": "Parcela carro",
            "amount": Decimal("12.00"),
            "category_slug": "carro",
            "category_name": "Carro",
            "payment_method": "debito",
            "expense_type": "actual",
            "recurrence_mode": None,
            "recurrence_end_month": None,
        }

    def get_monthly_values(self, months: list[str], data_kind: DataKind) -> list[dict]:
        return [self._month(month, data_kind) for month in months]

    def _month(self, month: str, data_kind: DataKind) -> dict:
        effective_kind = data_kind
        if data_kind == "actual_and_projected":
            effective_kind = (
                "actual" if month <= self.reference_month else "projected"
            )
        source_categories = self._values[effective_kind].get(month)
        if source_categories is None:
            sources = {
                source: {
                    "data_kind": None,
                    "status": "data_unavailable",
                    "data_found": False,
                    "total": None,
                    "categories": {},
                }
                for source in ("credit_card", "other_transactions")
            }
            total = None
        else:
            sources = {
                source: {
                    "data_kind": effective_kind,
                    "status": (
                        "available"
                        if effective_kind == "actual"
                        else "projected"
                    ),
                    "data_found": bool(categories),
                    "total": sum(categories.values(), start=Decimal("0")),
                    "categories": categories,
                }
                for source, categories in source_categories.items()
            }
            total = sum(
                (source["total"] for source in sources.values()),
                start=Decimal("0"),
            )
        return {
            "month": month,
            "data_kind": data_kind,
            "reference_month": self.reference_month,
            "total": total,
            "sources": sources,
        }


def main() -> None:
    load_dotenv()
    reader = FakeMonthlyValuesReader()
    agent_tool = FinancialDataAgent(reader).as_tool()
    result = agent_tool.invoke(
        {
            "task": (
                "Compare julho realizado com a projecao de agosto "
                "de 2026 para o cartao de credito."
            )
        }
    )
    print(result)


if __name__ == "__main__":
    main()
