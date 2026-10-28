"""
Gemma 4 31B IT Vision Provider Tests
======================================
Unit tests (no API key needed) + integration tests (require NVIDIA_API_KEY).
"""

import sys
import os
import base64
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═════════════════════════════════════════════════════════════════════════════
# §1  UNIT TESTS — No API key required
# ═════════════════════════════════════════════════════════════════════════════

class TestVisionTaskTypes:
    """Tests for vision task classification."""

    def test_task_enum_values(self):
        from engines.gemma_vision import VisionTask
        assert VisionTask.SCREENSHOT_CLASSIFY.value == "screenshot_classify"
        assert VisionTask.OCR_READ.value == "ocr_read"
        assert VisionTask.UI_ELEMENT_FIND.value == "ui_element_find"
        assert VisionTask.VISUAL_VERIFY.value == "visual_verify"

    def test_token_budgets_exist(self):
        from engines.gemma_vision import _TOKEN_BUDGETS, VisionTask
        for task in VisionTask:
            assert task in _TOKEN_BUDGETS, f"No budget for {task}"
            assert _TOKEN_BUDGETS[task] > 0

    def test_classify_budget_is_low(self):
        from engines.gemma_vision import _TOKEN_BUDGETS, VisionTask
        assert _TOKEN_BUDGETS[VisionTask.SCREENSHOT_CLASSIFY] <= 256

    def test_ocr_budget_is_high(self):
        from engines.gemma_vision import _TOKEN_BUDGETS, VisionTask
        assert _TOKEN_BUDGETS[VisionTask.OCR_READ] >= 512


class TestVisionDetection:
    """Tests for vision request detection."""

    def test_requires_vision_positive(self):
        from engines.gemma_vision import requires_vision
        assert requires_vision("Take a screenshot of the screen") is True
        assert requires_vision("What's on the screen?") is True
        assert requires_vision("Read the text on screen") is True
        assert requires_vision("What app is open?") is True
        assert requires_vision("Find the settings button") is True
        assert requires_vision("Describe the image") is True
        assert requires_vision("Do OCR on this") is True
        assert requires_vision("Check the screen please") is True
        assert requires_vision("Verify the screen shows home") is True

    def test_requires_vision_negative(self):
        from engines.gemma_vision import requires_vision
        assert requires_vision("What is the weather?") is False
        assert requires_vision("Tell me a joke") is False
        assert requires_vision("Set a timer for 5 minutes") is False
        assert requires_vision("Play some music") is False
        assert requires_vision("How are you doing?") is False

    def test_classify_ocr(self):
        from engines.gemma_vision import classify_vision_task, VisionTask
        assert classify_vision_task("Read the text on screen") == VisionTask.OCR_READ
        assert classify_vision_task("OCR this image") == VisionTask.OCR_READ
        assert classify_vision_task("What does it say?") == VisionTask.OCR_READ

    def test_classify_screenshot(self):
        from engines.gemma_vision import classify_vision_task, VisionTask
        assert classify_vision_task("What app is this?") == VisionTask.SCREENSHOT_CLASSIFY
        assert classify_vision_task("Which screen is open?") == VisionTask.SCREENSHOT_CLASSIFY

    def test_classify_verify(self):
        from engines.gemma_vision import classify_vision_task, VisionTask
        assert classify_vision_task("Verify the settings are open") == VisionTask.VISUAL_VERIFY
        assert classify_vision_task("Did it work?") == VisionTask.VISUAL_VERIFY

    def test_classify_find_element(self):
        from engines.gemma_vision import classify_vision_task, VisionTask
        assert classify_vision_task("Find the button for settings") == VisionTask.UI_ELEMENT_FIND

    def test_classify_fallback(self):
        from engines.gemma_vision import classify_vision_task, VisionTask
        assert classify_vision_task("Describe this image") == VisionTask.IMAGE_DESCRIBE


