"""
Alita Tool Registry — Definitions and parsers for agentic tool use.
===================================================================
Provides tool definitions, prompt formatting, and parsing for Qwen 3:8B
and cloud models to autonomously invoke tools, observe results, and iterate.
"""

from __future__ import annotations

import datetime
import json
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger("alita.tools")


# ── Lazy Handlers to avoid circular imports ──────────────────────────────────

def _handle_read_screen(**kwargs) -> str:
    try:
        from engines.screen_ocr import screen_ocr
        text = screen_ocr.get_screen_text()
        summary = screen_ocr.get_summary()
        if not text:
            return f"Screen summary: {summary}\n(No raw OCR text captured)"
        return f"Screen summary: {summary}\nOCR Content:\n{text[:1500]}"
    except Exception as exc:
        return f"Error reading screen: {exc}"


def _handle_read_file(path: str, **kwargs) -> str:
    try:
        from threads.automation_handler import read_file
        res = read_file(path)
        if isinstance(res, dict):
            if res.get("success"):
                return res.get("content", "")
            return res.get("error", "Failed to read file.")
        return str(res)
    except Exception as exc:
        return f"Error reading file '{path}': {exc}"


def _handle_write_file(path: str, content: str, **kwargs) -> str:
    try:
        from threads.automation_handler import write_file
        res = write_file(path, content)
        if isinstance(res, dict):
            if res.get("success"):
                return f"Successfully wrote {len(content)} bytes to {path}"
            return res.get("error", "Failed to write file.")
        return str(res)
    except Exception as exc:
        return f"Error writing file '{path}': {exc}"


def _handle_search_knowledge(query: str, user_id: str = "default", **kwargs) -> str:
    try:
        from engines.knowledge_graph import knowledge_graph
        ctx = knowledge_graph.get_relevant_context(query, user_id=user_id)
        if not ctx:
            return "No verified facts found in knowledge graph for query."
        return ctx
    except Exception as exc:
        return f"Error querying knowledge graph: {exc}"


def _handle_add_knowledge(text: str, user_id: str = "default", **kwargs) -> str:
    try:
        from engines.knowledge_graph import knowledge_graph
        stored = knowledge_graph.extract_and_store(text, user_id=user_id)
        if stored:
            triples_str = ", ".join(f"({t.subject}, {t.relation}, {t.object})" for t in stored)
            return f"Successfully stored facts in knowledge graph: {triples_str}"
        return "No extractable relationship triples found in text."
    except Exception as exc:
        return f"Error adding to knowledge graph: {exc}"


def _handle_open_app(app_name: str, **kwargs) -> str:
    try:
        from threads.automation_handler import open_app
        res = open_app(app_name)
        if isinstance(res, dict):
            if res.get("success"):
                return f"Opened application: {app_name}"
            return res.get("message") or res.get("error") or f"Could not open {app_name}"
        return str(res)
    except Exception as exc:
        return f"Error opening application '{app_name}': {exc}"


def _handle_get_time(**kwargs) -> str:
    now = datetime.datetime.now()
    return now.strftime("%A, %B %d, %Y %I:%M:%S %p")


def _handle_web_search(query: str, **kwargs) -> str:
    try:
        from threads.automation_handler import search_web
        res = search_web(query)
        if isinstance(res, dict):
            return res.get("message", f"Initiated search for: {query}")
        return str(res)
    except Exception as exc:
        return f"Error executing web search for '{query}': {exc}"


def _handle_get_system_info(**kwargs) -> str:
    try:
        from threads.automation_handler import get_system_info
        info = get_system_info()
        return json.dumps(info, indent=2)
    except Exception as exc:
        return f"Error getting system info: {exc}"


def _handle_capture_screen(**kwargs) -> str:
    try:
        from engines.screen_ocr import screen_ocr
        snap = screen_ocr.force_scan()
        if snap and snap.text:
            return f"Captured screen text:\n{snap.text[:1500]}\nApp: {snap.app_title}"
        text = screen_ocr.get_screen_text()
        if text:
            return f"Captured screen text:\n{text[:1500]}"
        return "Screen capture completed. Visual display appears graphical with no significant text detected."
    except Exception as exc:
        return f"Error capturing screen: {exc}"


