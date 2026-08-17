from collections.abc import Callable
from typing import Any, Literal

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

PaymentMethod = Literal["credito", "pix", "debito", "dinheiro", "transferencia", "outro"]
ExpenseType = Literal["actual", "planned"]
RecurrenceMode = Literal["none", "unlimited", "until"]
CreateExpenseHandler = Callable[[str, str, str, str, str, str, str, str | None], dict[str, Any]]


class CreateExpenseInput(BaseModel):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="Mês do lançamento no formato YYYY-MM.")
    description: str = Field(min_length=2, max_length=180, description="Nome ou descrição do lançamento.")
    amount: str = Field(description="Valor monetário positivo com duas casas decimais.")
    category_slug: str = Field(min_length=1, max_length=50, description="Slug da categoria existente.")
    payment_method: PaymentMethod
    expense_type: ExpenseType
    recurrence_mode: RecurrenceMode = "none"
    recurrence_end_month: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="Último mês da recorrência quando o modo for until.")


def create_expense_tool(handler: CreateExpenseHandler) -> BaseTool:
    @tool("create_expense", args_schema=CreateExpenseInput)
    def create_expense(month: str, description: str, amount: str, category_slug: str, payment_method: PaymentMethod, expense_type: ExpenseType, recurrence_mode: RecurrenceMode = "none", recurrence_end_month: str | None = None) -> dict[str, Any]:
        """Cria um lançamento manual somente após aprovação humana."""
        return handler(month, description, amount, category_slug, payment_method, expense_type, recurrence_mode, recurrence_end_month)

    return create_expense
