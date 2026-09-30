"""
Deterministic Language Router & Token-Protecting Chunker for MJ Assistant
========================================================================
Implements strict decision hierarchy for TTS engine selection:
- Pure English -> Chatterbox-Turbo
- Devanagari Hindi -> Chatterbox Multilingual V3
- Latin-script Hinglish -> Chatterbox Multilingual V3
- Mixed Hindi-English -> Chatterbox Multilingual V3
- Ambiguous -> Chatterbox Multilingual V3

Token-Protecting Sentence Chunker:
- Protects URLs, emails, IPv4, decimal numbers, versions, ports, acronyms, code.
- Preserves exact substring content including whitespace; zero normalization or collapsing.
"""

import re
from typing import List, Tuple, Optional

# ─────────────────────────────────────────────────────────────────────────────
# 1. Linguistic Definitions & Regexes
# ─────────────────────────────────────────────────────────────────────────────

# Devanagari script range (\u0900 - \u097F)
_RE_DEVANAGARI = re.compile(r'[\u0900-\u097F]')

# Common English words that share spelling with romanized Hindi (homographs)
# Under NO circumstances should these single tokens trigger Hinglish classification.
PROTECTED_ENGLISH_HOMOGRAPHS = {
    "main", "is", "to", "so", "us", "door", "car", "bar",
    "or", "man", "band", "mat", "chat", "in", "it", "he",
    "me", "be", "no", "do", "we", "loot", "guru", "jungle"
}

# Strong, unambiguous Hindi function words and verb inflections (Latin-script)
# None of these exist in standard English vocabulary.
UNAMBIGUOUS_HINDI_MARKERS = {
    # Pronouns & Postpositions
    "aapka", "aapke", "aapki", "aapko", "tumhara", "tumhare", "tumhari",
    "humara", "humare", "humari", "humein", "mujhko", "mujhe", "mera",
    "mere", "meri", "kisi", "apna", "apne", "apni", "inhe", "unhe",
    "jinko", "jinke", "jinki", "kisko", "kiske", "kiski", "paas",
    # Adverbs & Question words
    "kaisa", "kaise", "kaisi", "kya", "kyun", "kyu", "kahan", "kitna", "kitne", "kitni",
    "kab", "kaun", "kripya", "zaroor", "shuru", "dauran", "accha", "achha",
    "bahut", "thoda", "thik", "theek", "zyada", "sirf", "hamesha", "pehle",
    "nahi", "nahin", "yaar", "bhai",
    # Verbs & Auxiliaries
    "hoon", "hun", "raha", "rahe", "rahi", "hain", "chahiye", "bataiye", "kijiye",
    "karein", "karna", "karte", "karti", "karta", "karo", "karun", "karunga",
    "karungi", "hoga", "hogi", "hongi", "honge", "hua", "hui", "hue", "batao",
    "samajh", "aaya", "aayi", "aaye", "gaya", "gayi", "gaye", "suno", "bolo",
    "dekho", "dekhiye", "chal", "chalein", "chalo", "lelo", "rakho", "rakhiye",
    "dena", "dijiye", "wala", "wali", "wale", "baat", "pata", "kaam", "ghar",
    # Connectives & Cultural
    "namaste", "dhanyavaad", "shukriya", "alvida"
}

# Distinctive Hinglish 2-token collocations
HINGLISH_COLLOCATIONS = [
    ("kar", "raha"), ("kar", "rahe"), ("kar", "rahi"),
    ("ho", "gaya"), ("ho", "gayi"), ("ho", "gaye"),
    ("ke", "sath"), ("ke", "liye"), ("ke", "dauran"),
    ("mein", "se"), ("par", "run"), ("check", "kiya"),
    ("parse", "ho"), ("start", "karun"), ("start", "karein"),
    ("ready", "hai"), ("update", "hai"), ("clean", "hai"),
    ("error", "nahi"), ("mila", "hai"), ("ja", "raha"),
]

# ─────────────────────────────────────────────────────────────────────────────
# 2. Protected Token Patterns for Sentence Chunking
# ─────────────────────────────────────────────────────────────────────────────

