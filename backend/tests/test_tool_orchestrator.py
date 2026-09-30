import pytest
import asyncio
from engines.tool_orchestrator import ToolOrchestrator


@pytest.mark.anyio
async def test_simple_query_no_tools():
    """Test 1: Simple query returns text answer immediately without tool calls."""
    calls = []

    async def mock_llm(messages):
        calls.append(messages)
        return "4"

    tools = [
        {
            "name": "calc",
            "description": "Calculate expression",
            "parameters": {},
            "handler": lambda expr: "4",
        }
    ]

    orchestrator = ToolOrchestrator(llm_fn=mock_llm, tools=tools, max_iterations=5)
    response = await orchestrator.run("What is 2+2?", "System prompt", session=None)

    assert response == "4"
    assert len(calls) == 1
    assert len(orchestrator.executed_tools) == 0


@pytest.mark.anyio
async def test_tool_call_detected():
    """Test 2: LLM returns a tool call, orchestrator parses and executes tool."""
    executed = []

    def mock_tool(name: str):
        executed.append(name)
        return f"Hello, {name}!"

    tools = [
        {
            "name": "greet",
            "description": "Greet person",
            "parameters": {"name": {"type": "string"}},
            "handler": mock_tool,
        }
    ]

    llm_turn = 0

    async def mock_llm(messages):
        nonlocal llm_turn
        llm_turn += 1
        if llm_turn == 1:
            return '<tool_call>{"name": "greet", "arguments": {"name": "Sarwan"}}</tool_call>'
        return f"Final Answer: {messages[-1]['content']}"

    orchestrator = ToolOrchestrator(llm_fn=mock_llm, tools=tools, max_iterations=5)
    response = await orchestrator.run("Say hello to Sarwan", "System prompt", session=None)

    assert executed == ["Sarwan"]
    assert "Hello, Sarwan!" in response
    assert len(orchestrator.executed_tools) == 1
    assert orchestrator.executed_tools[0]["tool"] == "greet"


@pytest.mark.anyio
async def test_multi_step_loop():
    """Test 3: Multi-step tool loop where tool result is fed back into LLM, leading to final answer."""
    step = 0

    def tool_step1():
        return "First observation"

    def tool_step2():
        return "Second observation"

    tools = [
        {"name": "step1_tool", "description": "Step 1", "parameters": {}, "handler": tool_step1},
        {"name": "step2_tool", "description": "Step 2", "parameters": {}, "handler": tool_step2},
    ]

    async def mock_llm(messages):
        nonlocal step
        step += 1
        if step == 1:
            return '<tool_call>{"name": "step1_tool", "arguments": {}}</tool_call>'
        elif step == 2:
            assert "First observation" in messages[-1]["content"]
            return '<tool_call>{"name": "step2_tool", "arguments": {}}</tool_call>'
        else:
            assert "Second observation" in messages[-1]["content"]
            return "Both steps completed successfully."

    orchestrator = ToolOrchestrator(llm_fn=mock_llm, tools=tools, max_iterations=5)
    response = await orchestrator.run("Do two steps", "System prompt", session=None)

    assert response == "Both steps completed successfully."
    assert step == 3
    assert len(orchestrator.executed_tools) == 2


@pytest.mark.anyio
async def test_max_iterations_guard():
    """Test 4: Max iterations guard stops infinite tool calling loop at max_iterations (5)."""
    iterations = 0

    def endless_tool():
        return "data"

    tools = [
        {"name": "loop_tool", "description": "Loops", "parameters": {}, "handler": endless_tool}
    ]

    async def mock_llm(messages):
        nonlocal iterations
        iterations += 1
        return '<tool_call>{"name": "loop_tool", "arguments": {}}</tool_call>'

    orchestrator = ToolOrchestrator(llm_fn=mock_llm, tools=tools, max_iterations=5)
    response = await orchestrator.run("Loop forever", "System prompt", session=None)

    assert iterations == 5
    assert len(orchestrator.executed_tools) == 5
    # Max iterations reached returns best answer/last response or fallback
    assert response is not None


@pytest.mark.anyio
async def test_tool_error_handling():
    """Test 5: Tool raises exception, orchestrator catches it and feeds error back to LLM."""
    def broken_tool():
        raise ValueError("Simulated tool crash")

    tools = [
        {"name": "bad_tool", "description": "Fails", "parameters": {}, "handler": broken_tool}
    ]

    step = 0

    async def mock_llm(messages):
        nonlocal step
        step += 1
        if step == 1:
            return '<tool_call>{"name": "bad_tool", "arguments": {}}</tool_call>'
        # Verify the error was passed into messages
        last_msg = messages[-1]["content"]
        assert "Simulated tool crash" in last_msg or "error" in last_msg.lower()
        return "I encountered an error with the tool but handled it gracefully."

    orchestrator = ToolOrchestrator(llm_fn=mock_llm, tools=tools, max_iterations=5)
    response = await orchestrator.run("Run bad tool", "System prompt", session=None)

    assert "handled it gracefully" in response
    assert step == 2
