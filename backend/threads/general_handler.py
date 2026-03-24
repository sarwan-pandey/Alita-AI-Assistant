"""
Thread 1: General Handler — Casual conversation, Q&A, knowledge.

Smart routing with CONCURRENT failover:
  - Medical/health queries → DeepSeek first (accuracy) → [Groq+NVIDIA race] → Gemini
  - Everything else        → [Groq+NVIDIA race] (fastest wins) → DeepSeek → Gemini

Speed optimizations:
  - Concurrent provider racing — Groq + NVIDIA run simultaneously
  - Strict HTTP timeouts (8-10s) — fail fast, don't hang
  - Shared message builder — zero redundant formatting
"""

import re
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

log = logging.getLogger("alita.general")

# ── Shared thread pool — reuse across calls (avoids pool creation overhead) ──
_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="llm")

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

def _build_messages(system_prompt: str, history: list, user_text: str) -> list[dict]:
    """Build the messages list once — shared by all providers."""
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        messages.append({
            "role": msg["role"] if msg["role"] in ("user", "assistant") else "assistant",
            "content": msg["content"],
        })
    messages.append({"role": "user", "content": user_text})
    return messages


# ─────────────────────────────────────────────────────────────────────────────
# PROVIDER FUNCTIONS — each has strict timeouts
# ─────────────────────────────────────────────────────────────────────────────

def _try_deepseek(user_text: str, session, settings, system_prompt: str,
                  history: list, max_tokens: int,
                  cancel_event: threading.Event | None = None) -> str | None:
    """
    Try DeepSeek API for high-accuracy responses.
    DeepSeek-V3 is excellent for medical, scientific, and knowledge-heavy queries.
    Uses OpenAI-compatible API format. Timeout: 10s.
    """
    if not settings.deepseek_api_key:
        return None
    if cancel_event and cancel_event.is_set():
        log.info("[%s] DeepSeek skipped — cancel_event set (barge-in)", session.session_id)
        return None

    messages = _build_messages(system_prompt, history, user_text)

    try:
        from openai import OpenAI  # type: ignore[import-untyped]
    except ModuleNotFoundError:
        # Fall back to raw HTTP if openai package not installed
        try:
            import httpx  # type: ignore[import-untyped]
            import json as _json

            resp = httpx.post(
                "https://api.deepseek.com/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.deepseek_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.deepseek_model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": settings.llm_temperature,
                },
                timeout=10.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                text = data["choices"][0]["message"]["content"]
                if text:
                    log.info("[%s] DeepSeek response (httpx): %d chars", session.session_id, len(text))
                    return text
            else:
                log.warning("[%s] DeepSeek HTTP %d: %s", session.session_id, resp.status_code, resp.text[:200])
                return None
        except Exception as e:
            log.warning("[%s] DeepSeek httpx failed: %s", session.session_id, e)
            return None

    # Use openai SDK (preferred path) — 10s timeout
    try:
        client = OpenAI(
            api_key=settings.deepseek_api_key,
            base_url="https://api.deepseek.com",
            timeout=10.0,
        )

        resp = client.chat.completions.create(
            model=settings.deepseek_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=settings.llm_temperature,
        )
        text = resp.choices[0].message.content
        if text:
            log.info("[%s] DeepSeek response: %d chars", session.session_id, len(text))
            return text
    except Exception as e:
        log.warning("[%s] DeepSeek failed: %s", session.session_id, e)

    return None


