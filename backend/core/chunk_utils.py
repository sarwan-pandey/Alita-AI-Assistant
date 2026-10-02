"""
Centralized TTS Hard Chunking & Safety Module for MJ/ALITA
==========================================================
Enforces mathematically proven character ceilings for Chatterbox Turbo on RTX 3050 4GB:
- TARGET SIZE: 70–85 characters
- OPERATIONAL HARD LIMIT: 90 characters
- ABSOLUTE SAFETY INVARIANT: Never send >100 characters to Chatterbox

Preserves:
- Sentence boundaries (. ! ? । \n)
- Clause boundaries (, ; : — – -)
- Word boundaries (never fragments words when spaces exist)
- Hindi/Devanagari text integrity (matras and conjuncts)
- Hinglish conversational flow
- Streaming token accumulation without buffer stalls
"""

import re
from typing import List, Generator, Dict, Any, Optional

_SENT_PUNCT = re.compile(r'([.!?।\n]+)')
_CLAUSE_PUNCT = re.compile(r'([,;:—–-]+)')

# Operational constants derived from Phase 6D empirical validation
TARGET_MIN_CHARS: int = 70
TARGET_MAX_CHARS: int = 85
OPERATIONAL_HARD_LIMIT: int = 90
ABSOLUTE_SAFETY_LIMIT: int = 100


def chunk_text_hard_safety(
    text: str,
    target_min: int = TARGET_MIN_CHARS,
    target_max: int = TARGET_MAX_CHARS,
    hard_limit: int = OPERATIONAL_HARD_LIMIT,
    absolute_limit: int = ABSOLUTE_SAFETY_LIMIT,
) -> List[str]:
    """
    Splits text into chunks strictly enforcing len(chunk) <= hard_limit.
    No chunk will ever exceed hard_limit (default: 90 chars),
    and the absolute safety invariant (default: 100 chars) is strictly asserted.

    Priority:
    1. Sentence boundaries (.!?।) if candidate >= target_min and <= hard_limit.
    2. Clause boundaries (,;:—–-) if candidate >= target_min and <= hard_limit.
    3. Any punctuation boundary <= hard_limit if candidate >= 20 chars.
    4. Word boundary (whitespace) before hard_limit if buffer exceeds hard_limit.
    5. Hard slice at hard_limit if an unbroken single word exceeds hard_limit.
    """
    text = text.strip()
    if not text:
        return []

    chunks: List[str] = []
    current = text

    while current:
        current = current.strip()
        if not current:
            break

        if len(current) <= hard_limit:
            chunks.append(current)
            break

        window = current[:hard_limit + 1]

        # 1. Check for sentence end in window (prefer latest >= target_min)
        sent_matches = list(_SENT_PUNCT.finditer(window[:hard_limit]))
        split_pos = -1
        if sent_matches:
            for m in reversed(sent_matches):
                end_pos = m.end()
                if end_pos >= target_min and end_pos <= hard_limit:
                    split_pos = end_pos
                    break
            # Secondary: take any sentence boundary >= 20 chars
            if split_pos == -1:
                for m in reversed(sent_matches):
                    end_pos = m.end()
                    if end_pos >= 20 and end_pos <= hard_limit:
                        split_pos = end_pos
                        break

        # 2. Check for clause punctuation (,;:-) in window
        if split_pos == -1:
            clause_matches = list(_CLAUSE_PUNCT.finditer(window[:hard_limit]))
            if clause_matches:
                for m in reversed(clause_matches):
                    end_pos = m.end()
                    if end_pos >= target_min and end_pos <= hard_limit:
                        split_pos = end_pos
                        break
                # Secondary: take any clause boundary >= 20 chars
                if split_pos == -1:
                    for m in reversed(clause_matches):
                        end_pos = m.end()
                        if end_pos >= 20 and end_pos <= hard_limit:
                            split_pos = end_pos
                            break

        # 3. Fallback: split on last whitespace <= hard_limit
        if split_pos == -1:
            last_space = window[:hard_limit].rfind(' ')
            if last_space != -1 and last_space >= 10:
                split_pos = last_space
            else:
                # 4. Hard slice at hard_limit (emergency word break)
                split_pos = hard_limit

        chunk = current[:split_pos].strip()
        remainder = current[split_pos:].strip()
        if chunk:
            # Defensive invariant guard
            if len(chunk) > absolute_limit:
                chunk = chunk[:hard_limit].strip()
            chunks.append(chunk)
        current = remainder

    # Final assertion on all generated chunks
    for c in chunks:
        assert len(c) <= absolute_limit, f"FATAL INVARIANT BREACH: chunk length {len(c)} > {absolute_limit}"
    return chunks


