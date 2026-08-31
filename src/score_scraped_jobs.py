"""Scrape LinkedIn job postings and score each one fake/real with the trained model.

Usage:
    # public, no login
    python3 src/score_scraped_jobs.py --mode public --keywords "data analyst" --location "United States" --max-jobs 25

    # authenticated (needs .env with LINKEDIN_EMAIL/LINKEDIN_PASSWORD)
    python3 src/score_scraped_jobs.py --mode auth --keywords "data analyst" --location "United States" --max-jobs 15

Writes data/scraped/scored_<keywords>_<timestamp>.xlsx with one row per
posting: Job Role, Company Name, Apply Link, Job Profile (truncated),
Required Experience, Risk Level, and Fraud %.
"""

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

import joblib
import pandas as pd
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import engineer_features  # noqa: E402
from utils import extract_experience_from_text, update_google_sheet  # noqa: E402

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "models" / "fake_job_classifier.joblib"
OUT_DIR = ROOT / "data" / "scraped"

JOB_PROFILE_MAX_CHARS = 300


def _truncate(text, max_chars=JOB_PROFILE_MAX_CHARS):
    if not isinstance(text, str) or not text.strip():
        return ""
    text = " ".join(text.split())  # collapse newlines/whitespace
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


def _risk_level(prob):
    if prob is None or pd.isna(prob):
        return "Unscored"
    if prob >= 0.65:
        return "High"
    if prob >= 0.3:
        return "Medium"
    return "Low"


def main():
    parser = argparse.ArgumentParser(description="Scrape LinkedIn jobs and flag likely-fake postings.")
    parser.add_argument("--mode", choices=["public", "auth"], default="public")
    parser.add_argument("--keywords", required=True)
    parser.add_argument("--location", default="")
    parser.add_argument("--max-jobs", type=int, default=25)
    parser.add_argument("--headless", action="store_true", help="auth mode only")
    parser.add_argument("--threshold", type=float, default=0.5, help="probability cutoff for flagging fraudulent")
    parser.add_argument("--sheet-url", default=None, help="Google Sheet URL to append results directly to")
    args = parser.parse_args()

    if not MODEL_PATH.exists():
        raise SystemExit(f"No trained model at {MODEL_PATH}. Run src/train.py first.")

    if args.mode == "public":
        from scraper.public_scraper import scrape

        records = scrape(args.keywords, args.location, max_jobs=args.max_jobs)
    else:
        from scraper.auth_scraper import scrape

        records = scrape(args.keywords, args.location, max_jobs=args.max_jobs, headless=args.headless)

    if not records:
        print("No jobs scraped, nothing to score.")
        return

    # Parse required experience from job descriptions
    for rec in records:
        rec["required_experience"] = extract_experience_from_text(
            rec.get("description"), fallback_seniority=rec.get("required_experience")
        )

    df = pd.DataFrame(records)
    featured = engineer_features(df)

    pipeline = joblib.load(MODEL_PATH)
    proba = pipeline.predict_proba(featured)[:, 1]
    pred = (proba >= args.threshold).astype(int)

    df["fraud_probability"] = proba.round(4)
    df["fraudulent"] = pred

    result = pd.DataFrame(
        {
            "Job Role": df["title"],
            "Company Name": df["company_name"],
            "Apply Link": df["source_url"],
            "Job Profile": df["description"].apply(_truncate),
            "Required Experience": df["required_experience"],
            "Risk Level": df["fraud_probability"].apply(_risk_level),
            "Fraud %": (df["fraud_probability"] * 100).round(1),
        }
    )
    result = result.sort_values("Fraud %", ascending=False)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_keywords = args.keywords.replace(" ", "_")[:30]
    out_path = OUT_DIR / f"scored_{safe_keywords}_{timestamp}.xlsx"
    result.to_excel(out_path, index=False)

    sheet_url = args.sheet_url or os.getenv("GOOGLE_SHEET_URL")
    if sheet_url:
        update_google_sheet(sheet_url, result)

    n_flagged = int(pred.sum())
    print(f"\nScored {len(df)} postings — {n_flagged} flagged as likely fraudulent (threshold={args.threshold}).")
    print(f"Wrote {out_path}")
    print("\nTop flagged postings:")
    print(
        result[result["Risk Level"] == "High"][["Job Role", "Company Name", "Fraud %"]]
        .head(10)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
