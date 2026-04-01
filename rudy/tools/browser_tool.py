#!/usr/bin/env python3

"""
Browser Tool for Robin Agent -- Playwright-direct web capability.

Provides Robin with autonomous web browsing via Playwright (no AI agent wrapper).
Robin's LangGraph loop handles the reasoning; this tool handles the browser.

Architecture:
    Robin (LangGraph) -> browser_tool.browse() -> Playwright -> Chromium (headless)

    This is a TOOL, not a sub-agent. Robin decides what to browse and what to
    extract. The tool just opens the page and returns content.

Capabilities:
    - browse(url) -> page title + text content + meta info
    - browse(url, selector) -> extract specific element text
    - browse(url, screenshot=True) -> take screenshot (for visual monitoring)
    - search(query) -> simple web search (via DuckDuckGo HTML)

Headless mode is ALWAYS ON -- critical for NightShift when desktop is locked.

Lucius Gate: LG-002, APPROVED 2026-03-29 (Lite Review, 3 deps, LOW risk)

Dependencies:
    - playwright (+ greenlet, pyee) -- already installed on Oracle
    - Chromium browser binary -- installed via playwright install chromium
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote_plus

logger = logging.getLogger("robin.tools.browser")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Max page text to return (avoid flooding Robin's context window)
MAX_TEXT_LENGTH = 8000

# Default timeout for page loads (ms)
DEFAULT_TIMEOUT_MS = 30000

# Screenshot save location
from rudy.paths import SCREENSHOT_DIR  # noqa: E402

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class BrowseResult:
    """Result of a browser action."""
    success: bool
    url: str
    title: str = ""
    text: str = ""
    meta: dict = field(default_factory=dict)
    screenshot_path: str = ""
    error: str = ""
    duration_ms: int = 0

    def to_tool_response(self) -> str:
        """Format as text for Robin's LLM context."""
        if not self.success:
            return f"Browse FAILED: {self.error}"

        parts = [
            f"URL: {self.url}",
            f"Title: {self.title}",
        ]

        if self.meta:
            desc = self.meta.get("description", "")
            if desc:
                parts.append(f"Description: {desc}")

        if self.text:
            text = self.text[:MAX_TEXT_LENGTH]
            if len(self.text) > MAX_TEXT_LENGTH:
                text += f"\n... (truncated, {len(self.text)} total chars)"
            parts.append(f"\nPage Content:\n{text}")

        if self.screenshot_path:
            parts.append(f"\nScreenshot saved: {self.screenshot_path}")

        parts.append(f"\n(Loaded in {self.duration_ms}ms)")
        return "\n".join(parts)

# ---------------------------------------------------------------------------
# Core browser functions (synchronous wrappers for Robin's sync agent loop)
# ---------------------------------------------------------------------------

def browse(
    url: str,
    selector: Optional[str] = None,
    screenshot: bool = False,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> BrowseResult:
    """
    Open a URL and extract content.

    Args:
        url: The URL to navigate to
        selector: Optional CSS selector to extract specific element text
        screenshot: If True, also save a screenshot
        timeout_ms: Page load timeout in milliseconds

    Returns:
        BrowseResult with title, text, meta info, and optional screenshot path
    """
    start_time = time.time()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return BrowseResult(
            success=False,
            url=url,
            error="Playwright not installed. Run: pip install playwright && python -m playwright install chromium",
            duration_ms=int((time.time() - start_time) * 1000),
        )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",  # Prevent shared memory issues on low-RAM
                    "--disable-gpu",  # W1 has shared iGPU, don't compete for VRAM
                    "--disable-extensions",
                    "--disable-background-timer-throttling",
                ]
            )

            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36 "
                    "Robin/1.0 (Batcave Autonomous Agent)"
                ),
                viewport={"width": 1280, "height": 720},
                ignore_https_errors=True,  # Some internal dashboards use self-signed certs
            )

            page = context.new_page()

            # Navigate
            logger.info(f"Browsing: {url}")
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")

            # Extract title
            title = page.title() or ""

            # Extract meta description
            meta = {}
            try:
                desc_el = page.query_selector('meta[name="description"]')
                if desc_el:
                    meta["description"] = desc_el.get_attribute("content") or ""
            except Exception:
                pass

            # Extract text
            if selector:
                # Specific element
                try:
                    element = page.query_selector(selector)
                    text = element.inner_text() if element else f"Selector '{selector}' not found on page"
                except Exception as e:
                    text = f"Selector error: {e}"
            else:
                # Full page text (cleaned)
                text = page.inner_text("body") or ""

            # Screenshot
            screenshot_path = ""
            if screenshot:
                SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
                ts = time.strftime("%Y%m%d_%H%M%S")
                safe_url = url.replace("://", "_").replace("/", "_")[:60]
                filename = f"robin_browse_{ts}_{safe_url}.png"
                screenshot_path = str(SCREENSHOT_DIR / filename)
                page.screenshot(path=screenshot_path, full_page=False)
                logger.info(f"Screenshot saved: {screenshot_path}")

            # Get final URL (in case of redirects)
            final_url = page.url

            # Cleanup
            context.close()
            browser.close()

            duration = int((time.time() - start_time) * 1000)

            return BrowseResult(
                success=True,
                url=final_url,
                title=title,
                text=text,
                meta=meta,
                screenshot_path=screenshot_path,
                duration_ms=duration,
            )

    except Exception as e:
        duration = int((time.time() - start_time) * 1000)
        logger.error(f"Browse failed for {url}: {e}")
        return BrowseResult(
            success=False,
            url=url,
            error=str(e),
            duration_ms=duration,
        )

