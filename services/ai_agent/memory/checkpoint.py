import atexit
import os
from contextlib import ExitStack
from functools import lru_cache
from urllib.parse import quote_plus
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.postgres import PostgresSaver


_checkpointer_resources = ExitStack()
atexit.register(_checkpointer_resources.close)


def _postgres_connection_string() -> str:
    """Build the checkpointer DSN from the application database settings."""
    configured_dsn = os.environ.get("POSTGRES_CHECKPOINT_DSN")
    if configured_dsn:
        return configured_dsn

    user = quote_plus(os.environ.get("POSTGRES_USER", "postgres"))
    password = quote_plus(os.environ.get("POSTGRES_PASSWORD", "postgres"))
    host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
    port = os.environ.get("POSTGRES_PORT", "5432")
    database = quote_plus(os.environ.get("POSTGRES_DB", "controle_financas"))
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


@lru_cache(maxsize=1)
def get_checkpointer() -> PostgresSaver:
    """Return the process-wide persistent PostgreSQL checkpointer."""
    checkpointer = _checkpointer_resources.enter_context(
        PostgresSaver.from_conn_string(_postgres_connection_string())
    )
    checkpointer.setup()
    return checkpointer


def create_thread_id() -> str:
    """Create an identifier for a new conversation thread."""
    return str(uuid4())


def create_thread_config(thread_id: str | None = None) -> RunnableConfig:
    """Build the LangGraph configuration used to load and save a thread."""
    return {
        "configurable": {
            "thread_id": thread_id or create_thread_id(),
        }
    }
