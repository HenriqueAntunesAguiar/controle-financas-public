from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from ..get_monthly_values.result import DataKind, MonthlyValuesReader
from .comparison import MonthlyValues, ValueSource, calculate_monthly_comparison, empty_month


class CompareMonthlyValuesInput(BaseModel):
    previous_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="Mes anterior no formato YYYY-MM.")
    current_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", description="Mes atual no formato YYYY-MM.")
    source: ValueSource = Field(description="Origem que deve ser a mesma nos dois meses: all, credit_card ou other_transactions.")
    data_kind: DataKind = Field(description="Natureza dos dados comparados. Use actual_and_projected para comparar realizado e projetado.")
    limit: int = Field(default=5, ge=1, le=20, description="Quantidade maxima de variacoes retornadas.")


def create_compare_monthly_values_tool(reader: MonthlyValuesReader) -> BaseTool:
    """Cria a comparacao composta com consulta e calculo deterministico."""

    @tool("compare_monthly_values", args_schema=CompareMonthlyValuesInput)
    def compare_monthly_values(previous_month: str, current_month: str, source: ValueSource, data_kind: DataKind, limit: int = 5) -> dict:
        """Compara meses e consolida categorias quando source for all."""
        values = reader.get_monthly_values([previous_month, current_month], data_kind)
        values_by_month = {item["month"]: item for item in values}
        previous_values = values_by_month.get(previous_month, empty_month(previous_month, data_kind))
        current_values = values_by_month.get(current_month, empty_month(current_month, data_kind))
        return calculate_monthly_comparison(
            previous=MonthlyValues.model_validate(previous_values),
            current=MonthlyValues.model_validate(current_values),
            source=source,
            data_kind=data_kind,
            limit=limit,
        )

    return compare_monthly_values