def _try_nvidia(user_text: str, session, settings, system_prompt: str,
                history: list, max_tokens: int,
                cancel_event: threading.Event | None = None) -> str | None:
    """
    Try NVIDIA Build API (Nemotron 3 Super 120B).
    Uses OpenAI-compatible endpoint. Timeout: 10s.
    """
    if not settings.nvidia_api_key:
        return None
    if cancel_event and cancel_event.is_set():
        log.info("[%s] NVIDIA skipped — cancel_event set (barge-in)", session.session_id)
        return None

    try:
        from openai import OpenAI  # type: ignore[import-untyped]
    except ModuleNotFoundError:
        log.warning("[%s] 'openai' package not installed for NVIDIA", session.session_id)
        return None

    try:
        client = OpenAI(
            api_key=settings.nvidia_api_key,
            base_url="https://integrate.api.nvidia.com/v1",
            timeout=10.0,
        )

        messages = _build_messages(system_prompt, history, user_text)

        resp = client.chat.completions.create(
            model=settings.nvidia_model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=settings.llm_temperature,
            top_p=0.95,
        )
        text = resp.choices[0].message.content
        if text:
            log.info("[%s] NVIDIA Nemotron response: %d chars", session.session_id, len(text))
            return text
    except Exception as e:
        log.warning("[%s] NVIDIA Nemotron failed: %s", session.session_id, e)

    return None


def _try_groq(user_text: str, session, settings, system_prompt: str,
              history: list, max_tokens: int,
              cancel_event: threading.Event | None = None) -> str | None:
    """Try Groq with all keys rotated. Timeout: 8s (fastest provider). Returns response text or None."""
    if cancel_event and cancel_event.is_set():
        log.info("[%s] Groq skipped — cancel_event set (barge-in)", session.session_id)
        return None
    try:
        from groq_pool import get_rotator as _get_groq_rotator  # type: ignore[import]
        rotator = _get_groq_rotator()
        num_groq_keys = len(rotator.keys)

        for attempt in range(num_groq_keys):
            _groq_key = rotator.get_key()
            if not _groq_key:
                continue
            try:
                from groq import Groq  # type: ignore[import-untyped]
                client = Groq(api_key=_groq_key, timeout=8.0)

                messages = _build_messages(system_prompt, history, user_text)

                resp = client.chat.completions.create(
                    model=settings.groq_model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=settings.llm_temperature,
                )
                text = resp.choices[0].message.content
                if text:
                    log.info("[%s] Groq response: %d chars (key #%d)", session.session_id, len(text), attempt + 1)
                    return text
            except ModuleNotFoundError as e:
                log.critical("[%s] 'groq' package not installed! (%s)", session.session_id, e)
                break
            except Exception as e:
                exc_str = str(e)
                if "rate_limit" in exc_str.lower() or "429" in exc_str:
                    rotator.mark_rate_limited(_groq_key, 15)
                    log.warning("[%s] Groq key #%d rate-limited (%d/%d)",
                               session.session_id, attempt + 1, attempt + 1, num_groq_keys)
                    continue
                log.warning("[%s] Groq failed: %s", session.session_id, e)
                break
    except ModuleNotFoundError as e:
        log.critical("[%s] 'groq_pool' module not found! (%s)", session.session_id, e)
    except Exception as e:
        log.warning("[%s] Groq setup error: %s", session.session_id, e)

    return None


def _try_gemini(user_text: str, session, settings, system_prompt: str,
                history: list, max_tokens: int,
                cancel_event: threading.Event | None = None) -> str | None:
    """Try Gemini with all keys rotated. Timeout: 12s. Returns response text or None."""
    if cancel_event and cancel_event.is_set():
        log.info("[%s] Gemini skipped — cancel_event set (barge-in)", session.session_id)
        return None
    all_keys = settings.get_all_gemini_keys()
    if not all_keys:
        return None

    try:
        import google.generativeai as genai  # type: ignore[import-untyped]
        from main import key_rotator  # type: ignore[import]
    except ModuleNotFoundError as e:
        log.critical("[%s] 'google-generativeai' not installed! (%s)", session.session_id, e)
        return None

    for _attempt in range(len(all_keys)):
        _gemini_key = key_rotator.get_key()
        try:
            genai.configure(api_key=_gemini_key)
            model = genai.GenerativeModel(
                model_name=settings.gemini_model,
                system_instruction=system_prompt,
                generation_config=genai.GenerationConfig(
                    max_output_tokens=max_tokens,
                    temperature=settings.llm_temperature,
                ),
            )
            gemini_history = []
            for msg in history:
                role = "user" if msg["role"] == "user" else "model"
                gemini_history.append({"role": role, "parts": [msg["content"]]})

            chat = model.start_chat(history=gemini_history)
            response = chat.send_message(
                user_text,
                request_options={"timeout": 12},
            )

            if response.text:
                log.info("[%s] Gemini response: %d chars (key #%d)", session.session_id, len(response.text), _attempt + 1)
                return response.text
        except Exception as e:
            exc_str = str(e)
            if "rate_limit" in exc_str.lower() or "429" in exc_str or "quota" in exc_str.lower() or "resource" in exc_str.lower():
                key_rotator.mark_rate_limited(_gemini_key, 60)
                log.warning("[%s] Gemini key #%d rate-limited (%d/%d)",
                           session.session_id, _attempt + 1, _attempt + 1, len(all_keys))
                continue
            log.warning("[%s] Gemini failed: %s", session.session_id, e)
            break

    return None