class TestVisionMetrics:
    """Tests for VisionMetrics."""

    def test_defaults(self):
        from engines.gemma_vision import VisionMetrics
        m = VisionMetrics()
        assert m.success is False
        assert m.total_ms == 0.0
        assert m.task == ""

    def test_finalize(self):
        from engines.gemma_vision import VisionMetrics
        m = VisionMetrics()
        m.request_start = 100.0
        m.first_token_time = 100.3
        m.response_complete_time = 101.0
        m.finalize()
        assert abs(m.ttft_ms - 300.0) < 1.0
        assert abs(m.total_ms - 1000.0) < 1.0

    def test_summary(self):
        from engines.gemma_vision import VisionMetrics
        m = VisionMetrics(
            task="screenshot_classify", success=True,
            total_ms=500.0, ttft_ms=200.0,
            prompt_tokens=100, completion_tokens=50, total_tokens=150,
            image_size_bytes=50000, response_text="Test app",
        )
        s = m.summary()
        assert "gemma_vision" in s
        assert "OK" in s
        assert "screenshot_classify" in s


class TestVisionFindings:
    """Tests for VisionFindings structured output."""

    def test_success_context(self):
        from engines.gemma_vision import VisionFindings, VisionTask
        f = VisionFindings(
            task=VisionTask.SCREENSHOT_CLASSIFY,
            success=True,
            description="The Settings app is open showing Wi-Fi settings.",
            confidence="high",
        )
        ctx = f.to_mj_context()
        assert "[Vision Analysis" in ctx
        assert "Settings" in ctx
        assert "Wi-Fi" in ctx

    def test_failure_context(self):
        from engines.gemma_vision import VisionFindings, VisionTask
        f = VisionFindings(
            task=VisionTask.OCR_READ,
            success=False,
            error="No API key",
        )
        ctx = f.to_mj_context()
        assert "Failed" in ctx
        assert "No API key" in ctx

    def test_elements_in_context(self):
        from engines.gemma_vision import VisionFindings, VisionTask
        f = VisionFindings(
            task=VisionTask.UI_ELEMENT_FIND,
            success=True,
            description="Found the button",
            elements_found=["Settings", "Wi-Fi toggle"],
        )
        ctx = f.to_mj_context()
        assert "Settings" in ctx
        assert "Wi-Fi toggle" in ctx


class TestClientInit:
    """Tests for GemmaVisionClient initialization."""

    def test_import(self):
        from engines.gemma_vision import GemmaVisionClient, get_gemma_client
        assert GemmaVisionClient is not None
        assert callable(get_gemma_client)

    def test_no_key(self):
        from engines.gemma_vision import GemmaVisionClient
        client = GemmaVisionClient(api_key="")
        assert client.available is False

    def test_with_key(self):
        from engines.gemma_vision import GemmaVisionClient
        client = GemmaVisionClient(api_key="test-key")
        assert client.available is True
        assert client.model_id == "google/gemma-4-31b-it"

    def test_custom_model(self):
        from engines.gemma_vision import GemmaVisionClient
        client = GemmaVisionClient(api_key="test", model_id="custom/model")
        assert client.model_id == "custom/model"

    def test_analyze_no_key(self):
        from engines.gemma_vision import GemmaVisionClient
        client = GemmaVisionClient(api_key="")
        findings = client.analyze_image("base64data", "What is this?")
        assert findings.success is False
        assert "API key" in findings.error

    def test_analyze_no_image(self):
        from engines.gemma_vision import GemmaVisionClient
        client = GemmaVisionClient(api_key="test-key")
        findings = client.analyze_image("", "What is this?")
        assert findings.success is False
        assert "No image" in findings.error


class TestUIElementExtraction:
    """Tests for UI element extraction helper."""

    def test_extract_quoted(self):
        from engines.gemma_vision import _extract_ui_elements
        text = 'I found "Settings" and "Wi-Fi" buttons.'
        elements = _extract_ui_elements(text)
        assert "Settings" in elements
        assert "Wi-Fi" in elements

    def test_extract_labeled(self):
        from engines.gemma_vision import _extract_ui_elements
        text = "Button: Save Changes. Icon: gear symbol"
        elements = _extract_ui_elements(text)
        assert any("Save" in e for e in elements)

    def test_max_elements(self):
        from engines.gemma_vision import _extract_ui_elements
        text = " ".join([f'"Element{i}"' for i in range(50)])
        elements = _extract_ui_elements(text)
        assert len(elements) <= 20


