"""
Thread 1: General Handler — Casual conversation, Q&A, knowledge.

Uses local Ollama (Qwen3 4B Q4) for ALL queries — no cloud providers needed.

Features:
  - Single local LLM provider (Ollama) — zero API keys, zero rate limits
  - Response caching for repeated queries
  - Streaming support (token-by-token delivery)
  - Barge-in cancellation via cancel_event
"""

import re
import time
import logging
import threading
import queue

log = logging.getLogger("alita.general")


# ── Medical query detection ─────────────────────────────────────────────────
# Keywords that indicate health/medical questions (English + Hindi romanized)
_MEDICAL_PATTERN = re.compile(
    r'\b('
    # Symptoms
    r'headache|fever|cold|cough|pain|ache|sore|hurt|burn|bleed|bleeding|swollen|'
    r'vomit|nausea|dizzy|dizziness|rash|allergy|allergic|infection|wound|fracture|'
    r'sprain|cramp|diarrhea|constipation|acidity|gas|bloating|fatigue|weakness|'
    r'breathless|breathing|choking|unconscious|faint|seizure|chest\s*pain|'
    r'stomach|throat|muscle|joint|back\s*pain|migraine|insomnia|anxiety|stress|'
    r'blood\s*pressure|sugar|diabetes|asthma|dehydration|sunburn|bite|sting|'
    r'poisoning|overdose|stroke|heart\s*attack|concussion|hypothermia|heatstroke|'
    # Treatments & remedies
    r'remedy|remedies|home\s*remedy|treatment|medicine|tablet|syrup|ointment|'
    r'dosage|dose|first\s*aid|cure|heal|relief|soothe|paracetamol|crocin|'
    r'brufen|ibuprofen|aspirin|antacid|ors|bandage|ice\s*pack|'
    r'ayurvedic|ayurveda|herbal|turmeric|ginger|honey|tulsi|neem|aloe|'
    # Medical questions
    r'doctor|hospital|medical|health|healthy|nutrition|diet|vitamin|'
    r'pregnant|pregnancy|bp|bmi|calorie|exercise|workout|yoga|'
    r'immunity|immune|vaccine|symptom|diagnos|'
    # CPR / Emergency
    r'cpr|emergency|ambulance|108|112|'
    # Hindi medical terms (romanized)
    r'bukhar|dard|sir\s*dard|pet\s*dard|sardard|sardi|khasi|khansi|'
    r'ulti|chakkar|sujan|ghav|jalan|thakan|kamzori|'
    r'dawa|ilaj|upchar|upay|nuskha|gharelu|aushadhi|'
    r'doctor|aspatal|dawai|goli'
    r')\b',
    re.IGNORECASE
)


def _is_medical_query(text: str) -> bool:
    """Detect if the user query is health/medical related."""
    return bool(_MEDICAL_PATTERN.search(text))


# ─────────────────────────────────────────────────────────────────────────────
# SHARED MESSAGE BUILDER — zero redundant formatting
# ─────────────────────────────────────────────────────────────────────────────

def _inject_world_model(system_prompt: str) -> str:
    """Inject live dual-device (PC & Phone) awareness into LLM system prompt."""
    try:
        from engines.world_model import world_model
        reality_block = world_model.format_prompt_context()
        if reality_block:
            return system_prompt + "\n\n" + reality_block
    except Exception as exc:
        log.debug("[world_model] context injection skipped: %s", exc)
    return system_prompt


def _build_messages(system_prompt: str, history: list, user_text: str) -> list[dict]:
    """Build the messages list once — shared by all providers."""
    system_prompt = _inject_world_model(system_prompt)
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        messages.append({
            "role": msg["role"] if msg["role"] in ("user", "assistant") else "assistant",
            "content": msg["content"],
        })
    messages.append({"role": "user", "content": user_text})
    return messages


# ─────────────────────────────────────────────────────────────────────────────
# OLLAMA PROVIDER — local Qwen3 4B Q4 via Ollama
# ─────────────────────────────────────────────────────────────────────────────

# Personal memory trigger words — only queries referring to user context need ChromaDB
_MEMORY_PATTERN = re.compile(
    r'\b(my|mine|remember|recall|remind\s+me|favorite|favourite|prefer|preference|preferences|'
    r'where\s+do\s+i|who\s+am\s+i|what\s+did\s+i|told\s+you|earlier|last\s+time|'
    r'mera|meri|mere|mujhe|yaad\s+hai|yaad\s+rakho)\b',
    re.IGNORECASE
)

