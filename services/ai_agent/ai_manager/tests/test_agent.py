from unittest import TestCase
from unittest.mock import Mock, patch

from langchain_core.tools import tool

from ai_manager.agent import create_ai_manager_agent


@tool("financial_data_agent")
def fake_data_agent(task: str) -> str:
    """Fake financial data agent."""
    return task


@tool("financial_operation_agent")
def fake_operation_agent(task: str) -> str:
    """Fake financial operation agent."""
    return task


class AIManagerToolsTest(TestCase):
    @patch("ai_manager.agent.get_checkpointer")
    @patch("ai_manager.agent.get_guardrail_classifier")
    @patch("ai_manager.agent.get_summarization_model")
    @patch("ai_manager.agent.get_manager_model")
    @patch("ai_manager.agent.FinancialOperationAgent")
    @patch("ai_manager.agent.FinancialDataAgent")
    @patch("ai_manager.agent.create_agent")
    def test_registers_both_financial_agents_as_default_tools(self, create_agent_mock, data_class_mock, operation_class_mock, manager_model_mock, summarization_model_mock, guardrail_mock, checkpointer_mock) -> None:
        data_class_mock.return_value.as_tool.return_value = fake_data_agent
        operation_class_mock.return_value.as_tool.return_value = fake_operation_agent

        create_ai_manager_agent()

        tools = create_agent_mock.call_args.kwargs["tools"]
        self.assertEqual([item.name for item in tools], ["financial_data_agent", "financial_operation_agent"])
        operation_class_mock.assert_called_once_with(checkpointer=None)

    @patch("ai_manager.agent.get_checkpointer", return_value=Mock())
    @patch("ai_manager.agent.get_guardrail_classifier", return_value=Mock())
    @patch("ai_manager.agent.get_summarization_model", return_value=Mock())
    @patch("ai_manager.agent.get_manager_model", return_value=Mock())
    @patch("ai_manager.agent.FinancialOperationAgent")
    @patch("ai_manager.agent.FinancialDataAgent")
    @patch("ai_manager.agent.create_agent")
    def test_explicit_tools_replace_the_default_composition(self, create_agent_mock, data_class_mock, operation_class_mock, manager_model_mock, summarization_model_mock, guardrail_mock, checkpointer_mock) -> None:
        create_ai_manager_agent(tools=[fake_data_agent, fake_operation_agent])

        tools = create_agent_mock.call_args.kwargs["tools"]
        self.assertEqual([item.name for item in tools], ["financial_data_agent", "financial_operation_agent"])
        data_class_mock.assert_not_called()
        operation_class_mock.assert_not_called()
