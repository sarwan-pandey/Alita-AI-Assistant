"""
Alita Smart Router — Dynamic Local vs Cloud LLM Complexity Classifier
======================================================================
Routes simple, everyday conversation and commands to local Qwen 3:8B (fast, private, 0 API cost),
and complex analytical, multi-step, vision, or research queries to Gemini 2.5 Flash (cloud).
"""

import re
import logging

log = logging.getLogger("alita.smart_router")

# Keywords that indicate complex reasoning, research, synthesis, or code debugging
COMPLEX_KEYWORDS = [
    r"\banalyze\b",
    r"\banalyse\b",
    r"\bsummarize\b",
    r"\bsummarise\b",
    r"\bcompare\b",
    r"\bdebug\b",
    r"\bexplain\s+why\b",
    r"\bresearch\b",
    r"\bplan\b",
    r"\breview\b",
    r"\bevaluate\b",
    r"\brecommend\b",
]

_COMPLEX_PATTERN = re.compile("|".join(COMPLEX_KEYWORDS), re.IGNORECASE)


def classify_complexity(query: str, has_image: bool = False) -> str:
    """
    Classifies a query to determine whether to execute it locally or route to cloud.
    
    Returns:
      "cloud" -> Route to Gemini 2.5 Flash
      "local" -> Route to local Qwen 3:8B via Ollama
    
    Rules (in order of evaluation):
      1. has_image == True -> "cloud" (Qwen 3:8B is text-only; vision requires Gemini)
      2. Complex reasoning keywords -> "cloud"
      3. Long queries (> 50 words) -> "cloud"
      4. All other queries (conversational, brief, system actions) -> "local"
    """
    if has_image:
        return "cloud"

    if not query or not query.strip():
        return "local"

    words = query.strip().split()
    word_count = len(words)

    # Check for complex cognitive keywords
    if _COMPLEX_PATTERN.search(query):
        return "cloud"

    # Deep/long prompt queries benefit from cloud reasoning capacity
    if word_count > 50:
        return "cloud"

    return "local"
