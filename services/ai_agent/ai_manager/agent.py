from collections.abc import Sequence

from langchain.agents import create_agent
from langchain.agents.middleware import PIIMiddleware, SummarizationMiddleware
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver

from financial_data_agent import FinancialDataAgent
from financial_operation_agent import FinancialOperationAgent
from guardrails.inbound import (
    SemanticInputGuardrailMiddleware,
    get_guardrail_classifier,
)
from memory import SYSTEM_PROMPT_AI_SUMMARIZER, get_checkpointer
from model_providers import get_manager_model, get_summarization_model

from .prompt_version.prompt import SYSTEM_PROMPT_AI_MANAGER


def create_ai_manager_agent(*, tools: Sequence[BaseTool] | None = None, checkpointer: BaseCheckpointSaver | None = None):
    """Cria o AI Manager com os agentes financeiros disponiveis como tools."""
    selected_checkpointer = checkpointer if checkpointer is not None else get_checkpointer()
    selected_tools = list(tools or [])
    selected_names = {selected_tool.name for selected_tool in selected_tools}
    default_tools = []
    if "financial_data_agent" not in selected_names:
        default_tools.append(FinancialDataAgent().as_tool())
    if "financial_operation_agent" not in selected_names:
        default_tools.append(FinancialOperationAgent(checkpointer=None).as_tool())
    selected_tools = [*default_tools, *selected_tools]

    return create_agent(
        model=get_manager_model(),
        tools=selected_tools,
        system_prompt=SYSTEM_PROMPT_AI_MANAGER,
        middleware=[
            SemanticInputGuardrailMiddleware(get_guardrail_classifier()),
            PIIMiddleware(
                "credit_card",
                strategy="mask",
                apply_to_input=True,
            ),
            SummarizationMiddleware(
                model=get_summarization_model(),
                trigger=("messages", 20),
                keep=("messages", 10),
                summary_prompt=SYSTEM_PROMPT_AI_SUMMARIZER,
            ),
        ],
        checkpointer=selected_checkpointer,
    )
