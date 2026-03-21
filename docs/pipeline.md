# Fumble — Processing Pipeline

Each URL from a job alert email passes through the following stages in order.
Stages marked **[no LLM]** cost nothing. Stages that call an LLM name the role used.

```
┌─────────────────────────────────────────────────────────────┐
│  EMAIL FETCH   email_fetch.py                               │
│  Input:  IMAP mailbox, date range / unread flag             │
│          or --url / --url-file for manual input             │
│  Output: list of (tracking_url, source, scraper)            │
│  Models: none                                               │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  PRE-CHECKS   cli.py   [no LLM]                             │
│                                                             │
│  1. Seen-URL cache  ──► already in seen_urls?               │
│                              │ yes → skip (no DB entry)     │
│                              │ no  ↓                        │
│  2. Scrape  scrape.py                                       │
│     Extractor priority chain (curl path):                   │
│       a. JSON-LD JobPosting schema (_extract_jsonld_job)    │
│       b. Next.js __NEXT_DATA__ JSON (_extract_next_data)    │
│       c. Plain HTML tag stripping (_strip_html)             │
│     Browser path (LinkedIn etc.): Playwright inner_text     │
│     → raw page text + canonical URL + scrape_method         │
│        scrape error → log failures.log, skip                │
│                                                             │
│  3. Login wall check (URL pattern match)                    │
│        wall detected → log failures.log, skip               │
│                                                             │
│  4. Canonical dedup                                         │
│     url_exists() / seen_canonical set                       │
│        duplicate → skip (no DB entry)                       │
│                                                             │
│  5. Page length guard  (< 150 chars)                        │
│        too short → log failures.log, skip                   │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  TRIAGE   extract.py::is_listing_quick                      │
│  Model:   TRIAGE_MODEL  (default: ollama/llama3.2)          │
│  Note:    skipped entirely for non-Ollama providers         │
│                                                             │
│  Binary check on first 3 000 chars of raw text:            │
│  Is this page actually a job listing?                       │
│  Passes by default; only rejects when confident it is NOT   │
│  (login wall, search results page, cookie notice, etc.)     │
│                                                             │
│  Output: bool                                               │
│     false → log failures.log, skip (no DB entry)           │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  EXTRACT   extract.py::extract_listing                      │
│  Model:    EXTRACT_MODEL  (default: ollama/qwen3.5:9b)      │
│            recommended: gemini/gemini-2.5-flash-lite        │
│                                                             │
│  Structured extraction from raw text:                       │
│    is_job_listing  bool                                     │
│    employer        string                                   │
│    job_title       string                                   │
│    language        DE | EN                                  │
│    listing_text    full listing reproduced as markdown      │
│                   (content integrity enforced in prompt;    │
│                    formatting improved where needed)        │
│                                                             │
│  is_job_listing=false → log failures.log, skip (no DB entry)│
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  SPAM FILTER   extract.py::spam_filter                      │
│                                                             │
│  Step A — Keyword check  [no LLM]                           │
│    Matches job_title against ## Spam keywords in criteria   │
│    Hit → reasoning = "Job title contained '{keyword}'."     │
│           pipeline_stage = keyword_spam                     │
│           save stub Assessment to DB  (rating = spam)  ──► DB│
│                                                             │
│  Step B — LLM semantic check  (only if A passed)            │
│  Model:   TRIAGE_MODEL  (default: ollama/llama3.2)          │
│    Checks first 3 000 chars of listing_text:                │
│    Does the role type clearly fall outside all target roles? │
│    Conservative — only flags obvious role-type mismatches   │
│    Hit → reasoning = short phrase stating mismatch          │
│           pipeline_stage = llm_spam                         │
│           save stub Assessment to DB  (rating = spam)  ──► DB│
│                                                             │
│  Stub Assessment fields for spam-filtered entries:          │
│    job_summary, fit fields = empty / dummy values           │
│    assessed_model = "spam/{TRIAGE_MODEL}"                   │
└────────────────────────────┬────────────────────────────────┘
                             │  (not spam)
                             ▼
┌─────────────────────────────────────────────────────────────┐
│  ASSESS   assess.py::assess_fit                             │
│  Model:   ASSESS_MODEL  (default: ollama/qwen3.5:9b)        │
│           recommended: anthropic/claude-haiku-4-5-20251001  │
│                                                             │
│  Full fit assessment against profile + criteria:            │
│    job_summary       one-sentence role description          │
│    role_check        bool — does role type match at all?    │
│    role_fit          high | medium | low                    │
│    role_fit_reason   one sentence                           │
│    gap_risk          high | medium | low                    │
│    gap_risk_reason   one sentence                           │
│    domain_fit        high | medium | low                    │
│    domain_fit_reason one sentence                           │
│    fit_areas         2–4 short phrases                      │
│    gaps              list of {description, severity}        │
│    suggestion        apply | consider | skip | spam         │
│    reasoning         one sentence — decisive factor + caveat│
│                                                             │
│  suggestion=spam means role_check=false (assess model       │
│  confirmed role type mismatch after seeing full listing)    │
│                                                             │
│  pipeline_stage = assessed  (always, for this path)         │
│  save Assessment to DB  ──────────────────────────────► DB  │
└─────────────────────────────────────────────────────────────┘
```

## Outcome summary

| Outcome | DB entry? | `pipeline_stage` | `rating` | `suggestion` |
|---|---|---|---|---|
| Pre-check skip (dedup, wall, short page) | No | — | — | — |
| Triage reject | No | — | — | — |
| Extract reject (not a listing) | No | — | — | — |
| Keyword spam | Yes | `keyword_spam` | `spam` | `skip` |
| LLM spam | Yes | `llm_spam` | `spam` | `skip` |
| Assess — role mismatch | Yes | `assessed` | `spam` | `spam` |
| Assess — normal result | Yes | `assessed` | `new` | `apply/consider/skip` |

## Models and roles

| Role | Default | Recommended | Env vars |
|---|---|---|---|
| Triage | `ollama/llama3.2` | `ollama/llama3.2` (or skip — not used for non-Ollama providers) | `LLM_TRIAGE_PROVIDER`, `LLM_TRIAGE_MODEL` |
| Extract | `ollama/qwen3.5:9b` | `gemini/gemini-2.5-flash-lite` — free tier, fast | `LLM_EXTRACT_PROVIDER`, `LLM_EXTRACT_MODEL` |
| Assess | `ollama/qwen3.5:9b` | `anthropic/claude-haiku-4-5-20251001` — cheap, fast, high quality | `LLM_ASSESS_PROVIDER`, `LLM_ASSESS_MODEL` |

Triage is skipped entirely for non-Ollama providers (API models are fast enough that the pre-filter adds no value).

Anthropic assessment uses prompt caching: profile and criteria are cached across a batch run, reducing input token cost by ~80% after the first call.

## Failures log

Skipped URLs that reached the scrape stage but did not produce a DB entry are logged to `data/failures.log`:

```
<iso-datetime> | <source> | <reason> | <url>
```

Reason values: `scrape_failed`, `login_wall`, `page_too_short`, `not_a_job_listing_triage`, `not_a_job_listing`, `extraction_failed`, `assessment_failed`.
