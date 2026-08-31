"""Common record shape produced by both scrapers, so score_scraped_jobs.py can
feed either one straight into src/features.py without extra glue code.
"""

JOB_RECORD_FIELDS = [
    # fields the trained model actually uses (see features.RAW_INPUT_COLUMNS)
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
    # metadata, not used by the model but useful in the output list
    "job_id",
    "company_name",
    "source_url",
    "posted_date",
    "scraped_at",
]


def empty_job_record() -> dict:
    return {field: None for field in JOB_RECORD_FIELDS}
