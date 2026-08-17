from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from .result import ExpenseReader, build_expense_result


class GetExpenseByIdInput(BaseModel):
    expense_id: int = Field(gt=0, description="Identificador do lancamento manual.")


def create_get_expense_by_id_tool(reader: ExpenseReader) -> BaseTool:
    """Cria a ferramenta de consulta unitaria com seu reader injetado."""

    @tool("get_expense_by_id", args_schema=GetExpenseByIdInput)
    def get_expense_by_id(expense_id: int) -> dict:
        """Consulta um lancamento manual ativo pelo identificador."""
        return build_expense_result(expense_id, reader.get_expense_by_id(expense_id))

    return get_expense_by_id
