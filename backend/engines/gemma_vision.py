"""
Gemma 4 31B IT Vision Client — NVIDIA NIM
===========================================
Dedicated vision analysis client for screenshot understanding, OCR,
image analysis, UI understanding, and visual verification.

Key features:
  - Adaptive visual-token budgets (low for classification, high for OCR)
  - Structured findings returned to MJ
  - No device execution authority
  - OpenAI-compatible streaming via NVIDIA NIM
  - Base64 image input
  - Detailed timing metrics

This module does NOT replace Lightning for conversation.
Gemma activates ONLY for vision-specific requests.
"""

from __future__ import annotations

import base64
import io
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("alita.gemma_vision")


# ── Vision Task Types ────────────────────────────────────────────────────────

class VisionTask(str, Enum):
    """Types of vision analysis with corresponding token budgets."""
    SCREENSHOT_CLASSIFY = "screenshot_classify"   # What app/screen is this?
    UI_ELEMENT_FIND = "ui_element_find"           # Find button/field/element
    OCR_READ = "ocr_read"                         # Read text from image
    IMAGE_DESCRIBE = "image_describe"             # General image description
    VISUAL_VERIFY = "visual_verify"               # Verify UI state/action result
    VIDEO_FRAME = "video_frame"                   # Analyze a video frame


# Token budget per task — low for simple classification, high for OCR
_TOKEN_BUDGETS: Dict[VisionTask, int] = {
    VisionTask.SCREENSHOT_CLASSIFY: 128,    # Just identify the screen
    VisionTask.UI_ELEMENT_FIND: 256,        # Describe element location
    VisionTask.OCR_READ: 1024,              # Full text extraction
    VisionTask.IMAGE_DESCRIBE: 512,         # General description
    VisionTask.VISUAL_VERIFY: 256,          # Yes/no + brief explanation
    VisionTask.VIDEO_FRAME: 512,            # Frame analysis
}


# ── Metrics ──────────────────────────────────────────────────────────────────

@dataclass
class VisionMetrics:
    """Timing and quality metrics for a vision analysis request."""
    request_start: float = 0.0
    first_token_time: float = 0.0
    response_complete_time: float = 0.0

    # Derived
    ttft_ms: float = 0.0
    total_ms: float = 0.0

    # Content
    task: str = ""
    prompt_preview: str = ""
    image_size_bytes: int = 0
    response_text: str = ""
    max_tokens_used: int = 0

    # Token usage
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    # Status
    success: bool = False
    error: str = ""
    model_id: str = ""

    def finalize(self) -> None:
        if self.first_token_time and self.request_start:
            self.ttft_ms = (self.first_token_time - self.request_start) * 1000
        if self.response_complete_time and self.request_start:
            self.total_ms = (self.response_complete_time - self.request_start) * 1000

    def summary(self) -> str:
        status = "OK" if self.success else f"FAIL({self.error[:40]})"
        return (
            f"[gemma_vision] {status} | "
            f"Task={self.task} | TTFT={self.ttft_ms:.0f}ms | "
            f"Total={self.total_ms:.0f}ms | "
            f"Tokens={self.prompt_tokens}+{self.completion_tokens}={self.total_tokens} | "
            f"ImgSize={self.image_size_bytes}b | "
            f"Response={len(self.response_text)}c"
        )


# ── Structured Findings ─────────────────────────────────────────────────────

@dataclass
class VisionFindings:
    """Structured output from vision analysis, returned to MJ."""
    task: VisionTask
    success: bool = False
    description: str = ""         # Natural language summary
    elements_found: List[str] = field(default_factory=list)  # UI elements, text blocks
    confidence: str = "unknown"   # "high", "medium", "low", "unknown"
    raw_response: str = ""        # Full model response
    error: str = ""
    metrics: Optional[VisionMetrics] = None

    def to_mj_context(self) -> str:
        """Format findings for injection into MJ's context."""
        if not self.success:
            return f"[Vision Analysis Failed: {self.error}]"

        lines = [f"[Vision Analysis ({self.task.value})]"]
        lines.append(f"Description: {self.description}")
        if self.elements_found:
            lines.append(f"Found: {', '.join(self.elements_found[:10])}")
        if self.confidence != "unknown":
            lines.append(f"Confidence: {self.confidence}")
        return "\n".join(lines)


# ── Vision Request Detection ────────────────────────────────────────────────

