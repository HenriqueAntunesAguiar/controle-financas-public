from decimal import Decimal
from typing import Any, Literal, Protocol


DataKind = Literal["actual", "projected", "actual_and_projected"]


class MonthlyValuesReader(Protocol):
    def get_monthly_values(self, months: list[str], data_kind: DataKind) -> list[dict[str, Any]]: ...


def money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal("0.01")), ".2f")


def _serialize_source(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "data_kind": source["data_kind"],
        "status": source["status"],
        "data_found": source["data_found"],
        "total": money(source["total"]),
        "categories": {
            category: money(Decimal(total))
            for category, total in source["categories"].items()
        },
    }


def build_monthly_values_result(monthly_values: list[dict[str, Any]], months: list[str], data_kind: DataKind) -> dict[str, Any]:
    return {
        "requested_months": months,
        "requested_data_kind": data_kind,
        "months": [
            {
                "month": values["month"],
                "reference_month": values["reference_month"],
                "data_kind": values["data_kind"],
                "data_found": any(
                    source["data_found"] for source in values["sources"].values()
                ),
                "total": money(values["total"]),
                "sources": {
                    name: _serialize_source(source)
                    for name, source in values["sources"].items()
                },
            }
            for values in monthly_values
        ],
    }
