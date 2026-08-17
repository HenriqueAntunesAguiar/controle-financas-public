from typing import Literal

from pydantic import BaseModel, Field


class GuardrailDecision(BaseModel):
    """Structured decision returned by the inbound semantic classifier."""

    decision: Literal["allow", "block", "review"]
    reason_code: Literal[
        "safe",
        "prompt_injection",
        "harmful_content",
        "out_of_scope",
        "sensitive_data",
    ]
    confidence: float = Field(ge=0, le=1)
