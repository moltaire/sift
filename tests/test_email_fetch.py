"""Tests for pure functions in fumble/email_fetch.py."""
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import pytest

from fumble.email_fetch import _extract_urls, _get_html_body


# ---------------------------------------------------------------------------
# _extract_urls
# ---------------------------------------------------------------------------

def test_extract_urls_basic_match():
    text = 'See job at <a href="https://click.stepstone.de/job/123">here</a>'
    result = _extract_urls(text, "stepstone.de")
    assert result == ["https://click.stepstone.de/job/123"]


def test_extract_urls_no_match():
    text = "Visit https://example.com for details"
    result = _extract_urls(text, "stepstone.de")
    assert result == []


def test_extract_urls_multiple_matches():
    text = (
        'https://click.stepstone.de/job/1 '
        'https://click.stepstone.de/job/2 '
        'https://unrelated.com/other'
    )
    result = _extract_urls(text, "stepstone.de")
    assert len(result) == 2
    assert all("stepstone.de" in u for u in result)


def test_extract_urls_html_unescaping():
    # HTML-encoded ampersands should be decoded
    text = 'href="https://click.stepstone.de/job?id=1&amp;ref=email"'
    result = _extract_urls(text, "stepstone.de")
    assert result == ["https://click.stepstone.de/job?id=1&ref=email"]


def test_extract_urls_dedup_by_capture_group():
    # Two tracking URLs pointing to the same LinkedIn job ID
    text = (
        "https://www.linkedin.com/comm/jobs/view/111/?tracking=aaa "
        "https://www.linkedin.com/comm/jobs/view/111/?tracking=bbb "
        "https://www.linkedin.com/comm/jobs/view/222/?tracking=ccc"
    )
    result = _extract_urls(text, r"linkedin\.com/comm/jobs/view/", dedup_pattern=r"view/(\d+)")
    assert len(result) == 2
    assert any("111" in u for u in result)
    assert any("222" in u for u in result)


def test_extract_urls_dedup_falls_back_to_full_url_when_no_capture():
    # If the dedup pattern doesn't match, the full URL is used as the key
    text = (
        "https://goodjobs.eu/job/abc "
        "https://goodjobs.eu/job/abc"
    )
    result = _extract_urls(text, "goodjobs.eu", dedup_pattern=r"NOMATCH/(\d+)")
    # Both have the same full URL — dedup should keep one
    assert len(result) == 1


def test_extract_urls_no_dedup_keeps_duplicates():
    text = (
        "https://click.stepstone.de/job/123 "
        "https://click.stepstone.de/job/123"
    )
    result = _extract_urls(text, "stepstone.de", dedup_pattern=None)
    assert len(result) == 2


def test_extract_urls_empty_text():
    assert _extract_urls("", "stepstone.de") == []


# ---------------------------------------------------------------------------
# _get_html_body
# ---------------------------------------------------------------------------

def test_get_html_body_prefers_html_part():
    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText("plain text", "plain"))
    msg.attach(MIMEText("<p>html content</p>", "html"))
    result = _get_html_body(msg)
    assert "<p>html content</p>" in result


def test_get_html_body_falls_back_to_plain():
    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText("plain only", "plain"))
    result = _get_html_body(msg)
    assert "plain only" in result


def test_get_html_body_returns_empty_for_no_body():
    msg = MIMEMultipart("mixed")
    result = _get_html_body(msg)
    assert result == ""


def test_get_html_body_simple_html_message():
    msg = MIMEText("<html><body>Job alert</body></html>", "html")
    result = _get_html_body(msg)
    assert "Job alert" in result
