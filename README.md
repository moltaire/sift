# Fumble

<img src="docs/screenshot.png" width="70%">

A job screening tool that makes job ad discovery just as fun (shrug) as Tinder. Fumble scrapes listings from your job alert emails, has an LLM assess each one against your profile and criteria, then lets you swipe through the results: liking, skipping, or superliking, until your inbox is clear.

## How it works

1. **Fetch** — connects to your IMAP mailbox and extracts job URLs from configured email folders (StepStone, LinkedIn, etc.)
2. **Scrape** — fetches each URL using curl_cffi (impersonating a real browser) where possible, falling back to a headless Chromium browser (Playwright) for sites that require JavaScript or a logged-in session. Structured data is preferred: JSON-LD `JobPosting` schema is extracted first, then Next.js `__NEXT_DATA__`, then plain text stripping as a fallback.
3. **Extract** — an LLM structures the raw page text into a job listing (employer, title, language, listing text formatted as markdown)
4. **Assess** — a second LLM call scores the listing on domain fit, role fit, and gap risk against your profile and criteria, and produces a structured assessment with fit areas, gaps, and an overall recommendation
5. **Store** — results are saved to `data/fumble.db` (SQLite)
6. **Review** — browse, filter, rate, and bookmark results in the dashboard

URLs are cached after processing — re-running over the same date range skips already-seen URLs without re-scraping.

## Setup

### Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- A Playwright-compatible Chrome install: `uv run python -m playwright install chrome`
- At least one LLM provider (see [LLM configuration](#llm-configuration) below)

### Install

```bash
# Install dependencies into a local venv
uv sync

# Install fumble as a global tool so you can run it from any directory
uv tool install --editable .
```

After tool install, two commands are available globally:

| Command | Description |
|---|---|
| `fumblebee` | Run the pipeline |
| `fumble` | Launch the dashboard |

### Configuration

Copy `.env.example` to `.env` and fill in:

```
# IMAP credentials
IMAP_HOST=imap.example.com
IMAP_EMAIL=you@example.com
IMAP_PASSWORD=yourpassword

# LLM — see "LLM configuration" below for all options
```

Edit `resources/sources.toml` to configure which email folders to scan and what URL patterns to extract. Each source maps an IMAP folder to a regex pattern matched against URLs found in emails. Currently configured sources:

| Source | Notes |
|---|---|
| StepStone | Matches StepStone redirect links |
| LinkedIn | Matches LinkedIn job alert emails; deduplicates by job ID; uses browser scraper |
| GoodJobs | Matches Brevo tracking links |
| Climatebase | Matches SendGrid tracking links |

Each source can optionally set `scraper = "browser"` to force Playwright (needed for login-required sites). The default is `"auto"` — curl first, browser fallback.

Copy `resources/profile.example.md` → `resources/profile.md` and `resources/search-criteria.example.md` → `resources/search-criteria.md`, then fill them in with your background and job search criteria. These files are gitignored so your personal details stay local.

### Login-required sources

Some sources (e.g. LinkedIn) require a logged-in browser session. Run this once before the first pipeline run:

```
fumblebee --login https://www.linkedin.com/login
```

Log in inside the browser window, then press Enter in the terminal. The session is saved to `data/browser_profile/` and reused automatically on every subsequent scrape. Use the same command for any other source that requires login.

## Usage

### Run the pipeline

```
fumblebee [options]
```

| Argument | Default | Description |
|---|---|---|
| `--days N` | `3` | Fetch emails from the last N days |
| `--unread` | off | Only process unread emails |
| `--url URL` | — | Process a specific URL directly, bypassing email fetch (can be repeated) |
| `--url-file FILE` | — | Process all URLs from a file (one per line, non-http lines ignored) |
| `--force` | off | Ignore the seen-URL cache and reprocess all fetched URLs |
| `--reassess` | off | Re-run LLM fit assessment on all stored listings without re-scraping; preserves ratings |
| `--clear-ratings` | off | Reset all user ratings to `new` (prompts for confirmation) |
| `--mark-read` | off | Mark fetched emails as read after processing |
| `--login URL` | — | Open a headed browser at URL to log in and save the session |

### Run the dashboard

```
fumble
```

The dashboard lets you:
- Switch between **Inbox** (unrated), **Saved** (liked/superliked), **Hidden** (disliked), and **All** views
- Refine by recommendation, domain fit, role fit, gap risk, employer, and job title via the filter popover
- View the full job listing alongside the structured AI assessment — fit areas, gaps with severity, and per-dimension explanations
- Rate entries with superlike / like / dislike; rated entries auto-advance to the next listing
- Toggle **focus mode** to hide the table and controls for distraction-free swiping
- Permanently delete entries

**Keyboard shortcuts**

| Key | Action |
|-----|--------|
| `k` / `→` | Next listing |
| `j` / `←` | Previous listing |
| `3` | Superlike |
| `2` | Like |
| `1` | Dislike |
| `g i` | Go to Inbox |
| `g s` | Go to Saved |
| `g h` | Go to Hidden |
| `g a` | Go to All |
| `f` | Toggle focus mode |
| `/` | Focus search bar |
| `Esc` | Blur search bar |

## LLM configuration

Fumble supports Ollama (local), Gemini, Anthropic, and OpenAI. The pipeline has three LLM roles with independent provider and model settings:

| Role | What it does | Default provider | Default model |
|---|---|---|---|
| **Extract** | Structures raw page text into a listing | `ollama` | `qwen3.5:9b` |
| **Triage** | Fast binary check: is this actually a job listing? | `ollama` | `llama3.2` |
| **Assess** | Scores fit against your profile and criteria | `ollama` | `qwen3.5:9b` |

Each role reads from its own env vars, all of which are optional and fall back to the base `LLM_PROVIDER` / `LLM_MODEL`:

```
# Base — applies to all roles unless overridden
LLM_PROVIDER=ollama          # ollama | gemini | anthropic | openai
LLM_MODEL=qwen3.5:9b

# Per-role overrides (all optional)
LLM_EXTRACT_PROVIDER=gemini
LLM_EXTRACT_MODEL=gemini-2.5-flash-lite

LLM_TRIAGE_PROVIDER=ollama
LLM_TRIAGE_MODEL=llama3.2

LLM_ASSESS_PROVIDER=anthropic
LLM_ASSESS_MODEL=claude-haiku-4-5-20251001
```

### Provider notes

| Provider | Key variable | Notes |
|---|---|---|
| `ollama` | — | Runs locally, no API cost. Requires capable hardware for quality results (tested on M4 Pro 24GB). |
| `gemini` | `GOOGLE_API_KEY` | Gemini 2.5 Flash Lite is free tier (1,000 req/day), fast, and produces good extraction results. Recommended for the Extract role. |
| `anthropic` | `ANTHROPIC_API_KEY` | Claude Haiku is cheap (~$0.01–0.02 per listing), very fast, and produces high-quality assessments. Supports prompt caching — stable context (profile, criteria) is cached across a batch run, reducing input token cost by ~80% after the first call. Recommended for the Assess role. |
| `openai` | `OPENAI_API_KEY` | |

Triage is skipped entirely for non-Ollama providers (API models are fast enough that the pre-filter adds no value).

### Recommended setups

**Fully local (no API cost):**
```
LLM_PROVIDER=ollama
LLM_MODEL=qwen3.5:9b
```
Requires Ollama running locally with `qwen3.5:9b` and `llama3.2` pulled. Slow on modest hardware; extraction takes 1–2 min per listing on CPU.

**Fast and mostly free (recommended):**
```
LLM_EXTRACT_PROVIDER=gemini
LLM_EXTRACT_MODEL=gemini-2.5-flash-lite
GOOGLE_API_KEY=...

LLM_ASSESS_PROVIDER=anthropic
LLM_ASSESS_MODEL=claude-haiku-4-5-20251001
ANTHROPIC_API_KEY=...

LLM_TRIAGE_PROVIDER=ollama
LLM_TRIAGE_MODEL=llama3.2
```
Extraction is free (Gemini free tier). Assessment costs roughly $0.01–0.02 per listing with Haiku. At 50 listings/day this is well under $1/day.

## Project structure

```
fumble/
  cli.py             # fumblebee entry point and pipeline orchestration
  email_fetch.py     # IMAP connection and URL extraction
  scrape.py          # curl_cffi scraping with Playwright fallback; JSON-LD and Next.js extractors
  extract.py         # LLM-based listing extraction and spam filter
  assess.py          # LLM-based fit assessment
  llm.py             # Provider-agnostic LLM call layer (Ollama, Gemini, Anthropic, OpenAI)
  store.py           # SQLite persistence
  dashboard.py       # Streamlit dashboard
  dashboard_cli.py   # fumble entry point
scripts/
  compare_extraction.py  # Pipeline comparison tool (raw HTML vs extraction stages vs LLM output)
resources/
  profile.md             # Candidate profile (read by LLM) — gitignored, copy from profile.example.md
  search-criteria.md     # Job search criteria (read by LLM) — gitignored, copy from search-criteria.example.md
  profile.example.md     # Template for profile.md
  search-criteria.example.md  # Template for search-criteria.md
  sources.toml           # Email folder and URL pattern configuration
data/
  fumble.db              # SQLite database (gitignored)
  browser_profile/       # Persistent Playwright session (gitignored)
  failures.log           # Scrape/extraction failure log
```
