"""Scrapes LinkedIn job search results using an AUTHENTICATED session (Selenium).

*** READ THIS FIRST ***
Logging in and scraping with your own LinkedIn account is a clear violation of
LinkedIn's Terms of Service and can get the account restricted or permanently
banned. This script exists for personal/educational use on YOUR OWN account,
at LOW volume, with the built-in delays left intact. Don't run this against
an account you can't afford to lose, and don't share/sell scraped data.

Setup:
    1. cp .env.example .env   and fill in LINKEDIN_EMAIL / LINKEDIN_PASSWORD
    2. pip install -r requirements.txt   (needs selenium + webdriver-manager)
    3. Have Google Chrome installed.

Usage:
    python3 -m src.scraper.auth_scraper --keywords "data analyst" --location "United States" --max-jobs 15

First run: leave --headless off so you can manually solve any CAPTCHA / 2FA
checkpoint LinkedIn throws up during login.
"""

import argparse
import os
import pickle
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

from .schema import empty_job_record

ROOT = Path(__file__).resolve().parents[2]
COOKIE_PATH = ROOT / "data" / ".linkedin_cookies.pkl"

LOGIN_URL = "https://www.linkedin.com/login"
JOBS_SEARCH_URL = "https://www.linkedin.com/jobs/search/"
JOB_VIEW_URL = "https://www.linkedin.com/jobs/view/{job_id}/"


def _polite_sleep(delay_range):
    time.sleep(random.uniform(*delay_range))


def build_driver(headless: bool = False):
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--window-size=1280,1600")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
    )
    return driver


def _save_cookies(driver):
    COOKIE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(COOKIE_PATH, "wb") as f:
        pickle.dump(driver.get_cookies(), f)


def _load_cookies(driver) -> bool:
    if not COOKIE_PATH.exists():
        return False
    driver.get("https://www.linkedin.com")
    with open(COOKIE_PATH, "rb") as f:
        cookies = pickle.load(f)
    for cookie in cookies:
        cookie.pop("sameSite", None)
        try:
            driver.add_cookie(cookie)
        except Exception:  # noqa: BLE001
            pass
    return True


def _is_logged_in(driver) -> bool:
    driver.get("https://www.linkedin.com/feed/")
    time.sleep(2)
    return "/feed" in driver.current_url


def login(driver, email: str, password: str, manual_checkpoint_timeout: int = 120):
    if _load_cookies(driver) and _is_logged_in(driver):
        print("Reused saved session, already logged in.")
        return

    driver.get(LOGIN_URL)
    wait = WebDriverWait(driver, 15)
    wait.until(EC.presence_of_element_located((By.ID, "username"))).send_keys(email)
    driver.find_element(By.ID, "password").send_keys(password)
    driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
    time.sleep(3)

    if "checkpoint" in driver.current_url or "challenge" in driver.current_url:
        print(
            f"LinkedIn is asking for a manual security check (CAPTCHA/2FA). "
            f"Complete it in the browser window now — waiting up to {manual_checkpoint_timeout}s ..."
        )
        try:
            WebDriverWait(driver, manual_checkpoint_timeout).until(
                lambda d: "/feed" in d.current_url
            )
        except TimeoutException:
            raise RuntimeError("Login checkpoint not resolved in time. Re-run and try again.")

    if "/feed" not in driver.current_url:
        WebDriverWait(driver, 15).until(EC.url_contains("/feed"))

    print("Logged in.")
    _save_cookies(driver)


def _extract_job_id(card) -> str:
    for attr in ("data-job-id", "data-occludable-job-id"):
        val = card.get_attribute(attr)
        if val:
            return val.split(":")[-1]
    try:
        link = card.find_element(By.CSS_SELECTOR, "a[href*='/jobs/view/']")
        href = link.get_attribute("href")
        digits = "".join(ch for ch in href.rstrip("/").split("/")[-1] if ch.isdigit())
        if digits:
            return digits
    except NoSuchElementException:
        pass
    return None


