"""Train the fake-job-posting classifier on fake-job-posting/job_postings_train.csv
and save the fitted pipeline to models/fake_job_classifier.joblib.

Usage:
    python3 src/train.py
"""

import sys
from pathlib import Path

import joblib
import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix, roc_auc_score
from sklearn.model_selection import train_test_split

sys.path.insert(0, str(Path(__file__).resolve().parent))
from features import engineer_features, build_pipeline  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TRAIN_CSV = ROOT / "fake-job-posting" / "job_postings_train.csv"
MODEL_PATH = ROOT / "models" / "fake_job_classifier.joblib"


def main():
    print(f"Loading {TRAIN_CSV} ...")
    df = pd.read_csv(TRAIN_CSV)
    print(f"{len(df)} rows, fraudulent rate: {df['fraudulent'].mean():.2%}")

    df = engineer_features(df)
    X = df
    y = df["fraudulent"]

    X_train, X_val, y_train, y_val = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    pipeline = build_pipeline()
    print("Training LogisticRegression pipeline (TF-IDF + categorical + numeric features)...")
    pipeline.fit(X_train, y_train)

    val_proba = pipeline.predict_proba(X_val)[:, 1]
    val_pred = pipeline.predict(X_val)

    print("\n--- Validation results (held-out 20% of training data) ---")
    print(classification_report(y_val, val_pred, target_names=["real", "fraudulent"], digits=3))
    print("Confusion matrix (rows=true, cols=pred):")
    print(confusion_matrix(y_val, val_pred))
    print(f"ROC-AUC: {roc_auc_score(y_val, val_proba):.4f}")

    print(f"\nRefitting on 100% of training data and saving to {MODEL_PATH} ...")
    pipeline.fit(X, y)
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipeline, MODEL_PATH)
    print("Done.")


if __name__ == "__main__":
    main()
