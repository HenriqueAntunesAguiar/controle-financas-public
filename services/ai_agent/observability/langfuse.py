"""Integracao opcional do Langfuse com os agentes LangChain."""

from __future__ import annotations

import os
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterator


def is_langfuse_enabled() -> bool:
    """Ativa tracing somente quando habilitado e com as duas chaves."""

    enabled = os.environ.get("LANGFUSE_ENABLED", "false").lower()
    return enabled in {"1", "true", "yes"} and all(
        os.environ.get(name)
        for name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
    )


@lru_cache(maxsize=1)
def _client():
    from langfuse import Langfuse

    return Langfuse()


@contextmanager
def observe_agent_run(*, session_id: str, user_id: str | None = None, trace_name: str = "financial-data-agent", tags: list[str] | None = None, metadata: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
    """Cria o trace raiz e devolve a configuracao usada no agent.invoke.

    CallbackHandler escuta os eventos do LangChain e envia as chamadas do
    agente, dos modelos e das ferramentas para o Langfuse.
    """

    if not is_langfuse_enabled():
        yield {}
        return

    from langfuse import propagate_attributes
    from langfuse.langchain import CallbackHandler

    client = _client()
    handler = CallbackHandler()
    selected_tags = ["langchain", "development", *(tags or [])]
    with client.start_as_current_observation(
        as_type="span",
        name=trace_name,
    ):
        with propagate_attributes(
            session_id=session_id,
            user_id=user_id,
            trace_name=trace_name,
            tags=selected_tags,
            metadata=metadata or {},
        ):
            yield {
                "callbacks": [handler],
                "run_name": trace_name,
            }


def check_langfuse_auth() -> bool:
    """Verifica as credenciais; deve ser usado somente durante a configuracao."""

    if not is_langfuse_enabled():
        return False
    return bool(_client().auth_check())


def flush_langfuse() -> None:
    """Envia os eventos pendentes antes de encerrar scripts curtos."""

    if is_langfuse_enabled():
        _client().flush()


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    if not is_langfuse_enabled():
        raise SystemExit(
            "Langfuse desativado ou sem LANGFUSE_PUBLIC_KEY/SECRET_KEY."
        )
    print("Autenticacao Langfuse OK" if check_langfuse_auth() else "Falha na autenticacao")