def search_jobs(driver, keywords: str, location: str, max_jobs: int = 25, delay_range=(3, 6)) -> list:
    url = f"{JOBS_SEARCH_URL}?keywords={keywords}&location={location}"
    driver.get(url)
    _polite_sleep(delay_range)

    jobs = {}
    scroll_container_selectors = ["div.jobs-search-results-list", "div.scaffold-layout__list"]
    stalled_rounds = 0

    while len(jobs) < max_jobs and stalled_rounds < 4:
        cards = driver.find_elements(By.CSS_SELECTOR, "li[data-occludable-job-id], li.jobs-search-results__list-item")
        before = len(jobs)
        for card in cards:
            job_id = _extract_job_id(card)
            if not job_id or job_id in jobs:
                continue
            title_el = _first_match(card, ["a.job-card-list__title", "a[href*='/jobs/view/']"])
            company_el = _first_match(card, ["span.job-card-container__primary-description", ".job-card-container__company-name"])
            location_el = _first_match(card, ["li.job-card-container__metadata-item"])
            jobs[job_id] = {
                "job_id": job_id,
                "title": title_el.text.strip() if title_el else None,
                "company_name": company_el.text.strip() if company_el else None,
                "location": location_el.text.strip() if location_el else None,
                "source_url": JOB_VIEW_URL.format(job_id=job_id),
            }
            if len(jobs) >= max_jobs:
                break

        if len(jobs) == before:
            stalled_rounds += 1
        else:
            stalled_rounds = 0

        for selector in scroll_container_selectors:
            containers = driver.find_elements(By.CSS_SELECTOR, selector)
            if containers:
                driver.execute_script("arguments[0].scrollBy(0, 800);", containers[0])
                break
        else:
            driver.execute_script("window.scrollBy(0, 800);")
        _polite_sleep(delay_range)

    return list(jobs.values())[:max_jobs]


def _first_match(root, selectors):
    for selector in selectors:
        try:
            return root.find_element(By.CSS_SELECTOR, selector)
        except NoSuchElementException:
            continue
    return None


def fetch_job_details(driver, job_id: str, delay_range=(3, 6)) -> dict:
    driver.get(JOB_VIEW_URL.format(job_id=job_id))
    _polite_sleep(delay_range)

    details = {
        "description": None,
        "employment_type": None,
        "required_experience": None,
        "function": None,
        "industry": None,
    }

    desc_el = _first_match(
        driver, ["div.jobs-description__content", "div.jobs-box__html-content", "article"]
    )
    if desc_el:
        details["description"] = desc_el.text.strip()

    insight_els = driver.find_elements(
        By.CSS_SELECTOR, "li.job-details-jobs-unified-top-card__job-insight, span.ui-label"
    )
    insight_text = " | ".join(el.text.strip() for el in insight_els if el.text.strip())
    if insight_text:
        details["employment_type"] = details["employment_type"] or insight_text

    return details


def scrape(keywords: str, location: str, max_jobs: int = 25, headless: bool = False, delay_range=(3, 6)) -> list:
    load_dotenv(ROOT / ".env")
    email = os.getenv("LINKEDIN_EMAIL")
    password = os.getenv("LINKEDIN_PASSWORD")
    if not email or not password:
        raise SystemExit("Set LINKEDIN_EMAIL and LINKEDIN_PASSWORD in a .env file (see .env.example).")

    print(
        "NOTE: authenticated scraping violates LinkedIn's Terms of Service and risks "
        "your account being restricted. Proceeding at low volume with delays.\n"
    )

    driver = build_driver(headless=headless)
    try:
        login(driver, email, password)
        search_results = search_jobs(driver, keywords, location, max_jobs=max_jobs, delay_range=delay_range)
        print(f"Found {len(search_results)} job cards. Fetching details ...")

        records = []
        for i, job in enumerate(search_results, 1):
            record = empty_job_record()
            record.update(job)
            try:
                details = fetch_job_details(driver, job["job_id"], delay_range=delay_range)
                record.update({k: v for k, v in details.items() if v})
            except Exception as exc:  # noqa: BLE001
                print(f"  [{i}/{len(search_results)}] failed to fetch details for {job['job_id']}: {exc}")
            record["scraped_at"] = datetime.now(timezone.utc).isoformat()
            records.append(record)
            print(f"  [{i}/{len(search_results)}] {record.get('title')!r} @ {record.get('company_name')!r}")

        return records
    finally:
        driver.quit()


def _cli():
    parser = argparse.ArgumentParser(description="Scrape authenticated LinkedIn job search results.")
    parser.add_argument("--keywords", required=True)
    parser.add_argument("--location", default="")
    parser.add_argument("--max-jobs", type=int, default=15)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--min-delay", type=float, default=3.0)
    parser.add_argument("--max-delay", type=float, default=6.0)
    parser.add_argument("--out", default=None, help="Excel (.xlsx) path to write results to")
    args = parser.parse_args()

    records = scrape(
        args.keywords,
        args.location,
        max_jobs=args.max_jobs,
        headless=args.headless,
        delay_range=(args.min_delay, args.max_delay),
    )

    import pandas as pd

    df = pd.DataFrame(records)
    out_path = Path(args.out) if args.out else ROOT / "data" / "scraped" / f"linkedin_auth_{args.keywords[:30].replace(' ', '_')}.xlsx"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(out_path, index=False)
    print(f"\nWrote {len(df)} records to {out_path}")


if __name__ == "__main__":
    _cli()
