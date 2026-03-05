"""
Thread 2: Realtime Handler — Time, weather, math, web search, news.
Uses live APIs and function calling for real-time data.
"""

import logging
import urllib.request
import json
from datetime import datetime

log = logging.getLogger("alita.realtime")


# ── Realtime Functions ────────────────────────────────────────────────────

def get_current_time(timezone: str = "Asia/Kolkata") -> dict:
    """Get the current date and time."""
    try:
        import pytz
        tz = pytz.timezone(timezone)
        now = datetime.now(tz)
    except Exception:
        now = datetime.now()
    return {
        "time": now.strftime("%I:%M %p"),
        "date": now.strftime("%A, %B %d, %Y"),
        "timezone": timezone,
    }


def do_math(expression: str) -> dict:
    """Evaluate a mathematical expression safely."""
    try:
        result = eval(expression, {"__builtins__": {}}, {
            "abs": abs, "round": round, "min": min, "max": max,
            "pow": pow, "sum": sum, "int": int, "float": float,
        })
        return {"expression": expression, "result": str(result)}
    except Exception as e:
        return {"expression": expression, "error": str(e)}


def get_weather(city: str) -> dict:
    """Get current weather for a city."""
    try:
        url = f"https://wttr.in/{city}?format=%C+%t+%h+%w"
        req = urllib.request.Request(url, headers={"User-Agent": "Alita/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read().decode("utf-8").strip()
        return {"city": city, "weather": data}
    except Exception:
        return {"city": city, "weather": "Could not fetch weather. Try again later."}


def web_search(query: str) -> dict:
    """Web search placeholder."""
    return {
        "query": query,
        "note": "I'll answer based on my knowledge. For real-time results, check Google.",
    }


import random

_MOTIVATIONAL_QUOTES = [
    "Every day is a fresh start. Make it count!",
    "You are capable of amazing things.",
    "Small steps every day lead to big results.",
    "Believe in yourself and all that you are.",
    "Today is your day to shine!",
    "The secret of getting ahead is getting started.",
    "You're doing better than you think.",
    "Every expert was once a beginner.",
    "Stay curious, stay hungry.",
    "Progress, not perfection.",
    "Your potential is limitless.",
    "One day or day one — you decide.",
]


def get_daily_briefing(city: str = "Delhi") -> dict:
    """Get a compound daily briefing: time + weather + motivational quote."""
    time_data = get_current_time()
    weather_data = get_weather(city)
    quote = random.choice(_MOTIVATIONAL_QUOTES)

    return {
        "type": "daily_briefing",
        "time": time_data["time"],
        "date": time_data["date"],
        "weather": weather_data["weather"],
        "city": city,
        "quote": quote,
    }


# ── Main Handler ──────────────────────────────────────────────────────────

def handle_realtime(user_text: str, session, settings, system_prompt: str,
                    history: list, max_tokens: int, response_cache) -> list[str]:
    """
    Handle realtime queries. Detects the specific function needed,
    calls it, then formats the response via LLM.
    """
    text_lower = user_text.lower()

    # ── Direct function detection ─────────────────────────────────────
    func_result = None

    # Daily Briefing ("good morning", "daily briefing", etc.)
    if any(kw in text_lower for kw in ["good morning", "daily briefing", "brief me",
                                        "start my day", "morning update", "suprabhat"]):
        import re
        city_match = re.search(r"(?:in|from|for)\s+(\w[\w\s]*)", text_lower)
        city = city_match.group(1).strip() if city_match else "Delhi"
        func_result = get_daily_briefing(city)

    # Time queries
    elif any(kw in text_lower for kw in ["time", "date", "day", "baje", "samay", "tarikh"]):
        timezone = "Asia/Kolkata"  # Default
        if "new york" in text_lower or "us" in text_lower:
            timezone = "US/Eastern"
        elif "london" in text_lower or "uk" in text_lower:
            timezone = "Europe/London"
        elif "tokyo" in text_lower or "japan" in text_lower:
            timezone = "Asia/Tokyo"
        func_result = get_current_time(timezone)

    # Weather queries
    elif any(kw in text_lower for kw in ["weather", "temperature", "mausam", "forecast"]):
        # Extract city name (simple approach)
        import re
        city_match = re.search(r"(?:weather|temperature|mausam|forecast)\s+(?:in|of|for)\s+(\w[\w\s]*)", text_lower)
        city = city_match.group(1).strip() if city_match else "Delhi"
        func_result = get_weather(city)

    # Math queries
    elif any(kw in text_lower for kw in ["calculate", "solve", "math"]) or \
         any(op in user_text for op in ["+", "-", "*", "/", "^"]):
        import re
        # Extract math expression
        expr_match = re.search(r"[\d\.\+\-\*\/\^\(\)\s]+", user_text)
        if expr_match:
            expr = expr_match.group(0).strip()
            func_result = do_math(expr)

    # ── Format response via LLM ───────────────────────────────────────
    if func_result:
        # Use LLM to format the raw data into a natural response
        format_prompt = f"""You are Alita, a smart voice assistant. 
Based on this data, give a natural, concise spoken response:
Data: {json.dumps(func_result)}
User asked: "{user_text}"
Respond naturally in 1-2 sentences:"""

        from groq_pool import get_rotator as _get_groq_rotator
        _groq_key = _get_groq_rotator().get_key()
        if _groq_key:
            try:
                from groq import Groq
                client = Groq(api_key=_groq_key)
                resp = client.chat.completions.create(
                    model=settings.groq_model,
                    messages=[{"role": "user", "content": format_prompt}],
                    max_tokens=100,
                    temperature=0.5,
                )
                text = resp.choices[0].message.content
                if text:
                    response_cache.put(user_text, text)
                    return [text]
            except Exception as e:
                exc_str = str(e)
                if "rate_limit" in exc_str.lower() or "429" in exc_str:
                    _get_groq_rotator().mark_rate_limited(_groq_key, 60)
                log.warning("LLM format failed: %s", e)

        # Fallback: return raw data
        return [str(func_result)]

    # ── No specific function matched — handle as general with realtime context ─
    from threads.general_handler import handle_general
    return handle_general(user_text, session, settings, system_prompt, history, max_tokens, response_cache)
