from collections.abc import Callable
from typing import Any, Literal

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

PaymentMethod = Literal["credito", "pix", "debito", "dinheiro", "transferencia", "outro"]
ExpenseType = Literal["actual", "planned"]
RecurrenceMode = Literal["none", "unlimited", "until"]
UpdateExpenseHandler = Callable[[int, str, str, str, str, str, str, str, str | None], dict[str, Any]]


class UpdateExpenseInput(BaseModel):
    expense_id: int = Field(gt=0, description="Identificador do lançamento existente.")
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="Mês do lançamento no formato YYYY-MM.")
    description: str = Field(min_length=2, max_length=180, description="Nome ou descrição do lançamento.")
    amount: str = Field(description="Valor monetário positivo com duas casas decimais.")
    category_slug: str = Field(min_length=1, max_length=50, description="Slug da categoria existente.")
    payment_method: PaymentMethod
    expense_type: ExpenseType
    recurrence_mode: RecurrenceMode = "none"
    recurrence_end_month: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="Último mês da recorrência quando o modo for until.")


def update_expense_tool(handler: UpdateExpenseHandler) -> BaseTool:
    @tool("update_expense", args_schema=UpdateExpenseInput)
    def update_expense(expense_id: int, month: str, description: str, amount: str, category_slug: str, payment_method: PaymentMethod, expense_type: ExpenseType, recurrence_mode: RecurrenceMode = "none", recurrence_end_month: str | None = None) -> dict[str, Any]:
        """Atualiza integralmente um lançamento somente após aprovação humana."""
        return handler(expense_id, month, description, amount, category_slug, payment_method, expense_type, recurrence_mode, recurrence_end_month)

    return update_expense
