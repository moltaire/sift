import json
import sqlite3
from datetime import datetime
from pathlib import Path

from fumble.assess import Assessment

DB_PATH = Path(__file__).parent.parent / "data/fumble.db"


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the assessments table and apply any missing migrations."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS assessments (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                url          TEXT UNIQUE,
                source       TEXT,
                scraped_at   TEXT,
                assessed_at  TEXT,
                employer     TEXT,
                job_title    TEXT,
                language     TEXT,
                listing_text TEXT,
                domain_fit   TEXT,
                role_fit     TEXT,
                gap_risk     TEXT,
                job_summary  TEXT,
                reasoning    TEXT,
                suggestion   TEXT,
                rating       TEXT DEFAULT 'new'
            )
        """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_urls (
                url      TEXT PRIMARY KEY,
                seen_at  TEXT NOT NULL
            )
        """
        )

        for col in [
            "employer TEXT",
            "job_title TEXT",
            "listing_text TEXT",
            "job_summary TEXT",
            "domain_fit_reason TEXT",
            "role_fit_reason TEXT",
            "gap_risk_reason TEXT",
            "fit_areas TEXT DEFAULT '[]'",
            "gaps TEXT DEFAULT '[]'",
            "rating TEXT DEFAULT 'new'",
            "assessed_at TEXT",
            "assessed_model TEXT DEFAULT ''",
            "role_check INTEGER DEFAULT 1",
            "pipeline_stage TEXT DEFAULT 'assessed'",
            "scrape_method TEXT DEFAULT ''",
        ]:
            try:
                conn.execute(f"ALTER TABLE assessments ADD COLUMN {col}")
            except sqlite3.OperationalError:
                pass

        # Backfill pipeline_stage for rows created before this column existed.
        # Old spam rows (assessed_model LIKE 'spam/%') can't be distinguished as
        # keyword_spam vs llm_spam, so they get 'llm_spam' as a conservative guess.
        conn.execute(
            "UPDATE assessments SET pipeline_stage = 'llm_spam' WHERE pipeline_stage IS NULL AND assessed_model LIKE 'spam/%'"
        )
        conn.execute(
            "UPDATE assessments SET pipeline_stage = 'assessed' WHERE pipeline_stage IS NULL"
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS embeddings (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
                model         TEXT NOT NULL,
                input_type    TEXT NOT NULL,
                embedding     BLOB NOT NULL,
                embedded_at   TEXT NOT NULL
            )
        """
        )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_embeddings_unique
                ON embeddings(assessment_id, model, input_type)
        """
        )

        # Migrate bookmarked/hidden → rating (for older databases that have these columns)
        try:
            conn.execute(
                "UPDATE assessments SET rating = 'liked' WHERE bookmarked = 1 AND (rating IS NULL OR rating = 'new')"
            )
            conn.execute(
                "UPDATE assessments SET rating = 'disliked' WHERE hidden = 1 AND bookmarked = 0 AND (rating IS NULL OR rating = 'new')"
            )
        except sqlite3.OperationalError:
            pass


def save_assessment(a: Assessment) -> None:
    """Insert one assessment. Skips silently if the URL already exists."""
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO assessments
                (url, source, scrape_method, scraped_at, assessed_at, assessed_model, employer,
                 job_title, language, listing_text, job_summary, role_check, domain_fit,
                 domain_fit_reason, role_fit, role_fit_reason, gap_risk, gap_risk_reason,
                 fit_areas, gaps, reasoning, suggestion, rating, pipeline_stage)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                a.url,
                a.source,
                a.scrape_method,
                a.scraped_at.isoformat(),
                a.assessed_at.isoformat(),
                a.assessed_model,
                a.employer,
                a.job_title,
                a.language,
                a.listing_text,
                a.job_summary,
                int(a.role_check),
                a.domain_fit,
                a.domain_fit_reason,
                a.role_fit,
                a.role_fit_reason,
                a.gap_risk,
                a.gap_risk_reason,
                json.dumps(a.fit_areas),
                json.dumps([g.model_dump() for g in a.gaps]),
                a.reasoning,
                a.suggestion,
                a.rating,
                a.pipeline_stage,
            ),
        )


