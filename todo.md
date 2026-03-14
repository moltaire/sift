# Fumble — TODO

## Assessment quality
- [ ] Add an "Examples" section to `search-criteria.md` describing what good and bad fits look like (no code needed, likely high impact)
- [ ] RAG-lite exemplars: embed liked/disliked listings, inject the 1-2 most similar into the assessment prompt to avoid context limits — `rating` in the DB (`liked` / `disliked`) is the natural source for this

## LLM
- [ ] Split model config: cheap/local model for extraction, powerful model for assessment (`LLM_MODEL_EXTRACT` / `LLM_MODEL_ASSESS`)

## Pipeline
- [ ] Retry failed scrapes before silently skipping
- [ ] Review failures.log after first real run — tune MIN_LISTING_LENGTH and is_job_listing prompt if needed; watch for JS-rendered pages where curl gets through but content is too sparse (no `__NEXT_DATA__`, no readable text)
- [ ] Log curl→browser fallbacks to failures.log for observability
- [ ] Monitor `__NEXT_DATA__` extraction quality as new sources are added — it's generic but only validated on Climatebase so far
- [ ] RSS source support: add `type = "rss"` to sources.toml, new `rss_fetch.py` returning same `(url, source, scraper)` tuples as email fetch, honour `--days` via `<pubDate>`; always scrape (skip full-content optimisation for now)

## Dashboard
- [ ] Run panel: trigger the pipeline from within the dashboard (select --days/--unread/--force/--mark-read, run main.py as a subprocess, stream output to the UI)
- [ ] Consider on-demand second LLM call for deeper fit/gap detail (lazy, stored in DB)

## LangGraph migration
- [ ] Refactor pipeline into LangGraph nodes (extract → assess → store)
- [ ] Add parallel fanout for URL scraping
- [ ] Add input adapters: file upload alongside email (paste already covered by --url)
