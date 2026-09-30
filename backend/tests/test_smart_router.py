import pytest
from engines.smart_router import classify_complexity


def test_simple_queries_route_local():
    """Test 1: Basic common queries should route to local Qwen 3:8B."""
    simple_queries = [
        "What time is it?",
        "Open Chrome",
        "Hello",
        "Play some music",
    ]
    for q in simple_queries:
        assert classify_complexity(q) == "local", f"Failed for query: {q}"


def test_complex_queries_route_cloud():
    """Test 2: Analytical, summarizing, and reasoning-heavy queries should route to cloud (Gemini)."""
    complex_queries = [
        "Analyze this error and suggest fixes",
        "Summarize this document",
        "Compare these two approaches and recommend the best one",
        "Debug why my Python code crashes on line 42",
    ]
    for q in complex_queries:
        assert classify_complexity(q) == "cloud", f"Failed for query: {q}"


def test_vision_queries_route_cloud():
    """Test 3: Queries with image attachments must always route to cloud since Qwen 3:8B is text-only."""
    queries = [
        ("What is on my screen?", True),
        ("Describe this image", True),
        ("Hello", True),
        ("Explain this chart", True),
    ]
    for q, has_img in queries:
        assert classify_complexity(q, has_image=has_img) == "cloud", f"Failed for query: {q} with has_image=True"


def test_hindi_simple_stays_local():
    """Test 4: Common Hindi/Hinglish commands stay on local Qwen model."""
    hindi_queries = [
        "Kya time hua hai?",
        "Chrome kholo",
        "Gaana bajao",
    ]
    for q in hindi_queries:
        assert classify_complexity(q) == "local", f"Failed for query: {q}"


def test_short_queries_local():
    """Test 5: Short queries without complex keywords stay local."""
    short_queries = [
        "Turn up the volume",
        "Tell me a joke",
        "Who is the president of France?",
        "Good morning Alita",
    ]
    for q in short_queries:
        assert len(q.split()) < 15
        assert classify_complexity(q) == "local", f"Failed for query: {q}"
