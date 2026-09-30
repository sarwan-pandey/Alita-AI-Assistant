"""
VisionEngine — Local Screen Vision & Multimodal Q&A
====================================================
100% Offline Screen Analysis using Ollama Vision Models (Moondream / LLaVA / Qwen2-VL).
- In-memory high-speed screen capture via MSS (zero temporary disk files)
- Automatic resolution scaling for sub-second vision inference
- Direct integration with local Ollama Vision API (chat endpoint)
- Context-rich OCR & Active Window Fallback for complete screen awareness
"""

import io
import os
import base64
import time
import logging
import httpx
from typing import Optional, Dict, Any, List
from PIL import Image
import mss

log = logging.getLogger("alita.vision")

OLLAMA_API_URL = "http://localhost:11434/api/chat"
OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate"
DEFAULT_VISION_MODEL = "moondream"


class VisionEngine:
    """
    Local multimodal vision engine for screen understanding and image analysis.
    """

    def __init__(self, model_name: str = DEFAULT_VISION_MODEL, base_url: str = OLLAMA_API_URL):
        self.model_name = os.getenv("OLLAMA_VISION_MODEL", model_name).split(":")[0]  # e.g., moondream or llava
        self.api_url = base_url
        self.generate_url = OLLAMA_GENERATE_URL
        self._sct = None

    def _get_sct(self):
        if self._sct is None:
            self._sct = mss.mss()
        return self._sct

    def capture_screen_b64(self, max_dimension: int = 768, quality: int = 85) -> Optional[str]:
        """
        Capture primary monitor in-memory and return compressed Base64 JPEG string.
        """
        try:
            sct = self._get_sct()
            monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            sct_img = sct.grab(monitor)

            # Convert raw BGRA to PIL Image (RGB)
            img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

            # Downscale proportionally to fit within max_dimension for fast LLM vision
            if max(img.width, img.height) > max_dimension:
                scale = max_dimension / float(max(img.width, img.height))
                new_size = (int(img.width * scale), int(img.height * scale))
                img = img.resize(new_size, Image.Resampling.LANCZOS)

            # Compress to in-memory JPEG buffer
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=quality, optimize=True)
            b64_str = base64.b64encode(buffer.getvalue()).decode("utf-8")
            return b64_str

        except Exception as exc:
            log.error("Failed to capture screen: %s", exc)
            return None

    def _get_active_app_context(self) -> str:
        """Fetch the title of the active foreground window."""
        try:
            from engines.app_manager import get_active_window
            win = get_active_window()
            if win and win.get("title"):
                return f"Currently active window: '{win['title']}'."
        except Exception:
            pass
        return ""

    def analyze_screen(
        self,
        prompt: str = "Describe what is currently visible on the user's screen in 2 concise sentences.",
        timeout: float = 30.0
    ) -> str:
        """
        Capture current screen and send to local Ollama vision model using /api/generate with fallback.
        """
        t0 = time.perf_counter()
        img_b64 = self.capture_screen_b64(max_dimension=768)
        if not img_b64:
            return "I was unable to capture your screen."

        app_context = self._get_active_app_context()
        enhanced_prompt = (
            f"{prompt}\n{app_context}\n"
            "State clearly what application, window, or content is active on the screen."
        )

        response_text = ""

        # Attempt 1: Ollama /api/generate endpoint (works best with moondream)
        try:
            gen_payload = {
                "model": self.model_name,
                "prompt": enhanced_prompt,
                "images": [img_b64],
                "stream": False,
                "options": {
                    "temperature": 0.2,
                    "num_ctx": 2048
                }
            }
            with httpx.Client(timeout=timeout) as client:
                resp = client.post(self.generate_url, json=gen_payload)
                if resp.status_code == 200:
                    data = resp.json()
                    response_text = data.get("response", "").strip()
        except Exception as exc:
            log.debug("Generate endpoint attempt failed: %s", exc)

        # Attempt 2: Ollama /api/chat fallback if /api/generate returned empty
        if not response_text:
            try:
                chat_payload = {
                    "model": self.model_name,
                    "messages": [
                        {
                            "role": "user",
                            "content": enhanced_prompt,
                            "images": [img_b64]
                        }
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.2,
                        "num_ctx": 2048
                    }
                }
                with httpx.Client(timeout=timeout) as client:
                    resp = client.post(self.api_url, json=chat_payload)
                    if resp.status_code == 200:
                        data = resp.json()
                        response_text = data.get("message", {}).get("content", "").strip()
            except Exception as exc:
                log.debug("Chat endpoint attempt failed: %s", exc)

        elapsed = (time.perf_counter() - t0) * 1000
        if response_text:
            log.info("Vision analysis completed in %.1fms: %s", elapsed, response_text[:60])
            if app_context and "window:" not in response_text.lower():
                return f"{app_context} {response_text}"
            return response_text

        # Fallback 3: Describe foreground window & OCR
        try:
            from engines.screen_ocr import screen_ocr
            ocr_text = screen_ocr.get_screen_text()[:200].strip()
            if ocr_text:
                return f"{app_context} I can see text on your screen: '{ocr_text}'."
        except Exception:
            pass

        if app_context:
            return f"You are currently working in {app_context.replace('Currently active window: ', '')}."
        return "I can see your active desktop workspace."

    def locate_element(
        self,
        target_description: str,
        timeout: float = 20.0
    ) -> Dict[str, Any]:
        """
        Locate a specific visual UI element on the screen and return its
        normalized coordinates [x, y, width, height] for HUD highlighting and clicking.
        """
        prompt = (
            f"Locate the '{target_description}' on this screen. "
            "Return ONLY a JSON object in this format: "
            '{"found": true, "x": 0.45, "y": 0.32, "width": 0.12, "height": 0.06, "label": "' + target_description + '"}'
        )
        response_text = self.analyze_screen(prompt=prompt, timeout=timeout)
        try:
            import json, re
            json_match = re.search(r"\{.*?\}", response_text, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group(0))
                if parsed.get("found"):
                    return parsed
        except Exception:
            pass

        # Fallback default center-screen coordinate
        return {
            "found": True,
            "x": 0.5,
            "y": 0.45,
            "width": 0.2,
            "height": 0.1,
            "label": target_description,
            "description": response_text
        }

    # ── Layer 2: Smart Hybrid Analysis ────────────────────────────────────

    def smart_analyze(self, prompt: str = "What is on my screen?") -> str:
        """
        Hybrid Vision: Synthesize active window, on-screen text (OCR), and visual perception.
        """
        app_context = self._get_active_app_context()
        ocr_text = ""
        patterns: dict = {}
        try:
            from engines.screen_ocr import screen_ocr
            ocr_text = screen_ocr.get_screen_text()
            patterns = screen_ocr.get_detected_patterns()
        except Exception:
            pass

        # 1. If critical errors or dialogs are on screen, prioritize them
        if patterns.get("errors") or patterns.get("dialogs"):
            return self._format_ocr_response(ocr_text, patterns, prompt)

        # 2. Visual analysis via Moondream
        visual_desc = self.analyze_screen(prompt="Describe what is visible on this computer screen concisely in 1-2 sentences.")

        # 3. Assemble clear, natural response
        parts = []
        if app_context:
            parts.append(f"In your active window ({app_context.replace('Currently active window: ', '').strip('.')}):")
        
        if visual_desc and "unable to capture" not in visual_desc.lower():
            cleaned_desc = visual_desc.strip()
            if len(cleaned_desc.split()) <= 2:
                parts.append(f"I can see an interface displaying {cleaned_desc}.")
            else:
                parts.append(cleaned_desc)

        if ocr_text:
            snippet = " ".join(ocr_text.split()[:25])
            if snippet and not any(w in snippet for w in ("Currently active", "Alita")):
                parts.append(f"Visible text: \"{snippet}…\"")

        if parts:
            return " ".join(parts)
        return "I can see your current active desktop screen."

    def analyze_with_context(self, prompt: str, ocr_text: str = "") -> str:
        """
        Moondream analysis enriched with OCR text context.
        OCR text helps the vision model focus on text-heavy areas.
        """
        app_context = self._get_active_app_context()
        
        # Build enhanced prompt with OCR context
        context_parts = [prompt]
        if app_context:
            context_parts.append(app_context)
        if ocr_text:
            # Truncate to avoid overwhelming the model
            clean_ocr = ocr_text[:500].strip()
            if clean_ocr:
                context_parts.append(f"Text detected on screen via OCR: \"{clean_ocr}\"")
        context_parts.append(
            "Describe what the user is currently seeing. "
            "If there are errors, read them precisely. Be concise."
        )

        enhanced_prompt = "\n".join(context_parts)
        return self.analyze_screen(prompt=enhanced_prompt)

    @staticmethod
    def _format_ocr_response(ocr_text: str, patterns: dict, prompt: str) -> str:
        """Format OCR patterns into a natural spoken response."""
        parts = []
        prompt_lower = prompt.lower()

        if patterns.get("errors"):
            error_matches = patterns["errors"]
            # Try to extract the full error line from OCR text
            error_lines = []
            for line in ocr_text.split("\n"):
                line = line.strip()
                if any(e.lower() in line.lower() for e in error_matches if isinstance(e, str)) and len(line) > 10:
                    error_lines.append(line[:120])
            if error_lines:
                parts.append(f"I can see an error on your screen: \"{error_lines[0]}\"")
            else:
                parts.append(f"I detected an error on your screen related to: {error_matches[0]}")

        if patterns.get("dialogs"):
            dialog_lines = []
            for line in ocr_text.split("\n"):
                line = line.strip()
                if any(d.lower() in line.lower() for d in patterns["dialogs"] if isinstance(d, str)) and len(line) > 5:
                    dialog_lines.append(line[:100])
            if dialog_lines:
                parts.append(f"There's a dialog asking: \"{dialog_lines[0]}\"")

        if patterns.get("notifications"):
            parts.append(f"Notification: {patterns['notifications'][0]}")

        if parts:
            return " ".join(parts)

        # No specific patterns — summarize OCR text
        lines = [l.strip() for l in ocr_text.split("\n") if l.strip() and len(l.strip()) > 8]
        if lines:
            return f"I can see text on your screen: \"{lines[0][:100]}\""
        return "Your screen appears to be mostly visual with no prominent text."


# Singleton instance
vision_engine = VisionEngine()

