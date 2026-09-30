# Implementation Plan: General-Purpose Closed-Loop Phone Automation with Screen Perception & Task Planning

Extends the original unlock-verification work into a general capability: Alita perceives the actual screen before and after **every** action (not just unlock), plans multi-step tasks, recovers from interruptions, and never stores credentials in plaintext.

---

## User Review Required

> [!IMPORTANT]
> **What Changed vs. the original plan**: The original plan built one verified action (unlock). This plan generalizes that pattern into the core execution loop so it applies to *any* instruction:
> 1. **Generic Perceive → Act → Verify Loop**: Every tap, swipe, text entry, and app launch is wrapped in the same "check state → act → confirm effect" pattern the unlock flow used — not just Keyguard.
> 2. **Real Screen Understanding**: Alita reads the actual accessibility tree (element text, IDs, bounds) of whatever app is open, with a screenshot+vision fallback when the tree is unreliable (e.g., WebViews, games, custom-rendered UI).
> 3. **Multi-Step Task Planning**: Instructions like *"open WhatsApp and tell Rahul I'm running late"* are decomposed into a step sequence, executed one verified step at a time, with re-planning if a step doesn't produce the expected screen.
> 4. **Interruption Handling**: Permission dialogs, OEM battery/autostart popups, notification banners, and crashed/backgrounded apps are detected mid-task and handled (dismiss known patterns, or pause and ask you) instead of silently breaking the flow.
> 5. **Retry & Escalation Policy**: A failed verification triggers a bounded retry (e.g., re-tap, wait-and-recheck) before Alita reports failure and stops — she doesn't just try once and give up, but she also doesn't loop forever.
> 6. **Credential Security Fix**: Your PIN moves out of backend source code entirely. It lives encrypted on-device (Android Keystore) or in a local secrets file the backend reads at runtime — never hardcoded, never logged.
> 7. **Confirmation State Tracking**: Sensitive-action confirmations ("Alita, are you sure you want to unlock and send this?") persist correctly across the next user turn instead of being a one-shot check.

---

## Proposed Changes

### Component 1: Android Companion Native Bridge (`android_companion/`)

#### [MODIFY] [AlitaPhoneBridgeService.kt](file:///c:/Users/sarwa/Desktop/aura-assistant/android_companion/app/src/main/java/ai/alita/companion/AlitaPhoneBridgeService.kt)
- Keep the `"get_state"` handler from the original plan (`isScreenOn`, `isLocked`, `currentPackage`, `batteryPercent`, `isCharging`), and extend it with:
  - `hasOverlayPopup` (heuristic: foreground window class matches known system-dialog / OEM-popup patterns)
  - `deviceModel`, `androidVersion` (static, cached once)
- Keep the enhanced `unlockDevice()` behavior (already-unlocked short-circuit, 800ms-then-check), but change the fixed sleep to a **poll loop**: check `km.isKeyguardLocked` every 150ms up to a 3s timeout, returning as soon as the state flips instead of always waiting the full window.
- **Remove the plaintext PIN parameter path.** `unlockDevice()` now reads the credential from Android Keystore-backed `EncryptedSharedPreferences` on the device itself, set once via a companion-app setup screen — the backend sends only `{"command": "unlock"}`, never the PIN value.

#### [NEW] [AlitaAccessibilityService.kt](file:///c:/Users/sarwa/Desktop/aura-assistant/android_companion/app/src/main/java/ai/alita/companion/AlitaAccessibilityService.kt) — extend
- Add `"read_screen"` command: serialize the current `rootInActiveWindow` into a compact JSON tree — each node's `text`, `contentDescription`, `viewIdResourceName`, `className`, `bounds`, and `clickable` flag. This is what lets Alita find "the Send button" in an arbitrary app instead of only knowing lock-state.
- Add `"execute_action"` command handling four primitives, each returning a structured result:
  - `tap(selector)` — selector can be by text, resource-id, or bounds
  - `type_text(selector, text)`
  - `swipe(direction | coordinates)`
  - `launch_app(packageName)`