# ─────────────────────────────────────────────────────────────────────────────
# CONCURRENT PROVIDER RACING — try multiple providers simultaneously
# ─────────────────────────────────────────────────────────────────────────────

def _race_providers(providers: list, user_text: str, session, settings,
                    system_prompt: str, history: list, max_tokens: int,
                    race_timeout: float = 12.0,
                    cancel_event: threading.Event | None = None) -> str | None:
    """
    Run multiple LLM providers CONCURRENTLY — return the first successful response.
    Supports instant abort via cancel_event (set on barge-in).
    """
    if not providers:
        return None
    if cancel_event and cancel_event.is_set():
        log.info("[%s] Race aborted — cancel_event set (barge-in)", session.session_id)
        return None

    # Single provider — no need for threading overhead
    if len(providers) == 1:
        return providers[0](user_text, session, settings, system_prompt, history, max_tokens,
                           cancel_event=cancel_event)

    futures = {}
    for provider_fn in providers:
        future = _executor.submit(
            provider_fn, user_text, session, settings, system_prompt, history, max_tokens,
            cancel_event
        )
        futures[future] = provider_fn.__name__

    try:
        for future in as_completed(futures, timeout=race_timeout):
            # Check cancel_event between results — abort instantly on barge-in
            if cancel_event and cancel_event.is_set():  # type: ignore[union-attr]
                for f in futures:  # type: ignore[assignment]
                    if not f.done():  # type: ignore[union-attr]
                        f.cancel()  # type: ignore[union-attr]
                log.info("[%s] Race aborted mid-flight — barge-in cancel", session.session_id)
                return None
            provider_name = futures[future]
            try:
                result = future.result()
                if result:
                    # Cancel remaining futures — we have a winner
                    for f in futures:  # type: ignore[assignment]
                        if f != future and not f.done():  # type: ignore[union-attr]
                            f.cancel()  # type: ignore[union-attr]
                    log.info("[%s] 🏆 Race winner: %s", session.session_id, provider_name)
                    return result
            except Exception as e:
                log.warning("[%s] Race: %s failed: %s", session.session_id, provider_name, e)
    except TimeoutError:
        log.warning("[%s] Race: all providers timed out after %.1fs", session.session_id, race_timeout)
        # Cancel all remaining futures
        for f in futures:  # type: ignore[assignment]
            if not f.done():  # type: ignore[union-attr]
                f.cancel()  # type: ignore[union-attr]

    return None


# ─────────────────────────────────────────────────────────────────────────────
# MAIN HANDLER — Smart routing with concurrent fallback
# ─────────────────────────────────────────────────────────────────────────────

