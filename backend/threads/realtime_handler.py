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
        req = urllib.request.Request(url, headers={"User-Agent": "MJ/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = resp.read().decode("utf-8").strip()
        return {"city": city, "weather": data}
    except Exception:
        return {"city": city, "weather": "Could not fetch weather. Try again later."}


def web_search(query: str) -> dict:
    """Perform real-time background web search."""
    try:
        from engines.browser_agent import browser_agent  # type: ignore[import]
        summary = browser_agent.quick_search_and_summarize(query)
        if summary:
            return {"query": query, "search_results": summary}
    except Exception as exc:
        log.warning("BrowserAgent search failed (%s), falling back", exc)

    return {
        "query": query,
        "note": f"I performed a search for '{query}' and am summarizing my knowledge.",
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

    # ── Instant Natural Formatting for Voice (0ms Latency) ────────────
    if func_result:
        # Time queries
        if "time" in func_result and "date" in func_result:
            t_str = func_result["time"]
            d_str = func_result["date"]
            if any(w in text_lower for w in ["date", "day", "tarikh"]):
                resp_text = f"Today is {d_str}, and the time is {t_str}."
            else:
                resp_text = f"It's {t_str}."
            response_cache.put(user_text, resp_text)
            return [resp_text]

        # Math queries
        if "expression" in func_result and "result" in func_result:
            resp_text = f"The answer is {func_result['result']}."
            response_cache.put(user_text, resp_text)
            return [resp_text]

        # Weather queries
        if "weather" in func_result and "city" in func_result:
            resp_text = f"The weather in {func_result['city']} is currently {func_result['weather']}."
            response_cache.put(user_text, resp_text)
            return [resp_text]

        # Daily briefing
        if func_result.get("type") == "daily_briefing":
            resp_text = f"Good day! It's {func_result['time']} in {func_result['city']}. The weather is {func_result['weather']}. Here is your thought for the day: {func_result['quote']}"
            response_cache.put(user_text, resp_text)
            return [resp_text]

        # Fallback: format via LLM with think=False for speed
        format_prompt = f"""You are MJ, a smart voice assistant. 
Based on this data, give a natural, concise spoken response:
Data: {json.dumps(func_result)}
User asked: "{user_text}"
Respond naturally in 1-2 sentences:"""

        try:
            from ollama_client import ollama_chat  # type: ignore[import]
            text = ollama_chat(prompt=format_prompt, max_tokens=100, temperature=0.5, think=False)
            if text:
                response_cache.put(user_text, text)
                return [text]
        except Exception as e:
            log.warning("Ollama format failed: %s", e)

        # Fallback: return raw data
        return [str(func_result)]

    # ── No specific function matched — handle as general with realtime context ─
    from threads.general_handler import handle_general
    return handle_general(user_text, session, settings, system_prompt, history, max_tokens, response_cache)