- Add `"screenshot"` command (base64 PNG) as the fallback path when `read_screen` returns a sparse/empty tree (WebViews, games, custom Canvas UIs).
- Add a lightweight **known-popup dismissal table**: matched by package name + text pattern (e.g., "Allow", "While using the app", Realme/ColorOS autostart prompts) → auto-tap the safe/expected button. Anything not in the table is surfaced to the backend as `unhandledPopup` rather than guessed at.

#### [MODIFY] AlitaCompanion setup flow
- Add a one-time "Set unlock PIN" screen in the companion app itself that writes the PIN into `EncryptedSharedPreferences`. The backend never transmits or stores the raw PIN after this migration.
- Recompile `AlitaCompanion.apk` and update `/download-apk`.

---

### Component 2: Backend Mobile Orchestrator (`backend/engines/`)

#### [NEW] [action_executor.py](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/action_executor.py)
This is the generalized version of the unlock-only loop — the single place every phone action routes through.
- `async def execute_and_verify(action, expected_state_fn, timeout_s=3.0, poll_interval_s=0.15, max_retries=1)`:
  1. **Perceive**: call `get_live_phone_state()` + `read_screen()` before acting.
  2. **Act**: dispatch `action` (tap/swipe/type/launch) via the bridge.
  3. **Verify**: poll `read_screen()`/`get_live_phone_state()` until `expected_state_fn` returns true or timeout elapses — never a single fixed `sleep`.
  4. **Retry policy**: on timeout, check `hasOverlayPopup`/`unhandledPopup` first (see interruption handling below); if none, retry the action up to `max_retries` times; if still failing, return a structured failure with the last observed screen state attached (for diagnosis and for Alita to describe accurately, not vaguely).
- This function replaces the bespoke unlock-only verification code; `unlock_screen()` becomes one caller of `execute_and_verify` among many.

#### [NEW] [interruption_handler.py](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/interruption_handler.py)
- `detect_interruption(screen_tree)` — checks for permission dialogs, OEM popups, crash/ANR dialogs, or unexpected package changes mid-task.
- `resolve_known_popup(popup)` — delegates to the bridge's known-popup table for auto-dismissal; returns whether it was auto-resolved.
- If unresolved: pauses the current task, and returns a summary Alita can use to ask the user how to proceed (e.g., *"A permission dialog appeared that I don't recognize — should I allow it?"*) rather than guessing or silently failing.

#### [NEW] [task_planner.py](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/task_planner.py)
- `plan_steps(instruction, current_screen_state) -> list[Step]`: uses the LLM (via `llm_engine.py`) with the live screen tree as context to produce an ordered list of primitive actions (e.g., `launch_app("com.whatsapp")` → `tap(selector="Rahul")` → `tap(selector="message input")` → `type_text(..., "running late")` → `tap(selector="Send")`).
- `execute_plan(steps)`: runs each step through `action_executor.execute_and_verify`, re-reading the screen after every step. If a step's real-world result doesn't match what the plan expected (e.g., contact list looks different than assumed), it calls back into `plan_steps` with the updated screen state to **replan the remainder** rather than blindly continuing a stale plan.
- Caps total steps and total wall-clock time per task to avoid runaway loops.

