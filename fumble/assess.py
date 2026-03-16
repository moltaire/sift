from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel

from fumble.extract import JobListing
from fumble.llm import MODEL, PROVIDER, call_llm

SYSTEM_PROMPT = """You are a precise job screening assistant.
Assess how well a job listing matches a candidate's profile and search criteria.
Be concise and direct. Think concisely — limit reasoning to essential steps."""

USER_PROMPT = """## Candidate Profile
{profile_text}

## Search Criteria
{criteria_text}

## Job Listing
{listing_text}

---

Assess this job listing against the profile and criteria above.

**job_summary** (required): one sentence — what the role is, at what kind of organisation, and the main focus. Plain text, no jargon.

**For each dimension, provide a rating and a one-sentence reason:**
- domain_fit (high/medium/low): match between job domain and the candidate's target domains. high = primary target domain. medium = adjacent or acceptable. low = unrelated.
- domain_fit_reason: one sentence. Skip the subject — start directly with the key fact.
- role_fit (high/medium/low): match between role type and the candidate's target roles. high = strong match. medium = partial match. low = does not match.
- role_fit_reason: one sentence. Skip the subject — start directly with the key fact.
- gap_risk (high/medium/low): risk of being screened out due to profile gaps. high = clearly lacks required experience. medium = some requirements are a stretch. low = plausible fit.
- gap_risk_reason: one sentence. Skip the subject — start directly with the key fact.

**fit_areas**: list of 2-4 short phrases identifying where the candidate matches well.

**gaps**: list of gaps between the role requirements and the candidate profile. For each gap:
- description: one short phrase naming the gap.
- severity: minor (easily addressed or not critical) / manageable (real gap but not disqualifying) / severe (likely dealbreaker).

**suggestion**: apply / consider / skip

**reasoning**: 2 sentences maximum. Lead with the decisive factor, then the trade-off or caveat if any. Plain text, no bullet points.
"""


class Gap(BaseModel):
    description: str
    severity: Literal["minor", "manageable", "severe"]


class FitResult(BaseModel):
    """What the LLM produces — purely analytical fields."""

    job_summary: str
    domain_fit: Literal["high", "medium", "low"]
    domain_fit_reason: str
    role_fit: Literal["high", "medium", "low"]
    role_fit_reason: str
    gap_risk: Literal["high", "medium", "low"]
    gap_risk_reason: str
    fit_areas: list[str]
    gaps: list[Gap]
    suggestion: Literal["apply", "consider", "skip"]
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


def assess_fit(
    listing: JobListing,
    profile_text: str,
    criteria_text: str,
    url: str = "",
    source: str = "",
    scraped_at: datetime | None = None,
) -> Assessment:
    prompt = USER_PROMPT.format(
        profile_text=profile_text,
        criteria_text=criteria_text,
        listing_text=listing.listing_text or "[No listing text extracted]",
    )

    content = call_llm(
        SYSTEM_PROMPT,
        prompt,
        FitResult.model_json_schema(),
        extra_options={"temperature": 0.6, "num_predict": 1500, "top_k": 20, "presence_penalty": 1.5},
    )
    fit = FitResult.model_validate_json(content)

    now = datetime.now(timezone.utc)
    return Assessment(
        **listing.model_dump(exclude={"is_job_listing"}),
        **fit.model_dump(),
        url=url,
        source=source,
        scraped_at=scraped_at or now,
        assessed_at=now,
        assessed_model=f"{PROVIDER}/{MODEL}",
    )