def handle_general(user_text: str, session, settings, system_prompt: str,
                   history: list, max_tokens: int, response_cache,
                   cancel_event: threading.Event | None = None) -> list[str]:
    """
    Handle general conversation queries with SMART ROUTING + CONCURRENT FALLBACK.
    Supports instant abort via cancel_event (set on barge-in).
    """
    t_start = time.perf_counter()

    # ── Check cache (instant — 0ms) ──────────────────────────────────────
    cached = response_cache.get(user_text)
    if cached:
        log.info("[%s] Cache HIT for general query (0ms)", session.session_id)
        return [cached]

    # ── Smart routing: detect medical queries ─────────────────────────────
    is_medical = _is_medical_query(user_text)
    log.info("[%s] handle_general | medical=%s | query='%s'",
             session.session_id, is_medical, user_text[:60])  # type: ignore[index]

    if is_medical:
        # MEDICAL QUERY → DeepSeek first (accuracy), then [Groq+NVIDIA race], then Gemini
        log.info("[%s] 🏥 Medical query → DeepSeek first", session.session_id)

        result = _try_deepseek(user_text, session, settings, system_prompt, history, max_tokens,
                               cancel_event=cancel_event)
        if result:
            response_cache.put(user_text, result)
            log.info("[%s] ✅ Response in %.1fs (DeepSeek)", session.session_id, time.perf_counter() - t_start)
            return [result]

        # DeepSeek failed → race Groq + NVIDIA simultaneously
        log.info("[%s] DeepSeek failed → racing Groq+NVIDIA", session.session_id)
        result = _race_providers(
            [_try_groq, _try_nvidia],
            user_text, session, settings, system_prompt, history, max_tokens,
            cancel_event=cancel_event
        )
        if result:
            response_cache.put(user_text, result)
            log.info("[%s] ✅ Response in %.1fs (race winner)", session.session_id, time.perf_counter() - t_start)
            return [result]

    else:
        # CASUAL QUERY → Race Groq + NVIDIA simultaneously (fastest wins!)
        log.info("[%s] 💬 Casual query → racing Groq+NVIDIA", session.session_id)

        result = _race_providers(
            [_try_groq, _try_nvidia],
            user_text, session, settings, system_prompt, history, max_tokens,
            cancel_event=cancel_event
        )
        if result:
            response_cache.put(user_text, result)
            log.info("[%s] ✅ Response in %.1fs (race winner)", session.session_id, time.perf_counter() - t_start)
            return [result]

        # Race failed → try DeepSeek
        log.info("[%s] Race failed → trying DeepSeek", session.session_id)
        result = _try_deepseek(user_text, session, settings, system_prompt, history, max_tokens,
                               cancel_event=cancel_event)
        if result:
            response_cache.put(user_text, result)
            log.info("[%s] ✅ Response in %.1fs (DeepSeek)", session.session_id, time.perf_counter() - t_start)
            return [result]

    # ── Last resort: Gemini ───────────────────────────────────────────────
    log.info("[%s] All fast providers failed → Gemini (last resort)", session.session_id)
    result = _try_gemini(user_text, session, settings, system_prompt, history, max_tokens,
                         cancel_event=cancel_event)
    if result:
        response_cache.put(user_text, result)
        log.info("[%s] ✅ Response in %.1fs (Gemini)", session.session_id, time.perf_counter() - t_start)
        return [result]

    elapsed = time.perf_counter() - t_start
    log.error("[%s] *** ALL LLM APIs EXHAUSTED *** (%.1fs elapsed)", session.session_id, elapsed)
    return ["Sorry, I'm having trouble connecting right now. Please try again in a moment!"]


# ─────────────────────────────────────────────────────────────────────────────
# STREAMING VARIANT — true token-by-token delivery via queue.Queue
# ─────────────────────────────────────────────────────────────────────────────

import queue