#### [MODIFY] [phone_orchestrator.py](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/phone_orchestrator.py)
- `get_live_phone_state()` as in the original plan, plus the new `hasOverlayPopup`, `deviceModel`, `androidVersion` fields.
- `unlock_screen()` reimplemented as a thin wrapper around `action_executor.execute_and_verify`, with the expected-state function `lambda s: s.isLocked == False`. **No PIN value is passed or stored here** — the bridge command carries no credential.
- `run_instruction(instruction)` — new top-level entry point: pre-checks sensitive-action intent (below), then hands off to `task_planner.plan_steps` / `execute_plan` for anything beyond a single known action, and to `action_executor.execute_and_verify` directly for simple single-step actions (skip planning overhead when it's just "unlock" or "what's my battery").

#### [NEW] [security_vault.py](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/security_vault.py)
- `check_sensitive_action_intent(instruction, session_state) -> SensitiveActionResult`, fully specified (the original plan named this but left it unspecified):
  - Classifies instructions against a sensitive-action list (unlock, send message, make payment, delete data, open banking/authenticator apps).
  - If sensitive and not yet confirmed this session: returns `needs_confirmation=True` and a `confirmation_prompt` string; writes a `pending_confirmation` entry (instruction hash + timestamp, short TTL e.g. 2 minutes) into `session_state`.
  - On the user's **next turn**, if it affirmatively answers the pending confirmation (checked via `session_state`, not re-parsed from scratch), the action proceeds; otherwise the pending confirmation expires and must be re-asked. This closes the "stub" gap from the original plan.
- Confirms no plaintext credential ever enters `session_state`, logs, or the LLM context — only the *decision* to unlock, never the PIN.

---

### Component 3: Brain & Prompt Intelligence (`backend/main.py` & `backend/engines/llm_engine.py`)

#### [MODIFY] [llm_engine.py](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/llm_engine.py)
- System prompt updated to describe the **general** capability, not just unlock:
  - Alita perceives real screen state before acting on any instruction, for any app.
  - She narrates multi-step tasks step-by-step as they execute ("Opening WhatsApp… found Rahul's chat… typing your message…") rather than only at the end.
  - She reports verified outcomes per step, and explicitly flags when something on-screen didn't match expectations instead of assuming success.
  - She asks for confirmation before sensitive actions and remembers a pending confirmation into the next turn.
  - She can discuss battery, notifications, open apps, and now also **what's currently visible on screen** (from the last `read_screen()` call), grounded in real telemetry.

#### [MODIFY] [main.py](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/main.py)
- `_build_system_prompt` injects `[CONNECTED MOBILE COMPANION TELEMETRY]` as before (device, status, screen lock state, battery, active app, top notifications), plus a compact **on-screen element summary** (e.g., "Visible: Send button, message input field, contact 'Rahul'") when a task is mid-execution, so the model's next planning step is grounded in the real UI rather than an assumption.
- Session state carries `pending_confirmation` (from `security_vault.py`) and `active_task_plan` (from `task_planner.py`) so multi-turn confirmations and in-progress multi-step tasks survive across chat turns.

---

## Verification Plan

### Automated Empirical Tests

1. **Generic Action Verification (`test_action_executor.py`)**
   - Test 1: `execute_and_verify` on a tap action succeeds and returns before the full timeout when the expected state is reached early (proves polling, not fixed-sleep).
   - Test 2: A tap that doesn't produce the expected screen triggers exactly `max_retries` retries, then returns a structured failure with the last observed screen attached.

2. **Screen Perception (`test_screen_reading.py`)**
   - Test 3: `read_screen()` on a known app returns expected element text/resource-ids.
   - Test 4: When the accessibility tree is empty/sparse, the fallback screenshot path is invoked automatically.

3. **Interruption Handling (`test_interruption_handler.py`)**
   - Test 5: A known OEM popup (e.g., autostart prompt) is auto-dismissed via the known-popup table without halting the task.
   - Test 6: An unrecognized dialog pauses the task and surfaces `unhandledPopup` rather than guessing an action.

4. **Multi-Step Task Planning (`test_task_planner.py`)**
   - Test 7: A "send WhatsApp message to X" instruction produces a step plan, each step is individually verified, and a mismatched intermediate screen triggers replanning rather than continuing blindly.

5. **Security (`test_credential_security.py`)**
   - Test 8: Grep backend source and logs for the PIN value — assert it never appears in plaintext anywhere in `backend/`.
   - Test 9: Unlock command payload sent from backend to bridge contains no credential field.

6. **Confirmation State Persistence (`test_security_vault.py`)**
   - Test 10: A sensitive instruction sets `pending_confirmation`; an affirmative reply on the next turn proceeds without re-asking; an unrelated reply lets the confirmation expire after TTL.

### Manual Verification
- Say *"Unlock my phone"* while unlocked → Alita confirms already-unlocked, no credential ever leaves the device.
- Say *"Open WhatsApp and message Rahul that I'm running late"* → Alita narrates each verified step and reports the final confirmed send state.
- Trigger a permission dialog mid-task (e.g., first-time camera access) → Alita either auto-dismisses (if known) or pauses and asks, rather than stalling silently.
- Ask *"What's on my screen right now?"* mid-task → Alita answers from the live accessibility read, not a guess.
- Inspect the backend repo and logs directly → confirm no PIN string appears anywhere in plaintext.
