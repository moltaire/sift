# Fumble — Database Schema

Database: `data/fumble.db` (SQLite)

---

## Table: `assessments`

One row per unique job listing URL. Populated by the pipeline; updated by user ratings in the dashboard.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `url` | TEXT UNIQUE | Canonical job URL (query params and fragments stripped) |
| `source` | TEXT | Email source name, e.g. `linkedin`, `stepstone`, `goodjobs` |
| `scraped_at` | TEXT | ISO 8601 UTC datetime when the page was scraped |
| `assessed_at` | TEXT | ISO 8601 UTC datetime when the assessment was written |
| `assessed_model` | TEXT | Model that produced the assessment, e.g. `anthropic/claude-haiku-4-5-20251001`; `spam/llama3.2` for spam-filtered entries |
| `pipeline_stage` | TEXT | How far through the pipeline this entry got — see values below |
| `employer` | TEXT | Company name as extracted from the listing |
| `job_title` | TEXT | Exact job title as written in the listing |
| `language` | TEXT | `DE` or `EN` |
| `listing_text` | TEXT | Full listing cleaned to markdown; **empty for spam-filtered entries** |
| `job_summary` | TEXT | One-sentence role description produced by the assess model; **empty for spam-filtered entries** |
| `role_check` | INTEGER | `1` if the role type matched at all; `0` if assess model confirmed a role-type mismatch (`suggestion=spam`); always `1` for spam-filtered entries (the check never ran) |
| `role_fit` | TEXT | `high` / `medium` / `low`; dummy `low` for spam-filtered entries |
| `role_fit_reason` | TEXT | One sentence from assess model; **empty for spam-filtered entries** |
| `gap_risk` | TEXT | `high` / `medium` / `low`; dummy `high` for spam-filtered entries |
| `gap_risk_reason` | TEXT | One sentence from assess model; **empty for spam-filtered entries** |
| `domain_fit` | TEXT | `high` / `medium` / `low`; dummy `low` for spam-filtered entries |
| `domain_fit_reason` | TEXT | One sentence from assess model; **empty for spam-filtered entries** |
| `fit_areas` | TEXT | JSON array of 2–4 short phrases where candidate matches well; `[]` for spam-filtered entries |
| `gaps` | TEXT | JSON array of `{"description": str, "severity": "minor"\|"manageable"\|"severe"}`; `[]` for spam-filtered entries |
| `suggestion` | TEXT | `apply` / `consider` / `skip` / `spam`; always `skip` for spam-filtered entries (assess model sets `spam`) |
| `reasoning` | TEXT | For assessed entries: one sentence stating the decisive factor and main caveat. For spam-filtered entries: the spam reason phrase (e.g. `"Job title contained 'sales'."`) |
| `rating` | TEXT | User-assigned rating — see values below |

### `pipeline_stage` values

| Value | Meaning |
|---|---|
| `keyword_spam` | Stopped at keyword filter; job title matched a spam keyword; never reached an LLM |
| `llm_spam` | Passed keyword filter; stopped by triage LLM semantic spam check |
| `assessed` | Ran through full assess model; includes entries where assess model itself flagged `suggestion=spam` |

### `suggestion` values

| Value | Meaning |
|---|---|
| `apply` | High role fit and low/medium gap risk |
| `consider` | Medium role fit with low gap risk, or high role fit with medium gap risk |
| `skip` | Role type matches but gap risk is high, or fit too weak overall; also used for spam-filtered entries |
| `spam` | Assess model confirmed role type mismatch (`role_check=false`) |

### `rating` values

| Value | Set by | Meaning |
|---|---|---|
| `new` | Pipeline | Not yet rated by user (default) |
| `liked` | User | Saved / bookmarked |
| `superliked` | User | Strongly saved |
| `disliked` | User | Hidden |
| `applied` | User | Already applied |
| `spam` | Pipeline or user | Spam-filtered or manually marked as spam |

### Notes on spam entries

Entries with `pipeline_stage = keyword_spam` or `llm_spam` are stubs — only the extraction fields (`employer`, `job_title`, `language`) are populated from the extract model. The fit fields (`role_fit`, `gap_risk`, `domain_fit`, `fit_areas`, `gaps`, `reasoning`) are either empty or dummy values. `reasoning` holds the spam reason phrase.

Entries with `pipeline_stage = assessed` and `suggestion = spam` are full assessments — all fields are populated normally by the assess model.

---

## Table: `seen_urls`

Deduplication cache. Tracks every URL processed in any run (both tracking URLs from emails and canonical job URLs), regardless of whether a DB entry was created. Prevents re-scraping on subsequent runs.

| Column | Type | Description |
|---|---|---|
| `url` | TEXT PK | The URL (tracking or canonical) |
| `seen_at` | TEXT | ISO 8601 datetime when first processed |

---

## Table: `embeddings`

Stores vector embeddings for listings, used for similarity search. One row per (assessment, model, input_type) combination.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PK | Auto-increment |
| `assessment_id` | INTEGER FK | References `assessments(id)`; cascade-deletes with the assessment |
| `model` | TEXT | Embedding model identifier |
| `input_type` | TEXT | What was embedded, e.g. `listing`, `summary` |
| `embedding` | BLOB | Raw float32 bytes |
| `embedded_at` | TEXT | ISO 8601 datetime |

Unique index on `(assessment_id, model, input_type)`.

---

## Useful queries

```sql
-- Count by pipeline stage
SELECT pipeline_stage, COUNT(*) FROM assessments GROUP BY pipeline_stage;

-- Spam breakdown: keyword vs LLM vs assess-model
SELECT
    pipeline_stage,
    COUNT(*) AS n
FROM assessments
WHERE rating = 'spam'
GROUP BY pipeline_stage;

-- Has the LLM spam filter ever caught anything the keyword filter missed?
SELECT COUNT(*) FROM assessments WHERE pipeline_stage = 'llm_spam';

-- Assessment outcomes for non-spam entries
SELECT suggestion, COUNT(*) FROM assessments
WHERE pipeline_stage = 'assessed' AND rating != 'spam'
GROUP BY suggestion;

-- Full results with fit dimensions
SELECT
    employer,
    job_title,
    suggestion,
    role_fit,
    gap_risk,
    domain_fit,
    rating,
    pipeline_stage,
    scraped_at
FROM assessments
ORDER BY scraped_at DESC;
```
