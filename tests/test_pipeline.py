"""Tests for pure utility functions in main.py."""
import sys
import unittest.mock as mock
from pathlib import Path

import pytest

# main.py lives at the project root and reads resource files at import time.
# Stub those reads so the tests work without profile.md / search-criteria.md.
with mock.patch("pathlib.Path.read_text", return_value="stub content"):
    sys.path.insert(0, str(Path(__file__).parent.parent))
    import main


# ---------------------------------------------------------------------------
# _strip_params
# ---------------------------------------------------------------------------

def test_strip_params_removes_query():
    url = "https://www.linkedin.com/jobs/view/12345/?tracking=foo&ref=bar"
    assert main._strip_params(url) == "https://www.linkedin.com/jobs/view/12345/"


def test_strip_params_removes_fragment():
    url = "https://example.com/job#section"
    assert main._strip_params(url) == "https://example.com/job"


def test_strip_params_leaves_clean_url_unchanged():
    url = "https://goodjobs.eu/jobs/software-engineer"
    assert main._strip_params(url) == url


def test_strip_params_handles_both_query_and_fragment():
    url = "https://example.com/job?ref=email#apply"
    assert main._strip_params(url) == "https://example.com/job"


# ---------------------------------------------------------------------------
# _is_wall
# ---------------------------------------------------------------------------

def test_is_wall_detects_checkpoint():
    assert main._is_wall("https://www.linkedin.com/checkpoint/challengesV2/abc")


def test_is_wall_detects_login():
    assert main._is_wall("https://www.linkedin.com/login?redirect=/jobs")


def test_is_wall_detects_authwall():
    assert main._is_wall("https://www.linkedin.com/authwall?trk=foo")


def test_is_wall_detects_signin():
    assert main._is_wall("https://example.com/signin?next=/job/123")


def test_is_wall_detects_sign_in():
    assert main._is_wall("https://example.com/sign-in")


def test_is_wall_false_for_normal_job_url():
    assert not main._is_wall("https://www.linkedin.com/jobs/view/4356712616/")


def test_is_wall_case_insensitive():
    assert main._is_wall("https://example.com/LOGIN")