def search_web(query: str, max_results: int = 5) -> BrowseResult:
    """
    Simple web search via DuckDuckGo HTML (no API key needed).

    Args:
        query: Search query string
        max_results: Max results to extract

    Returns:
        BrowseResult with search results as text
    """
    search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    result = browse(search_url, timeout_ms=15000)

    if result.success:
        # DuckDuckGo HTML results are in the body text
        # Robin can parse the results from the page content
        result.meta["search_query"] = query
        result.meta["search_engine"] = "DuckDuckGo"

    return result

# ---------------------------------------------------------------------------
# Multi-page monitoring (for dashboard/status page checks)
# ---------------------------------------------------------------------------

def check_urls(urls: list[str], timeout_ms: int = 15000) -> list[BrowseResult]:
    """
    Check multiple URLs in sequence. Useful for status page monitoring.

    Args:
        urls: List of URLs to check
        timeout_ms: Timeout per page

    Returns:
        List of BrowseResult objects
    """
    results = []
    for url in urls:
        result = browse(url, timeout_ms=timeout_ms)
        results.append(result)
    return results

# ---------------------------------------------------------------------------
# Tool interface for Robin's LangGraph (matches MCP tool dispatch pattern)
# ---------------------------------------------------------------------------

def handle_browser_tool_call(args: dict) -> str:
    """
    Entry point for Robin's execute_tool node.

    Expected args formats:
        {"url": "https://example.com"}
        {"url": "https://example.com", "selector": "#main-content"}
        {"url": "https://example.com", "screenshot": true}
        {"search": "latest cybersecurity threats"}
        {"check_urls": ["https://status.example.com", "https://health.api.com"]}

    Returns:
        Text response for Robin's context
    """
    # Web search
    if "search" in args:
        result = search_web(args["search"], max_results=args.get("max_results", 5))
        return result.to_tool_response()

    # Multi-URL check
    if "check_urls" in args:
        urls = args["check_urls"]
        if isinstance(urls, str):
            urls = json.loads(urls)
        results = check_urls(urls, timeout_ms=args.get("timeout_ms", 15000))
        lines = [f"Checked {len(results)} URLs:\n"]
        for r in results:
            status = "OK" if r.success else "FAIL"
            lines.append(f"  [{status}] {r.url} - {r.title} ({r.duration_ms}ms)")
            if r.error:
                lines.append(f"    Error: {r.error}")
        return "\n".join(lines)

    # Single URL browse
    if "url" in args:
        result = browse(
            url=args["url"],
            selector=args.get("selector"),
            screenshot=args.get("screenshot", False),
            timeout_ms=args.get("timeout_ms", DEFAULT_TIMEOUT_MS),
        )
        return result.to_tool_response()

    return "Browser tool error: provide 'url', 'search', or 'check_urls' in args"

# ---------------------------------------------------------------------------
# CLI test harness
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    logging.basicConfig(level=logging.INFO)

    print("=" * 60)
    print("Browser Tool -- Test Harness")
    print("=" * 60)

    # Test 1: Browse example.com
    print("\n[TEST 1] Browse example.com...")
    result = browse("https://example.com")
    print(f"  Success: {result.success}")
    print(f"  Title: {result.title}")
    print(f"  Text length: {len(result.text)} chars")
    print(f"  Duration: {result.duration_ms}ms")
    if result.error:
        print(f"  Error: {result.error}")

    # Test 2: Tool interface
    print("\n[TEST 2] Tool interface (handle_browser_tool_call)...")
    response = handle_browser_tool_call({"url": "https://example.com"})
    print(f"  Response length: {len(response)} chars")
    print(f"  First 200 chars: {response[:200]}")

    # Test 3: Search
    print("\n[TEST 3] Web search via DuckDuckGo...")
    result = search_web("Batcave security monitoring")
    print(f"  Success: {result.success}")
    print(f"  Duration: {result.duration_ms}ms")
    if result.error:
        print(f"  Error: {result.error}")

    print("\n" + "=" * 60)
    print("Browser tool tests complete.")
    print("=" * 60)
