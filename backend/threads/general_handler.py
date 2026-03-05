"""
Thread 1: General Handler — Casual conversation, Q&A, knowledge.
Uses Groq (primary) or Gemini (fallback) for LLM responses.
"""

import logging

log = logging.getLogger("alita.general")


def handle_general(user_text: str, session, settings, system_prompt: str,
                   history: list, max_tokens: int, response_cache) -> list[str]:
    """
    Handle general conversation queries.
    Groq first → Gemini fallback → error message.
    """

    # ── Check cache ───────────────────────────────────────────────────────
    cached = response_cache.get(user_text)
    if cached:
        log.info("[%s] Cache HIT for general query", session.session_id)
        return [cached]

    # ── Try Groq (primary) ────────────────────────────────────────────────
    from groq_pool import get_rotator as _get_groq_rotator
    _groq_key = _get_groq_rotator().get_key()
    if _groq_key:
        try:
            from groq import Groq
            client = Groq(api_key=_groq_key)

            messages = [{"role": "system", "content": system_prompt}]
            for msg in history:
                messages.append({
                    "role": msg["role"] if msg["role"] in ("user", "assistant") else "assistant",
                    "content": msg["content"],
                })
            messages.append({"role": "user", "content": user_text})

            resp = client.chat.completions.create(
                model=settings.groq_model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=settings.llm_temperature,
            )
            text = resp.choices[0].message.content
            if text:
                log.info("[%s] Groq general response: %d chars", session.session_id, len(text))
                response_cache.put(user_text, text)
                return [text]
        except Exception as e:
            exc_str = str(e)
            if "rate_limit" in exc_str.lower() or "429" in exc_str:
                _get_groq_rotator().mark_rate_limited(_groq_key, 60)
            log.warning("[%s] Groq failed: %s", session.session_id, e)

    # ── Try Gemini (fallback) ─────────────────────────────────────────────
    all_keys = settings.get_all_gemini_keys()
    if all_keys:
        import google.generativeai as genai
        from main import key_rotator

        # Retry with different keys on rate limit
        for _attempt in range(min(3, len(all_keys))):
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
                response = chat.send_message(user_text)

                if response.text:
                    log.info("[%s] Gemini general response: %d chars", session.session_id, len(response.text))
                    response_cache.put(user_text, response.text)
                    return [response.text]
            except Exception as e:
                exc_str = str(e)
                if "rate_limit" in exc_str.lower() or "429" in exc_str or "quota" in exc_str.lower() or "resource" in exc_str.lower():
                    key_rotator.mark_rate_limited(_gemini_key, 60)
                    log.warning("[%s] Gemini key rate-limited, trying next key (attempt %d)", session.session_id, _attempt + 1)
                    continue  # Try next key
                log.warning("[%s] Gemini also failed: %s", session.session_id, e)
                break  # Non-rate-limit error, don't retry

    return ["Sorry, I'm having trouble connecting right now. Please try again in a moment!"]
