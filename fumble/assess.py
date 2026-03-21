from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

from fumble.extract import JobListing
from fumble.llm import ASSESS_MODEL, ASSESS_PROVIDER, call_llm

SYSTEM_PROMPT = """You are a job screening assistant. 
Assess how well a job listing matches a candidate profile and search criteria.
Be direct. Give one firm answer per field. Do not hedge.

Priority order when making your assessment:
1. Role fit — does the day-to-day work match the target role types?
2. Gap risk — are there gaps severe enough to cause rejection?
3. Domain fit — is the employer domain relevant? This is least important.

A good domain match never compensates for poor role fit or high gap risk."""

CONTEXT_PROMPT = """## Candidate Profile
{profile_text}

## Search Criteria
{criteria_text}"""

LISTING_PROMPT = """## Job Listing
{listing_text}

---

Assess this job listing. Fill in every field below.

**job_summary**: One sentence. What is the role, at what kind of organisation, and what is the main focus.

**role_check**: yes or no. Does the primary day-to-day function of this role match the candidate's target role types?
If no, set suggestion to spam and skip the remaining dimensions.

**role_fit**: high / medium / low
- high: primary function is a target role type
- medium: partial match, or a secondary target role type
- low: outside target role types

**role_fit_reason**: One sentence. Start with the key fact, not the subject.

**gap_risk**: high / medium / low
Severity rules:
- severe gap: role explicitly requires years of industry/business experience the candidate lacks; mandatory technical skills entirely absent from profile; required certifications or licences not held
- manageable gap: preferred (not required) skills missing; industry context that could map from research; learnable tools
- minor gap: nice-to-haves, soft skills, domain familiarity without depth requirement
Rating rules:
- high: at least one severe gap present — do not average, one severe gap is enough
- medium: gaps are manageable but real
- low: no severe gaps, plausible fit overall

**gap_risk_reason**: One sentence. Name the most severe gap. Start with the key fact.

**domain_fit**: high / medium / low
- high: employer domain is in the candidate's priority domains
- medium: adjacent or acceptable domain
- low: unrelated domain
Note: domain_fit does not change the suggestion unless role_fit and gap_risk are equal.

**domain_fit_reason**: One sentence. Start with the key fact.

**fit_areas**: 2 to 4 short phrases where the candidate matches well.

**gaps**: List each gap with a description and severity (minor / manageable / severe).

**suggestion**: apply / consider / skip / spam
- spam: role_check was no
- apply: high role_fit and low or medium gap_risk
- consider: medium role_fit with low gap_risk, or high role_fit with medium gap_risk
- skip: role type matches but gap_risk is high, or fit is too weak overall

**reasoning**: One sentence. State the decisive factor and the main caveat, separated by a semicolon. Use plain language — no field names or technical labels. No bullet points."""


class Gap(BaseModel):
    description: str
    severity: Literal["minor", "manageable", "severe"]


class FitResult(BaseModel):
    """What the LLM produces — purely analytical fields."""

    job_summary: str
    role_check: bool
    role_fit: Literal["high", "medium", "low"]
    role_fit_reason: str
    gap_risk: Literal["high", "medium", "low"]
    gap_risk_reason: str
    domain_fit: Literal["high", "medium", "low"]
    domain_fit_reason: str
    gaps: list[Gap]
    fit_areas: list[str]
    suggestion: Literal["apply", "consider", "skip", "spam"]
    reasoning: str


class Assessment(JobListing, FitResult):
    """Full record — extraction + fit analysis + pipeline metadata."""

    is_job_listing: bool = True  # always true by the time we reach assessment
    url: str
    source: str
    scraped_at: datetime
    assessed_at: datetime
    assessed_model: str = ""
    rating: str = "new"  # new | liked | disliked
    pipeline_stage: str = "assessed"  # keyword_spam | llm_spam | assessed


def assess_fit(
    listing: JobListing,
    profile_text: str,
    criteria_text: str,
    url: str = "",
    source: str = "",
    scraped_at: datetime | None = None,
) -> Assessment:
    cached_prefix = CONTEXT_PROMPT.format(profile_text=profile_text, criteria_text=criteria_text)
    prompt = LISTING_PROMPT.format(listing_text=listing.listing_text or "[No listing text extracted]")

    content = call_llm(SYSTEM_PROMPT, prompt, FitResult.model_json_schema(), provider=ASSESS_PROVIDER, model=ASSESS_MODEL, cached_prefix=cached_prefix)
    fit = FitResult.model_validate_json(content)

    now = datetime.now(timezone.utc)
    return Assessment(
        **listing.model_dump(exclude={"is_job_listing"}),
        **fit.model_dump(),
        url=url,
        source=source,
        scraped_at=scraped_at or now,
        assessed_at=now,
        assessed_model=f"{ASSESS_PROVIDER}/{ASSESS_MODEL}",
    )
