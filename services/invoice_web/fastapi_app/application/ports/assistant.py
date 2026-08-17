from __future__ import annotations

from typing import Any, Protocol


class AssistantPort(Protocol):
    def chat(self, thread_id: str, message: str) -> dict[str, Any]: ...

    def decide(self, thread_id: str, interrupt_id: str, decision: str) -> dict[str, Any]: ...
