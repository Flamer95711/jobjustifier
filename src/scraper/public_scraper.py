"""Scrapes LinkedIn's PUBLIC job search results (no login required).

Uses the same "guest" endpoint LinkedIn's own /jobs/search page calls to page
in more results, then visits each job's public view page for the full
description and criteria (seniority, employment type, function, industry).

IMPORTANT — read before using:
  - This scrapes public pages only, but LinkedIn's Terms of Service still
    prohibit automated scraping. Use for personal/educational purposes, keep
    volume low, and expect LinkedIn to rate-limit or block your IP if you
    push too hard.
  - LinkedIn's HTML/endpoints change without notice; selectors here may need
    updates over time.
  - Respect the built-in delays. Don't remove them to go faster.

Usage:
    python3 -m src.scraper.public_scraper --keywords "data analyst" --location "United States" --max-jobs 25
"""

import argparse
import random
import time
from datetime import datetime, timezone
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from .schema import empty_job_record

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
JOB_VIEW_URL = "https://www.linkedin.com/jobs/view/{job_id}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

RESULTS_PER_PAGE = 25


def _polite_sleep(delay_range):
    time.sleep(random.uniform(*delay_range))


def _get_with_retry(session, url, params=None, max_retries=3, delay_range=(2, 5)):
    for attempt in range(1, max_retries + 1):
        resp = session.get(url, params=params, headers=HEADERS, timeout=15)
        if resp.status_code == 200:
            return resp
        if resp.status_code in (429, 999):
            wait = (2 ** attempt) + random.uniform(0, 1)
            print(f"  rate-limited (status {resp.status_code}), backing off {wait:.1f}s ...")
            time.sleep(wait)
            continue
        resp.raise_for_status()
    raise RuntimeError(f"Failed to fetch {url} after {max_retries} retries")


def _parse_search_results(html: str) -> list:
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("div.base-card") or soup.select("li")
    jobs = []
    for card in cards:
        urn = card.get("data-entity-urn", "")
        job_id = urn.split(":")[-1] if urn else None

        link = card.select_one("a.base-card__full-link") or card.select_one("a")
        source_url = link["href"].split("?")[0] if link and link.has_attr("href") else None
        if not job_id and source_url:
            digits = "".join(ch for ch in source_url.rstrip("/").split("/")[-1] if ch.isdigit())
            job_id = digits or None
        if not job_id:
            continue

        title_el = card.select_one("h3.base-search-card__title")
        company_el = card.select_one("h4.base-search-card__subtitle")
        location_el = card.select_one("span.job-search-card__location")
        date_el = card.select_one("time")

        jobs.append(
            {
                "job_id": job_id,
                "title": title_el.get_text(strip=True) if title_el else None,
                "company_name": company_el.get_text(strip=True) if company_el else None,
                "location": location_el.get_text(strip=True) if location_el else None,
                "source_url": source_url or JOB_VIEW_URL.format(job_id=job_id),
                "posted_date": date_el.get("datetime") if date_el else None,
            }
        )
    return jobs


def _parse_job_detail(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    details = {
        "description": None,
        "employment_type": None,
        "required_experience": None,
        "function": None,
        "industry": None,
    }

    desc_el = soup.select_one("div.show-more-less-html__markup") or soup.select_one(
        "div.description__text"
    )
    if desc_el:
        details["description"] = desc_el.get_text("\n", strip=True)

    label_map = {
        "seniority level": "required_experience",
        "employment type": "employment_type",
        "job function": "function",
        "industries": "industry",
    }
    for item in soup.select("li.description__job-criteria-item"):
        header_el = item.select_one("h3")
        value_el = item.select_one("span")
        if not header_el or not value_el:
            continue
        label = header_el.get_text(strip=True).lower()
        field = label_map.get(label)
        if field:
            details[field] = value_el.get_text(strip=True)

    return details


def search_jobs(keywords: str, location: str, max_jobs: int = 25, delay_range=(2, 5)) -> list:
    """Fetch job search result cards (title/company/location/id), no detail fetch yet."""
    session = requests.Session()
    jobs = []
    start = 0
    while len(jobs) < max_jobs:
        params = {"keywords": keywords, "location": location, "start": start}
        print(f"Fetching search results, start={start} ...")
        resp = _get_with_retry(session, SEARCH_URL, params=params, delay_range=delay_range)
        page_jobs = _parse_search_results(resp.text)
        if not page_jobs:
            print("No more results.")
            break
        jobs.extend(page_jobs)
        start += RESULTS_PER_PAGE
        _polite_sleep(delay_range)
    return jobs[:max_jobs]


def fetch_job_details(job_id: str, session: requests.Session, delay_range=(2, 5)) -> dict:
    url = JOB_VIEW_URL.format(job_id=job_id)
    resp = _get_with_retry(session, url, delay_range=delay_range)
    return _parse_job_detail(resp.text)


def scrape(keywords: str, location: str, max_jobs: int = 25, delay_range=(2, 5)) -> list:
    """Full pipeline: search + per-job detail fetch. Returns a list of dicts
    shaped per scraper.schema.JOB_RECORD_FIELDS, ready for feature engineering.
    """
    print(
        "NOTE: scraping LinkedIn's public pages is against their Terms of Service. "
        "Keep volume low and use responsibly.\n"
    )
    search_results = search_jobs(keywords, location, max_jobs=max_jobs, delay_range=delay_range)
    print(f"Found {len(search_results)} job cards. Fetching details ...")

    session = requests.Session()
    records = []
    for i, job in enumerate(search_results, 1):
        record = empty_job_record()
        record.update(job)
        try:
            details = fetch_job_details(job["job_id"], session, delay_range=delay_range)
            record.update({k: v for k, v in details.items() if v})
        except Exception as exc:  # noqa: BLE001
            print(f"  [{i}/{len(search_results)}] failed to fetch details for {job['job_id']}: {exc}")
        record["scraped_at"] = datetime.now(timezone.utc).isoformat()
        records.append(record)
        print(f"  [{i}/{len(search_results)}] {record.get('title')!r} @ {record.get('company_name')!r}")
        _polite_sleep(delay_range)

    return records


def _cli():
    parser = argparse.ArgumentParser(description="Scrape public LinkedIn job search results.")
    parser.add_argument("--keywords", required=True)
    parser.add_argument("--location", default="")
    parser.add_argument("--max-jobs", type=int, default=25)
    parser.add_argument("--min-delay", type=float, default=2.0)
    parser.add_argument("--max-delay", type=float, default=5.0)
    parser.add_argument("--out", default=None, help="Excel (.xlsx) path to write results to")
    args = parser.parse_args()

    records = scrape(
        args.keywords,
        args.location,
        max_jobs=args.max_jobs,
        delay_range=(args.min_delay, args.max_delay),
    )

    import pandas as pd
    from pathlib import Path

    df = pd.DataFrame(records)
    out_path = Path(args.out) if args.out else Path(__file__).resolve().parents[2] / "data" / "scraped" / f"linkedin_public_{quote(args.keywords)[:30]}.xlsx"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(out_path, index=False)
    print(f"\nWrote {len(df)} records to {out_path}")


if __name__ == "__main__":
    _cli()
