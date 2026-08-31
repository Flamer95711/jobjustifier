"""Shared feature engineering for the fake-job-posting classifier.

Used by both src/train.py (fitting) and src/predict.py / src/score_scraped_jobs.py
(inference), so the exact same transformations are applied every time.
"""

import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.linear_model import LogisticRegression

TEXT_SOURCE_COLUMNS = ["title", "company_profile", "description", "requirements", "benefits"]
CATEGORICAL_COLUMNS = [
    "employment_type",
    "required_experience",
    "required_education",
    "industry",
    "function",
    "country",
]
NUMERIC_COLUMNS = [
    "telecommuting",
    "has_company_logo",
    "has_questions",
    "missing_company_profile",
    "missing_benefits",
    "missing_salary_range",
    "text_length",
]

# Columns a raw job posting record needs (scraped or from the Kaggle CSV) before
# engineer_features() can run. Missing ones are filled in with safe defaults.
RAW_INPUT_COLUMNS = [
    "title",
    "location",
    "department",
    "salary_range",
    "company_profile",
    "description",
    "requirements",
    "benefits",
    "telecommuting",
    "has_company_logo",
    "has_questions",
    "employment_type",
    "required_experience",
    "required_education",
    "industry",
    "function",
]


def _extract_country(location: str) -> str:
    if not isinstance(location, str) or not location.strip():
        return "Unknown"
    return location.split(",")[0].strip() or "Unknown"


def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Take a raw job-posting DataFrame and return one with the derived columns
    the model pipeline expects. Non-destructive: returns a new DataFrame.
    """
    df = df.copy()

    for col in RAW_INPUT_COLUMNS:
        if col not in df.columns:
            df[col] = None

    for col in ["telecommuting", "has_company_logo", "has_questions"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    df["missing_company_profile"] = df["company_profile"].isna() | (
        df["company_profile"].astype(str).str.strip() == ""
    )
    df["missing_company_profile"] = df["missing_company_profile"].astype(int)

    df["missing_benefits"] = df["benefits"].isna() | (df["benefits"].astype(str).str.strip() == "")
    df["missing_benefits"] = df["missing_benefits"].astype(int)

    df["missing_salary_range"] = df["salary_range"].isna() | (
        df["salary_range"].astype(str).str.strip() == ""
    )
    df["missing_salary_range"] = df["missing_salary_range"].astype(int)

    df["country"] = df["location"].apply(_extract_country)

    text_parts = [df[col].fillna("").astype(str) for col in TEXT_SOURCE_COLUMNS]
    combined_text = text_parts[0]
    for part in text_parts[1:]:
        combined_text = combined_text + " " + part
    df["text"] = combined_text.str.strip()
    df["text_length"] = df["text"].str.len()

    for col in CATEGORICAL_COLUMNS:
        if col == "country":
            continue
        df[col] = df[col].fillna("Unknown").astype(str)
        df.loc[df[col].str.strip() == "", col] = "Unknown"

    return df


def build_pipeline() -> Pipeline:
    """Fresh, unfit sklearn Pipeline: feature transformer + classifier."""
    preprocessor = ColumnTransformer(
        transformers=[
            ("tfidf", TfidfVectorizer(max_features=8000, ngram_range=(1, 2), stop_words="english", min_df=2), "text"),
            ("categorical", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_COLUMNS),
            ("numeric", "passthrough", NUMERIC_COLUMNS),
        ]
    )

    classifier = LogisticRegression(max_iter=2000, class_weight="balanced", C=1.0, solver="liblinear")

    return Pipeline(steps=[("preprocess", preprocessor), ("classifier", classifier)])
