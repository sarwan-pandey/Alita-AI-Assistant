import pytest
import asyncio
from engines.reflection import ReflectionGuard


@pytest.mark.anyio
async def test_good_answer_passes():
    """Test 1: Good answer passes through without triggering correction."""
    calls = 0

    async def mock_llm(messages):
        nonlocal calls
        calls += 1
        return "Corrected"

    guard = ReflectionGuard(llm_fn=mock_llm, max_retries=2)
    assert not guard.needs_reflection("What is 2+2?", "4")

    result = await guard.process("What is 2+2?", "4")
    assert result == "4"
    assert calls == 0


@pytest.mark.anyio
async def test_empty_answer_triggers_retry():
    """Test 2: Empty answer triggers reflection/retry to get a real answer."""
    calls = 0

    async def mock_llm(messages):
        nonlocal calls
        calls += 1
        return "This is the generated answer."

    guard = ReflectionGuard(llm_fn=mock_llm, max_retries=2)
    assert guard.needs_reflection("Explain photosynthesis", "")

    result = await guard.process("Explain photosynthesis", "")
    assert result == "This is the generated answer."
    assert calls == 1


@pytest.mark.anyio
async def test_i_dont_know_triggers_retry():
    """Test 3: 'I don't know' cop-out triggers retry/reflection."""
    calls = 0

    async def mock_llm(messages):
        nonlocal calls
        calls += 1
        return "Paris is the capital of France."

    guard = ReflectionGuard(llm_fn=mock_llm, max_retries=2)
    assert guard.needs_reflection("What is the capital of France?", "I don't know the answer to that.")

    result = await guard.process("What is the capital of France?", "I don't know the answer to that.")
    assert "Paris" in result
    assert calls == 1


@pytest.mark.anyio
async def test_max_retries_respected():
    """Test 4: When LLM repeatedly returns cop-outs, stops after max_retries (2)."""
    calls = 0

    async def mock_llm(messages):
        nonlocal calls
        calls += 1
        return "I cannot answer."

    guard = ReflectionGuard(llm_fn=mock_llm, max_retries=2)
    result = await guard.process("Difficult query", "I don't know")
    assert calls == 2
    assert result == "I cannot answer."


@pytest.mark.anyio
async def test_fast_path_no_reflection():
    """Test 5: Fast path skips reflection entirely for simple casual greetings."""
    calls = 0

    async def mock_llm(messages):
        nonlocal calls
        calls += 1
        return "Should not be called"

    guard = ReflectionGuard(llm_fn=mock_llm, max_retries=2)
    assert not guard.needs_reflection("hello", "Hi there! How can I help?")

    result = await guard.process("hello", "Hi there! How can I help?")
    assert result == "Hi there! How can I help?"
    assert calls == 0
