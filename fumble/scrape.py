import html as html_lib
from pathlib import Path
from typing import Literal

from curl_cffi import requests as curl_requests
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

_REPO_ROOT = Path(__file__).parent.parent
BROWSER_PROFILE = _REPO_ROOT / "data/browser_profile"

Scraper = Literal["auto", "browser", "curl"]

_CLOUDFLARE_BLOCK_MARKERS = ["Ray ID", "Sorry, you have been blocked"]


def _is_blocked(text: str) -> bool:
    return any(marker in text for marker in _CLOUDFLARE_BLOCK_MARKERS)


_LINKEDIN_TAIL_MARKERS = [
    "\n### Seniority level",
    "\n### Employment type",
    "\n### Job function",
    "\n### Industries",
    "\nSet alert for similar jobs",
    "\nSee how you compare to other applicants",
    "\nPeople also viewed",
    "\nSimilar jobs",
]


def _postprocess(text: str, url: str) -> str:
    text = html_lib.unescape(text)
    if "linkedin.com" in url:
        for marker in _LINKEDIN_TAIL_MARKERS:
            idx = text.find(marker)
            if idx != -1:
                text = text[:idx]
    return text.strip()[:_MAX_TEXT_LENGTH]


def _extract_jsonld_job(html: str) -> str | None:
    """Extract job details from JSON-LD JobPosting schema if present."""
    import json
    import re

    blocks = re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE)
    for block in blocks:
        try:
            data = json.loads(block)
        except (json.JSONDecodeError, ValueError):
            continue

        # Handle @graph arrays and plain objects
        candidates = data if isinstance(data, list) else [data]
        if isinstance(data, dict) and "@graph" in data:
            candidates = data["@graph"]

        for obj in candidates:
            if not isinstance(obj, dict):
                continue
            obj_type = obj.get("@type", "")
            types = obj_type if isinstance(obj_type, list) else [obj_type]
            if "JobPosting" not in types:
                continue

            title = obj.get("title") or obj.get("name") or ""
            org = obj.get("hiringOrganization", {})
            if isinstance(org, dict):
                org_name = org.get("name", "")
            else:
                org_name = str(org)

            parts = []
            if title and org_name:
                parts.append(f"# {title} at {org_name}\n")
            elif title:
                parts.append(f"# {title}\n")

            def _clean(s: str) -> str:
                s = html_lib.unescape(s)
                s = re.sub(r"<[^>]+>", " ", s)
                s = re.sub(r"[ \t]+", " ", s)
                s = re.sub(r"\n{3,}", "\n\n", s)
                return s.strip()

            description = obj.get("description", "")
            if description:
                parts.append(_clean(description))

            for field in ("qualifications", "responsibilities", "benefits"):
                val = obj.get(field, "")
                if val:
                    parts.append(f"\n## {field.capitalize()}\n{_clean(val)}")

            result = "\n\n".join(parts).strip()
            if result:
                return result[:_MAX_TEXT_LENGTH]

    return None


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


_MAX_TEXT_LENGTH = 15_000  # chars — job listings are never longer than this


def _strip_html(html: str) -> str:
    import re
    # Remove scripts, styles, and structural/navigational elements with their content
    html = re.sub(r"<(script|style|nav|header|footer|aside)[^>]*>.*?</(script|style|nav|header|footer|aside)>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<[^>]+>", " ", html)
    html = re.sub(r"[ \t]+", " ", html)
    html = re.sub(r"\n{3,}", "\n\n", html)
    text = html.strip()
    return text[:_MAX_TEXT_LENGTH]


def _scrape_curl(url: str) -> tuple[str, str, str]:
    """Fetch using curl_cffi, impersonating Firefox. Raises on failure or block."""
    r = curl_requests.get(url, impersonate="firefox", allow_redirects=True)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    if _is_blocked(r.text):
        raise RuntimeError("Cloudflare block detected")
    if jsonld := _extract_jsonld_job(r.text):
        method = "JSON-LD"
        text = jsonld
    elif next_data := _extract_next_data(r.text):
        method = "__NEXT_DATA__"
        text = next_data
    else:
        method = "strip_html"
        text = _strip_html(r.text)
    print(f"  scraper: {method}")
    text = _postprocess(text, str(r.url))
    print(f"  text length: {len(text):,} chars")
    return text, str(r.url), method


def _scrape_browser(url: str) -> tuple[str, str, str]:
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

        text = page.inner_text("body")
        method = "browser/inner_text"
        print(f"  scraper: {method}")
        text = _postprocess(text, page.url)
        print(f"  text length: {len(text):,} chars")
        result = text, page.url, method
        context.close()
        return result


def scrape_job_page(url: str, scraper: Scraper = "auto") -> tuple[str, str, str]:
    """Fetch a job page and return (text, resolved_url, scrape_method).

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