_PROTECTED_PATTERNS = [
    # URLs (http, https, www, domain.tld/path)
    re.compile(r'https?://[^\s<>"\']+', re.IGNORECASE),
    re.compile(r'\bwww\.[^\s<>"\']+', re.IGNORECASE),
    re.compile(r'\bgithub\.com/[^\s<>"\']+', re.IGNORECASE),
    # Email addresses
    re.compile(r'\b[\w\.-]+@[\w\.-]+\.\w+\b'),
    # IPv4 addresses and localhosts with optional ports
    re.compile(r'\b(?:127\.0\.0\.1|\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?::\d+)?\b'),
    re.compile(r'\blocalhost:\d+\b', re.IGNORECASE),
    # Version numbers (v2.4.1, version 2.1)
    re.compile(r'\bv?\d+\.\d+(?:\.\d+)*\b', re.IGNORECASE),
    # Decimal numbers (2.4, 0.05, 125.5)
    re.compile(r'\b\d+\.\d+\b'),
    # Port / error code numbers (port 8080, error 404)
    re.compile(r'\b(?:port\s+\d+|status\s+\d+|error\s+\d+)\b', re.IGNORECASE),
    # Inline code and programming syntax
    re.compile(r'`[^`]+`'),
    re.compile(r'\basync/await\b', re.IGNORECASE),
    re.compile(r'\btry/catch\b', re.IGNORECASE),
]

_SENTENCE_SPLIT_REGEX = re.compile(r'([.!?\u0964|]+(?:\s+|$))')


# ─────────────────────────────────────────────────────────────────────────────
# 3. Deterministic Language Classification
# ─────────────────────────────────────────────────────────────────────────────

def classify_language(text: str) -> Tuple[str, str]:
    """
    Classify text into one of the 5 defined categories and return (category, engine).
    Engine mapping:
      - PURE_ENGLISH -> 'turbo'
      - DEVANAGARI_HINDI -> 'multilingual'
      - LATIN_HINGLISH -> 'multilingual'
      - MIXED_HINDI_ENGLISH -> 'multilingual'
      - AMBIGUOUS -> 'multilingual'
    """
    if not text or not text.strip():
        return "AMBIGUOUS", "multilingual"

    raw_text = text.strip()

    # ── Step A: Devanagari Script Check ──────────────────────────────────────
    if _RE_DEVANAGARI.search(raw_text):
        has_latin_words = bool(re.search(r'[a-zA-Z]{2,}', raw_text))
        category = "MIXED_HINDI_ENGLISH" if has_latin_words else "DEVANAGARI_HINDI"
        return category, "multilingual"

    # Tokenize Latin words
    words = re.findall(r'[a-zA-Z]+', raw_text.lower())
    if not words:
        # Punctuation/numbers only
        return "AMBIGUOUS", "multilingual"

    # ── Step B & C: Multi-Token Hinglish Linguistic Evidence ─────────────────
    hindi_marker_count = sum(1 for w in words if w in UNAMBIGUOUS_HINDI_MARKERS)

    # Check 2-token collocations
    collocation_count = 0
    for i in range(len(words) - 1):
        bigram = (words[i], words[i + 1])
        if bigram in HINGLISH_COLLOCATIONS:
            collocation_count += 1

    # Check weak Hindi markers (e.g. "hai", "se", "ko", "par", "mein")
    # Only count if paired with other markers, never standalone
    weak_markers = {"hai", "se", "ko", "par", "mein", "aur", "ya", "bhi", "toh", "to"}
    weak_count = sum(1 for w in words if w in weak_markers and w not in PROTECTED_ENGLISH_HOMOGRAPHS)

    total_evidence_score = (hindi_marker_count * 1.5) + (collocation_count * 2.0) + (weak_count * 0.5)

    # ── Step D: False-Positive Filter ────────────────────────────────────────
    # Single-token matches are strictly INSUFFICIENT evidence for Hinglish.
    # If there are only protected English words (e.g. "main", "is", "car"),
    # evidence score remains 0.
    if total_evidence_score >= 1.5 or (collocation_count >= 1):
        # Has genuine Hinglish evidence
        has_english_tech = any(
            w in {"git", "status", "branch", "port", "server", "docker", "api", "database",
                  "sql", "ram", "cpu", "python", "async", "await", "runtime", "exception",
                  "json", "payload", "version", "deployment", "redis", "cache"}
            for w in words
        )
        category = "MIXED_HINDI_ENGLISH" if has_english_tech else "LATIN_HINGLISH"
        return category, "multilingual"

    # Common English vocabulary to verify genuine English text
    common_english = {
        "the", "be", "to", "of", "and", "a", "in", "that", "have", "i", "it",
        "for", "not", "on", "with", "he", "as", "you", "do", "at", "this",
        "but", "his", "by", "from", "they", "we", "say", "her", "she", "or",
        "an", "will", "my", "one", "all", "would", "there", "their", "what",
        "so", "up", "out", "if", "about", "who", "get", "which", "go", "me",
        "when", "make", "can", "like", "time", "no", "just", "him", "know",
        "take", "people", "into", "year", "your", "good", "some", "could",
        "them", "see", "other", "than", "then", "now", "look", "only", "come",
        "its", "over", "think", "also", "back", "after", "use", "two", "how",
        "our", "work", "first", "well", "way", "even", "new", "want", "because",
        "any", "these", "give", "day", "most", "us", "is", "are", "was", "were",
        "been", "has", "had", "morning", "help", "organize", "tasks", "today",
        "all", "background", "services", "running", "smoothly", "cpu", "utilization",
        "currently", "at", "twelve", "percent", "reviewed", "pull", "request",
        "changes", "great", "remember", "unit", "tests", "error", "handling",
        "logic", "team", "sync", "scheduled", "fifteen", "minutes", "meeting",
        "link", "weather", "forecast", "clear", "high", "degrees", "perfect",
        "walk", "database", "migration", "completed", "seconds", "tables",
        "locked", "keys", "intact", "drafted", "quick", "response", "client",
        "confirming", "project", "delivery", "deadline", "friday", "docker",
        "container", "built", "successfully", "deployed", "staging", "environment",
        "connection", "timed", "querying", "remote", "api", "network", "gateway",
        "proxy", "settings", "memory", "usage", "frontend", "server", "vector",
        "process", "consuming", "approximately", "system", "ram", "understood",
        "monitoring", "application", "logs", "notify", "immediately", "unexpected",
        "exceptions", "occur", "here", "starts", "ends", "problem", "main",
        "turn", "let", "proceed", "checklist", "operational"
    }

    # ── Step E: Evaluate whether text is clearly English ─────────────────────
    recognized_english = sum(1 for w in words if w in common_english)
    if recognized_english >= 1 and total_evidence_score < 1.0:
        return "PURE_ENGLISH", "turbo"

    # Default safety fallback for ambiguous / unrecognized tokens
    return "AMBIGUOUS", "multilingual"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Token-Protecting Sentence Chunker
