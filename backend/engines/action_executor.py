"""
action_executor.py — Closed-Loop Perceive → Act → Verify Execution Engine

Wraps every phone action (tap, swipe, type, launch, unlock) in closed-loop state verification:
1. Perceive: Captures live phone state and view-tree before acting.
2. Act: Dispatches action micro-instruction to device bridge.
3. Verify: Polls state/screen (every 150ms) until expected condition is verified or timeout.
4. Self-Healing & Retry: Resolves interruptions or performs bounded retries on failure.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from engines.interruption_handler import interruption_handler, InterruptionResult
from engines.screen_analyzer import screen_analyzer, ScreenContext

logger = logging.getLogger("alita.action_executor")


@dataclass
class ExecutionOutcome:
    success: bool
    verified: bool
    retries_attempted: int = 0
    action: Dict[str, Any] = field(default_factory=dict)
    pre_state: Dict[str, Any] = field(default_factory=dict)
    post_state: Dict[str, Any] = field(default_factory=dict)
    interruption: Optional[InterruptionResult] = None
    elapsed_s: float = 0.0
    error: Optional[str] = None
    error_type: Optional[str] = None  # "ELEMENT_NOT_FOUND", "WRONG_SCREEN", "POPUP_BLOCKING", "LOADING", "TIMEOUT"
    screen_context: Optional[ScreenContext] = None
    message: str = ""


class ActionExecutor:
    """
    Universal closed-loop action execution and verification engine.
    """

    def __init__(self, bridge_dispatch_fn: Optional[Callable[[Dict[str, Any]], Any]] = None):
        self._dispatch = bridge_dispatch_fn

    def set_bridge_dispatcher(self, dispatch_fn: Callable[[Dict[str, Any]], Any]) -> None:
        self._dispatch = dispatch_fn

    async def execute_and_verify(
        self,
        action: Dict[str, Any],
        expected_state_fn: Callable[[Dict[str, Any]], bool],
        get_state_fn: Callable[[], Any],
        read_screen_fn: Optional[Callable[[], Any]] = None,
        timeout_s: float = 3.0,
        poll_interval_s: float = 0.15,
        max_retries: int = 1,
    ) -> ExecutionOutcome:
        """
        Execute an action with closed-loop perception and verification.
        
        Args:
            action: Action dict (e.g. {"command": "tap", "x": 500, "y": 800})
            expected_state_fn: Predicate returning True when desired post-action state is reached.
            get_state_fn: Async or sync function returning current phone telemetry/state.
            read_screen_fn: Optional async function returning active view-tree.
            timeout_s: Verification timeout in seconds (default 3.0s).
            poll_interval_s: Interval between state polls (default 150ms).
            max_retries: Maximum retries if verification fails (default 1).
        """
        start_time = time.time()
        retries = 0
        screen_ctx: Optional[ScreenContext] = None

        # Step 1: Perceive (Pre-State & Screen Analysis)
        pre_state = await self._call_async_or_sync(get_state_fn)
        if read_screen_fn:
            pre_screen = await self._call_async_or_sync(read_screen_fn)
            if isinstance(pre_state, dict) and isinstance(pre_screen, dict):
                pre_state["view_tree"] = pre_screen
                screen_ctx = screen_analyzer.analyze_screen(pre_screen)

                # Smart Wait: If screen shows loading spinner, wait for it to settle (up to 2.5s)
                if screen_ctx.has_loading_spinner:
                    logger.info("Screen shows loading state before action. Waiting for screen to settle...")
                    settle_start = time.time()
                    while time.time() - settle_start < 2.5:
                        await asyncio.sleep(0.3)
                        updated_screen = await self._call_async_or_sync(read_screen_fn)
                        if isinstance(updated_screen, dict):
                            pre_screen = updated_screen
                            pre_state["view_tree"] = updated_screen
                            screen_ctx = screen_analyzer.analyze_screen(updated_screen)
                            if not screen_ctx.has_loading_spinner:
                                logger.info("Screen settled from loading state.")
                                break

                # Smart Pre-Action Target Resolution:
                # If action wants to tap/click a target or semantic query, resolve coordinates from screen tree
                target_query = action.get("find_target") or action.get("target")
                if target_query and action.get("command") in ("click", "tap") and ("x" not in action or "y" not in action):
                    matched_node = screen_analyzer.find_element_smart(pre_screen, target_query)
                    if matched_node:
                        b = screen_analyzer._parse_bounds(matched_node.get("bounds"))
                        if b["cx"] > 0 and b["cy"] > 0:
                            action["x"] = float(b["cx"])
                            action["y"] = float(b["cy"])
                            action["command"] = "tap"
                            logger.info(f"Smart pre-action resolved '{target_query}' to ({action['x']}, {action['y']})")
                        elif matched_node.get("resourceId"):
                            action["resourceId"] = matched_node["resourceId"]
                            if matched_node.get("text"):
                                action["target"] = matched_node["text"]

        # Imperative actions (tap, swipe, global navigation, click) must never short-circuit pre-execution.
        can_short_circuit = action.get("command") in ("unlock", "unlock_screen", "launch_app")
        if can_short_circuit:
            try:
                if expected_state_fn(pre_state):
                    logger.info(f"Action '{action.get('command')}' already in expected state. Short-circuiting.")
                    return ExecutionOutcome(
                        success=True,
                        verified=True,
                        retries_attempted=0,
                        action=action,
                        pre_state=pre_state,
                        post_state=pre_state,
                        screen_context=screen_ctx,
                        elapsed_s=time.time() - start_time,
                        message="Target state already achieved.",
                    )
            except Exception as e:
                logger.debug(f"Pre-state check evaluated with exception: {e}")

        last_observed_state = pre_state

        while retries <= max_retries:
            # Step 2: Act
            if not self._dispatch:
                return ExecutionOutcome(
                    success=False,
                    verified=False,
                    error="No bridge dispatcher configured.",
                    elapsed_s=time.time() - start_time,
                )

            logger.info(f"Dispatching action: {action.get('command')} (attempt {retries + 1}/{max_retries + 1})")
            act_res = None
            try:
                act_res = await self._call_async_or_sync(lambda: self._dispatch(action))
            except Exception as e:
                logger.warning(f"Bridge dispatch raised exception: {e}")

            # Step 3: Perceive & Verify (Post-State)
            poll_start = time.time()
            is_verified = False
            is_app_launch = (action.get("command") == "launch_app")
            is_unlock = (action.get("command") in ("unlock", "unlock_screen"))

            while time.time() - poll_start < timeout_s:
                await asyncio.sleep(min(0.3, poll_interval_s) if (is_app_launch or is_unlock) else poll_interval_s)
                curr_state = await self._call_async_or_sync(get_state_fn)
                # For app launches and unlocks, avoid choking phone with continuous read_screen
                if read_screen_fn and not is_app_launch and not is_unlock:
                    curr_screen = await self._call_async_or_sync(read_screen_fn)
                    if isinstance(curr_state, dict) and isinstance(curr_screen, dict):
                        curr_state["view_tree"] = curr_screen

                last_observed_state = curr_state

                try:
                    if expected_state_fn(curr_state):
                        is_verified = True
                        break
                except Exception as e:
                    logger.debug(f"Verification predicate check: {e}")

            # Fallback for launch_app: if the phone confirmed the intent was launched successfully
            if not is_verified and is_app_launch and act_res and act_res.get("success"):
                logger.info(f"App launch intent confirmed by phone bridge for {action.get('package')}; accepting as launched.")
                is_verified = True

            # Direct verification for global actions: if the phone confirmed the global action was performed
            if not is_verified and action.get("command") == "global" and act_res and act_res.get("success"):
                logger.info(f"Global action '{action.get('action')}' confirmed by phone bridge.")
                is_verified = True

            # Direct verification for unlock: if the phone bridge confirmed keyguard dismissed or already unlocked
            if not is_verified and is_unlock and act_res and (
                act_res.get("isLocked") is False or
                act_res.get("alreadyUnlocked") or
                act_res.get("verifiedUnlocked")
            ):
                logger.info(f"Screen unlock confirmed by phone bridge ({act_res.get('message', 'Keyguard dismissed')}); accepting as unlocked.")
                is_verified = True
                if isinstance(last_observed_state, dict):
                    last_observed_state["isLocked"] = False
                    if act_res.get("currentPackage"):
                        last_observed_state["currentPackage"] = act_res["currentPackage"]
                    if act_res.get("alreadyUnlocked"):
                        last_observed_state["alreadyUnlocked"] = True

            if is_verified:
                elapsed = time.time() - start_time
                logger.info(f"Action '{action.get('command')}' verified successfully in {elapsed:.2f}s")
                post_ctx = screen_analyzer.analyze_screen(last_observed_state.get("view_tree", {})) if isinstance(last_observed_state, dict) else screen_ctx
                return ExecutionOutcome(
                    success=True,
                    verified=True,
                    retries_attempted=retries,
                    action=action,
                    pre_state=pre_state,
                    post_state=last_observed_state,
                    screen_context=post_ctx,
                    elapsed_s=elapsed,
                    message="Target state already achieved." if (isinstance(last_observed_state, dict) and last_observed_state.get("alreadyUnlocked")) else "Action successfully verified.",
                )

            # Step 4: Verification failed — Diagnose error type & execute smart recovery
            screen_tree = last_observed_state.get("view_tree", {}) if isinstance(last_observed_state, dict) else {}
            interruption = interruption_handler.detect_interruption(screen_tree)
            current_ctx = screen_analyzer.analyze_screen(screen_tree) if screen_tree else None

            # Error Classification
            error_type = "TIMEOUT"
            if interruption.is_interrupted:
                error_type = "POPUP_BLOCKING"
            elif current_ctx and current_ctx.has_loading_spinner:
                error_type = "LOADING"
            elif action.get("target") or action.get("find_target"):
                # If target was expected on screen but couldn't be verified
                error_type = "ELEMENT_NOT_FOUND"

            logger.warning(f"Verification failure classified as: {error_type}")

            if interruption.is_interrupted:
                logger.warning(f"Interruption detected during verification: {interruption.dialog_title}")
                if interruption.auto_resolvable and interruption.target_button:
                    # Auto-dismiss popup and re-poll
                    dismiss_res = await interruption_handler.resolve_known_popup(
                        interruption,
                        lambda btn: self._dispatch({"command": "click", "target": btn})
                    )
                    if dismiss_res:
                        logger.info("Known popup dismissed. Re-verifying expected state...")
                        await asyncio.sleep(0.4)
                        curr_state = await self._call_async_or_sync(get_state_fn)
                        if expected_state_fn(curr_state):
                            return ExecutionOutcome(
                                success=True,
                                verified=True,
                                retries_attempted=retries,
                                action=action,
                                pre_state=pre_state,
                                post_state=curr_state,
                                interruption=interruption,
                                screen_context=current_ctx,
                                elapsed_s=time.time() - start_time,
                                message="Interruption auto-resolved and action verified.",
                            )
                else:
                    # Unhandled popup — halt retries and surface to user
                    return ExecutionOutcome(
                        success=False,
                        verified=False,
                        retries_attempted=retries,
                        action=action,
                        pre_state=pre_state,
                        post_state=last_observed_state,
                        interruption=interruption,
                        error_type=error_type,
                        screen_context=current_ctx,
                        elapsed_s=time.time() - start_time,
                        error=f"Task paused: {interruption.dialog_title} ({interruption.suggested_action})",
                    )

            # Smart Recovery per error type before next retry
            retries += 1
            if retries <= max_retries:
                if error_type == "ELEMENT_NOT_FOUND" and self._dispatch:
                    # Scroll down to reveal hidden element
                    logger.info("ELEMENT_NOT_FOUND: Attempting scroll down before retry...")
                    try:
                        await self._call_async_or_sync(lambda: self._dispatch({
                            "command": "swipe",
                            "startX": 540.0,
                            "startY": 1500.0,
                            "endX": 540.0,
                            "endY": 700.0,
                            "duration": 300,
                        }))
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        logger.debug(f"Scroll recovery error: {e}")

                elif error_type == "LOADING":
                    logger.info("LOADING: Pausing 1.0s for UI to settle...")
                    await asyncio.sleep(1.0)
                else:
                    logger.info(f"Verification timeout after {timeout_s}s. Retrying action...")
                    await asyncio.sleep(0.3)

        return ExecutionOutcome(
            success=False,
            verified=False,
            retries_attempted=retries - 1,
            action=action,
            pre_state=pre_state,
            post_state=last_observed_state,
            error_type=error_type,
            screen_context=current_ctx,
            elapsed_s=time.time() - start_time,
            error=f"Action '{action.get('command')}' failed verification after {max_retries + 1} attempts ({error_type}).",
        )

    async def _call_async_or_sync(self, fn: Callable, *args, **kwargs) -> Any:
        if not fn:
            return {}
        res = fn(*args, **kwargs)
        if asyncio.iscoroutine(res) or isinstance(res, asyncio.Future):
            return await res
        return res


# Global singleton
action_executor = ActionExecutor()
