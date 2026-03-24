# ═══════════════════════════════════════════════════════════════════
# ALITA CHECKPOINT & RESUME SYSTEM
# File: backend/utils/checkpoint_manager.py
#
# HOW IT WORKS:
# 1. Before every LLM call → save full state to checkpoint.json
# 2. During streaming → every token appended to partial_response.txt
# 3. If LLM stops mid-way → nothing is lost beyond the partial tail
# 4. Switch account → run resume_alita.py → continues from exact point
# ═══════════════════════════════════════════════════════════════════

import json
import os
import time
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional

# ── Where checkpoints are stored ──────────────────────────────────
CHECKPOINT_DIR = Path("./alita_checkpoints")
CHECKPOINT_DIR.mkdir(exist_ok=True)


class AlitaCheckpoint:
    """
    Saves and restores full Alita session state.
    Used in llm_engine.py to wrap every LLM call.
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.checkpoint_path = CHECKPOINT_DIR / f"{session_id}_checkpoint.json"
        self.partial_path    = CHECKPOINT_DIR / f"{session_id}_partial.txt"
        self.resume_path     = CHECKPOINT_DIR / f"{session_id}_resume_prompt.txt"
        self.state = self._load_or_init()

    # ── Init / Load ────────────────────────────────────────────────
    def _load_or_init(self) -> dict:
        if self.checkpoint_path.exists():
            with open(self.checkpoint_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(f"[CHECKPOINT] Loaded existing session: {self.session_id}")
            print(f"[CHECKPOINT] Resuming from turn {data['turn_number']}")
            return data
        return {
            "session_id":        self.session_id,
            "created_at":        datetime.now().isoformat(),
            "last_updated":      datetime.now().isoformat(),
            "turn_number":       0,
            "status":            "active",      # active | interrupted | complete
            "conversation_history": [],          # full message list for LLM
            "alita_context":     {},             # last ALITA_CONTEXT block
            "face_data_history": [],             # all ALITA_FACE_DATA outputs
            "memory_snapshot":   {},             # ChromaDB / Mem0 state at save
            "partial_response":  "",             # tokens received before cutoff
            "last_complete_response": "",        # last fully completed response
            "metadata": {
                "user_id":        None,
                "handler_type":   "general",
                "llm_model":      "gemini-2.5-flash",
                "total_tokens_used": 0,
            }
        }

    # ── Save checkpoint before LLM call ───────────────────────────
    def save_before_call(
        self,
        user_message: str,
        alita_context: dict,
        memory_snapshot: dict = None,
        llm_model: str = "gemini-2.5-flash"
    ):
        """
        Call this BEFORE sending to the LLM.
        Saves everything needed to reconstruct the exact state.
        """
        self.state["turn_number"]  += 1
        self.state["last_updated"]  = datetime.now().isoformat()
        self.state["status"]        = "in_progress"
        self.state["alita_context"] = alita_context
        self.state["partial_response"] = ""
        self.state["metadata"]["llm_model"]   = llm_model
        if memory_snapshot:
            self.state["memory_snapshot"] = memory_snapshot

        # Add user message to history
        self.state["conversation_history"].append({
            "role": "user",
            "content": user_message,
            "turn": self.state["turn_number"],
            "timestamp": datetime.now().isoformat()
        })

        self._write()
        self._clear_partial()
        print(f"[CHECKPOINT] Saved before turn {self.state['turn_number']}")

    # ── Append streaming token ─────────────────────────────────────
    def append_token(self, token: str):
        """
        Call this for EVERY streamed token from the LLM.
        Writes to partial file immediately — survives any crash.
        """
        self.state["partial_response"] += token
        # Append to partial file (fast, no full JSON rewrite)
        with open(self.partial_path, "a", encoding="utf-8") as f:
            f.write(token)

    # ── Save after complete response ───────────────────────────────
    def save_after_response(self, full_response: str, face_data: dict = None):
        """
        Call this AFTER the LLM finishes successfully.
        Marks the turn as complete.
        """
        self.state["status"] = "active"
        self.state["last_complete_response"] = full_response
        self.state["partial_response"] = ""
        self.state["last_updated"] = datetime.now().isoformat()

        # Add assistant response to history
        self.state["conversation_history"].append({
            "role": "assistant",
            "content": full_response,
            "turn": self.state["turn_number"],
            "timestamp": datetime.now().isoformat(),
            "face_data": face_data or {}
        })

        if face_data:
            self.state["face_data_history"].append({
                "turn": self.state["turn_number"],
                "face_data": face_data
            })

        self._write()
        self._clear_partial()
        self._generate_resume_prompt()
        print(f"[CHECKPOINT] Turn {self.state['turn_number']} complete.")

    # ── Mark as interrupted ────────────────────────────────────────
    def mark_interrupted(self):
        """
        Call this in your exception handler when a token limit or
        network error is detected mid-stream.
        """
        # Read whatever partial tokens exist on disk
        partial = ""
        if self.partial_path.exists():
            partial = self.partial_path.read_text(encoding="utf-8")

        self.state["status"] = "interrupted"
        self.state["partial_response"] = partial
        self.state["last_updated"] = datetime.now().isoformat()
        self._write()
        self._generate_resume_prompt()

        print(f"[CHECKPOINT] INTERRUPTED at turn {self.state['turn_number']}")
        print(f"[CHECKPOINT] Partial response saved: {len(partial)} chars")
        print(f"[CHECKPOINT] Resume file: {self.resume_path}")

    # ── Generate resume prompt ─────────────────────────────────────
    def _generate_resume_prompt(self):
        """
        Writes a ready-to-use resume instruction file.
        Paste this into your new account/session to continue.
        """
        partial = self.state.get("partial_response", "").strip()
        turn    = self.state["turn_number"]
        status  = self.state["status"]

        if status == "interrupted" and partial:
            resume_instruction = f"""
