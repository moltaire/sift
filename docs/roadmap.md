# Fumble — Roadmap & Ideas

## Assessment quality

- [ ] Add an "Examples" section to `search-criteria.md` with concrete good and bad fit examples — no code needed, likely high impact on assessment accuracy
- [ ] RAG-lite exemplars: at assessment time, retrieve the 1–2 most similar liked/disliked listings from the DB by embedding similarity and inject them into the prompt — `rating` in the DB is the natural label source
- [ ] On-demand deeper fit/gap breakdown: a second LLM call triggered when a listing is selected in the dashboard (lazy, stored as JSON in the DB). Could produce colour-coded fit points, gap points, and open questions — more actionable than the current summary
- [ ] Cover letter angle: for `apply` / `consider` listings, generate a 2–3 sentence framing for a cover letter based on the specific fit points

## Pipeline

- [ ] Retry failed scrapes before silently skipping
- [ ] Log curl→browser fallbacks to `failures.log` for observability
- [ ] Monitor `__NEXT_DATA__` extraction quality as new sources are added — it's generic but only validated on a few sources so far
- [ ] RSS source support: add `type = "rss"` to `sources.toml`, new `rss_fetch.py` returning the same `(url, source, scraper)` tuples as email fetch, honour `--days` via `<pubDate>`
- [ ] **List-source support** (two-hop scraping): some sources (80,000 Hours, Interamt) don't include job links directly in the email — instead the email links to a page listing new jobs, or is just a notification that new results exist. Needs a new fetch step between email and scraping. See design notes below.

## Dashboard

- [ ] Run panel: trigger the pipeline from within the dashboard — select `--days` / `--unread` / `--force`, run as subprocess, stream output to the UI
- [ ] Record `applied_at` timestamp when a job is marked as applied — add column to DB (with migration in `init_db`), set/clear in `update_rating`, surface in the Applied view

## Spam filter

See [`embedding-classifier-spec.md`](embedding-classifier-spec.md) for a detailed design of an embedding-based spam classifier. The experiment was run in March 2026 — centroid and kNN classifiers on title embeddings achieved insufficient recall (~62%) at the current corpus size. The spec includes the outcome and the `embeddings` table is already in the schema. Revisit as the labelled corpus grows.

## Architecture

- [ ] LangGraph migration: refactor the pipeline into LangGraph nodes (extract → assess → store) with conditional edges, retry logic, and parallel fanout for URL scraping
- [ ] Additional input adapters: file/URL paste is covered by `--url`; a file upload in the dashboard would be a natural addition
- [ ] If the dashboard becomes a daily-use tool: Streamlit's `st.dataframe` (row selection, no editing) vs `st.data_editor` (editing, no selection) tension becomes a ceiling. A lightweight FastAPI + HTMX or small React frontend would handle stateful tables natively
- [ ] Profile interview agent: conversational LLM flow to generate or update `search-criteria.md` based on what's working



## List-source design notes

Two-hop flow for sources where the email doesn't contain direct job links:

```
# Pattern A — list URL comes from the email (80,000 Hours, possibly Interamt):
email → extract list URL (url_pattern) → fetch list page → extract job URLs (job_url_pattern) → scrape each

# Pattern B — list URL is fixed, email is just a notification (Interamt if no useful link in email):
email = trigger only → fetch hardcoded list_url → extract job URLs (job_url_pattern) → scrape each
```

**Proposed `sources.toml` fields:**

```toml
# Pattern A
[[sources]]
name = "80000hours"
folder = "Job Search/80000 Hours"
url_pattern = "80000hours\\.org/job-board"      # matched against links in the email
job_url_pattern = "80000hours\\.org/job-board/role/"  # matched against links on the list page

# Pattern B
[[sources]]
name = "interamt"
folder = "Job Search/Interamt"
list_url = "https://www.interamt.de/kunden/..."  # fixed URL — email is just a trigger signal
job_url_pattern = "interamt\\.de/kunden/app/stelle\\?id="
scraper = "browser"   # Interamt requires login
```

Distinguishing logic: if `list_url` is set → use it directly; if `url_pattern` + `job_url_pattern` → extract list URL from email first. Plain `url_pattern` alone (no `job_url_pattern`) → existing direct behaviour, no change.

**Implementation plan (feature branch):**

1. `email_fetch.py`: after extracting list URLs from the email, detect `job_url_pattern` → fetch the list page (curl first, browser if `scraper = "browser"`), run `_extract_urls()` with `job_url_pattern` to get job URLs. Also handle `list_url` (skip email extraction, use fixed URL). Return job URLs as normal — rest of pipeline unchanged.
2. `settings_page.py`: add `list_url` and `job_url_pattern` fields to the source dialog (Advanced section). Live tester already works for `url_pattern`; `job_url_pattern` can reuse the same approach.

**Open question — needs checking once emails arrive:**
- Does the Interamt email contain a usable list URL (Pattern A), or is it a pure notification with no link (Pattern B)?
- Does the 80,000 Hours email contain a direct link to the job board, or a tracking redirect?
- Is the Interamt list page JS-rendered / login-gated? (Assumed yes — `scraper = "browser"` + `fumblebee --login` needed first.)

**Dedup:** free — the existing seen-URL cache deduplicates at the job URL level, so the same job appearing on the list page across multiple email triggers is skipped automatically.

---

## Usability

- [ ] Better error messages: IMAP login failures, folder-not-found, and scrape errors should surface clearly rather than crashing silently
