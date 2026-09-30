# pyre-ignore-all-errors
"""
Compound Multi-App Pipeline Engine
===================================
Executes sequential multi-step workflows parsed from single-sentence commands.
Supports in-memory inter-step data buffers:
  - Screenshots → Passed directly into WhatsApp/Discord/Email file sharing
  - Scraped/Copied text → Passed into Notepad/Word/Search actions
  - System controls → Volume/Brightness/Dark Mode chaining
"""

import os
import re
import time
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("alita.pipeline")

# Regex to split multilingual chained sentences
_SPLIT_REGEX = re.compile(
    r'\s+(?:and then|and also|and|then|after that|phir|aur phir|aur|uske baad|fir)\s+',
    re.IGNORECASE
)

# Avoid splitting numbers or file names (e.g., "cats and dogs.txt")
_FALSE_SPLIT_PATTERNS = [
    re.compile(r'\b(copy|paste)\s+and\s+(match|paste)\b', re.IGNORECASE),
    re.compile(r'\b(search|look up)\s+.*\s+and\s+.*\b', re.IGNORECASE),
]


class PipelineContext:
    """In-memory data blackboard passed between pipeline steps."""
    def __init__(self) -> None:
        self.screenshot_path: Optional[str] = None
        self.clipboard_data: Optional[str] = None
        self.last_app: Optional[str] = None
        self.extracted_text: Optional[str] = None
        self.target_device: Optional[str] = None
        self.step_results: List[Dict[str, Any]] = []