def _inject_memory(system_prompt: str, user_text: str, user_id: str) -> str:
    """Recall past memories from ChromaDB and inject them into system prompt.
    Skips ChromaDB embedding lookup entirely for generic questions (saves ~1,500ms)."""
    if not _MEMORY_PATTERN.search(user_text):
        return system_prompt

    try:
        from main import memory_recall  # type: ignore[import]
        memories = memory_recall(user_id, user_text, n_results=3)
        if memories:
            memory_block = "\n".join(f"• {m}" for m in memories if m.strip())
            if memory_block:
                system_prompt += (
                    "\n\n[PAST MEMORY — What you remember from previous conversations:]\n"
                    + memory_block
                )
                log.info("[memory] Injected %d memories for user=%s", len(memories), user_id[:8])
    except Exception as exc:
        log.debug("[memory] Recall skipped: %s", exc)
    return system_prompt


def _try_ollama(user_text: str, session, settings, system_prompt: str,
                history: list, max_tokens: int,
                cancel_event: threading.Event | None = None) -> str | None:
    """
    Try local Ollama model (Qwen3 4B Q4) — zero API cost, no rate limits.
    Uses the centralized ollama_client module.
    """
    if cancel_event and cancel_event.is_set():
        log.info("[%s] Ollama skipped — cancel_event set (barge-in)", session.session_id)
        return None

    try:
        from ollama_client import ollama_chat_messages, get_model_name  # type: ignore[import]
    except ImportError:
        log.error("[%s] ollama_client module not found!", session.session_id)
        return None

    # Inject cross-session memory into system prompt
    system_prompt = _inject_memory(system_prompt, user_text, session.user_id)

    messages = _build_messages(system_prompt, history, user_text)

    # Medical queries get a hint for extra accuracy
    if _is_medical_query(user_text):
        messages[0]["content"] += (
            "\n\nIMPORTANT: This appears to be a health/medical query. "
            "Be accurate, cite common medical knowledge, recommend seeing a doctor "
            "for serious concerns, and provide home remedies when safe."
        )

    try:
        text = ollama_chat_messages(
            messages=messages,
            model=getattr(settings, "ollama_model", "") or get_model_name(),
            max_tokens=max_tokens,
            temperature=getattr(settings, "llm_temperature", 0.7),
        )
        if text:
            log.info("[%s] Ollama response: %d chars (model=%s)",
                     session.session_id, len(text), get_model_name())
            return text
    except Exception as e:
        log.warning("[%s] Ollama failed: %s", session.session_id, e)

    return None


# ─────────────────────────────────────────────────────────────────────────────
# MAIN HANDLER — Simple and clean with local Ollama
# ─────────────────────────────────────────────────────────────────────────────

def handle_general(user_text: str, session, settings, system_prompt: str,
                   history: list, max_tokens: int, response_cache,
                   cancel_event: threading.Event | None = None) -> list[str]:
    """
    Handle general conversation queries using local Ollama (Qwen3-8B).
    Supports instant abort via cancel_event (set on barge-in).
    """
    t_start = time.perf_counter()

    # ── Check cache (instant — 0ms) ──────────────────────────────────────
    cached = response_cache.get(user_text)
    if cached:
        log.info("[%s] Cache HIT for general query (0ms)", session.session_id)
        return [cached]

    # ── Log query type ─────────────────────────────────────────────────────
    is_medical = _is_medical_query(user_text)
    log.info("[%s] handle_general | medical=%s | query='%s'",
             session.session_id, is_medical, user_text[:60])  # type: ignore[index]

    # ── Try Ollama (local) ────────────────────────────────────────────────
    result = _try_ollama(user_text, session, settings, system_prompt, history, max_tokens,
                         cancel_event=cancel_event)
    if result:
        response_cache.put(user_text, result)
        log.info("[%s] ✅ Response in %.1fs (Ollama local)",
                 session.session_id, time.perf_counter() - t_start)
        return [result]

    elapsed = time.perf_counter() - t_start
    log.error("[%s] *** Ollama FAILED *** (%.1fs elapsed) — is Ollama running?",
              session.session_id, elapsed)
    return ["Sorry, I'm having trouble connecting to the local model. "
            "Please make sure Ollama is running (ollama serve) and qwen3:8b is pulled."]


# ─────────────────────────────────────────────────────────────────────────────
# STREAMING VARIANT — true token-by-token delivery via queue.Queue
# ─────────────────────────────────────────────────────────────────────────────