# Patterns that indicate a vision request
_VISION_KEYWORDS = re.compile(
    r"\b(?:"
    r"screenshot|screen\s*shot|screen\s*cap|capture\s*screen|"
    r"what(?:'s| is)\s+on\s+(?:the\s+)?screen|"
    r"look\s+at\s+(?:the\s+)?screen|"
    r"read\s+(?:the\s+)?(?:text|screen)|"
    r"what\s+(?:does|do)\s+(?:you|it)\s+(?:see|show)|"
    r"describe\s+(?:the\s+)?(?:image|picture|photo|screen)|"
    r"ocr|"
    r"find\s+(?:\w+\s+)*(?:button|icon|element|field|text)|"
    r"check\s+(?:the\s+)?(?:screen|display|ui)|"
    r"verify\s+(?:the\s+)?(?:screen|result|action)|"
    r"what\s+app\s+is\s+(?:this|open)|"
    r"image\s+analy"
    r")\b",
    re.IGNORECASE,
)

_OCR_KEYWORDS = re.compile(
    r"\b(?:ocr|read\s+(?:the\s+)?text|extract\s+text|what\s+(?:does\s+it|do\s+the\w*)\s+say)\b",
    re.IGNORECASE,
)

_CLASSIFY_KEYWORDS = re.compile(
    r"\b(?:what\s+app|which\s+screen|identify\s+(?:the\s+)?app|what\s+is\s+(?:this|open))\b",
    re.IGNORECASE,
)

_VERIFY_KEYWORDS = re.compile(
    r"\b(?:verify|confirm|check\s+if|did\s+it\s+(?:work|succeed)|is\s+it\s+(?:done|open|closed))\b",
    re.IGNORECASE,
)


def requires_vision(user_message: str) -> bool:
    """Check if a user message requires vision analysis."""
    return bool(_VISION_KEYWORDS.search(user_message))


def classify_vision_task(user_message: str) -> VisionTask:
    """Classify which vision task type is needed based on the user's message."""
    if _OCR_KEYWORDS.search(user_message):
        return VisionTask.OCR_READ
    if _CLASSIFY_KEYWORDS.search(user_message):
        return VisionTask.SCREENSHOT_CLASSIFY
    if _VERIFY_KEYWORDS.search(user_message):
        return VisionTask.VISUAL_VERIFY
    if re.search(r"\bfind\b.*\b(?:button|icon|element|field)\b", user_message, re.IGNORECASE):
        return VisionTask.UI_ELEMENT_FIND
    return VisionTask.IMAGE_DESCRIBE


# ── System Prompts ───────────────────────────────────────────────────────────

_BASE_VISION_PROMPT = (
    "You are a vision analysis module for MJ, a voice assistant. "
    "Analyze the provided image and return structured findings. "
    "Be precise and factual. Do not hallucinate UI elements that are not visible. "
    "You have NO device execution authority — you only observe and report."
)

_TASK_PROMPTS: Dict[VisionTask, str] = {
    VisionTask.SCREENSHOT_CLASSIFY: (
        f"{_BASE_VISION_PROMPT}\n"
        "Task: Identify the app or screen shown. "
        "Report: app name, screen type (home, settings, chat, etc.), "
        "and any notable UI state (notifications, errors, dialogs)."
    ),
    VisionTask.UI_ELEMENT_FIND: (
        f"{_BASE_VISION_PROMPT}\n"
        "Task: Find the specified UI element in the screenshot. "
        "Report: element type, label/text, approximate position "
        "(top/center/bottom, left/center/right), and whether it appears tappable."
    ),
    VisionTask.OCR_READ: (
        f"{_BASE_VISION_PROMPT}\n"
        "Task: Extract and return ALL visible text from the image. "
        "Preserve layout structure. Include button labels, menu items, "
        "notifications, and any error messages. Be thorough."
    ),
    VisionTask.IMAGE_DESCRIBE: (
        f"{_BASE_VISION_PROMPT}\n"
        "Task: Describe what is shown in the image. "
        "Include key objects, text, people, colors, and context."
    ),
    VisionTask.VISUAL_VERIFY: (
        f"{_BASE_VISION_PROMPT}\n"
        "Task: Verify the requested condition in the screenshot. "
        "Report: YES or NO, followed by a brief explanation of what you see."
    ),
    VisionTask.VIDEO_FRAME: (
        f"{_BASE_VISION_PROMPT}\n"
        "Task: Analyze this video frame. "
        "Describe the current scene, any visible UI, text, or actions."
    ),
}


# ── Gemma 4 Vision Client ───────────────────────────────────────────────────

