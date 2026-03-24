"""
ws_router.py — Alita WebSocket response routing utilities.

Re-exports the core functions from engines.llm_engine for convenience,
as the ALITA Master Prompt integration guide expects them here.

Usage:
    from routers.ws_router import parse_alita_response, build_alita_context
"""

# Re-export from the canonical location (engines/llm_engine.py)
from engines.llm_engine import (  # type: ignore[import]
    parse_alita_response,
    build_alita_context,
    load_alita_prompt,
    ALITA_SYSTEM,
)

__all__ = [
    "parse_alita_response",
    "build_alita_context",
    "load_alita_prompt",
    "ALITA_SYSTEM",
]
