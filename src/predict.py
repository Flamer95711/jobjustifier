"""Run the trained model on fake-job-posting/job_postings_test.csv.

Writes:
  - data/predictions/submission.xlsx        (id, fraudulent)      -> matches sample_submission.csv format
  - data/predictions/test_predictions.xlsx  (id, fraudulent, fraud_probability, title, location)

Usage:
    python3 src/predict.py
"""

import sys
from pathlib import Path

import joblib
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import engineer_features  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TEST_CSV = ROOT / "fake-job-posting" / "job_postings_test.csv"
MODEL_PATH = ROOT / "models" / "fake_job_classifier.joblib"
OUT_DIR = ROOT / "data" / "predictions"


def main():
    if not MODEL_PATH.exists():
        raise SystemExit(f"No trained model found at {MODEL_PATH}. Run src/train.py first.")

    print(f"Loading model from {MODEL_PATH} ...")
    pipeline = joblib.load(MODEL_PATH)

    print(f"Loading {TEST_CSV} ...")
    df = pd.read_csv(TEST_CSV)
    featured = engineer_features(df)

    proba = pipeline.predict_proba(featured)[:, 1]
    pred = (proba >= 0.5).astype(int)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    submission = pd.DataFrame({"id": df["id"], "fraudulent": pred})
    submission_path = OUT_DIR / "submission.xlsx"
    submission.to_excel(submission_path, index=False)

    detailed = pd.DataFrame(
        {
            "id": df["id"],
            "title": df["title"],
            "location": df["location"],
            "fraudulent": pred,
            "fraud_probability": proba.round(4),
        }
    ).sort_values("fraud_probability", ascending=False)
    detailed_path = OUT_DIR / "test_predictions.xlsx"
    detailed.to_excel(detailed_path, index=False)

    print(f"Predicted {pred.sum()} fraudulent / {len(pred)} total ({pred.mean():.2%})")
    print(f"Wrote {submission_path}")
    print(f"Wrote {detailed_path}")


if __name__ == "__main__":
    main()
