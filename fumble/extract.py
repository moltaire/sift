from typing import Literal

from pydantic import BaseModel

from fumble.llm import EXTRACT_MODEL, PROVIDER, TRIAGE_MODEL, call_llm

SYSTEM_PROMPT = """You are a precise text extraction assistant.
Your first job is to determine whether the input actually contains a job listing.
If it does, extract and clean the listing content.
If it does not — e.g. it is a login wall, cookie notice, error page, job search results page, or otherwise lacks a specific job advertisement — set is_job_listing to false and leave all other fields empty.
Think concisely — limit reasoning to essential steps."""

USER_PROMPT = """## Raw scraped content
{raw_text}

---

First, decide: does this content contain an actual job listing (a specific job advertisement with description, responsibilities, or requirements)?

Set is_job_listing accordingly, then extract:

- employer: company name (empty string if unclear)
- job_title: exact job title as written (empty string if unclear)
- language: DE or EN based on the job listing language
- listing_text: the cleaned job listing in markdown. Include job description, responsibilities, requirements, and any about-the-company section. Exclude navigation, cookie notices, footer, sidebar, links to other jobs, and other boilerplate. Preserve structure and original wording. Empty string if is_job_listing is false.
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
    if PROVIDER != "ollama":
        return True
    prompt = _TRIAGE_PROMPT.format(text=text[:_TRIAGE_CHAR_LIMIT])
    try:
        content = call_llm(_TRIAGE_SYSTEM, prompt, _TriageResult.model_json_schema(), model=TRIAGE_MODEL, think=False)
        return _TriageResult.model_validate_json(content).is_job_listing
    except Exception:
        return True  # safe default: never filter on error


EXTRACT_OPTIONS = {"num_predict": 4000, "top_k": 20, "presence_penalty": 1.5}


def extract_listing(raw_text: str) -> JobListing:
    prompt = USER_PROMPT.format(raw_text=raw_text)
    content = call_llm(SYSTEM_PROMPT, prompt, JobListing.model_json_schema(), model=EXTRACT_MODEL, temperature=0, extra_options=EXTRACT_OPTIONS)
    return JobListing.model_validate_json(content)
