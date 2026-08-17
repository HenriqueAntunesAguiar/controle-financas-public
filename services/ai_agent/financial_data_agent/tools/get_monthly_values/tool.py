from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from .result import DataKind, MonthlyValuesReader, build_monthly_values_result


class GetMonthlyValuesInput(BaseModel):
    months: list[str] = Field(
        min_length=1,
        max_length=12,
        description="Meses consultados no formato YYYY-MM.",
    )
    data_kind: DataKind = Field(
        description=(
            "Natureza dos dados: actual para realizados, projected para "
            "projecoes, ou actual_and_projected para realizado quando "
            "disponivel e projecao nos periodos futuros."
        ),
    )


def create_get_monthly_values_tool(reader: MonthlyValuesReader) -> BaseTool:
    """Cria a ferramenta de consulta com sua fonte de dados injetada."""

    @tool("get_monthly_values", args_schema=GetMonthlyValuesInput)
    def get_monthly_values(months: list[str], data_kind: DataKind) -> dict:
        """Consulta totais mensais por origem, categoria e natureza temporal."""
        values = reader.get_monthly_values(months, data_kind)
        return build_monthly_values_result(values, months, data_kind)

    return get_monthly_values
