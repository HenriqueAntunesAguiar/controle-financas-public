from typing import Any


MONTH_NAMES = {
    "01": "janeiro",
    "02": "fevereiro",
    "03": "março",
    "04": "abril",
    "05": "maio",
    "06": "junho",
    "07": "julho",
    "08": "agosto",
    "09": "setembro",
    "10": "outubro",
    "11": "novembro",
    "12": "dezembro",
}

FIELD_LABELS = {
    "expense_id": "ID",
    "description": "nome",
    "category_slug": "categoria",
    "amount": "valor",
    "payment_method": "meio de pagamento",
    "expense_type": "tipo",
    "recurrence_mode": "recorrência",
    "recurrence_end_month": "fim da recorrência",
}

ACTION_TITLES = {
    "create_expense": "Irei adicionar o seguinte lançamento:",
    "update_expense": "Irei atualizar o seguinte lançamento:",
    "delete_expense": "Irei remover o seguinte lançamento:",
}


def _month_lines(month: str) -> list[str]:
    try:
        year, month_number = month.split("-", maxsplit=1)
        month_name = MONTH_NAMES[month_number]
    except (KeyError, ValueError):
        return [f"mês: {month}"]
    return [f"mês: {month_name}", f"ano: {year}"]


def describe_financial_operation(tool_call: dict[str, Any], _state: Any, _runtime: Any) -> str:
    """Formata a operação pendente para revisão humana."""

    name = tool_call["name"]
    args = tool_call.get("args", {})
    lines = [ACTION_TITLES.get(name, "Irei executar a seguinte operação financeira:")]

    for field, value in args.items():
        if value is None or value == "":
            continue

        if field == "month":
            lines.extend(_month_lines(str(value)))
            continue

        label = FIELD_LABELS.get(field, field.replace("_", " "))
        lines.append(f"{label}: {value}")

    lines.append("")
    lines.append("Confirma esta alteração?")
    return "\n".join(lines)