class CompoundPipeline:
    """Orchestrates sequential multi-step actions across different system components."""

    def __init__(self) -> None:
        pass

    def is_compound(self, text: str) -> bool:
        """Determine if a query contains sequential compound actions."""
        text_lower = text.lower().strip()
        # Must contain at least one connector
        if not _SPLIT_REGEX.search(text_lower):
            return False

        # Guard: Check if it's just a conversational question
        if re.search(r'^(what|how|why|who|where|is|are|can you explain)\b', text_lower):
            return False

        steps = self.split_steps(text)
        return len(steps) >= 2

    def split_steps(self, command: str) -> List[str]:
        """Split a compound sentence into individual actionable command strings."""
        parts = _SPLIT_REGEX.split(command.strip())
        steps = []
        for p in parts:
            clean = p.strip()
            if clean and len(clean.split()) >= 1:
                # Normalize leading verbs if needed
                steps.append(clean)
        return steps if len(steps) > 1 else [command]

    def execute(
        self,
        command: str,
        session: Optional[Any] = None,
        settings: Optional[Any] = None,
        notify: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> Dict[str, Any]:
        """
        Execute a compound pipeline sequentially with inter-step data propagation.
        """
        steps = self.split_steps(command)
        ctx = PipelineContext()
        t0 = time.perf_counter()

        # Pre-resolve initial device target from the complete compound instruction
        try:
            from engines.semantic_target_binder import semantic_target_binder
            init_bind = semantic_target_binder.resolve(command)
            if init_bind.get("target_device"):
                ctx.target_device = init_bind["target_device"]
        except Exception as _e:
            logger.debug("[CompoundPipeline] Initial target bind check: %s", _e)

        logger.info("[CompoundPipeline] Starting %d-step pipeline (device=%s) for: '%s'",
                    len(steps), ctx.target_device, command[:60])
        if notify:
            notify({
                "type": "pipeline_started",
                "total_steps": len(steps),
                "steps": steps,
                "command": command
            })

        from threads.automation_handler import handle_automation, _fast_parse_automation_command

        for idx, step_text in enumerate(steps):
            step_num = idx + 1
            logger.info("[CompoundPipeline] Executing Step %d/%d: '%s'", step_num, len(steps), step_text)

            if notify:
                notify({
                    "type": "pipeline_step",
                    "step": step_num,
                    "total_steps": len(steps),
                    "step_text": step_text,
                    "thought": f"Executing Step {step_num}/{len(steps)}: {step_text}"
                })

            step_res = self._execute_single_step(step_text, ctx, session, settings)
            ctx.step_results.append({
                "step": step_num,
                "command": step_text,
                "result": step_res
            })

            # Brief inter-step stabilization delay
            if idx < len(steps) - 1:
                time.sleep(0.35)

        elapsed = (time.perf_counter() - t0) * 1000
        summary_items = [f"Step {r['step']}: {r['command']} -> {r['result'].get('detail', 'done')}" for r in ctx.step_results]
        summary_text = " | ".join(summary_items)

        logger.info("[CompoundPipeline] Pipeline finished in %.1fms: %s", elapsed, summary_text[:80])
        if notify:
            notify({
                "type": "pipeline_complete",
                "total_steps": len(steps),
                "elapsed_ms": elapsed,
                "summary": summary_text
            })

        return {
            "status": "success",
            "steps_count": len(steps),
            "elapsed_ms": elapsed,
            "summary": summary_text,
            "results": ctx.step_results
        }

    def _execute_single_step(
        self,
        step_text: str,
        ctx: PipelineContext,
        session: Optional[Any],
        settings: Optional[Any]
    ) -> Dict[str, Any]:
        """Execute a single step, injecting context from previous steps if available."""
        from threads.automation_handler import handle_automation, _fast_parse_automation_command
        import pyautogui

        step_lower = step_text.lower()

        # Step Device Target Resolution (inherited from previous step or compound query)
        try:
            from engines.semantic_target_binder import semantic_target_binder
            step_sem = semantic_target_binder.resolve(step_text, inherited_target=ctx.target_device)
            step_device = step_sem.get("target_device") or ctx.target_device
            if step_device:
                ctx.target_device = step_device
        except Exception as _b_err:
            logger.debug("[CompoundPipeline] Target bind error: %s", _b_err)
            step_device = ctx.target_device

        # Step Type 0: Mobile Phone Companion Execution
        if step_device == "phone":
            try:
                from engines.phone_orchestrator import phone_orchestrator
                import asyncio
                import concurrent.futures
                st_dict = getattr(session, "__dict__", {})
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop and loop.is_running():
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                        res = ex.submit(asyncio.run, phone_orchestrator.run_instruction(step_text, session_state=st_dict)).result(timeout=15)
                else:
                    res = asyncio.run(phone_orchestrator.run_instruction(step_text, session_state=st_dict))

                if res.get("success"):
                    detail_msg = res.get("message", "Done on your phone.")
                elif res.get("needs_confirmation"):
                    detail_msg = res.get("confirmation_prompt") or res.get("prompt") or "Please confirm to proceed on your phone."
                else:
                    detail_msg = res.get("message") or res.get("error") or "Completed on your phone."

                return {
                    "status": "success" if res.get("success") else ("pending" if res.get("needs_confirmation") else "error"),
                    "action": "phone_orchestrator",
                    "detail": detail_msg
                }
            except Exception as _ph_err:
                logger.warning("[CompoundPipeline] Mobile phone dispatch error: %s", _ph_err)

        # Step Type A: Screenshot Capture
        if re.search(r'\b(screenshot|capture\s+screen|screen\s+grab)\b', step_lower):
            try:
                import tempfile
                import mss
                from PIL import Image

                with mss.mss() as sct:
                    monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
                    shot = sct.grab(monitor)
                    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                    tmp_dir = os.path.join(os.environ.get("TEMP", "."), "alita_pipeline")
                    os.makedirs(tmp_dir, exist_ok=True)
                    shot_path = os.path.join(tmp_dir, f"screenshot_{int(time.time())}.png")
                    img.save(shot_path, format="PNG")
                    ctx.screenshot_path = shot_path

                    return {
                        "status": "success",
                        "action": "screenshot",
                        "detail": f"Captured screenshot to {shot_path}",
                        "file_path": shot_path
                    }
            except Exception as e:
                logger.error("[CompoundPipeline] Screenshot failed: %s", e)

        # Step Type B: WhatsApp / File Sharing (Inter-step propagation)
        if re.search(r'\b(whatsapp|send|share)\b', step_lower) and ctx.screenshot_path:
            # Inject the captured screenshot path into sharing action
            try:
                from engines.screen_agent import _exec_send_file
                params = {
                    "target_app": "whatsapp",
                    "target": "whatsapp",
                    "file_name": ctx.screenshot_path,
                    "file": ctx.screenshot_path,
                }
                # Extract recipient name if mentioned
                name_match = re.search(r'(?:to|ko|pe)\s+([A-Za-z0-9_]+)', step_text)
                if name_match:
                    params["contact"] = name_match.group(1)
                res = _exec_send_file(params, lambda x: None)
                return {"status": "success", "action": "send_file", "detail": res}
            except Exception as e:
                logger.debug(f"[CompoundPipeline] Injected share failed: {e}")

        # Step Type C: Standard Automation Dispatch
        tokens = handle_automation(step_text, session, settings, "", [], 100, None)
        detail_msg = "".join(t for t in tokens if isinstance(t, str)) or f"Completed: {step_text}"
        return {"status": "success", "action": "automation", "detail": detail_msg}


# Singleton instance
compound_pipeline = CompoundPipeline()
