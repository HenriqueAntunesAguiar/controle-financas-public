from collections.abc import Callable
from typing import Any

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

class DeleteExpenseInput(BaseModel):
    expense_id: int = Field(gt=0, description="Identificador do lançamento que será removido.")


def delete_expense_tool(handler: Callable[[int], None]) -> BaseTool:
    @tool("delete_expense", args_schema=DeleteExpenseInput)
    def delete_expense(expense_id: int) -> dict[str, Any]:
        """Remove logicamente um lançamento somente após aprovação humana."""
        handler(expense_id)
        return {"expense_id": expense_id, "deleted": True}

    return delete_expense
