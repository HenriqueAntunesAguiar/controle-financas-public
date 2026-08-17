from typing import Protocol

from langchain.agents import create_agent
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.base import BaseCheckpointSaver

from model_providers import get_financial_data_model

from .prompt_version.prompt import SYSTEM_PROMPT_FINANCIAL_DATA_AGENT
from .repository import PostgresConnectionSettings, PostgresFinancialDataReader
from .tools import ExpenseReader, MonthlyValuesReader, create_compare_monthly_values_tool, create_get_expense_by_id_tool, create_get_monthly_values_tool


class FinancialDataReader(MonthlyValuesReader, ExpenseReader, Protocol):
    pass


class FinancialDataAgent:
    """Disponibiliza o mesmo agente de leitura para uso direto ou como tool."""

    def __init__(self, reader: FinancialDataReader | None = None, checkpointer: BaseCheckpointSaver | None = None):
        selected_reader = reader
        if selected_reader is None:
            settings = PostgresConnectionSettings.from_environment()
            selected_reader = PostgresFinancialDataReader(settings)

        self._agent = create_agent(
            model=get_financial_data_model(),
            tools=[
                create_get_monthly_values_tool(selected_reader),
                create_compare_monthly_values_tool(selected_reader),
                create_get_expense_by_id_tool(selected_reader),
            ],
            system_prompt=SYSTEM_PROMPT_FINANCIAL_DATA_AGENT,
            checkpointer=checkpointer,
        )
        self._tool = self._create_tool()

    def as_agent(self) -> Runnable:
        """Retorna o agente para execucao direta, testes ou benchmarks."""
        return self._agent

    def as_tool(self) -> BaseTool:
        """Retorna o agente encapsulado como tool para outro agente."""
        return self._tool

    def _create_tool(self) -> BaseTool:
        @tool("financial_data_agent")
        def call_financial_data_agent(task: str, config: RunnableConfig) -> str:
            """Executa uma consulta ou analise financeira somente leitura.

            A tarefa deve informar explicitamente os periodos, anos, natureza dos
            dados e origem quando forem necessarios. Use para consultar gastos,
            projecoes, categorias, lancamentos e comparacoes financeiras.
            """
            result = self._agent.invoke({"messages": [{"role": "user", "content": task}]}, config=config)
            return result["messages"][-1].content

        return call_financial_data_agent
