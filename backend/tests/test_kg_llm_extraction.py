import pytest
import asyncio
import json
from engines.knowledge_graph import KnowledgeGraph, Triple


@pytest.fixture
def fresh_kg(tmp_path):
    kg_file = str(tmp_path / "test_kg.json")
    kg = KnowledgeGraph(storage_path=kg_file)
    return kg


@pytest.mark.anyio
async def test_regex_catches_simple(fresh_kg):
    """Test 1: Standard regex matches simple 'My sister is Priya'."""
    stored = fresh_kg.extract_and_store("My sister is Priya", user_id="u1")
    assert len(stored) >= 1
    t = stored[0]
    assert t.subject == "user"
    assert t.relation == "sister"
    assert "priya" in t.object.lower()


@pytest.mark.anyio
async def test_llm_catches_complex(fresh_kg):
    """Test 2: LLM catches complex conversational phrasing where regex fails."""
    # First verify regex alone fails on this complex sentence
    regex_res = fresh_kg.extract_and_store(
        "I was talking to Priya yesterday, she's my older sister", user_id="u1"
    )
    assert len(regex_res) == 0

    # Now verify LLM extractor catches it
    async def mock_llm(prompt):
        return json.dumps([{"s": "user", "r": "sister", "o": "priya"}])

    stored = await fresh_kg.extract_with_llm(
        "I was talking to Priya yesterday, she's my older sister",
        user_id="u1",
        llm_fn=mock_llm,
    )
    assert len(stored) == 1
    assert stored[0].subject == "user"
    assert stored[0].relation == "sister"
    assert stored[0].object == "priya"


@pytest.mark.anyio
async def test_llm_catches_implicit(fresh_kg):
    """Test 3: LLM catches implicit life events like employment."""
    async def mock_llm(prompt):
        return json.dumps([{"s": "user", "r": "works_at", "o": "google"}])

    stored = await fresh_kg.extract_with_llm(
        "I just started at Google last week",
        user_id="u1",
        llm_fn=mock_llm,
    )
    assert len(stored) == 1
    assert stored[0].subject == "user"
    assert stored[0].relation == "works_at"
    assert stored[0].object == "google"


@pytest.mark.anyio
async def test_no_facts_returns_empty(fresh_kg):
    """Test 4: Non-factual chatter returns empty list."""
    async def mock_llm(prompt):
        return "[]"

    stored = await fresh_kg.extract_with_llm(
        "What's the weather like today?",
        user_id="u1",
        llm_fn=mock_llm,
    )
    assert len(stored) == 0


@pytest.mark.anyio
async def test_llm_extraction_timeout(fresh_kg):
    """Test 5: LLM timeout gracefully falls back to regex extraction."""
    async def slow_llm(prompt):
        await asyncio.sleep(2.0)
        return "[]"

    # Input has a regex pattern: "My brother is Rahul"
    stored = await fresh_kg.extract_with_llm(
        "My brother is Rahul",
        user_id="u1",
        llm_fn=slow_llm,
        timeout=0.1,
    )
    # Should fallback to regex and still capture Rahul
    assert len(stored) >= 1
    assert stored[0].subject == "user"
    assert stored[0].relation == "brother"
    assert "rahul" in stored[0].object.lower()
