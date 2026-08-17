from functools import lru_cache
from typing import Any

from langchain_core.runnables import Runnable

from model_providers import get_guardrail_model

from .models import GuardrailDecision


@lru_cache(maxsize=1)
def get_guardrail_classifier() -> Runnable[Any, GuardrailDecision]:
    """Return the shared inbound guardrail classifier."""
    return get_guardrail_model().with_structured_output(GuardrailDecision)
