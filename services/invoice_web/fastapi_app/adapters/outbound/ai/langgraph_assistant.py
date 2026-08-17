"""Adaptador que conecta a aplicacao web ao AI Manager LangGraph."""

from __future__ import annotations

import sys
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi_app.domain import ImportUnavailableError


AI_AGENT_ROOT = Path(__file__).resolve().parents[5] / "ai_agent"


class LangGraphAssistant:
    """Mantem uma unica instancia do AI Manager e persiste conversas por thread."""

    def __init__(self):
        self._agent: Any | None = None
        self._lock = Lock()

    def chat(self, thread_id: str, message: str) -> dict[str, Any]:
        return self._invoke(thread_id, {"messages": [{"role": "user", "content": message}]}, "chat")

    def decide(self, thread_id: str, interrupt_id: str, decision: str) -> dict[str, Any]:
        self._ensure_ai_agent_path()
        from langgraph.types import Command

        review: dict[str, str] = {"type": decision}
        if decision == "reject":
            review["message"] = "Operacao rejeitada pelo usuario."
        command = Command(resume={interrupt_id: {"decisions": [review]}})
        return self._invoke(thread_id, command, "approval")

    def _invoke(self, thread_id: str, agent_input: Any, entrypoint: str) -> dict[str, Any]:
        try:
            self._ensure_ai_agent_path()
            from memory import create_thread_config
            from observability import observe_agent_run

            with observe_agent_run(session_id=thread_id, trace_name="ai-manager", metadata={"entrypoint": f"web_{entrypoint}"}) as config:
                config.update(create_thread_config(thread_id))
                result = self._get_agent().invoke(agent_input, config=config)
            return self._serialize_result(thread_id, result)
        except ImportUnavailableError:
            raise
        except Exception as error:
            raise ImportUnavailableError("O assistente financeiro esta temporariamente indisponivel.") from error

    def _get_agent(self) -> Any:
        if self._agent is not None:
            return self._agent
        with self._lock:
            if self._agent is None:
                self._ensure_ai_agent_path()
                from ai_manager import create_ai_manager_agent

                self._agent = create_ai_manager_agent()
        return self._agent

    @staticmethod
    def _ensure_ai_agent_path() -> None:
        path = str(AI_AGENT_ROOT)
        if path not in sys.path:
            sys.path.insert(0, path)
        from dotenv import load_dotenv

        load_dotenv(AI_AGENT_ROOT / ".env")

    @classmethod
    def _serialize_result(cls, thread_id: str, result: dict[str, Any]) -> dict[str, Any]:
        interrupts = result.get("__interrupt__") or []
        if interrupts:
            interrupt = interrupts[0]
            value = interrupt.value if isinstance(interrupt.value, dict) else {}
            requests = value.get("action_requests") or []
            request = requests[0] if requests and isinstance(requests[0], dict) else {}
            description = str(request.get("description") or "Revise a operacao financeira antes de confirmar.")
            return {"thread_id": thread_id, "answer": "Confira os dados da operacao antes de confirmar.", "pending_approval": {"id": str(interrupt.id), "description": description}}

        messages = result.get("messages") or []
        content = getattr(messages[-1], "content", "") if messages else ""
        return {"thread_id": thread_id, "answer": cls._text_content(content), "pending_approval": None}

    @staticmethod
    def _text_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = [str(block.get("text", "")) for block in content if isinstance(block, dict) and block.get("type") == "text"]
            return "\n".join(part for part in parts if part)
        return str(content) if content is not None else ""
