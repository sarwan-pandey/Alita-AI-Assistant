import pytest
import asyncio
import os
from engines.memory_summarizer import MemorySummarizer


@pytest.fixture
def summarizer(tmp_path):
    storage_path = str(tmp_path / "summaries.json")

    async def mock_llm(prompt):
        # Extract meaningful lines from prompt
        return "- Sarwan lives in Pune\n- Priya is Sarwan's sister\n- Works at Google\n- Likes coffee"

    return MemorySummarizer(llm_fn=mock_llm, threshold=15, storage_path=storage_path)


@pytest.mark.anyio
async def test_summarize_conversations(summarizer):
    """Test 1: 20 conversations trigger summarization into key facts."""
    for i in range(20):
        summarizer.record_interaction("u1", f"Conversation turn {i}: discussing project updates and work.")

    assert summarizer.get_unsummarized_count("u1") == 20
    summary = await summarizer.maybe_summarize("u1")
    assert summary is not None
    assert len(summary.get("facts", [])) >= 4
    assert summarizer.get_unsummarized_count("u1") == 0


@pytest.mark.anyio
async def test_below_threshold_no_summary(summarizer):
    """Test 2: 5 conversations below threshold (15) trigger no summarization."""
    for i in range(5):
        summarizer.record_interaction("u1", f"Short talk {i}")

    assert summarizer.get_unsummarized_count("u1") == 5
    summary = await summarizer.maybe_summarize("u1")
    assert summary is None
    assert summarizer.get_unsummarized_count("u1") == 5


@pytest.mark.anyio
async def test_summary_preserves_names(tmp_path):
    """Test 3: Summarization preserves key proper nouns like Priya and Google."""
    storage_path = str(tmp_path / "names.json")

    async def name_preserving_llm(prompt):
        assert "Priya" in prompt
        assert "Google" in prompt
        return "- Priya works at Google\n- Priya is the user's sister"

    ms = MemorySummarizer(llm_fn=name_preserving_llm, threshold=15, storage_path=storage_path)
    for i in range(14):
        ms.record_interaction("u2", f"General chat {i}")
    ms.record_interaction("u2", "My sister Priya joined Google as a software engineer.")

    res = await ms.maybe_summarize("u2")
    assert res is not None
    raw_text = res.get("summary_text", "")
    assert "Priya" in raw_text
    assert "Google" in raw_text


@pytest.mark.anyio
async def test_summary_deduplicates(tmp_path):
    """Test 4: Repeated facts across turns are deduplicated in final summary."""
    storage_path = str(tmp_path / "dedup.json")

    async def echo_facts_llm(prompt):
        # LLM emits duplicate lines
        return "- User loves coffee\n- User loves coffee\n- User prefers dark roast\n- User loves coffee"

    ms = MemorySummarizer(llm_fn=echo_facts_llm, threshold=15, storage_path=storage_path)
    for _ in range(15):
        ms.record_interaction("u3", "I really love coffee!")

    res = await ms.maybe_summarize("u3")
    assert res is not None
    facts = res.get("facts", [])
    # "User loves coffee" should only appear once
    coffee_facts = [f for f in facts if "coffee" in f.lower()]
    assert len(coffee_facts) == 1


@pytest.mark.anyio
async def test_summary_stored_persistently(tmp_path):
    """Test 5: Summary is written to disk and survives reload/restart."""
    storage_path = str(tmp_path / "persistent.json")

    async def mock_llm(prompt):
        return "- User lives in Bengaluru"

    ms1 = MemorySummarizer(llm_fn=mock_llm, threshold=15, storage_path=storage_path)
    for i in range(15):
        ms1.record_interaction("u4", f"Chat {i}")

    await ms1.maybe_summarize("u4")

    # Create new instance with same storage path (simulating app restart)
    ms2 = MemorySummarizer(llm_fn=mock_llm, threshold=15, storage_path=storage_path)
    summaries = ms2.get_stored_summaries("u4")
    assert len(summaries) == 1
    assert "Bengaluru" in summaries[0]["summary_text"]