═══════════════════════════════════════════════════════════════
ALITA RESUME INSTRUCTION — Paste into new session
Session ID: {self.session_id}
Interrupted at: Turn {turn}
Generated: {datetime.now().isoformat()}
═══════════════════════════════════════════════════════════════

You are Alita, resuming a session that was interrupted mid-response
due to token limits. The conversation history below is complete.
Your last response was cut off.

WHAT YOU HAD WRITTEN BEFORE STOPPING:
---
{partial}
---

INSTRUCTION:
Continue your response from EXACTLY where you stopped above.
Do not repeat what you already wrote.
Do not acknowledge the interruption to the user.
Do not say "As I was saying..." — just continue the sentence naturally.
Output the continuation followed by the complete ALITA_FACE_DATA JSON block.

The full conversation history follows in the messages array.
"""
        else:
            last = self.state.get("last_complete_response", "")[:200]
            resume_instruction = f"""
═══════════════════════════════════════════════════════════════
ALITA RESUME INSTRUCTION — Paste into new session
Session ID: {self.session_id}
Resuming from: Turn {turn} (last turn was complete)
Generated: {datetime.now().isoformat()}
═══════════════════════════════════════════════════════════════

You are Alita, continuing a conversation that was transferred to a
new account/session. Your last complete response was:
---
{last}...
---

INSTRUCTION:
Continue the conversation naturally from this point.
The full conversation history follows in the messages array.
Maintain all emotional context and memory from previous turns.
Do not acknowledge the transfer — just be present and continue.
"""

        with open(self.resume_path, "w", encoding="utf-8") as f:
            f.write(resume_instruction.strip())

    # ── Get messages for LLM call ──────────────────────────────────
    def get_messages_for_llm(self) -> list:
        """
        Returns the full conversation history formatted for
        whichever LLM you are calling (Gemini / Groq / DeepSeek).
        """
        messages = []
        for entry in self.state["conversation_history"]:
            messages.append({
                "role":    entry["role"],
                "content": entry["content"]
            })
        return messages

    # ── Check if resuming from interruption ───────────────────────
    def is_resuming(self) -> bool:
        return self.state["status"] == "interrupted"

    def get_resume_instruction(self) -> str:
        if self.resume_path.exists():
            return self.resume_path.read_text(encoding="utf-8")
        return ""

    # ── Internal helpers ───────────────────────────────────────────
    def _write(self):
        with open(self.checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)

    def _clear_partial(self):
        with open(self.partial_path, "w", encoding="utf-8") as f:
            f.write("")

    # ── Summary for logging ────────────────────────────────────────
    def summary(self) -> str:
        s = self.state
        return (
            f"Session: {s['session_id']} | "
            f"Status: {s['status']} | "
            f"Turns: {s['turn_number']} | "
            f"History: {len(s['conversation_history'])} messages | "
            f"Updated: {s['last_updated']}"
        )


# ═══════════════════════════════════════════════════════════════════
# HOW TO USE IN llm_engine.py
# ═══════════════════════════════════════════════════════════════════
#
# from utils.checkpoint_manager import AlitaCheckpoint
#
# async def call_alita(
#     session_id: str,
#     user_message: str,
#     alita_context: dict,
#     memory_snapshot: dict = None
# ):
#     ckpt = AlitaCheckpoint(session_id)
#
#     # If resuming from interruption — inject resume instruction
#     if ckpt.is_resuming():
#         resume_note = ckpt.get_resume_instruction()
#         user_message = resume_note + "\n\n" + user_message
#
#     # STEP 1 — Save before call
#     ckpt.save_before_call(
#         user_message=user_message,
#         alita_context=alita_context,
#         memory_snapshot=memory_snapshot
#     )
#
#     full_response = ""
#     try:
#         # STEP 2 — Stream tokens, save each one
#         async for token in gemini_stream(
#             messages=ckpt.get_messages_for_llm(),
#             system=ALITA_SYSTEM
#         ):
#             full_response += token
#             ckpt.append_token(token)      # saves to disk per token
#             yield token                   # stream to WebSocket
#
#         # STEP 3 — Parse face data and save complete response
#         spoken, face_data = parse_alita_response(full_response)
#         ckpt.save_after_response(full_response, face_data)
#
#     except Exception as e:
#         # Token limit, network error, API error — anything
#         ckpt.mark_interrupted()
#         raise e
#
# ═══════════════════════════════════════════════════════════════════
# resume_alita.py  — Run this on your NEW account to continue
# ═══════════════════════════════════════════════════════════════════

"""
Standalone script. Run from terminal:

  python resume_alita.py --session SESSION_ID_HERE

