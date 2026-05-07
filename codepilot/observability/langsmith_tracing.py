"""LangSmith tracing activation. Sets LangChain env vars; no-op when key absent."""
from __future__ import annotations

import os


def configure_langsmith(api_key: str, project: str = "codepilot") -> None:
    """Activate LangSmith tracing by exporting the required env vars."""
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = api_key
    os.environ["LANGCHAIN_PROJECT"] = project
    os.environ["LANGSMITH_API_KEY"] = api_key


def is_configured() -> bool:
    return os.environ.get("LANGCHAIN_TRACING_V2") == "true" and bool(
        os.environ.get("LANGCHAIN_API_KEY")
    )
