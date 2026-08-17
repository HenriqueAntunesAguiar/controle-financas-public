from functools import lru_cache

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel


MANAGER_MODEL_NAME = "openai:gpt-5.6-luna"
SUMMARIZATION_MODEL_NAME = "openai:gpt-5.6-luna"
FINANCIAL_DATA_MODEL_NAME = "openai:gpt-5.6-luna"
FINANCIAL_OPERATION_MODEL_NAME = "openai:gpt-5.6-luna"
GUARDRAIL_MODEL_NAME = "openai:gpt-5.6-luna"


@lru_cache(maxsize=1)
def get_manager_model() -> BaseChatModel:
    """Return the shared model used by the AI Manager."""
    return init_chat_model(
        MANAGER_MODEL_NAME,
        reasoning_effort="none",
    )


@lru_cache(maxsize=1)
def get_summarization_model() -> BaseChatModel:
    """Return the shared model used to summarize conversation history."""
    return init_chat_model(SUMMARIZATION_MODEL_NAME)


@lru_cache(maxsize=1)
def get_financial_data_model() -> BaseChatModel:
    """Return the shared model used by the Financial Data Agent."""
    return init_chat_model(
        FINANCIAL_DATA_MODEL_NAME,
        reasoning_effort="none",
    )


@lru_cache(maxsize=1)
def get_guardrail_model() -> BaseChatModel:
    """Return the shared model used to classify agent input."""
    return init_chat_model(
        GUARDRAIL_MODEL_NAME,
        timeout=8,
        max_retries=1,
    )

@lru_cache(maxsize=1)
def get_financial_operation_model() -> BaseChatModel:
    """Return the shared model used by the Financial Operation Agent."""
    return init_chat_model(
            FINANCIAL_OPERATION_MODEL_NAME,
            reasoning_effort="none",
        )
