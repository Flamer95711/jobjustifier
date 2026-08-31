"""JSON-in/JSON-out scoring bridge for the Electron app.

Reads a JSON array of raw job-posting records from stdin (same shape as
scraper.schema.JOB_RECORD_FIELDS), engineers features, runs the trained
model, and writes the same records back to stdout with fraud_probability
and fraudulent fields added.

Usage:
    echo '[{"title": "...", ...}]' | python3 src/score_records.py [--threshold 0.5]
"""

import argparse
import json
import sys
from pathlib import Path

import joblib
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import engineer_features  # noqa: E402
from utils import extract_experience_from_text  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = ROOT / "models" / "fake_job_classifier.joblib"


def main():
    parser = argparse.ArgumentParser(description="Score raw job records read as JSON from stdin.")
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args()

    if not MODEL_PATH.exists():
        print(json.dumps({"error": f"No trained model at {MODEL_PATH}. Run src/train.py first."}))
        sys.exit(1)

    raw = sys.stdin.read()
    try:
        records = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"Invalid JSON on stdin: {exc}"}))
        sys.exit(1)

    if not records:
        print(json.dumps([]))
        return

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
    df = df.where(pd.notnull(df), None)

    print(df.to_json(orient="records"))


if __name__ == "__main__":
    main()
