#!/usr/bin/env python3

"""
Browser Tool Integration for Robin's LangGraph Agent.

This module patches the execute_tool_node to recognize browser tool calls
and route them to the Playwright-direct browser_tool module instead of
going through the MCP registry.

Usage in robin_agent_langgraph.py:
    from rudy.tools.browser_integration import (
        is_browser_tool_call,
        dispatch_browser_tool,
        BROWSER_TOOLS_PROMPT,
    )

    # In execute_tool_node, before MCP dispatch:
    if is_browser_tool_call(tool_name):
        result_text = dispatch_browser_tool(tool_name, tool_args)
    else:
        # existing MCP dispatch...

Robin's system prompt should include BROWSER_TOOLS_PROMPT so the LLM
knows the tool exists and how to call it.

Lucius Gate: Part of LG-002 (Playwright integration), APPROVED.
"""

import logging

logger = logging.getLogger("robin.tools.browser_integration")

# Tool names that Robin can use to invoke browser capability
BROWSER_TOOL_NAMES = {
    "robin.Browse",
    "robin.browse",
    "robin-browser.Browse",
    "browser.browse",
    "Browse",
    "browse",
}

BROWSER_SEARCH_NAMES = {
    "robin.SearchWeb",
    "robin.search_web",
    "robin-browser.SearchWeb",
    "browser.search",
    "SearchWeb",
    "search_web",
}

BROWSER_CHECK_NAMES = {
    "robin.CheckURLs",
    "robin.check_urls",
    "robin-browser.CheckURLs",
    "browser.check_urls",
    "CheckURLs",
    "check_urls",
}

ALL_BROWSER_TOOLS = BROWSER_TOOL_NAMES | BROWSER_SEARCH_NAMES | BROWSER_CHECK_NAMES

def is_browser_tool_call(tool_name: str) -> bool:
    """Check if a tool name matches any browser tool variant."""
    return tool_name in ALL_BROWSER_TOOLS

def dispatch_browser_tool(tool_name: str, tool_args: dict) -> str:
    """
    Dispatch a browser tool call to the Playwright-direct handler.

    Returns text result for Robin's LLM context.
    """
    try:
        from rudy.tools.browser_tool import handle_browser_tool_call
    except ImportError as e:
        logger.error(f"Browser tool import failed: {e}")
        return f"Browser tool unavailable: {e}. Ensure playwright is installed."

    # Normalize: if tool is a search variant, ensure args have 'search' key
    if tool_name in BROWSER_SEARCH_NAMES:
        if "search" not in tool_args and "query" in tool_args:
            tool_args["search"] = tool_args.pop("query")
        elif "search" not in tool_args and "url" not in tool_args:
            # Treat the first string arg as a search query
            for key, val in tool_args.items():
                if isinstance(val, str):
                    tool_args = {"search": val}
                    break

    # Normalize: if tool is a check variant, ensure args have 'check_urls' key
    if tool_name in BROWSER_CHECK_NAMES:
        if "check_urls" not in tool_args and "urls" in tool_args:
            tool_args["check_urls"] = tool_args.pop("urls")

    logger.info(f"Browser tool dispatch: {tool_name} -> {list(tool_args.keys())}")
    return handle_browser_tool_call(tool_args)

# ---------------------------------------------------------------------------
# Prompt addition for Robin's system prompt
# ---------------------------------------------------------------------------

BROWSER_TOOLS_PROMPT = """
- robin.Browse: Open a URL and extract page content
  Args: {"url": "https://...", "selector": "#optional-css-selector", "screenshot": false}
  Use for: reading web pages, checking dashboards, monitoring status pages

- robin.SearchWeb: Search the web via DuckDuckGo
  Args: {"query": "search terms here"}
  Use for: finding information, researching topics

- robin.CheckURLs: Check multiple URLs for availability
  Args: {"urls": ["https://url1.com", "https://url2.com"]}
  Use for: monitoring multiple services, health checks
"""