def _try_groq_stream(user_text: str, session, settings, system_prompt: str,
                     history: list, max_tokens: int, token_queue: queue.Queue,
                     cancel_event: threading.Event | None = None) -> bool:
    """
    Stream Groq response token-by-token into token_queue.
    Returns True if successful (tokens were streamed), False otherwise.
    Puts None sentinel when done.
    """
    if cancel_event and cancel_event.is_set():
        return False
    try:
        from groq_pool import get_rotator as _get_groq_rotator  # type: ignore[import]
        rotator = _get_groq_rotator()
        num_keys = len(rotator.keys)

        for attempt in range(num_keys):
            _key = rotator.get_key()
            if not _key:
                continue
            try:
                from groq import Groq  # type: ignore[import-untyped]
                client = Groq(api_key=_key, timeout=8.0)
                messages = _build_messages(system_prompt, history, user_text)

                stream = client.chat.completions.create(
                    model=settings.groq_model,
                    messages=messages,
                    max_tokens=max_tokens,
                    temperature=settings.llm_temperature,
                    stream=True,
                )

                token_count = 0
                for chunk in stream:
                    if cancel_event and cancel_event.is_set():  # type: ignore[union-attr]
                        log.info("[%s] Groq stream aborted (barge-in) after %d tokens",
                                 session.session_id, token_count)
                        token_queue.put(None)
                        return True  # partial stream is fine
                    delta = chunk.choices[0].delta
                    if delta and delta.content:
                        token_queue.put(delta.content)
                        token_count += 1  # type: ignore[operator]

                if token_count > 0:
                    token_queue.put(None)  # sentinel: stream complete
                    log.info("[%s] Groq streamed %d tokens (key #%d)",
                             session.session_id, token_count, attempt + 1)
                    return True
            except ModuleNotFoundError:
                log.critical("[%s] 'groq' package not installed!", session.session_id)
                break
            except Exception as e:
                exc_str = str(e)
                if "rate_limit" in exc_str.lower() or "429" in exc_str:
                    rotator.mark_rate_limited(_key, 15)
                    log.warning("[%s] Groq stream key #%d rate-limited",
                                session.session_id, attempt + 1)
                    continue
                log.warning("[%s] Groq stream failed: %s", session.session_id, e)
                break
    except Exception as e:
        log.warning("[%s] Groq stream setup error: %s", session.session_id, e)

    return False


def handle_general_stream(user_text: str, session, settings, system_prompt: str,
                          history: list, max_tokens: int, response_cache,
                          token_queue: queue.Queue,
                          cancel_event: threading.Event | None = None) -> None:
    """
    Streaming variant of handle_general.
    Puts tokens into token_queue as they arrive from the LLM.
    Falls back to batch providers if Groq streaming fails.
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

    # ── Try Groq streaming first (fastest provider) ───────────────────────
    is_medical = _is_medical_query(user_text)

    if is_medical:
        # Medical: try DeepSeek first (accuracy), then stream Groq
        result = _try_deepseek(user_text, session, settings, system_prompt,
                               history, max_tokens, cancel_event=cancel_event)
        if result:
            response_cache.put(user_text, result)
            token_queue.put(result)
            token_queue.put(None)
            log.info("[%s] Medical → DeepSeek batch (%.1fs)",
                     session.session_id, time.perf_counter() - t_start)
            return

    # ── Groq streaming (primary path for speed) ──────────────────────────
    log.info("[%s] 🔥 Trying Groq streaming...", session.session_id)
    if _try_groq_stream(user_text, session, settings, system_prompt,
                        history, max_tokens, token_queue,
                        cancel_event=cancel_event):
        log.info("[%s] ✅ Groq stream completed in %.1fs",
                 session.session_id, time.perf_counter() - t_start)
        return

    # ── Groq streaming failed → batch fallback (NVIDIA, DeepSeek, Gemini) ─
    log.info("[%s] Groq stream failed → batch fallback", session.session_id)
    result = _race_providers(
        [_try_nvidia] + ([_try_deepseek] if not is_medical else []),
        user_text, session, settings, system_prompt, history, max_tokens,
        cancel_event=cancel_event
    )
    if not result:
        result = _try_gemini(user_text, session, settings, system_prompt,
                             history, max_tokens, cancel_event=cancel_event)
    if not result:
        result = "Sorry, I'm having trouble connecting right now. Please try again!"

    response_cache.put(user_text, result)
    token_queue.put(result)
    token_queue.put(None)
    log.info("[%s] ✅ Batch fallback in %.1fs",
             session.session_id, time.perf_counter() - t_start)