class TestImageEncoding:
    """Tests for image encoding utility."""

    def test_encode_function(self):
        from engines.gemma_vision import encode_image_file
        assert callable(encode_image_file)


class TestProductionPreservation:
    """Verify production code is NOT modified."""

    def test_no_production_imports(self):
        """No production code imports gemma_vision."""
        prod_files = [
            "general_handler.py",
            "main.py",
            "tts_dispatch.py",
            "ollama_client.py",
        ]
        for fname in prod_files:
            fpath = os.path.join(os.path.dirname(__file__), "..", fname)
            if not os.path.exists(fpath):
                continue
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            assert "gemma_vision" not in content, f"{fname} imports gemma_vision!"

    def test_existing_vision_engine_intact(self):
        """Existing vision_engine.py is not modified."""
        ve_path = os.path.join(os.path.dirname(__file__), "..", "engines", "vision_engine.py")
        if os.path.exists(ve_path):
            with open(ve_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            assert "gemma_vision" not in content
            assert "GemmaVisionClient" not in content

    def test_automation_validator_untouched(self):
        """Automation validator remains authoritative."""
        val_path = os.path.join(os.path.dirname(__file__), "..", "tools", "android_validator.py")
        if os.path.exists(val_path):
            with open(val_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            assert "gemma_vision" not in content


# ═════════════════════════════════════════════════════════════════════════════
# §2  INTEGRATION TESTS — Require NVIDIA_API_KEY
# ═════════════════════════════════════════════════════════════════════════════

class TestGemmaIntegration:
    """Live Gemma 4 integration tests — skipped without API key."""

    def _get_client(self):
        from engines.gemma_vision import GemmaVisionClient
        key = os.getenv("NVIDIA_API_KEY", "")
        if not key:
            pytest.skip("NVIDIA_API_KEY not set")
        return GemmaVisionClient(api_key=key)

    def _make_test_image(self) -> str:
        """Create a simple test image (red square) as base64."""
        try:
            from PIL import Image
        except ImportError:
            pytest.skip("Pillow not installed")

        img = Image.new("RGB", (100, 100), color="red")
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")

    def test_health_check(self):
        client = self._get_client()
        health = client.health_check()
        assert health["available"] is True, f"Health failed: {health}"
        print(f"\n  Health: {health}")

    def test_simple_analysis(self):
        client = self._get_client()
        test_img = self._make_test_image()
        findings, metrics = client.analyze_with_metrics(
            test_img, "What color is this image?"
        )
        assert metrics.success, f"Failed: {metrics.error}"
        assert "red" in findings.description.lower(), f"Expected 'red': {findings.description}"
        print(f"\n  {metrics.summary()}")
        print(f"  Response: \"{findings.description[:100]}\"")

    def test_token_budget_classification(self):
        """Classification task should use low token budget."""
        client = self._get_client()
        test_img = self._make_test_image()
        from engines.gemma_vision import VisionTask
        findings, metrics = client.analyze_with_metrics(
            test_img, "What is this?", task=VisionTask.SCREENSHOT_CLASSIFY
        )
        assert metrics.max_tokens_used <= 256
        assert metrics.success, f"Failed: {metrics.error}"
        print(f"\n  {metrics.summary()}")

    def test_streaming_timing(self):
        """Verify TTFT < Total ordering with streaming."""
        client = self._get_client()
        test_img = self._make_test_image()
        _, metrics = client.analyze_with_metrics(
            test_img, "Describe this image in detail.", stream=True
        )
        assert metrics.success, f"Failed: {metrics.error}"
        assert metrics.ttft_ms > 0
        assert metrics.ttft_ms <= metrics.total_ms
        print(f"\n  TTFT={metrics.ttft_ms:.0f}ms Total={metrics.total_ms:.0f}ms")

    def test_no_device_execution(self):
        """Gemma should only report, not execute."""
        client = self._get_client()
        test_img = self._make_test_image()
        findings = client.analyze_image(
            test_img, "Open the settings app on this device."
        )
        # Findings should describe, not execute
        assert findings.success
        # The response should not contain tool calls or execution commands
        assert "executed" not in findings.raw_response.lower() or "cannot" in findings.raw_response.lower()


import io  # needed for test image creation
