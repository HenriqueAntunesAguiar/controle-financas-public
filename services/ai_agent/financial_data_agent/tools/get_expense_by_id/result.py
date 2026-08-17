from decimal import Decimal
from typing import Any, Protocol


class ExpenseReader(Protocol):
    def get_expense_by_id(self, expense_id: int) -> dict[str, Any] | None: ...


def build_expense_result(expense_id: int, expense: dict[str, Any] | None) -> dict[str, Any]:
    if expense is None:
        return {"expense_id": expense_id, "found": False, "expense": None}

    item = dict(expense)
    item["amount"] = format(Decimal(item["amount"]).quantize(Decimal("0.01")), ".2f")
    item["recurrence_mode"] = item.get("recurrence_mode") or "none"
    return {"expense_id": expense_id, "found": True, "expense": item}
