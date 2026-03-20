from typing import Literal

from pydantic import BaseModel

from fumble.llm import EXTRACT_MODEL, EXTRACT_PROVIDER, TRIAGE_MODEL, TRIAGE_PROVIDER, call_llm

SYSTEM_PROMPT = """You are a precise text extraction assistant.
Your first job is to determine whether the input actually contains a job listing.
If it does, extract and clean the listing content.
If it does not — e.g. it is a login wall, cookie notice, error page, job search results page, or otherwise lacks a specific job advertisement — set is_job_listing to false and leave all other fields empty.
Use at most 3 reasoning steps. Keep thinking under 100 words. Think once, answer directly."""

USER_PROMPT = """## Raw scraped content
{raw_text}

---

First, decide: does this content contain an actual job listing (a specific job advertisement with description, responsibilities, or requirements)?

Set is_job_listing accordingly, then extract:

- employer: company name (empty string if unclear)
- job_title: exact job title as written (empty string if unclear)
- language: DE or EN based on the job listing language
- listing_text: the complete job listing in markdown. Reproduce every section that belongs to the job advertisement — do not summarise, shorten, or omit any part. Use ## for main sections and ### for subsections. Include all of the following if present:
  - Company introduction / about the organisation
  - Role overview / what you will do
  - Responsibilities and tasks
  - Requirements and qualifications
  - What the employer offers / benefits
  - Application process and contact details
  Exclude only navigation menus, cookie notices, footer content, links to other jobs, and unrelated site boilerplate. Empty string if is_job_listing is false.
"""


class JobListing(BaseModel):
    is_job_listing: bool = False
    employer: str = ""
    job_title: str = ""
    language: Literal["DE", "EN"] = "EN"
    listing_text: str = ""


_TRIAGE_SYSTEM = "You are a filter that checks if scraped web content contains a job listing."
_TRIAGE_PROMPT = """Does this page contain a job listing?

Output true if yes or if you are unsure. Only output false when you are confident this is NOT a job listing — e.g. a login wall, cookie consent page, error page, or a page listing multiple search results rather than a single job advertisement.

## Content
{text}"""

_TRIAGE_CHAR_LIMIT = 3_000


class _TriageResult(BaseModel):
    is_job_listing: bool = True  # default True: when in doubt, pass through


def is_listing_quick(text: str) -> bool:
    """Fast binary check using a small model. Returns False only when confident it's not a listing.
    Always returns True for non-Ollama providers (API models are already fast)."""
    if TRIAGE_PROVIDER != "ollama":
        return True
    prompt = _TRIAGE_PROMPT.format(text=text[:_TRIAGE_CHAR_LIMIT])
    try:
        content = call_llm(_TRIAGE_SYSTEM, prompt, _TriageResult.model_json_schema(), model=TRIAGE_MODEL, provider=TRIAGE_PROVIDER, think=False)
        return _TriageResult.model_validate_json(content).is_job_listing
    except Exception:
        return True  # safe default: never filter on error


def extract_listing(raw_text: str) -> JobListing:
    prompt = USER_PROMPT.format(raw_text=raw_text)
    content = call_llm(SYSTEM_PROMPT, prompt, JobListing.model_json_schema(), model=EXTRACT_MODEL, provider=EXTRACT_PROVIDER)
    return JobListing.model_validate_json(content)


_SPAM_SYSTEM = """You are a job listing spam filter.
Decide if a job listing is clearly irrelevant for this candidate based on their search criteria.
Be conservative — only flag obvious mismatches. When in doubt, return is_spam=false."""

_SPAM_PROMPT = """## Candidate Search Criteria
{criteria_text}

## Job Listing
{listing_text}

---

Is this listing clearly irrelevant for this candidate based on their search criteria?

Focus on what the ROLE ITSELF requires day-to-day, not the organisation's domain.

Flag as spam (is_spam=true) only when the role clearly falls outside all of the candidate's target role types as defined in the Search Criteria above.
When in doubt, do not flag as spam.

reason: short phrase explaining why. Empty string if not spam."""

_SPAM_CHAR_LIMIT = 2_000


def _load_spam_keywords(criteria_text: str) -> list[str]:
    """Parse the '## Spam keywords' section from the criteria file. Returns lowercase strings."""
    keywords = []
    in_section = False
    for line in criteria_text.splitlines():
        if line.strip().startswith("## Spam keywords"):
            in_section = True
            continue
        if in_section:
            if line.startswith("## "):
                break
            stripped = line.strip()
            if not stripped.startswith("-"):
                continue
            keyword = stripped.lstrip("-").strip().lower()
            if keyword:
                keywords.append(keyword)
    return keywords


class _SpamResult(BaseModel):
    is_spam: bool = False
    reason: str = ""


def keyword_spam_check(job_title: str, criteria_text: str) -> tuple[bool, str]:
    """Keyword-only spam pre-filter. Matches against job title only.
    Returns (is_spam, matched_keyword)."""
    title = job_title.lower()
    for keyword in _load_spam_keywords(criteria_text):
        if keyword in title:
            return True, keyword
    return False, ""


def llm_spam_check(listing_text: str, criteria_text: str) -> tuple[bool, str]:
    """LLM semantic spam check. Returns (is_spam, reason). Conservatively returns (False, '') on error."""
    prompt = _SPAM_PROMPT.format(
        criteria_text=criteria_text,
        listing_text=listing_text[:_SPAM_CHAR_LIMIT],
    )
    try:
        content = call_llm(
            _SPAM_SYSTEM, prompt, _SpamResult.model_json_schema(),
            model=TRIAGE_MODEL, provider=TRIAGE_PROVIDER, think=False,
        )
        result = _SpamResult.model_validate_json(content)
        return result.is_spam, result.reason
    except Exception:
        return False, ""


def spam_filter(job_title: str, listing_text: str, criteria_text: str) -> tuple[bool, str]:
    """Fast spam check (keywords then LLM). Returns (is_spam, reason)."""
    is_spam, reason = keyword_spam_check(job_title, criteria_text)
    if is_spam:
        return True, reason
    return llm_spam_check(listing_text, criteria_text)