def _handle_analyze_screen(**kwargs) -> str:
    try:
        from engines.screen_context import screen_context
        ctx = screen_context.get_full_context()
        active_app = ctx.get("active_app", "Unknown")
        active_title = ctx.get("active_title", "")
        ocr_info = ctx.get("ocr", {})
        ocr_summary = ocr_info.get("summary", "")
        patterns = ocr_info.get("patterns", {})
        res = [
            f"Active Application: {active_app}",
            f"Window Title: {active_title}",
            f"Screen Summary: {ocr_summary or 'Normal UI state'}",
        ]
        if patterns.get("errors"):
            res.append(f"Errors Detected: {', '.join(patterns['errors'])}")
        if patterns.get("dialogs"):
            res.append(f"Dialogs Detected: {', '.join(patterns['dialogs'])}")
        return "\n".join(res)
    except Exception as exc:
        return f"Error analyzing screen: {exc}"


def _handle_click_element(target: str, **kwargs) -> str:
    try:
        from engines.ui_controller import ui_ctrl
        if ui_ctrl:
            btn = ui_ctrl.find_button(target)
            if btn and ui_ctrl.click_control(btn):
                return f"Successfully clicked button '{target}'"
        from engines.screen_agent import screen_agent
        task_id = f"click_{int(time.time())}"
        res = screen_agent.start_task(task_id, f"click {target}")
        if isinstance(res, dict):
            return res.get("msg", f"Executed click on '{target}'")
        return f"Dispatched click on '{target}'"
    except Exception as exc:
        return f"Error clicking element '{target}': {exc}"


def _handle_find_on_screen(text: str, **kwargs) -> str:
    try:
        from engines.screen_ocr import screen_ocr
        screen_text = screen_ocr.get_screen_text()
        if text.lower() in screen_text.lower():
            return f"Text '{text}' found on current screen."
        from engines.screen_context import screen_context
        ctx = screen_context.get_full_context()
        title = ctx.get("active_title", "")
        if text.lower() in title.lower():
            return f"Target '{text}' found in active window title: '{title}'"
        return f"Target '{text}' was NOT found on screen or in active window title."
    except Exception as exc:
        return f"Error searching screen: {exc}"


# ── Tool Definitions ─────────────────────────────────────────────────────────

TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "read_screen",
        "description": "Reads what is currently displayed on the user's screen using OCR and screen understanding.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "handler": _handle_read_screen,
    },
    {
        "name": "read_file",
        "description": "Reads the text contents of a file at the specified path.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The absolute or relative file path to read.",
                }
            },
            "required": ["path"],
        },
        "handler": _handle_read_file,
    },
    {
        "name": "write_file",
        "description": "Writes or overwrites text content to a file at the specified path.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The file path to write to.",
                },
                "content": {
                    "type": "string",
                    "description": "The text content to write into the file.",
                },
            },
            "required": ["path", "content"],
        },
        "handler": _handle_write_file,
    },
    {
        "name": "search_knowledge",
        "description": "Searches long-term knowledge graph for personal facts, family relations, preferences, or entity relationships.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The natural language query or entity name to search for.",
                }
            },
            "required": ["query"],
        },
        "handler": _handle_search_knowledge,
    },
    {
        "name": "add_knowledge",
        "description": "Extracts and stores verified personal facts or entity relationships into long-term knowledge graph.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The natural language statement containing facts to remember (e.g. 'Sarwan works at Google').",
                }
            },
            "required": ["text"],
        },
        "handler": _handle_add_knowledge,
    },
    {
        "name": "open_app",
        "description": "Launches or brings to focus an application on the user's computer (e.g. Chrome, Notepad, VS Code).",
        "parameters": {
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "The name of the application to open.",
                }
            },
            "required": ["app_name"],
        },
        "handler": _handle_open_app,
    },
    {
        "name": "get_time",
        "description": "Returns the current date, day of the week, and accurate local time.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "handler": _handle_get_time,
    },
    {
        "name": "web_search",
        "description": "Performs a web search to find current information, documentation, or answers.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query string.",
                }
            },
            "required": ["query"],
        },
        "handler": _handle_web_search,
    },
    {
        "name": "get_system_info",
        "description": "Retrieves operating system details, CPU, memory, battery, and disk status.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "handler": _handle_get_system_info,
    },
    {
        "name": "capture_screen",
        "description": "Performs an on-demand screen capture and returns full snapshot text and window context.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "handler": _handle_capture_screen,
    },
    {
        "name": "analyze_screen",
        "description": "Analyzes the current active window, focused application, dialog overlays, and screen anomalies.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
        "handler": _handle_analyze_screen,
    },
    {
        "name": "click_element",
        "description": "Clicks a visual or accessible button or UI element by name on the active screen.",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "The label, title, or name of the button/control to click.",
                }
            },
            "required": ["target"],
        },
        "handler": _handle_click_element,
    },
    {
        "name": "find_on_screen",
        "description": "Searches for a specific text string or UI element anywhere on the current screen.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text keyword to search for on the display.",
                }
            },
            "required": ["text"],
        },
        "handler": _handle_find_on_screen,
    },
]


