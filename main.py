import argparse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from fumble.assess import assess_fit
from fumble.email_fetch import fetch_job_urls
from fumble.extract import extract_listing, is_listing_quick
from fumble.scrape import login_flow, scrape_job_page
from fumble.extract import JobListing
from fumble.store import clear_ratings, init_db, load_assessments, mark_url_seen, save_assessment, update_assessment, tracking_url_seen, url_exists

PROFILE = Path("resources/profile.md").read_text()
CRITERIA = Path("resources/search-criteria.md").read_text()

LOG_PATH = Path("data/failures.log")
MIN_LISTING_LENGTH = 150  # chars — below this, extraction likely caught a wall or empty page


def _strip_params(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(query="", fragment=""))


def _log_failure(url: str, source: str, reason: str) -> None:
    LOG_PATH.parent.mkdir(exist_ok=True)
    with LOG_PATH.open("a") as f:
        f.write(f"{datetime.now().isoformat()} | {source} | {reason} | {url}\n")


WALL_PATTERNS = ["checkpoint", "login", "authwall", "signin", "sign-in"]

def _is_wall(url: str) -> bool:
    return any(p in url.lower() for p in WALL_PATTERNS)


def main():
    parser = argparse.ArgumentParser(description="Sift — automated job ad screening")
    parser.add_argument("--days", type=int, default=3, help="Fetch emails from the last N days (default: 3)")
    parser.add_argument("--unread", action="store_true", help="Only process unread emails")
    parser.add_argument("--url", action="append", dest="urls", metavar="URL", help="Process a specific URL directly (can be repeated)")
    parser.add_argument("--login", metavar="URL", help="Open a headed browser at URL to log in and save the session")
    parser.add_argument("--force", action="store_true", help="Process all URLs, ignoring the seen-URL cache")
    parser.add_argument("--mark-read", action="store_true", help="Mark fetched emails as read after processing")
    parser.add_argument("--reassess", action="store_true", help="Re-run LLM assessment on all stored listings without re-scraping")
    parser.add_argument("--clear-ratings", action="store_true", help="Reset all user ratings to 'new' (with confirmation)")
    args = parser.parse_args()

    if args.login:
        login_flow(start_url=args.login)
        return

    init_db()

    if args.clear_ratings:
        assessments = load_assessments()
        superliked = sum(1 for a in assessments if a.rating == "superliked")
        liked = sum(1 for a in assessments if a.rating == "liked")
        disliked = sum(1 for a in assessments if a.rating == "disliked")
        total_rated = superliked + liked + disliked
        if total_rated == 0:
            print("No ratings to clear.")
            return
        print(f"This will reset {total_rated} rating(s) to 'new' ({superliked} superliked, {liked} liked, {disliked} disliked).")
        confirm = input("Type 'yes' to confirm: ").strip().lower()
        if confirm == "yes":
            n = clear_ratings()
            print(f"Cleared {n} rating(s).")
        else:
            print("Aborted.")
        return

    if args.reassess:
        assessments = load_assessments()
        total = len(assessments)
        print(f"Re-assessing {total} listing(s)...")
        ok, failed = 0, 0
        for i, a in enumerate(assessments, 1):
            listing = JobListing(
                is_job_listing=True,
                employer=a.employer,
                job_title=a.job_title,
                language=a.language,
                listing_text=a.listing_text,
            )
            print(f"[{i}/{total}] {a.employer} — {a.job_title}...")
            try:
                result = assess_fit(listing=listing, profile_text=PROFILE, criteria_text=CRITERIA, url=a.url, source=a.source, scraped_at=a.scraped_at)
                update_assessment(result)
                print(f"  [{result.suggestion}] {result.domain_fit}/{result.role_fit} — {result.job_summary}")
                ok += 1
            except Exception as e:
                print(f"  Failed: {e}")
                failed += 1
        print(f"\nDone. {ok} re-assessed, {failed} failed.")
        return

    if args.urls:
        job_urls = [(url, "manual", "auto") for url in args.urls]
        print(f"Processing {len(job_urls)} manually provided URL(s)\n")
    elif args.unread:
        print("Fetching job URLs from unread emails...")
        job_urls = fetch_job_urls(unread_only=True, mark_read=args.mark_read)
        print(f"Found {len(job_urls)} URL(s) across all sources\n")
    else:
        since = date.today() - timedelta(days=args.days)
        print(f"Fetching job URLs from emails since {since}...")
        job_urls = fetch_job_urls(since=since, mark_read=args.mark_read)
        print(f"Found {len(job_urls)} URL(s) across all sources\n")

    seen_canonical: set[str] = set()
    new_count = 0
    skip_count = 0
    total = len(job_urls)

    for i, (tracking_url, source, scraper) in enumerate(job_urls, 1):
        if not args.force and tracking_url_seen(tracking_url):
            print(f"[{i}/{total}] [{source}] Already processed — skipping {tracking_url[:60]}")
            skip_count += 1
            continue

        print(f"[{i}/{total}] [{source}] Scraping {tracking_url[:60]}...")

        try:
            job_text, canonical_url = scrape_job_page(tracking_url, scraper=scraper)
            scraped_at = datetime.now(timezone.utc)
        except Exception as e:
            print(f"  Scrape failed: {e}")
            _log_failure(tracking_url, source, f"scrape_failed: {e}")
            mark_url_seen(tracking_url)
            skip_count += 1
            continue

        canonical_url = _strip_params(canonical_url)

        if _is_wall(canonical_url):
            print(f"  Login wall detected — skipping")
            _log_failure(canonical_url, source, "login_wall")
            mark_url_seen(tracking_url)
            mark_url_seen(canonical_url)
            skip_count += 1
            continue

        if not args.force and (canonical_url in seen_canonical or url_exists(canonical_url) or tracking_url_seen(canonical_url)):
            print(f"  Already seen — skipping")
            mark_url_seen(tracking_url)
            skip_count += 1
            continue

        seen_canonical.add(canonical_url)

        if len(job_text.strip()) < MIN_LISTING_LENGTH:
            print(f"  Page content too short — skipping")
            _log_failure(canonical_url, source, "page_too_short")
            mark_url_seen(tracking_url)
            mark_url_seen(canonical_url)
            skip_count += 1
            continue

        if not is_listing_quick(job_text):
            print(f"  Not a job listing (triage) — skipping")
            _log_failure(canonical_url, source, "not_a_job_listing_triage")
            mark_url_seen(tracking_url)
            mark_url_seen(canonical_url)
            skip_count += 1
            continue

        print(f"  Extracting...")
        try:
            listing = extract_listing(job_text)
        except Exception as e:
            print(f"  Extraction failed: {e}")
            _log_failure(canonical_url, source, f"extraction_failed: {e}")
            mark_url_seen(tracking_url)
            mark_url_seen(canonical_url)
            skip_count += 1
            continue

        print(f"  {listing.employer} — {listing.job_title}")

        if not listing.is_job_listing:
            print(f"  Not a job listing — skipping")
            _log_failure(canonical_url, source, "not_a_job_listing")
            mark_url_seen(tracking_url)
            mark_url_seen(canonical_url)
            skip_count += 1
            continue

        print(f"  Assessing...")
        try:
            result = assess_fit(
                listing=listing,
                profile_text=PROFILE,
                criteria_text=CRITERIA,
                url=canonical_url,
                source=source,
                scraped_at=scraped_at,
            )
        except Exception as e:
            print(f"  Assessment failed: {e}")
            _log_failure(canonical_url, source, f"assessment_failed: {e}")
            mark_url_seen(tracking_url)
            mark_url_seen(canonical_url)
            skip_count += 1
            continue

        if args.force:
            update_assessment(result)
        else:
            save_assessment(result)
        mark_url_seen(tracking_url)
        mark_url_seen(canonical_url)
        print(f"  [{result.suggestion}] {result.domain_fit}/{result.role_fit} — {result.job_summary}")
        new_count += 1

    print(f"\nDone. {new_count} new assessments, {skip_count} skipped.")


if __name__ == "__main__":
    main()
