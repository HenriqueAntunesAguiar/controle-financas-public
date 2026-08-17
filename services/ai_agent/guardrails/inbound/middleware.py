import logging
from typing import Any

from langchain.agents.middleware import AgentMiddleware, AgentState, hook_config
from langchain.messages import HumanMessage
from langchain_core.runnables import Runnable
from langgraph.runtime import Runtime

from .models import GuardrailDecision
from .prompt_version.prompt import SYSTEM_PROMPT_GUARDRAIL


logger = logging.getLogger(__name__)


class SemanticInputGuardrailMiddleware(AgentMiddleware):
    """Classify the latest user input before allowing the agent to run."""

    def __init__(self, classifier: Runnable[Any, GuardrailDecision]) -> None:
        super().__init__()
        self.classifier = classifier

    @hook_config(can_jump_to=["end"])
    def before_agent(self, state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
        current_message = next(
            (
                message
                for message in reversed(state["messages"])
                if isinstance(message, HumanMessage)
            ),
            None,
        )

        if current_message is None:
            return None

        try:
            decision = self.classifier.invoke(
                [
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT_GUARDRAIL,
                    },
                    {
                        "role": "user",
                        "content": current_message.content,
                    },
                ]
            )
        except Exception:
            logger.exception(
                "Falha ao validar a entrada no guardrail",
                extra={"component": "semantic_input_guardrail"},
            )
            return self._blocked_response(
                "Não foi possível validar sua solicitação agora. "
                "Tente novamente em alguns instantes."
            )

        if decision.decision == "allow":
            return None

        if decision.decision == "review":
            return self._blocked_response(
                "Não consegui validar essa solicitação com segurança. "
                "Reformule-a dentro do contexto financeiro."
            )

        return self._blocked_response("Não posso executar essa solicitação.")

    @staticmethod
    def _blocked_response(content: str) -> dict[str, Any]:
        return {
            "messages": [
                {
                    "role": "assistant",
                    "content": content,
                }
            ],
            "jump_to": "end",
        }