This will:
1. Load the checkpoint
2. Print a summary of where you were
3. Output the exact messages array to paste into your new LLM call
4. Generate a fresh resume_prompt.txt if needed
"""

import argparse

def resume_session(session_id: str):
    ckpt = AlitaCheckpoint(session_id)

    print("\n" + "═" * 60)
    print("ALITA RESUME TOOL")
    print("═" * 60)
    print(ckpt.summary())
    print()

    state = ckpt.state
    status = state["status"]

    if status == "interrupted":
        print(f"STATUS: INTERRUPTED at turn {state['turn_number']}")
        partial = state.get("partial_response", "")
        if partial:
            print(f"\nPARTIAL RESPONSE ({len(partial)} chars):")
            print("─" * 40)
            print(partial[:500] + ("..." if len(partial) > 500 else ""))
            print("─" * 40)
        print(f"\nRESUME PROMPT saved to: {ckpt.resume_path}")
        print("\nResume instruction:")
        print(ckpt.get_resume_instruction())

    elif status == "active":
        print(f"STATUS: ACTIVE — Last complete turn: {state['turn_number']}")
        last = state.get("last_complete_response", "")
        if last:
            print(f"\nLAST RESPONSE PREVIEW:")
            print(last[:300] + ("..." if len(last) > 300 else ""))

    print("\n" + "═" * 60)
    print("CONVERSATION HISTORY SUMMARY:")
    for msg in state["conversation_history"]:
        role = msg["role"].upper()
        preview = msg["content"][:80].replace("\n", " ")
        print(f"  Turn {msg.get('turn','?')} [{role}]: {preview}...")

    print("\n" + "═" * 60)
    print(f"FULL CHECKPOINT FILE: {ckpt.checkpoint_path}")
    print(f"RESUME PROMPT FILE:   {ckpt.resume_path}")
    print("═" * 60 + "\n")

    return ckpt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Resume an Alita session")
    parser.add_argument("--session", required=True, help="Session ID to resume")
    args = parser.parse_args()
    resume_session(args.session)


# ═══════════════════════════════════════════════════════════════════
# MULTI-ACCOUNT STRATEGY — The Right Way
# ═══════════════════════════════════════════════════════════════════
#
# ACCOUNT POOL MANAGER
# Keep 3-5 API accounts ready. Rotate automatically when one hits limits.
#
# accounts = [
#     {"provider": "google",  "api_key": os.getenv("GOOGLE_API_KEY_1")},
#     {"provider": "google",  "api_key": os.getenv("GOOGLE_API_KEY_2")},
#     {"provider": "groq",    "api_key": os.getenv("GROQ_API_KEY_1")},
#     {"provider": "groq",    "api_key": os.getenv("GROQ_API_KEY_2")},
#     {"provider": "deepseek","api_key": os.getenv("DEEPSEEK_API_KEY")},
# ]
#
# When token limit hits:
#   1. mark_interrupted() saves state automatically
#   2. Rotate to next account in pool
#   3. Load checkpoint on new account
#   4. Inject resume instruction as first system message
#   5. Continue streaming — user never sees a gap
#
# .env additions:
#   GOOGLE_API_KEY_1=...
#   GOOGLE_API_KEY_2=...
#   GROQ_API_KEY_1=...
#   GROQ_API_KEY_2=...
#   DEEPSEEK_API_KEY=...
#   ALITA_CHECKPOINT_DIR=./alita_checkpoints
#   ALITA_ACCOUNT_ROTATION=true
# ═══════════════════════════════════════════════════════════════════