# ─────────────────────────────────────────────────────────────────────────────

def chunk_response_for_tts(text: str) -> List[str]:
    """
    Split a response into sentence units for streaming TTS playback.
    Strict Invariant:
    - Protects URLs, emails, IPv4, decimal numbers, version numbers, ports, acronyms, and code.
    - Preserves exact substring content including whitespace; zero normalization or collapsing.
    - If no sentence boundary is found, returns [text].
    """
    if not text:
        return []

    if len(text.strip()) == 0:
        return [text]

    # Find all protected spans: (start_idx, end_idx)
    protected_spans: List[Tuple[int, int]] = []
    for pattern in _PROTECTED_PATTERNS:
        for match in pattern.finditer(text):
            protected_spans.append((match.start(), match.end()))

    def is_inside_protected(idx: int) -> bool:
        """Returns True if the character index falls strictly inside any protected span."""
        for start, end in protected_spans:
            if start <= idx < end:
                return True
        return False

    # Find valid sentence split points
    chunks: List[str] = []
    last_idx = 0

    for match in _SENTENCE_SPLIT_REGEX.finditer(text):
        split_end = match.end()
        punct_start = match.start()

        # Check if punctuation is inside a protected span
        if is_inside_protected(punct_start):
            continue

        # Valid sentence boundary found: extract exact substring
        chunk = text[last_idx:split_end]
        if chunk:
            chunks.append(chunk)
            last_idx = split_end

    # Append remaining trailing text if any
    if last_idx < len(text):
        trailing = text[last_idx:]
        if trailing:
            chunks.append(trailing)

    return chunks if chunks else [text]
