"""Tests for fumble/store.py — all run against a temp DB, never touch data/fumble.db."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from fumble.assess import Assessment, Gap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_assessment(**overrides) -> Assessment:
    defaults = dict(
        url="https://example.com/jobs/123",
        source="TestSource",
        employer="Acme Corp",
        job_title="Software Engineer",
        language="EN",
        listing_text="We are looking for a software engineer...",
        job_summary="Backend role at a mid-sized SaaS company.",
        role_check=True,
        domain_fit="high",
        domain_fit_reason="Matches target domain exactly.",
        role_fit="medium",
        role_fit_reason="Partial overlap with target roles.",
        gap_risk="low",
        gap_risk_reason="No significant gaps identified.",
        fit_areas=["Python expertise", "Remote-first culture"],
        gaps=[Gap(description="No Go experience", severity="minor")],
        suggestion="apply",
        reasoning="Strong domain fit. Minor gap in Go is unlikely to block.",
        scraped_at=datetime(2024, 1, 15, 10, 0, tzinfo=timezone.utc),
        assessed_at=datetime(2024, 1, 15, 10, 5, tzinfo=timezone.utc),
        assessed_model="ollama/llama3.2",
    )
    defaults.update(overrides)
    return Assessment(**defaults)


@pytest.fixture(autouse=True)
def patch_db(tmp_path, monkeypatch):
    """Redirect all store operations to a temp database."""
    import fumble.store as store
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "test.db")
    store.init_db()


# ---------------------------------------------------------------------------
# init_db
# ---------------------------------------------------------------------------

def test_init_db_creates_tables(tmp_path, monkeypatch):
    import sqlite3
    import fumble.store as store
    db_path = tmp_path / "fresh.db"
    monkeypatch.setattr(store, "DB_PATH", db_path)
    store.init_db()
    conn = sqlite3.connect(db_path)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "assessments" in tables
    assert "seen_urls" in tables
    conn.close()


def test_init_db_idempotent():
    import fumble.store as store
    # calling twice should not raise
    store.init_db()
    store.init_db()


# ---------------------------------------------------------------------------
# save_assessment
# ---------------------------------------------------------------------------

def test_save_assessment_roundtrip():
    import fumble.store as store
    a = _make_assessment()
    store.save_assessment(a)
    results = store.load_assessments()
    assert len(results) == 1
    r = results[0]
    assert r.url == a.url
    assert r.employer == "Acme Corp"
    assert r.job_title == "Software Engineer"
    assert r.suggestion == "apply"
    assert r.rating == "new"
    assert r.fit_areas == ["Python expertise", "Remote-first culture"]
    assert len(r.gaps) == 1
    assert r.gaps[0].description == "No Go experience"
    assert r.gaps[0].severity == "minor"


def test_save_assessment_duplicate_is_ignored():
    import fumble.store as store
    a = _make_assessment()
    store.save_assessment(a)
    store.save_assessment(a)  # second call should be silently ignored
    assert len(store.load_assessments()) == 1


def test_save_assessment_preserves_default_rating():
    import fumble.store as store
    store.save_assessment(_make_assessment())
    assert store.load_assessments()[0].rating == "new"


# ---------------------------------------------------------------------------
# update_assessment
# ---------------------------------------------------------------------------

def test_update_assessment_inserts_new():
    import fumble.store as store
    a = _make_assessment()
    store.update_assessment(a)
    assert len(store.load_assessments()) == 1


def test_update_assessment_overwrites_fields():
    import fumble.store as store
    a = _make_assessment()
    store.save_assessment(a)
    updated = _make_assessment(employer="New Employer", suggestion="skip")
    store.update_assessment(updated)
    results = store.load_assessments()
    assert len(results) == 1
    assert results[0].employer == "New Employer"
    assert results[0].suggestion == "skip"


def test_update_assessment_preserves_rating():
    import fumble.store as store
    a = _make_assessment()
    store.save_assessment(a)
    store.update_rating(a.url, "liked")
    store.update_assessment(_make_assessment(employer="Changed"))
    assert store.load_assessments()[0].rating == "liked"


# ---------------------------------------------------------------------------
# url_exists / tracking_url_seen / mark_url_seen
# ---------------------------------------------------------------------------

def test_url_exists_false_before_save():
    import fumble.store as store
    assert not store.url_exists("https://example.com/jobs/999")


def test_url_exists_true_after_save():
    import fumble.store as store
    a = _make_assessment()
    store.save_assessment(a)
    assert store.url_exists(a.url)


def test_tracking_url_seen_false_initially():
    import fumble.store as store
    assert not store.tracking_url_seen("https://tracking.example.com/click/abc")


def test_mark_url_seen_and_check():
    import fumble.store as store
    url = "https://tracking.example.com/click/abc"
    store.mark_url_seen(url)
    assert store.tracking_url_seen(url)


def test_mark_url_seen_idempotent():
    import fumble.store as store
    url = "https://tracking.example.com/click/abc"
    store.mark_url_seen(url)
    store.mark_url_seen(url)  # second call should not raise
    assert store.tracking_url_seen(url)


# ---------------------------------------------------------------------------
# update_rating
# ---------------------------------------------------------------------------

def test_update_rating():
    import fumble.store as store
    a = _make_assessment()
    store.save_assessment(a)
    for rating in ("liked", "disliked", "superliked", "new"):
        store.update_rating(a.url, rating)
        assert store.load_assessments()[0].rating == rating


# ---------------------------------------------------------------------------
# clear_ratings
# ---------------------------------------------------------------------------

def test_clear_ratings_resets_all():
    import fumble.store as store
    a1 = _make_assessment(url="https://example.com/1")
    a2 = _make_assessment(url="https://example.com/2")
    store.save_assessment(a1)
    store.save_assessment(a2)
    store.update_rating(a1.url, "liked")
    store.update_rating(a2.url, "disliked")
    count = store.clear_ratings()
    assert count == 2
    for a in store.load_assessments():
        assert a.rating == "new"


def test_clear_ratings_returns_zero_when_nothing_to_reset():
    import fumble.store as store
    store.save_assessment(_make_assessment())
    count = store.clear_ratings()
    assert count == 0  # already "new"


# ---------------------------------------------------------------------------
# delete_assessment
# ---------------------------------------------------------------------------

def test_delete_assessment():
    import fumble.store as store
    a = _make_assessment()
    store.save_assessment(a)
    store.delete_assessment(a.url)
    assert len(store.load_assessments()) == 0
    assert not store.url_exists(a.url)


def test_delete_nonexistent_is_noop():
    import fumble.store as store
    store.delete_assessment("https://example.com/nonexistent")  # should not raise


# ---------------------------------------------------------------------------
# load_assessments ordering
# ---------------------------------------------------------------------------

def test_load_assessments_newest_first():
    import fumble.store as store
    older = _make_assessment(url="https://example.com/old", scraped_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
    newer = _make_assessment(url="https://example.com/new", scraped_at=datetime(2024, 6, 1, tzinfo=timezone.utc))
    store.save_assessment(older)
    store.save_assessment(newer)
    results = store.load_assessments()
    assert results[0].url == "https://example.com/new"
    assert results[1].url == "https://example.com/old"
