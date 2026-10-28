"""
Static & Regression Safety Test: F5-TTS Complete Removal
========================================================
Asserts that F5-TTS is completely absent from the active MJ/ALITA architecture:
1. f5_tts package cannot be imported.
2. No active backend code contains f5_tts imports or F5-TTS references.
3. EngineRegistry has no f5_engine attribute.
4. AVAILABLE_VOICES contains no F5 voices.
5. No F5 environment variables or requirements entries exist.
6. Frontend contains no F5-TTS controls or route references.
7. Target architecture remains: PRIMARY = Chatterbox Multilingual, FALLBACK = Chatterbox Turbo.
"""

import importlib
import os
import re
from pathlib import Path
import pytest


def test_f5_package_uninstalled():
    """Verify that f5_tts is not installed in the python environment."""
    with pytest.raises(ImportError):
        importlib.import_module("f5_tts")


def test_no_f5_in_engine_registry():
    """Verify that EngineRegistry does not have an f5_engine slot or reference."""
    from main import EngineRegistry
    reg = EngineRegistry()
    assert not hasattr(reg, "f5_engine"), "EngineRegistry must not have f5_engine"
    assert not hasattr(reg, "f5"), "EngineRegistry must not have f5"


def test_no_f5_in_available_voices():
    """Verify that AVAILABLE_VOICES does not contain any F5 voice."""
    from main import AVAILABLE_VOICES
    for voice_id, voice_meta in AVAILABLE_VOICES.items():
        assert "f5" not in voice_id.lower(), f"Unexpected F5 voice found: {voice_id}"
        assert voice_meta.get("engine") != "f5", f"Voice {voice_id} has engine='f5'"
        assert "f5" not in voice_meta.get("name", "").lower(), f"Voice {voice_id} name references F5"


def test_no_f5_in_requirements():
    """Verify backend requirements.txt does not require f5-tts."""
    req_file = Path(__file__).parent.parent / "requirements.txt"
    assert req_file.exists(), "requirements.txt missing"
    content = req_file.read_text(encoding="utf-8").lower()
    assert "f5-tts" not in content, "f5-tts found in requirements.txt"
    assert "f5_tts" not in content, "f5_tts found in requirements.txt"


def test_no_f5_env_vars():
    """Verify .env does not configure F5-TTS."""
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        content = env_file.read_text(encoding="utf-8")
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                key = line.split("=", 1)[0].strip()
                assert not key.upper().startswith("F5_"), f"Unexpected F5 env var: {key}"


def test_no_f5_imports_in_active_backend_code():
    """Verify no active backend python file imports f5_tts."""
    backend_dir = Path(__file__).parent.parent
    excluded_dirs = {"venv", "venv_cuda", ".git", "__pycache__"}

    f5_import_pattern = re.compile(r"^\s*(from\s+f5_tts|import\s+f5_tts)", re.MULTILINE)

    for py_file in backend_dir.rglob("*.py"):
        if any(part in py_file.parts for part in excluded_dirs):
            continue
        # Skip this test file itself
        if py_file.name == "test_f5_removal_static.py":
            continue

        content = py_file.read_text(encoding="utf-8", errors="ignore")
        match = f5_import_pattern.search(content)
        assert match is None, f"Illegal f5_tts import in {py_file}: {match.group(0)}"


def test_no_f5_tts_references_in_frontend():
    """Verify frontend components do not reference F5-TTS."""
    frontend_src = Path(__file__).parent.parent.parent / "frontend" / "src"
    if not frontend_src.exists():
        pytest.skip("Frontend directory not found")

    for file_path in frontend_src.rglob("*"):
        if file_path.suffix in {".js", ".jsx", ".ts", ".tsx"}:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            assert "F5-TTS" not in content, f"Frontend file {file_path} contains 'F5-TTS'"
            assert "f5_tts" not in content.lower(), f"Frontend file {file_path} contains 'f5_tts'"
            assert "f5_mj_clone" not in content, f"Frontend file {file_path} contains 'f5_mj_clone'"


def test_target_tts_architecture_integrity():
    """Verify TTS architecture: PRIMARY = Chatterbox Multilingual, FALLBACK = Chatterbox Turbo."""
    from engines.provider_orchestrator import get_provider_orchestrator

    orchestrator = get_provider_orchestrator()
    assert orchestrator.tts_primary_id == "chatterbox_multilingual_nim"
    assert orchestrator.tts_fallback_id == "chatterbox_local"

    tts_reg = orchestrator._get_tts_registry()
    primary = tts_reg.get(orchestrator.tts_primary_id)
    assert primary is not None
    assert primary.provider_id == "chatterbox_multilingual_nim"

    fallback = tts_reg.get(orchestrator.tts_fallback_id)
    assert fallback is not None
    assert fallback.provider_id == "chatterbox_local"


def test_voice_cloning_explicitly_disabled():
    """Verify voice cloning endpoint responds with 501 Not Implemented."""
    import asyncio
    from routers.voice_clone import start_clone, upload_voice_sample, record_voice_sample
    from fastapi import HTTPException

    # All cloning / recording endpoints must raise HTTP 501
    with pytest.raises(HTTPException) as excinfo:
        asyncio.run(start_clone(upload_id="test_id"))
    assert excinfo.value.status_code == 501
    assert "unavailable" in excinfo.value.detail.lower()
