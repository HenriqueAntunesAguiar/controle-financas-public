from collections.abc import Callable
from typing import Any, cast

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import interrupt

from model_providers import get_financial_operation_model

from financial_data_agent.tools.get_expense_by_id import (
    ExpenseReader,
    create_get_expense_by_id_tool,
)
from .approval import describe_financial_operation
from .prompt_version.prompt import SYSTEM_PROMPT_FINANCIAL_OPERATION_AGENT
from .tools.create_expense import create_expense_tool
from .tools.delete_expense import delete_expense_tool
from .tools.update_expense import update_expense_tool


OPERATION_TOOL_NAMES = {"create_expense", "delete_expense", "update_expense"}
ALLOWED_DECISIONS = ["approve", "reject"]
DEFAULT_CHECKPOINTER = object()


class FinancialOperationAgent:
    """Agente de escrita implementado como um StateGraph explicito."""

    def __init__(
        self,
        reader: ExpenseReader | None = None,
        create_handler: Callable[..., dict[str, Any]] | None = None,
        update_handler: Callable[..., dict[str, Any]] | None = None,
        delete_handler: Callable[[int], None] | None = None,
        checkpointer: BaseCheckpointSaver | None | object = DEFAULT_CHECKPOINTER,
    ):
        if checkpointer is DEFAULT_CHECKPOINTER:
            from memory import get_checkpointer

            checkpointer = get_checkpointer()
        selected_checkpointer = cast(BaseCheckpointSaver | None, checkpointer)
        dependencies = (reader, create_handler, update_handler, delete_handler)

        if any(item is None for item in dependencies) and not all(
            item is None for item in dependencies
        ):
            raise ValueError("Informe todas as dependencias ou nenhuma delas.")

        if all(item is None for item in dependencies):
            from .integration.invoice_web import create_default_dependencies

            reader, create_handler, update_handler, delete_handler = (
                create_default_dependencies()
            )

        assert reader is not None
        assert create_handler is not None
        assert update_handler is not None
        assert delete_handler is not None

        self._tools = [
            create_get_expense_by_id_tool(reader),
            create_expense_tool(create_handler),
            update_expense_tool(update_handler),
            delete_expense_tool(delete_handler),
        ]
        self._tools_by_name = {item.name: item for item in self._tools}
        self._model = get_financial_operation_model().bind_tools(self._tools)
        self._agent = self._build_graph(selected_checkpointer)
        self._tool = self._create_tool()

    def _build_graph(self, checkpointer: BaseCheckpointSaver | None) -> Runnable:

        graph = StateGraph(MessagesState)
        
        graph.add_node("model", self._call_model)
        graph.add_node("approval", self._request_approval)
        graph.add_node("tools", self._execute_tools)

        graph.add_edge(START, "model")
        graph.add_conditional_edges(
            "model",
            self._route_after_model,
            {"approval": "approval", "tools": "tools", "end": END},
        )
        graph.add_conditional_edges(
            "approval",
            self._route_after_approval,
            {"tools": "tools", "model": "model"},
        )
        graph.add_edge("tools", "model")

        return graph.compile(checkpointer=checkpointer)

    def _call_model(
        self, state: MessagesState, config: RunnableConfig
    ) -> dict[str, list[AIMessage]]:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_FINANCIAL_OPERATION_AGENT},
            *state["messages"],
        ]
        response = self._model.invoke(messages, config=config)
        return {"messages": [response]}

    @staticmethod
    def _latest_ai_message(state: MessagesState) -> AIMessage:
        message = next(
            (
                item
                for item in reversed(state["messages"])
                if isinstance(item, AIMessage)
            ),
            None,
        )
        if message is None:
            raise ValueError("O grafo nao encontrou uma mensagem do modelo.")
        return message

    @classmethod
    def _route_after_model(cls, state: MessagesState) -> str:
        tool_calls = cls._latest_ai_message(state).tool_calls

        if not tool_calls:
            return "end"
        
        if any(item["name"] in OPERATION_TOOL_NAMES for item in tool_calls):
            return "approval"
        
        return "tools"

    @classmethod
    def _route_after_approval(cls, state: MessagesState) -> str:
        return "tools" if cls._latest_ai_message(state).tool_calls else "model"

    def _request_approval(self, state: MessagesState) -> dict[str, list[Any]]:
        ai_message = self._latest_ai_message(state)
        protected_calls = [
            item
            for item in ai_message.tool_calls
            if item["name"] in OPERATION_TOOL_NAMES
        ]
        request = {
            "action_requests": [
                {
                    "name": item["name"],
                    "args": item["args"],
                    "description": describe_financial_operation(item, state, None),
                }
                for item in protected_calls
            ],
            "review_configs": [
                {
                    "action_name": item["name"],
                    "allowed_decisions": ALLOWED_DECISIONS,
                }
                for item in protected_calls
            ],
        }
        response = interrupt(request)
        decisions = response.get("decisions", [])
        if len(decisions) != len(protected_calls):
            raise ValueError(
                "A quantidade de decisoes deve corresponder as operacoes pendentes."
            )

        decisions_by_call_id = {
            tool_call["id"]: decision
            for tool_call, decision in zip(protected_calls, decisions, strict=True)
        }
        approved_calls = []
        rejected_messages = []
        for tool_call in ai_message.tool_calls:
            decision = decisions_by_call_id.get(tool_call["id"])
            if decision.get("type") == "approve":
                approved_calls.append(tool_call)
                continue
            if decision.get("type") != "reject" or decision is None:
                raise ValueError(
                    f"Decisao humana invalida: {decision.get('type')!r}."
                )
            rejected_messages.append(
                ToolMessage(
                    content=decision.get("message")
                    or "Operacao rejeitada pelo usuario. Nao tente novamente sem uma nova solicitacao explicita.",
                    name=tool_call["name"],
                    tool_call_id=tool_call["id"],
                    status="error",
                )
            )

        revised_message = ai_message.model_copy(
            update={"tool_calls": approved_calls}
        )
        return {"messages": [revised_message, *rejected_messages]}

    def _execute_tools(
        self, state: MessagesState, config: RunnableConfig
    ) -> dict[str, list[ToolMessage]]:
        ai_message = self._latest_ai_message(state)
        results = []
        for tool_call in ai_message.tool_calls:
            selected_tool = self._tools_by_name.get(tool_call["name"])
            if selected_tool is None:
                raise ValueError(f"Ferramenta desconhecida: {tool_call['name']!r}.")
            results.append(selected_tool.invoke(tool_call, config=config))
        return {"messages": results}

    def as_agent(self) -> Runnable:
        """Retorna o grafo compilado para execucao direta ou testes."""
        return self._agent

    def as_tool(self) -> BaseTool:
        """Retorna o grafo encapsulado como tool para o AI Manager."""
        return self._tool

    def _create_tool(self) -> BaseTool:
        @tool("financial_operation_agent")
        def call_financial_operation_agent(
            task: str, config: RunnableConfig
        ) -> str:
            """Solicita criacao, atualizacao ou remocao de lancamentos financeiros.

            Use somente quando o usuario pedir explicitamente uma alteracao. Informe
            todos os dados conhecidos e nunca presuma consentimento. O agente exibira
            uma previa da operacao e aguardara aprovacao humana antes de modificar o banco.
            """
            result = self._agent.invoke(
                {"messages": [{"role": "user", "content": task}]}, config=config
            )
            return result["messages"][-1].content

        return call_financial_operation_agent
