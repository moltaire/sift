from pathlib import Path
from typing import Literal

from curl_cffi import requests as curl_requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

BROWSER_PROFILE = Path("data/browser_profile")

Scraper = Literal["auto", "browser", "curl"]

_CLOUDFLARE_BLOCK_MARKERS = ["Ray ID", "Sorry, you have been blocked"]


def _is_blocked(text: str) -> bool:
    return any(marker in text for marker in _CLOUDFLARE_BLOCK_MARKERS)


def _extract_next_data(html: str) -> str | None:
    """Extract and flatten text from Next.js __NEXT_DATA__ JSON if present."""
    import json
    import re
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        return None

    def collect_strings(obj: object, min_len: int = 80) -> list[str]:
        if isinstance(obj, str):
            return [obj] if len(obj) >= min_len else []
        if isinstance(obj, dict):
            return [s for v in obj.values() for s in collect_strings(v, min_len)]
        if isinstance(obj, list):
            return [s for v in obj for s in collect_strings(v, min_len)]
        return []

    data = json.loads(m.group(1))
    strings = collect_strings(data)
    if not strings:
        return None

    # Strip HTML tags from each string
    cleaned = []
    for s in strings:
        s = re.sub(r"<[^>]+>", " ", s)
        s = re.sub(r"[ \t]+", " ", s).strip()
        if s:
            cleaned.append(s)
    return "\n\n".join(cleaned)


def _strip_html(html: str) -> str:
    import re
    html = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"[ \t]+", " ", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    return html.strip()


def _scrape_curl(url: str) -> tuple[str, str]:
    """Fetch using curl_cffi, impersonating Firefox. Raises on failure or block."""
    r = curl_requests.get(url, impersonate="firefox", allow_redirects=True)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    if _is_blocked(r.text):
        raise RuntimeError("Cloudflare block detected")
    text = _extract_next_data(r.text) or _strip_html(r.text)
    return text, str(r.url)


def _scrape_browser(url: str) -> tuple[str, str]:
    """Fetch using Playwright persistent context (preserves login state)."""
    BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(BROWSER_PROFILE),
            headless=True,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.new_page()
        page.goto(url, wait_until="load")

        try:
            page.get_by_role("button", name="Alles akzeptieren").click(timeout=3000)
        except PlaywrightTimeoutError:
            pass

        result = page.inner_text("body"), page.url
        context.close()
        return result


def scrape_job_page(url: str, scraper: Scraper = "auto") -> tuple[str, str]:
    """Fetch a job page and return (text, resolved_url).

    scraper="auto"    try curl first, fall back to browser
    scraper="curl"    curl only
    scraper="browser" browser only (use for login-required sources)
    """
    if scraper == "browser":
        return _scrape_browser(url)

    if scraper == "curl":
        return _scrape_curl(url)

    # auto: try curl, fall back to browser
    try:
        return _scrape_curl(url)
    except Exception as e:
        print(f"  curl failed ({e}), falling back to browser...")
        return _scrape_browser(url)


def login_flow(start_url: str = "https://www.linkedin.com/login") -> None:
    """Open a headed browser for manual login, then save the session."""
    BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(BROWSER_PROFILE),
            headless=False,
            channel="chrome",
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.new_page()
        page.goto(start_url, wait_until="load")
        print("Log in, then press Enter here to save the session and close the browser.")
        input()
        context.close()