def _try_ollama_stream(user_text: str, session, settings, system_prompt: str,
                       history: list, max_tokens: int, token_queue: queue.Queue,
                       cancel_event: threading.Event | None = None) -> bool:
    """
    Stream Ollama response token-by-token into token_queue.
    Uses the native Ollama API (/api/chat) to properly handle Qwen3's
    thinking mode — only real content tokens are forwarded.
    Returns True if successful (tokens were streamed), False otherwise.
    Puts None sentinel when done.
    """
    if cancel_event and cancel_event.is_set():
        return False

    try:
        import json as _json
        import httpx
        from ollama_client import (  # type: ignore[import]
            OLLAMA_NATIVE_URL, get_model_name,
            OLLAMA_NUM_CTX, OLLAMA_KEEP_ALIVE, OLLAMA_REPEAT_PENALTY,
        )
    except ImportError:
        log.error("[%s] Required modules not found!", session.session_id)
        return False

    try:
        # Inject cross-session memory into system prompt
        system_prompt = _inject_memory(system_prompt, user_text, session.user_id)

        messages = _build_messages(system_prompt, history, user_text)
        model = getattr(settings, "ollama_model", "") or get_model_name()

        payload = {
            "model": model,
            "messages": messages,
            "stream": True,
            "keep_alive": OLLAMA_KEEP_ALIVE,
            "options": {
                "num_predict": max(max_tokens, 768),
                "temperature": getattr(settings, "llm_temperature", 0.7),
                "num_ctx": OLLAMA_NUM_CTX,
                "repeat_penalty": OLLAMA_REPEAT_PENALTY,
            },
        }

        token_count = 0
        in_think_block = False
        with httpx.Client(timeout=60.0) as http:
            with http.stream("POST", f"{OLLAMA_NATIVE_URL}/api/chat", json=payload) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if cancel_event and cancel_event.is_set():
                        log.info("[%s] Ollama stream aborted (barge-in) after %d tokens",
                                 session.session_id, token_count)
                        token_queue.put(None)
                        return True  # partial stream is fine

                    if not line.strip():
                        continue

                    try:
                        data = _json.loads(line)
                    except _json.JSONDecodeError:
                        continue

                    # STRICT SUPPRESSION 1: Drop Ollama's separate thinking field completely.
                    # Never push reasoning thought tokens to token_queue or TTS.
                    if data.get("message", {}).get("thinking"):
                        continue

                    # STRICT SUPPRESSION 2: Drop and filter any inline <think> tags in content
                    content = data.get("message", {}).get("content", "")
                    if not content:
                        if data.get("done", False):
                            break
                        continue

                    if "<think>" in content:
                        in_think_block = True
                        if "</think>" in content:
                            content = content.split("</think>", 1)[1]
                            in_think_block = False
                        else:
                            content = ""
                    elif in_think_block:
                        if "</think>" in content:
                            content = content.split("</think>", 1)[1]
                            in_think_block = False
                        else:
                            content = ""

                    if content:
                        token_queue.put(content)
                        token_count += 1

                    # Check if done
                    if data.get("done", False):
                        break

        if token_count > 0:
            token_queue.put(None)  # sentinel: stream complete
            log.info("[%s] Ollama streamed %d tokens", session.session_id, token_count)
            return True

    except Exception as e:
        log.warning("[%s] Ollama stream failed: %s", session.session_id, e)

    return False


def handle_general_stream(user_text: str, session, settings, system_prompt: str,
                          history: list, max_tokens: int, response_cache,
                          token_queue: queue.Queue,
                          cancel_event: threading.Event | None = None) -> None:
    """
    Streaming variant of handle_general.
    Puts tokens into token_queue as they arrive from Ollama.
    Always puts None sentinel at the end.
    """
    t_start = time.perf_counter()

    # ── Cache check (instant) ─────────────────────────────────────────────
    cached = response_cache.get(user_text)
    if cached:
        log.info("[%s] Cache HIT for streaming query", session.session_id)
        token_queue.put(cached)
        token_queue.put(None)
        return

    # ── Try Ollama streaming (primary path) ───────────────────────────────
    log.info("[%s] 🔥 Trying Ollama streaming...", session.session_id)
    if _try_ollama_stream(user_text, session, settings, system_prompt,
                          history, max_tokens, token_queue,
                          cancel_event=cancel_event):
        log.info("[%s] ✅ Ollama stream completed in %.1fs",
                 session.session_id, time.perf_counter() - t_start)
        return

    # ── Streaming failed → batch fallback ─────────────────────────────────
    log.info("[%s] Ollama stream failed → trying batch", session.session_id)
    result = _try_ollama(user_text, session, settings, system_prompt,
                         history, max_tokens, cancel_event=cancel_event)
    if not result:
        result = ("Sorry, I'm having trouble connecting to the local model. "
                  "Please make sure Ollama is running (ollama serve).")

    response_cache.put(user_text, result)
    token_queue.put(result)
    token_queue.put(None)
    log.info("[%s] ✅ Batch fallback in %.1fs",
             session.session_id, time.perf_counter() - t_start)
