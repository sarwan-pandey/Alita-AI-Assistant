"""
Text processing and cleaning utilities for speech synthesis (TTS) pipeline.
Shared between main pipeline orchestrator and core.audio_pipeline.
"""

import re

# Pre-compiled regular expressions for high-throughput cleaning
_RE_TRIPLE_BOLD = re.compile(r'\*\*\*(.*?)\*\*\*')
_RE_DOUBLE_BOLD = re.compile(r'\*\*(.*?)\*\*')
_RE_DOUBLE_UNDER = re.compile(r'__(.*?)__')

_RE_ORAL_LAUGH_ASTERISK = re.compile(
    r'\*[^;*()\n.!?]{0,40}?\b(giggle[s]?|laugh[s]?|chuckle[s]?|snicker[s]?|giggling|chuckling|laughing|smiles warmly)\b[^;*()\n.!?]{0,40}?\*',
    flags=re.IGNORECASE,
)
_RE_ORAL_LAUGH_PAREN = re.compile(
    r'\([^;)\n]*?\b(giggle[s]?|laugh[s]?|chuckle[s]?|snicker[s]?)\b[^;)\n]*?\)',
    flags=re.IGNORECASE,
)
_RE_ORAL_SIGH_ASTERISK = re.compile(
    r'\*[^;*()\n.!?]{0,40}?\b(sigh[s]?|deep breath|takes a breath|sighing)\b[^;*()\n.!?]{0,40}?\*',
    flags=re.IGNORECASE,
)
_RE_ORAL_SIGH_PAREN = re.compile(
    r'\([^;)\n]*?\b(sigh[s]?|sighs deeply)\b[^;)\n]*?\)',
    flags=re.IGNORECASE,
)
_RE_ORAL_YAWN = re.compile(
    r'[\*\()][^;*\)\n]*?\b(yawn[s]?)\b[^;*\)\n]*?[\*\)]',
    flags=re.IGNORECASE,
)
_RE_ORAL_ELLIPSIS = re.compile(r'\s*(?:\.{3,}|…)\s*')
_RE_ORAL_STRIP_BRACKETS = re.compile(r'\[(?!(?:laugh|sigh|yawn|break_\d+)\])[^\]]+\]', flags=re.IGNORECASE)

_RE_STANDARD_BRACKETS = re.compile(r'\[[^\]]+\]')
_STAGE_WORDS = 'giggles|laughs|sighs|smirks|pouts|whispers|gasps|chuckles|teasingly|warmly|softly|playfully|sarcastically|crosses arms|looks away'
_RE_STAGE_PAREN = re.compile(rf'\([^)]*?\b({_STAGE_WORDS})\b[^)]*?\)', flags=re.IGNORECASE)
_RE_ACTION_ASTERISK = re.compile(r'\*[a-zA-Z][^*;\n]{0,60}\*')
_RE_WHITESPACE = re.compile(r'\s+')


def clean_text_for_tts(text: str, preserve_oral_tags: bool = False) -> str:
    """
    Strips action asterisks, bracketed directions, parenthetical stage cues,
    and markdown formatting. When preserve_oral_tags=True (for ChatTTS), translates
    adverbial laughter/sighs/yawns and pauses into [laugh], [sigh], [break_3] while
    preserving valid ChatTTS oral acoustic tags.
    """
    if not text:
        return ""

    # 1. Triple bold/italic ***word*** -> word
    cleaned = _RE_TRIPLE_BOLD.sub(r'\1', text)
    # 2. Markdown bold **word** -> word, __word__ -> word
    cleaned = _RE_DOUBLE_BOLD.sub(r'\1', cleaned)
    cleaned = _RE_DOUBLE_UNDER.sub(r'\1', cleaned)

    if preserve_oral_tags:
        # Translate conversational laughter cues
        cleaned = _RE_ORAL_LAUGH_ASTERISK.sub(' [laugh] ', cleaned)
        cleaned = _RE_ORAL_LAUGH_PAREN.sub(' [laugh] ', cleaned)

        # Translate conversational sigh / breath cues
        cleaned = _RE_ORAL_SIGH_ASTERISK.sub(' [sigh] ', cleaned)
        cleaned = _RE_ORAL_SIGH_PAREN.sub(' [sigh] ', cleaned)

        # Translate yawns
        cleaned = _RE_ORAL_YAWN.sub(' [yawn] ', cleaned)

        # Translate conversational ellipses (...) into natural breathing pause [break_3]
        cleaned = _RE_ORAL_ELLIPSIS.sub(' [break_3] ', cleaned)

        # Strip all brackets that are NOT recognized ChatTTS tags
        cleaned = _RE_ORAL_STRIP_BRACKETS.sub('', cleaned)
    else:
        # Square brackets [stage directions]
        cleaned = _RE_STANDARD_BRACKETS.sub('', cleaned)

    # Parenthetical stage cues with adverbs: (giggles), (affectionately whispers), (sighs deeply)
    cleaned = _RE_STAGE_PAREN.sub('', cleaned)
    # Roleplay action asterisks *smirks*, *looks at screen* (starts with letter, max 60 chars, no semicolons)
    cleaned = _RE_ACTION_ASTERISK.sub('', cleaned)
    # Backticks
    cleaned = cleaned.replace('`', '')
    # Normalize spaces
    cleaned = _RE_WHITESPACE.sub(' ', cleaned).strip()
    return cleaned


# Backward compatibility aliases
preprocess_text_for_tts = clean_text_for_tts
_clean_text_for_tts = clean_text_for_tts

__all__ = [
    "clean_text_for_tts",
    "preprocess_text_for_tts",
    "_clean_text_for_tts",
]