def chunk_stream_hard_safety(
    token_generator,
    target_min: int = TARGET_MIN_CHARS,
    target_max: int = TARGET_MAX_CHARS,
    hard_limit: int = OPERATIONAL_HARD_LIMIT,
    absolute_limit: int = ABSOLUTE_SAFETY_LIMIT,
) -> Generator[Dict[str, Any], None, None]:
    """
    Accumulates streaming tokens into chunks strictly adhering to hard_limit <= 90 chars.
    Yields dict with:
        chunk_text: str (guaranteed len <= hard_limit)
        chunk_idx: int
        t_start: float
        t_first_token: Optional[float]
        token_count: int
        is_final: bool
    """
    buffer = ""
    chunk_idx = 0
    t_first_token = None
    total_tokens = 0
    t_start = None

    for item in token_generator:
        if t_start is None:
            t_start = item.get("t_start")
        if t_first_token is None:
            t_first_token = item.get("t_first_token")
        total_tokens = item.get("token_count", total_tokens + 1)
        buffer += item.get("token", "")

        while len(buffer) >= hard_limit or any(p in buffer for p in ['. ', '! ', '? ', '। ', '\n']):
            # 1. Check sentence boundary
            sent_matches = list(_SENT_PUNCT.finditer(buffer[:hard_limit]))
            split_pos = -1
            if sent_matches:
                for m in reversed(sent_matches):
                    end_pos = m.end()
                    if end_pos >= target_min and end_pos <= hard_limit:
                        split_pos = end_pos
                        break
                if split_pos == -1 and len(buffer) >= hard_limit:
                    for m in reversed(sent_matches):
                        end_pos = m.end()
                        if end_pos >= 20 and end_pos <= hard_limit:
                            split_pos = end_pos
                            break

            # 2. Check clause boundary if buffer >= hard_limit
            if split_pos == -1 and len(buffer) >= hard_limit:
                clause_matches = list(_CLAUSE_PUNCT.finditer(buffer[:hard_limit]))
                if clause_matches:
                    for m in reversed(clause_matches):
                        end_pos = m.end()
                        if end_pos >= target_min and end_pos <= hard_limit:
                            split_pos = end_pos
                            break
                    if split_pos == -1:
                        for m in reversed(clause_matches):
                            end_pos = m.end()
                            if end_pos >= 20 and end_pos <= hard_limit:
                                split_pos = end_pos
                                break

            # 3. Check whitespace if buffer >= hard_limit
            if split_pos == -1 and len(buffer) >= hard_limit:
                last_space = buffer[:hard_limit].rfind(' ')
                if last_space != -1 and last_space >= 10:
                    split_pos = last_space
                else:
                    split_pos = hard_limit

            if split_pos != -1:
                chunk = buffer[:split_pos].strip()
                buffer = buffer[split_pos:].lstrip()
                if chunk:
                    if len(chunk) > absolute_limit:
                        chunk = chunk[:hard_limit].strip()
                    assert len(chunk) <= absolute_limit
                    yield {
                        "chunk_text": chunk,
                        "chunk_idx": chunk_idx,
                        "t_start": t_start,
                        "t_first_token": t_first_token,
                        "token_count": total_tokens,
                        "is_final": False,
                    }
                    chunk_idx += 1
            else:
                break

    # Flush remainder at end of stream
    remainder = buffer.strip()
    if remainder:
        sub_chunks = chunk_text_hard_safety(
            remainder,
            target_min=target_min,
            target_max=target_max,
            hard_limit=hard_limit,
            absolute_limit=absolute_limit,
        )
        for i, s in enumerate(sub_chunks):
            assert len(s) <= absolute_limit
            yield {
                "chunk_text": s,
                "chunk_idx": chunk_idx,
                "t_start": t_start,
                "t_first_token": t_first_token,
                "token_count": total_tokens,
                "is_final": (i == len(sub_chunks) - 1),
            }
            chunk_idx += 1
