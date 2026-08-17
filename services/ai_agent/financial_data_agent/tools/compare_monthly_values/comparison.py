from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..get_monthly_values.result import DataKind, money


ValueSource = Literal["all", "credit_card", "other_transactions"]


class MonthlySourceValues(BaseModel):
    data_kind: Literal["actual", "projected"] | None
    status: str
    data_found: bool
    total: Decimal | None
    categories: dict[str, Decimal]


class MonthlyValues(BaseModel):
    month: str = Field(
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description="Mes consultado no formato YYYY-MM.",
    )
    data_kind: DataKind
    reference_month: str | None
    total: Decimal | None
    sources: dict[str, MonthlySourceValues]


def _percentage_change(previous: Decimal, current: Decimal) -> str | None:
    if previous == 0:
        return None
    percentage = ((current - previous) / abs(previous)) * Decimal("100")
    return format(percentage.quantize(Decimal("0.01")), ".2f")


def _direction(difference: Decimal) -> Literal["increased", "decreased", "unchanged"]:
    if difference > 0:
        return "increased"
    if difference < 0:
        return "decreased"
    return "unchanged"


def _selected_sources(source: ValueSource) -> tuple[str, ...]:
    if source == "all":
        return ("credit_card", "other_transactions")
    return (source,)


def _selection(values: MonthlyValues, source: ValueSource) -> dict[str, Any]:
    selected = [values.sources[name] for name in _selected_sources(source)]
    available = all(item.total is not None for item in selected)
    total = (
        sum((item.total for item in selected if item.total is not None), Decimal("0"))
        if available
        else None
    )
    return {
        "month": values.month,
        "reference_month": values.reference_month,
        "status": selected[0].status if len(selected) == 1 else "available" if available else "incomplete",
        "data_kind": selected[0].data_kind if len(selected) == 1 else values.data_kind,
        "data_found": any(item.data_found for item in selected),
        "total": total,
    }


def _category_values(values: MonthlyValues, source: ValueSource) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    for source_name in _selected_sources(source):
        for category, total in values.sources[source_name].categories.items():
            result[category] = result.get(category, Decimal("0")) + total
    return result


def _category_source_breakdown(previous: MonthlyValues, current: MonthlyValues, source: ValueSource, category: str) -> list[dict[str, Any]]:
    breakdown = []
    for source_name in _selected_sources(source):
        previous_value = previous.sources[source_name].categories.get(category, Decimal("0"))
        current_value = current.sources[source_name].categories.get(category, Decimal("0"))
        if previous_value == 0 and current_value == 0:
            continue
        difference = current_value - previous_value
        breakdown.append({
            "source": source_name,
            "previous_total": money(previous_value),
            "current_total": money(current_value),
            "difference": money(difference),
            "direction": _direction(difference),
        })
    return breakdown


def calculate_monthly_comparison(previous: MonthlyValues, current: MonthlyValues, source: ValueSource, data_kind: DataKind, limit: int) -> dict:
    previous_selection = _selection(previous, source)
    current_selection = _selection(current, source)
    comparison_available = previous_selection["total"] is not None and current_selection["total"] is not None

    difference = None
    percentage_change = None
    direction = None
    if comparison_available:
        difference = current_selection["total"] - previous_selection["total"]
        percentage_change = _percentage_change(previous_selection["total"], current_selection["total"])
        direction = _direction(difference)

    category_changes = []
    if comparison_available:
        previous_categories = _category_values(previous, source)
        current_categories = _category_values(current, source)
        for category in previous_categories.keys() | current_categories.keys():
            previous_value = previous_categories.get(category, Decimal("0"))
            current_value = current_categories.get(category, Decimal("0"))
            category_difference = current_value - previous_value
            category_changes.append({
                "source": source,
                "category": category,
                "previous_total": money(previous_value),
                "current_total": money(current_value),
                "difference": money(category_difference),
                "percentage_change": _percentage_change(previous_value, current_value),
                "direction": _direction(category_difference),
                "source_breakdown": _category_source_breakdown(previous, current, source, category),
            })
        category_changes.sort(key=lambda item: abs(Decimal(item["difference"])), reverse=True)

    return {
        "comparison_scope": {"source": source, "data_kind": data_kind},
        "comparison_available": comparison_available,
        "previous": {**previous_selection, "total": money(previous_selection["total"])},
        "current": {**current_selection, "total": money(current_selection["total"])},
        "difference": money(difference),
        "percentage_change": percentage_change,
        "direction": direction,
        "category_changes": category_changes[:limit],
        "category_changes_total": len(category_changes),
        "category_changes_returned": min(limit, len(category_changes)),
    }


def empty_month(month: str, data_kind: DataKind) -> dict:
    unavailable = {
        "data_kind": None,
        "status": "data_unavailable",
        "data_found": False,
        "total": None,
        "categories": {},
    }
    return {
        "month": month,
        "data_kind": data_kind,
        "reference_month": None,
        "total": None,
        "sources": {
            "credit_card": unavailable,
            "other_transactions": unavailable.copy(),
        },
    }
