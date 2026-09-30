"""
Alita Tool Orchestrator — Autonomous Multi-Step Reasoning & Action Loop
=======================================================================
Implements the AGI ReAct (Reason + Act) loop:
1. Injects tool registry schema into system prompt
2. Calls LLM with conversational context
3. Detects and parses tool calls (<tool_call>...</tool_call>)
4. Executes the corresponding tool safely (sync or async)
5. Feeds tool execution results back into context
6. Iterates until LLM reaches final conclusion or max iterations hit
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from engines.tool_registry import (
    TOOL_DEFINITIONS,
    format_tools_for_prompt,
    parse_tool_call,
)

log = logging.getLogger("alita.orchestrator")


class ToolOrchestrator:
    """
    Manages multi-turn LLM reasoning and autonomous tool invocation.
    """

    def __init__(
        self,
        llm_fn: Callable[[List[Dict[str, Any]]], Any],
        tools: Optional[List[Dict[str, Any]]] = None,
        max_iterations: int = 5,
    ):
        self.llm_fn = llm_fn
        self.tools = tools if tools is not None else TOOL_DEFINITIONS
        self.tool_map: Dict[str, Dict[str, Any]] = {t["name"]: t for t in self.tools}
        self.max_iterations = max_iterations
        self.executed_tools: List[Dict[str, Any]] = []

    async def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> str:
        """
        Executes a registered tool by name with arguments.
        Handles both sync and async handlers with exception safety.
        """
        tool_def = self.tool_map.get(tool_name)
        if not tool_def:
            err = f"Error: Tool '{tool_name}' is not recognized. Available tools: {list(self.tool_map.keys())}"
            log.warning(err)
            return err

        handler = tool_def.get("handler")
        if not callable(handler):
            err = f"Error: Tool '{tool_name}' has no callable handler."
            log.error(err)
            return err

        try:
            # Check handler signature to adapt arguments safely
            sig = inspect.signature(handler)
            has_var_kwargs = any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            )
            if not has_var_kwargs:
                # Filter out unexpected keyword args
                valid_args = {k: v for k, v in args.items() if k in sig.parameters}
            else:
                valid_args = args

            if inspect.iscoroutinefunction(handler):
                result = await handler(**valid_args)
            else:
                # Run synchronous handlers in thread pool to prevent blocking event loop
                result = await asyncio.to_thread(handler, **valid_args)

            return str(result)
        except Exception as exc:
            err_msg = f"Error executing tool '{tool_name}': {type(exc).__name__}: {exc}"
            log.error(err_msg, exc_info=True)
            return err_msg

    async def run(
        self,
        user_message: str,
        system_prompt: str = "",
        session: Any = None,
    ) -> str:
        """
        The AGI agentic loop:
        Runs iteratively up to max_iterations turns of tool reasoning.
        """
        self.executed_tools.clear()

        # Augment system prompt with tool registry definitions
        tool_instructions = format_tools_for_prompt()
        if "### AVAILABLE TOOLS" not in system_prompt:
            augmented_system_prompt = f"{system_prompt}\n\n{tool_instructions}".strip()
        else:
            augmented_system_prompt = system_prompt

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": augmented_system_prompt},
            {"role": "user", "content": user_message},
        ]

        last_llm_response = ""

        for iteration in range(self.max_iterations):
            log.debug("Tool loop turn %d/%d", iteration + 1, self.max_iterations)

            # Call LLM
            llm_result = self.llm_fn(messages)
            if inspect.iscoroutine(llm_result):
                llm_response = await llm_result
            else:
                llm_response = llm_result

            last_llm_response = llm_response

            # Check if LLM requested a tool call
            tool_call = parse_tool_call(llm_response)
            if tool_call is None:
                # LLM finished thinking and provided final answer
                # Reflection guard self-correction check
                try:
                    from engines.reflection import ReflectionGuard
                    guard = ReflectionGuard(llm_fn=self.llm_fn, max_retries=2)
                    if guard.needs_reflection(user_message, llm_response):
                        return await guard.reflect_and_correct(user_message, llm_response, messages)
                except Exception as r_err:
                    log.debug("Reflection check skipped: %s", r_err)
                return llm_response

            tool_name, args = tool_call
            log.info("Agent tool call requested: %s(%s)", tool_name, args)

            # Execute tool
            tool_result = await self.execute_tool(tool_name, args)
            self.executed_tools.append({
                "tool": tool_name,
                "args": args,
                "result": tool_result,
                "iteration": iteration + 1,
            })

            # Append assistant step and tool observation to context
            messages.append({"role": "assistant", "content": llm_response})
            messages.append({
                "role": "tool",
                "name": tool_name,
                "content": f"[Tool Observation for {tool_name}]:\n{tool_result}",
            })

        log.warning("ToolOrchestrator reached max_iterations (%d)", self.max_iterations)
        return last_llm_response
