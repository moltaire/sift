import html
import os
import re
import tomllib
from datetime import date, timedelta
from email import message_from_bytes
from email.message import Message
from pathlib import Path

import imapclient
from dotenv import load_dotenv

load_dotenv()

SOURCES_PATH = Path("resources/sources.toml")


def _load_sources() -> list[dict]:
    with open(SOURCES_PATH, "rb") as f:
        return tomllib.load(f)["sources"]


def _connect() -> imapclient.IMAPClient:
    host = os.environ["IMAP_HOST"]
    port = int(os.environ.get("IMAP_PORT", 993))
    email = os.environ["IMAP_EMAIL"]
    password = os.environ["IMAP_PASSWORD"]

    server = imapclient.IMAPClient(host, port=port, ssl=True)
    server.login(email, password)
    return server


def _get_html_body(msg: Message) -> str:
    """Extract HTML (or plain text) body from a parsed email."""
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            return part.get_payload(decode=True).decode("utf-8", errors="ignore")
    # fallback to plain text
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            return part.get_payload(decode=True).decode("utf-8", errors="ignore")
    return ""


def _extract_urls(text: str, pattern: str, dedup_pattern: str | None = None) -> list[str]:
    """
    Extract all URLs matching pattern from raw HTML/text.
    If dedup_pattern is given, deduplicate by the first capture group of that pattern.
    """
    all_urls = re.findall(r'https?://[^\s"\'<>]+', text)
    matched = [html.unescape(url) for url in all_urls if re.search(pattern, url)]

    if not dedup_pattern:
        return matched

    seen = set()
    result = []
    for url in matched:
        m = re.search(dedup_pattern, url)
        key = m.group(1) if m else url
        if key not in seen:
            seen.add(key)
            result.append(url)
    return result


def fetch_job_urls(since: date | None = None, unread_only: bool = False, mark_read: bool = False) -> list[tuple[str, str, str]]:
    """
    Fetch emails from all configured folders.
    Uses UNSEEN if unread_only=True, otherwise fetches since a given date (default: 3 days).
    Returns a list of (url, source, scraper) tuples.
    """
    if not unread_only and since is None:
        since = date.today() - timedelta(days=3)

    sources = _load_sources()
    server = _connect()
    results = []

    try:
        for source in sources:
            folder = source["folder"]
            name = source["name"]
            pattern = source["url_pattern"]
            scraper = source.get("scraper", "auto")

            server.select_folder(folder)

            if unread_only:
                uids = server.search(["UNSEEN"])
                label = "unread"
            else:
                uids = server.search(["SINCE", since])
                label = f"since {since}"

            if not uids:
                print(f"[{name}] No emails ({label})")
                continue

            print(f"[{name}] {len(uids)} email(s) found")
            messages = server.fetch(uids, [b"BODY.PEEK[]"])

            url_count = 0
            for uid, data in messages.items():
                raw = data[b"BODY[]"]
                msg = message_from_bytes(raw)
                body = _get_html_body(msg)
                dedup_pattern = source.get("dedup_pattern")
                urls = _extract_urls(body, pattern, dedup_pattern)
                url_count += len(urls)
                for url in urls:
                    results.append((url, name, scraper))

            print(f"[{name}] {url_count} URL(s) extracted")
            if mark_read and uids:
                server.set_flags(uids, [b"\\Seen"])

    finally:
        server.logout()

    return results
