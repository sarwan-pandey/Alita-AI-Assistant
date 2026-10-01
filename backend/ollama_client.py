"""
Ollama Client — Centralized local LLM client for Alita.

Replaces all cloud LLM providers (Groq, DeepSeek, NVIDIA, Gemini) with a
single local Qwen3 4B Q4 model running via Ollama.

Uses the native Ollama API (/api/chat) with thinking mode support,
and the OpenAI-compatible API for streaming.

Usage:
    from ollama_client import ollama_chat, get_client

    # Simple one-liner:
    response = ollama_chat("What is the capital of France?")

    # With full control:
    client = get_client()
    resp = client.chat.completions.create(
        model="qwen3:4b-instruct",
        messages=[{"role": "user", "content": "Hello"}],
    )
"""

import os
import re
import json
import logging
import threading
from typing import Optional

log = logging.getLogger("alita.ollama")

# ── Configuration ────────────────────────────────────────────────────────────
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_NATIVE_URL: str = OLLAMA_BASE_URL.replace("/v1", "")  # http://localhost:11434
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct")

# ── Performance tuning (Optimized for 4GB VRAM + 16GB RAM) ───────────────────
# num_ctx: Context window size. 4096 for Qwen3 4B Q4.
OLLAMA_NUM_CTX: int = int(os.getenv("OLLAMA_NUM_CTX", "4096"))
# keep_alive: How long to keep model loaded in VRAM after last request.
#             -1 (int) = indefinitely in VRAM. Eliminates cold-start reload permanently (saves 8+s).
OLLAMA_KEEP_ALIVE_RAW: str = os.getenv("OLLAMA_KEEP_ALIVE", "-1")
try:
    OLLAMA_KEEP_ALIVE = int(OLLAMA_KEEP_ALIVE_RAW)
except ValueError:
    OLLAMA_KEEP_ALIVE = OLLAMA_KEEP_ALIVE_RAW
# repeat_penalty: Penalizes repeated tokens. 1.1 = mild, prevents loops.
OLLAMA_REPEAT_PENALTY: float = float(os.getenv("OLLAMA_REPEAT_PENALTY", "1.1"))

# ── Singleton clients ───────────────────────────────────────────────────────
_client = None
_client_lock = threading.Lock()
_http_client = None
_http_lock = threading.Lock()


def _get_http_client():
    """Get or create a shared httpx client for the native Ollama API."""
    global _http_client
    if _http_client is not None:
        return _http_client
    with _http_lock:
        if _http_client is not None:
            return _http_client
        try:
            import httpx
            _http_client = httpx.Client(
                base_url=OLLAMA_NATIVE_URL,
                timeout=120.0,  # CPU-mode cold start + long prompts can take >30s
            )
            log.info("Ollama HTTP client initialized -> %s", OLLAMA_NATIVE_URL)
            return _http_client
        except ImportError:
            log.error("'httpx' package not installed")
            return None


def get_client():
    """
    Get or create the shared OpenAI-compatible client for Ollama.
    Used primarily for streaming responses.
    Returns None if the openai package is not installed.
    """
    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is not None:
            return _client
        try:
            from openai import OpenAI  # type: ignore[import-untyped]
            _client = OpenAI(
                api_key="ollama",  # Ollama doesn't need a real key
                base_url=OLLAMA_BASE_URL,
                timeout=120.0,  # CPU-mode cold start + long prompts can take >30s
            )
            log.info("Ollama OpenAI client initialized -> %s (model: %s)", OLLAMA_BASE_URL, OLLAMA_MODEL)
            return _client
        except ImportError:
            log.error("'openai' package not installed — cannot create Ollama client")
            return None


def ollama_chat(
    prompt: str,
    system: str = "",
    messages: Optional[list] = None,
    model: str = "",
    max_tokens: int = 150,
    temperature: float = 0.7,
    stream: bool = False,
    think: bool = False,
) -> Optional[str]:
    """
    One-liner LLM call via Ollama native API.

    Uses /api/chat with think=false by default to disable Qwen3's internal reasoning mode for speed.
    For streaming, falls back to the OpenAI-compatible API.

    Args:
        prompt: User message (ignored if `messages` is provided)
        system: Optional system prompt
        messages: Full messages list (overrides prompt/system if provided)
        model: Model name (default: OLLAMA_MODEL from env)
        max_tokens: Maximum response tokens
        temperature: Creativity (0.0 = deterministic, 1.0 = creative)
        stream: If True, returns a generator of tokens via OpenAI API
        think: If True, enables extended chain-of-thought reasoning (slower)

    Returns:
        Response text string, or None on failure.
        If stream=True, returns the streaming response object instead.
    """
    model = model or OLLAMA_MODEL

    # Build messages if not provided
    if messages is None:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

    # ── Streaming: use OpenAI-compatible API ──────────────────────────────
    if stream:
        client = get_client()
        if not client:
            return None
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
                extra_body={
                    "keep_alive": OLLAMA_KEEP_ALIVE,
                    "options": {
                        "num_ctx": OLLAMA_NUM_CTX,
                        "repeat_penalty": OLLAMA_REPEAT_PENALTY,
                    }
                }
            )
            return resp  # type: ignore[return-value]
        except Exception as e:
            log.warning("Ollama stream failed: %s", e)
            return None

    # ── Non-streaming: use native Ollama API ─────────────────────────────
    http = _get_http_client()
    if not http:
        return None

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {
            "num_predict": max(max_tokens, 768) if think else max_tokens,
            "temperature": temperature,
            "num_ctx": OLLAMA_NUM_CTX,
            "repeat_penalty": OLLAMA_REPEAT_PENALTY,
        },
    }
    if not think:
        payload["think"] = False

    try:
        resp = http.post("/api/chat", json=payload)
        resp.raise_for_status()
        data = resp.json()

        text = data.get("message", {}).get("content", "")
        if text:
            # Strip any inline <think> tags if model emitted them inside content
            clean_text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.DOTALL).strip()
            if clean_text:
                log.debug("Ollama response: %d chars (model=%s)", len(clean_text), model)
                return clean_text

        # If content is empty (e.g. model was still reasoning or token limit was reached),
        # NEVER return thinking tokens as spoken output!
        thinking = data.get("message", {}).get("thinking", "")
        if thinking:
            log.warning("Ollama returned thinking (%d chars) but empty content — suppressing thoughts.",
                        len(thinking))
            return None

        log.warning("Ollama returned empty content: %s", json.dumps(data)[:200])
        return None

    except Exception as e:
        log.warning("Ollama chat failed: %s", e)
        return None


def ollama_chat_messages(
    messages: list,
    model: str = "",
    max_tokens: int = 300,
    temperature: float = 0.7,
) -> Optional[str]:
    """
    LLM call with full messages list (system + history + user).
    Convenience wrapper for handlers that build their own messages.
    """
    return ollama_chat(
        prompt="",
        messages=messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )


def is_ollama_running() -> bool:
    """Check if Ollama server is reachable."""
    try:
        http = _get_http_client()
        if http:
            resp = http.get("/api/tags")
            return resp.status_code == 200
    except Exception:
        pass
    # Fallback with urllib
    try:
        import urllib.request
        url = f"{OLLAMA_NATIVE_URL}/api/tags"
        req = urllib.request.urlopen(url, timeout=3)
        return req.status == 200
    except Exception:
        return False


def get_model_name() -> str:
    """Return the configured Ollama model name."""
    return OLLAMA_MODEL