# ── Format Tools for Prompt ──────────────────────────────────────────────────

def format_tools_for_prompt() -> str:
    """
    Formats the available tools into a clear instruction block
    suitable for injecting into the LLM system prompt.
    """
    lines = [
        "### AVAILABLE TOOLS",
        "You have access to the following tools to interact with the environment, inspect the screen, query memory, or manage files.",
        "If you need to call a tool to answer the user's request, emit a tool call block using the exact syntax below.",
        "",
        "Syntax for tool calls:",
        "<tool_call>",
        '{"name": "tool_name", "arguments": {"param1": "value1"}}',
        "</tool_call>",
        "",
        "Tools:",
    ]

    for tool in TOOL_DEFINITIONS:
        lines.append(f"- **{tool['name']}**: {tool['description']}")
        props = tool.get("parameters", {}).get("properties", {})
        if props:
            req = tool.get("parameters", {}).get("required", [])
            param_desc = []
            for p_name, p_info in props.items():
                r_mark = " (required)" if p_name in req else " (optional)"
                param_desc.append(f"{p_name}: {p_info.get('type', 'any')}{r_mark} - {p_info.get('description', '')}")
            lines.append("  Parameters:")
            for p in param_desc:
                lines.append(f"    • {p}")
        else:
            lines.append("  Parameters: none")
        lines.append("")

    lines.append(
        "Important: After calling a tool, you will receive the tool result in the next turn. "
        "Review the result before providing your final response to the user. "
        "When you have enough information to answer completely, respond directly to the user without emitting <tool_call>."
    )
    return "\n".join(lines)


# ── Parser ───────────────────────────────────────────────────────────────────

_TOOL_CALL_REGEX = re.compile(r"<tool_call>\s*({.*?})\s*</tool_call>", re.DOTALL | re.IGNORECASE)
_MARKDOWN_JSON_REGEX = re.compile(r"```(?:json)?\s*({[\s\S]*?\"name\"[\s\S]*?})\s*```", re.DOTALL | re.IGNORECASE)


def parse_tool_call(llm_output: str) -> Optional[Tuple[str, Dict[str, Any]]]:
    """
    Parses a tool call from LLM response text.
    Returns (tool_name, arguments_dict) if a tool call was detected and parsed,
    or None if no tool call is present.
    """
    if not llm_output or not isinstance(llm_output, str):
        return None

    # 1. Match explicit <tool_call>{...}</tool_call>
    m = _TOOL_CALL_REGEX.search(llm_output)
    if m:
        raw_json = m.group(1).strip()
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict) and "name" in parsed:
                tool_name = parsed["name"]
                args = parsed.get("arguments", parsed.get("parameters", {}))
                if isinstance(args, dict):
                    return tool_name, args
                return tool_name, {}
        except Exception as e:
            log.warning("Failed to parse tool_call JSON: %s (raw: %s)", e, raw_json)

    # 2. Match markdown code block containing JSON with "name" and "arguments"
    m_block = _MARKDOWN_JSON_REGEX.search(llm_output)
    if m_block:
        raw_json = m_block.group(1).strip()
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict) and "name" in parsed:
                # Ensure it corresponds to a known tool name
                name = parsed["name"]
                if any(t["name"] == name for t in TOOL_DEFINITIONS):
                    args = parsed.get("arguments", parsed.get("parameters", {}))
                    if isinstance(args, dict):
                        return name, args
                    return name, {}
        except Exception:
            pass

    # 3. Direct JSON string check if entire output is a JSON tool call
    stripped = llm_output.strip()
    if stripped.startswith("{") and stripped.endswith("}") and '"name"' in stripped:
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict) and "name" in parsed:
                name = parsed["name"]
                if any(t["name"] == name for t in TOOL_DEFINITIONS):
                    args = parsed.get("arguments", parsed.get("parameters", {}))
                    if isinstance(args, dict):
                        return name, args
                    return name, {}
        except Exception:
            pass

    return None
