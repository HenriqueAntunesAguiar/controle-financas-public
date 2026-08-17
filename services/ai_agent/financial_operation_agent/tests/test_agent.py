from unittest import TestCase
from unittest.mock import Mock, patch

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from financial_operation_agent import FinancialOperationAgent


class Reader:
    def get_expense_by_id(self, expense_id: int) -> None:
        return None


class FakeToolCallingModel:
    def __init__(self, *responses: AIMessage):
        self.responses = list(responses)
        self.tools = []

    def bind_tools(self, tools):
        self.tools = tools
        return self

    def invoke(self, _messages, config=None):
        return self.responses.pop(0)


def create_call() -> dict:
    return {
        "name": "create_expense",
        "args": {
            "month": "2026-08",
            "description": "Mercado",
            "amount": "100.00",
            "category_slug": "alimentacao",
            "payment_method": "pix",
            "expense_type": "actual",
            "recurrence_mode": "none",
        },
        "id": "create-1",
        "type": "tool_call",
    }


class FinancialOperationAgentGraphTest(TestCase):
    @patch("financial_operation_agent.agent.get_financial_operation_model")
    def test_builds_explicit_graph_with_all_tools(self, get_model_mock) -> None:
        model = FakeToolCallingModel(AIMessage(content="Sem operacao."))
        get_model_mock.return_value = model

        component = FinancialOperationAgent(
            Reader(),
            lambda *args: {},
            lambda *args: {},
            lambda expense_id: None,
            checkpointer=InMemorySaver(),
        )

        self.assertEqual(
            [item.name for item in model.tools],
            ["get_expense_by_id", "create_expense", "update_expense", "delete_expense"],
        )
        self.assertEqual(
            set(component.as_agent().get_graph().nodes),
            {"__start__", "model", "approval", "tools", "__end__"},
        )
        self.assertIs(component.as_tool(), component.as_tool())

    @patch("financial_operation_agent.agent.get_financial_operation_model")
    def test_approve_resumes_graph_and_executes_write(self, get_model_mock) -> None:
        model = FakeToolCallingModel(
            AIMessage(content="", tool_calls=[create_call()]),
            AIMessage(content="Lancamento criado."),
        )
        get_model_mock.return_value = model
        create_handler = Mock(return_value={"created": True})
        component = FinancialOperationAgent(
            Reader(),
            create_handler,
            lambda *args: {},
            lambda expense_id: None,
            checkpointer=InMemorySaver(),
        )
        config = {"configurable": {"thread_id": "approve-thread"}}

        interrupted = component.as_agent().invoke(
            {"messages": [{"role": "user", "content": "Adicione mercado"}]},
            config=config,
        )

        create_handler.assert_not_called()
        pending = interrupted["__interrupt__"][0]
        self.assertEqual(
            pending.value["action_requests"][0]["name"], "create_expense"
        )
        self.assertIn("Mercado", pending.value["action_requests"][0]["description"])

        completed = component.as_agent().invoke(
            Command(
                resume={
                    pending.id: {"decisions": [{"type": "approve"}]}
                }
            ),
            config=config,
        )

        create_handler.assert_called_once_with(
            "2026-08",
            "Mercado",
            "100.00",
            "alimentacao",
            "pix",
            "actual",
            "none",
            None,
        )
        self.assertEqual(completed["messages"][-1].content, "Lancamento criado.")

    @patch("financial_operation_agent.agent.get_financial_operation_model")
    def test_reject_resumes_graph_without_executing_write(self, get_model_mock) -> None:
        model = FakeToolCallingModel(
            AIMessage(content="", tool_calls=[create_call()]),
            AIMessage(content="Operacao cancelada."),
        )
        get_model_mock.return_value = model
        create_handler = Mock(return_value={"created": True})
        component = FinancialOperationAgent(
            Reader(),
            create_handler,
            lambda *args: {},
            lambda expense_id: None,
            checkpointer=InMemorySaver(),
        )
        config = {"configurable": {"thread_id": "reject-thread"}}
        interrupted = component.as_agent().invoke(
            {"messages": [{"role": "user", "content": "Adicione mercado"}]},
            config=config,
        )
        pending = interrupted["__interrupt__"][0]

        completed = component.as_agent().invoke(
            Command(
                resume={
                    pending.id: {
                        "decisions": [
                            {
                                "type": "reject",
                                "message": "Operacao rejeitada pelo usuario.",
                            }
                        ]
                    }
                }
            ),
            config=config,
        )

        create_handler.assert_not_called()
        self.assertEqual(completed["messages"][-1].content, "Operacao cancelada.")

    @patch("financial_operation_agent.integration.invoice_web.create_default_dependencies")
    @patch("memory.get_checkpointer")
    @patch("financial_operation_agent.agent.get_financial_operation_model")
    def test_builds_default_dependencies_when_called_without_arguments(
        self, get_model_mock, get_checkpointer_mock, create_dependencies_mock
    ) -> None:
        get_model_mock.return_value = FakeToolCallingModel(
            AIMessage(content="Sem operacao.")
        )
        get_checkpointer_mock.return_value = InMemorySaver()
        create_dependencies_mock.return_value = (
            Reader(),
            lambda *args: {},
            lambda *args: {},
            lambda expense_id: None,
        )

        component = FinancialOperationAgent()

        create_dependencies_mock.assert_called_once_with()
        self.assertIsNotNone(component.as_agent())
