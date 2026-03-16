"""Tests for pure text-processing functions in fumble/scrape.py."""
import json

import pytest

from fumble.scrape import _is_blocked, _strip_html, _extract_next_data


# ---------------------------------------------------------------------------
# _is_blocked
# ---------------------------------------------------------------------------

def test_is_blocked_detects_ray_id():
    assert _is_blocked("Please wait... Ray ID: abc123")


def test_is_blocked_detects_cloudflare_message():
    assert _is_blocked("Sorry, you have been blocked")


def test_is_blocked_false_for_normal_page():
    assert not _is_blocked("<html><body>Software Engineer at Acme</body></html>")


def test_is_blocked_false_for_empty():
    assert not _is_blocked("")


# ---------------------------------------------------------------------------
# _strip_html
# ---------------------------------------------------------------------------

def test_strip_html_removes_tags():
    result = _strip_html("<p>Hello <b>world</b></p>")
    assert "<" not in result
    assert "Hello" in result
    assert "world" in result


def test_strip_html_removes_script_content():
    result = _strip_html("<script>alert('xss')</script><p>Job description</p>")
    assert "alert" not in result
    assert "Job description" in result


def test_strip_html_removes_style_content():
    result = _strip_html("<style>.foo { color: red }</style><p>Apply now</p>")
    assert "color" not in result
    assert "Apply now" in result


def test_strip_html_removes_nav_and_footer():
    result = _strip_html("<nav>Home About</nav><main>Job title</main><footer>© 2024</footer>")
    assert "Home" not in result
    assert "Job title" in result
    assert "2024" not in result


def test_strip_html_truncates_to_max_length():
    long_html = "<p>" + "x" * 20_000 + "</p>"
    result = _strip_html(long_html)
    assert len(result) <= 15_000


def test_strip_html_collapses_whitespace():
    result = _strip_html("<p>Hello     world</p>")
    assert "  " not in result


def test_strip_html_empty_input():
    assert _strip_html("") == ""


# ---------------------------------------------------------------------------
# _extract_next_data
# ---------------------------------------------------------------------------

def _make_next_data_html(data: dict) -> str:
    payload = json.dumps(data)
    return f'<script id="__NEXT_DATA__" type="application/json">{payload}</script>'


def test_extract_next_data_returns_none_without_script():
    assert _extract_next_data("<html><body>No Next.js here</body></html>") is None


def test_extract_next_data_extracts_long_strings():
    data = {"props": {"pageProps": {"description": "A" * 100}}}
    result = _extract_next_data(_make_next_data_html(data))
    assert result is not None
    assert "A" * 80 in result


def test_extract_next_data_skips_short_strings():
    # Strings shorter than 80 chars should be ignored
    data = {"props": {"short": "hi"}}
    result = _extract_next_data(_make_next_data_html(data))
    assert result is None


def test_extract_next_data_strips_html_tags():
    data = {"description": "<p>" + "B" * 100 + "</p>"}
    result = _extract_next_data(_make_next_data_html(data))
    assert result is not None
    assert "<p>" not in result
    assert "B" * 80 in result


def test_extract_next_data_handles_nested_objects():
    data = {"a": {"b": {"c": "C" * 100}}}
    result = _extract_next_data(_make_next_data_html(data))
    assert result is not None
    assert "C" * 80 in result


def test_extract_next_data_handles_lists():
    data = {"items": ["D" * 100, "E" * 100]}
    result = _extract_next_data(_make_next_data_html(data))
    assert result is not None
    assert "D" * 80 in result
    assert "E" * 80 in result


def test_extract_next_data_returns_none_for_empty_data():
    result = _extract_next_data(_make_next_data_html({}))
    assert result is None