def update_assessment(a: Assessment) -> None:
    """Insert or overwrite an assessment, preserving user-managed fields (rating).
    Warns if no rows were affected on update."""
    params = (
        a.url,
        a.source,
        a.scrape_method,
        a.scraped_at.isoformat(),
        a.assessed_at.isoformat(),
        a.assessed_model,
        a.employer,
        a.job_title,
        a.language,
        a.listing_text,
        a.job_summary,
        int(a.role_check),
        a.domain_fit,
        a.domain_fit_reason,
        a.role_fit,
        a.role_fit_reason,
        a.gap_risk,
        a.gap_risk_reason,
        json.dumps(a.fit_areas),
        json.dumps([g.model_dump() for g in a.gaps]),
        a.reasoning,
        a.suggestion,
        a.pipeline_stage,
    )
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO assessments
                (url, source, scrape_method, scraped_at, assessed_at, assessed_model, employer,
                 job_title, language, listing_text, job_summary, role_check, domain_fit,
                 domain_fit_reason, role_fit, role_fit_reason, gap_risk, gap_risk_reason,
                 fit_areas, gaps, reasoning, suggestion, pipeline_stage)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                source          = excluded.source,
                scrape_method   = excluded.scrape_method,
                scraped_at      = excluded.scraped_at,
                assessed_at     = excluded.assessed_at,
                assessed_model  = excluded.assessed_model,
                employer        = excluded.employer,
                job_title       = excluded.job_title,
                language        = excluded.language,
                listing_text    = excluded.listing_text,
                job_summary     = excluded.job_summary,
                role_check      = excluded.role_check,
                domain_fit      = excluded.domain_fit,
                domain_fit_reason = excluded.domain_fit_reason,
                role_fit        = excluded.role_fit,
                role_fit_reason = excluded.role_fit_reason,
                gap_risk        = excluded.gap_risk,
                gap_risk_reason = excluded.gap_risk_reason,
                fit_areas       = excluded.fit_areas,
                gaps            = excluded.gaps,
                reasoning       = excluded.reasoning,
                suggestion      = excluded.suggestion,
                pipeline_stage  = excluded.pipeline_stage
        """,
            params,
        )
        if cur.rowcount == 0:
            print(f"  Warning: update_assessment affected 0 rows for {a.url}")


def update_rating(url: str, rating: str) -> None:
    """Update the user rating (new | liked | disliked | superliked | applied | spam) for an assessment."""
    with _connect() as conn:
        conn.execute(
            "UPDATE assessments SET rating = ? WHERE url = ?",
            (rating, url),
        )


def clear_ratings() -> int:
    """Reset all user ratings to 'new'. Returns the number of affected rows."""
    with _connect() as conn:
        cur = conn.execute("UPDATE assessments SET rating = 'new' WHERE rating != 'new'")
        return cur.rowcount


def delete_assessment(url: str) -> None:
    """Permanently remove an assessment from the database."""
    with _connect() as conn:
        conn.execute("DELETE FROM assessments WHERE url = ?", (url,))


def url_exists(url: str) -> bool:
    """Return True if this URL has already been assessed."""
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM assessments WHERE url = ?", (url,)).fetchone()
    return row is not None


def tracking_url_seen(url: str) -> bool:
    """Return True if this tracking URL has already been processed in a previous run."""
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM seen_urls WHERE url = ?", (url,)).fetchone()
    return row is not None


def mark_url_seen(url: str) -> None:
    """Record a tracking URL as processed so it can be skipped in future runs."""
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_urls (url, seen_at) VALUES (?, ?)",
            (url, datetime.now().isoformat()),
        )


def _rows_to_assessments(rows) -> list[Assessment]:
    results = []
    for row in rows:
        d = dict(row)
        d["scraped_at"] = datetime.fromisoformat(d["scraped_at"])
        d["assessed_at"] = datetime.fromisoformat(d["assessed_at"]) if d.get("assessed_at") else d["scraped_at"]
        d["assessed_model"] = d.get("assessed_model") or ""
        d["employer"] = d.get("employer") or ""
        d["job_title"] = d.get("job_title") or ""
        d["listing_text"] = d.get("listing_text") or ""
        d["job_summary"] = d.get("job_summary") or ""
        d["domain_fit_reason"] = d.get("domain_fit_reason") or ""
        d["role_fit_reason"] = d.get("role_fit_reason") or ""
        d["gap_risk_reason"] = d.get("gap_risk_reason") or ""
        d["fit_areas"] = json.loads(d.get("fit_areas") or "[]")
        d["gaps"] = json.loads(d.get("gaps") or "[]")
        d["rating"] = d.get("rating") or "new"
        d["role_check"] = bool(d.get("role_check", 1))
        d["pipeline_stage"] = d.get("pipeline_stage") or "assessed"
        # Drop legacy columns that may still exist in older databases
        for key in ("status", "hidden", "bookmarked", "stars", "summary"):
            d.pop(key, None)
        results.append(Assessment(**d))
    return results


def load_assessments() -> list[Assessment]:
    """Return all non-spam assessments, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM assessments WHERE (rating IS NULL OR rating != 'spam') ORDER BY scraped_at DESC"
        ).fetchall()
    return _rows_to_assessments(rows)


def load_spam() -> list[Assessment]:
    """Return spam-filtered assessments, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM assessments WHERE rating = 'spam' ORDER BY scraped_at DESC"
        ).fetchall()
    return _rows_to_assessments(rows)