class GemmaVisionClient:
    """
    NVIDIA NIM Gemma 4 31B IT vision client.

    OpenAI-compatible API with streaming support.
    Adaptive token budgets based on vision task type.
    Returns structured VisionFindings for MJ integration.

    Usage:
        client = GemmaVisionClient()
        findings = client.analyze_image(
            image_b64="...",
            user_query="What app is open?",
        )
        # findings.to_mj_context() -> structured text for MJ
    """

    DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
    DEFAULT_MODEL_ID = "google/gemma-4-31b-it"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "",
        model_id: str = "",
        timeout: Optional[float] = None,
    ):
        self._api_key = api_key if api_key is not None else os.getenv("NVIDIA_API_KEY", "")
        self._base_url = base_url or os.getenv("NVIDIA_GEMMA_URL", self.DEFAULT_BASE_URL)
        self._model_id = model_id or os.getenv("NVIDIA_GEMMA_MODEL", self.DEFAULT_MODEL_ID)
        self._timeout = timeout if timeout is not None else float(os.getenv("NVIDIA_VISION_TIMEOUT", "5.0"))
        self._client = None
        self._client_lock = threading.Lock()

    @property
    def available(self) -> bool:
        return bool(self._api_key)

    @property
    def model_id(self) -> str:
        return self._model_id

    def _get_client(self):
        if self._client is not None:
            return self._client
        with self._client_lock:
            if self._client is not None:
                return self._client
            if not self._api_key:
                return None
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    base_url=self._base_url,
                    api_key=self._api_key,
                    timeout=self._timeout,
                )
                log.info("[gemma_vision] Client initialized -> %s (%s, timeout=%.1fs)", self._base_url, self._model_id, self._timeout)
                return self._client
            except Exception as exc:
                log.error("[gemma_vision] Client init failed: %s", exc)
                return None

    # ── Core Analysis ────────────────────────────────────────────────────

    def analyze_with_metrics(
        self,
        image_b64: str,
        user_query: str,
        task: Optional[VisionTask] = None,
        max_tokens: Optional[int] = None,
        stream: bool = True,
    ) -> Tuple[VisionFindings, VisionMetrics]:
        """
        Analyze an image with adaptive token budget and streaming.

        Args:
            image_b64: Base64-encoded JPEG/PNG image
            user_query: The user's vision-related question
            task: Override auto-detected task type
            max_tokens: Override token budget
            stream: Use streaming (recommended for TTFT tracking)

        Returns:
            (VisionFindings, VisionMetrics)
        """
        # Auto-detect task if not specified
        if task is None:
            task = classify_vision_task(user_query)

        # Set token budget
        if max_tokens is None:
            max_tokens = _TOKEN_BUDGETS.get(task, 512)

        metrics = VisionMetrics(
            task=task.value,
            model_id=self._model_id,
            max_tokens_used=max_tokens,
            prompt_preview=user_query[:80],
            image_size_bytes=len(image_b64) * 3 // 4 if image_b64 else 0,  # approx decoded size
        )

        findings = VisionFindings(task=task)

        if not image_b64:
            findings.error = "No image provided"
            metrics.error = "No image provided"
            return findings, metrics

        client = self._get_client()
        if not client:
            findings.error = "No API key or client init failed"
            metrics.error = "No API key or client init failed"
            return findings, metrics

        # Build message with system prompt + user query + image
        system_prompt = _TASK_PROMPTS.get(task, _BASE_VISION_PROMPT)
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_query},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                    },
                ],
            },
        ]

        metrics.request_start = time.time()

        try:
            if stream:
                response_text = self._stream_response(
                    client, messages, max_tokens, metrics
                )
            else:
                response_text = self._sync_response(
                    client, messages, max_tokens, metrics
                )

            metrics.response_text = response_text or ""
            metrics.response_complete_time = time.time()
            metrics.success = bool(response_text)
            metrics.finalize()

            if response_text:
                findings.success = True
                findings.raw_response = response_text
                findings.description = response_text
                findings.confidence = "high" if metrics.total_tokens > 50 else "medium"

                # Extract structured elements for certain tasks
                if task == VisionTask.UI_ELEMENT_FIND:
                    findings.elements_found = _extract_ui_elements(response_text)
                elif task == VisionTask.OCR_READ:
                    findings.elements_found = [line.strip() for line in response_text.split("\n") if line.strip()]
            else:
                findings.error = metrics.error or "Empty response"

        except Exception as exc:
            metrics.error = str(exc)
            metrics.response_complete_time = time.time()
            metrics.finalize()
            findings.error = str(exc)
            log.warning("[gemma_vision] Analysis failed: %s", exc)

        return findings, metrics

    def _stream_response(
        self, client, messages: list, max_tokens: int, metrics: VisionMetrics
    ) -> Optional[str]:
        """Stream response and capture TTFT metrics."""
        stream = client.chat.completions.create(
            model=self._model_id,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.3,
            stream=True,
            stream_options={"include_usage": True},
        )

        accumulated = []
        first_token = False

        for chunk in stream:
            # Usage from final chunk
            if hasattr(chunk, "usage") and chunk.usage:
                metrics.prompt_tokens = chunk.usage.prompt_tokens or 0
                metrics.completion_tokens = chunk.usage.completion_tokens or 0
                metrics.total_tokens = chunk.usage.total_tokens or 0

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            if not delta or not delta.content:
                continue

            if not first_token:
                metrics.first_token_time = time.time()
                first_token = True

            accumulated.append(delta.content)

        return "".join(accumulated).strip() if accumulated else None

    def _sync_response(
        self, client, messages: list, max_tokens: int, metrics: VisionMetrics
    ) -> Optional[str]:
        """Non-streaming response."""
        resp = client.chat.completions.create(
            model=self._model_id,
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.3,
        )
        metrics.first_token_time = time.time()

        if resp.usage:
            metrics.prompt_tokens = resp.usage.prompt_tokens or 0
            metrics.completion_tokens = resp.usage.completion_tokens or 0
            metrics.total_tokens = resp.usage.total_tokens or 0

        if resp.choices:
            return resp.choices[0].message.content
        return None

    # ── Simple Interface ─────────────────────────────────────────────────

    def analyze_image(
        self,
        image_b64: str,
        user_query: str,
        task: Optional[VisionTask] = None,
    ) -> VisionFindings:
        """Simple interface — returns findings only."""
        findings, _ = self.analyze_with_metrics(image_b64, user_query, task)
        return findings

    def analyze_screenshot(
        self,
        screenshot_b64: str,
        query: str = "Describe what is on screen.",
    ) -> VisionFindings:
        """Convenience method for screenshot analysis."""
        return self.analyze_image(screenshot_b64, query, VisionTask.SCREENSHOT_CLASSIFY)

    def ocr(self, image_b64: str) -> VisionFindings:
        """Extract all text from an image."""
        return self.analyze_image(
            image_b64,
            "Extract and return ALL visible text from this image.",
            VisionTask.OCR_READ,
        )

    def verify_action(
        self,
        screenshot_b64: str,
        expected_state: str,
    ) -> VisionFindings:
        """Verify a UI action result."""
        return self.analyze_image(
            screenshot_b64,
            f"Verify: {expected_state}. Is this condition met in the screenshot?",
            VisionTask.VISUAL_VERIFY,
        )

    # ── Health Check ─────────────────────────────────────────────────────

    def health_check(self) -> Dict[str, Any]:
        if not self._api_key:
            return {"available": False, "error": "No API key"}
        client = self._get_client()
        if not client:
            return {"available": False, "error": "Client init failed"}
        try:
            models = client.models.list()
            return {"available": True, "model": self._model_id}
        except Exception as exc:
            return {"available": False, "error": str(exc)}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _extract_ui_elements(text: str) -> List[str]:
    """Extract mentioned UI elements from analysis text."""
    elements = []
    # Look for quoted labels or element descriptions
    quoted = re.findall(r'"([^"]+)"', text)
    elements.extend(quoted)
    # Look for "Button:", "Icon:", "Field:" patterns
    labeled = re.findall(r'(?:button|icon|field|menu|tab|link)[\s:]+["\']?([^"\'.,\n]+)', text, re.IGNORECASE)
    elements.extend(labeled)
    return list(dict.fromkeys(elements))[:20]  # Dedupe, max 20


def encode_image_file(image_path: str) -> str:
    """Encode a local image file to base64 string."""
    with open(image_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ── Module Singleton ─────────────────────────────────────────────────────────

_gemma_client: Optional[GemmaVisionClient] = None
_gemma_lock = threading.Lock()


def get_gemma_client() -> GemmaVisionClient:
    """Get or create the singleton Gemma vision client."""
    global _gemma_client
    if _gemma_client is not None:
        return _gemma_client
    with _gemma_lock:
        if _gemma_client is not None:
            return _gemma_client
        _gemma_client = GemmaVisionClient()
        return _gemma_client
