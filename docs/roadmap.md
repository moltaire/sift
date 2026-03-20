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

## Dashboard

- [ ] Run panel: trigger the pipeline from within the dashboard — select `--days` / `--unread` / `--force`, run as subprocess, stream output to the UI

## Spam filter

See [`embedding-classifier-spec.md`](embedding-classifier-spec.md) for a detailed design of an embedding-based spam classifier. The experiment was run in March 2026 — centroid and kNN classifiers on title embeddings achieved insufficient recall (~62%) at the current corpus size. The spec includes the outcome and the `embeddings` table is already in the schema. Revisit as the labelled corpus grows.

## Architecture

- [ ] LangGraph migration: refactor the pipeline into LangGraph nodes (extract → assess → store) with conditional edges, retry logic, and parallel fanout for URL scraping
- [ ] Additional input adapters: file/URL paste is covered by `--url`; a file upload in the dashboard would be a natural addition
- [ ] If the dashboard becomes a daily-use tool: Streamlit's `st.dataframe` (row selection, no editing) vs `st.data_editor` (editing, no selection) tension becomes a ceiling. A lightweight FastAPI + HTMX or small React frontend would handle stateful tables natively
- [ ] Profile interview agent: conversational LLM flow to generate or update `search-criteria.md` based on what's working
