"""Utility functions for experience parsing from job descriptions and Google Sheets export.
"""

import os
import re
from pathlib import Path
import pandas as pd
import requests

try:
    import gspread
except ImportError:
    gspread = None


def extract_experience_from_text(text: str, fallback_seniority: str = None) -> str:
    """Parses required years of experience from job description using regex.
    
    Returns parsed experience string (e.g. '3-5 years', '5+ years', 'Entry level')
    or falls back to default_seniority / 'Not Specified'.
    """
    if not text or not isinstance(text, str):
        return fallback_seniority or "Not Specified"

    text_clean = " ".join(text.split())

    # 1. Range of years (e.g. "3-5 years", "3 to 5 yrs", "1-2 years")
    range_match = re.search(
        r'\b(\d+)\s*(?:-|–|to)\s*(\d+)\s*\+?\s*(?:years?|yrs?)(?:\s+of)?\s*(?:relevant\s+)?(?:experience|exp)?\b',
        text_clean,
        re.IGNORECASE,
    )
    if range_match:
        min_yrs, max_yrs = range_match.group(1), range_match.group(2)
        parsed = f"{min_yrs}-{max_yrs} years"
        return f"{fallback_seniority} ({parsed})" if fallback_seniority else parsed

    # 2. Minimum or At least X years (e.g. "minimum 3 years", "at least 5 yrs")
    min_match = re.search(
        r'\b(?:minimum|at\s+least)\s+(?:of\s+)?(\d+)\s*(?:\+)?\s*(?:years?|yrs?)(?:\s+of)?\s*(?:relevant\s+)?(?:experience|exp)?\b',
        text_clean,
        re.IGNORECASE,
    )
    if min_match:
        yrs = min_match.group(1)
        parsed = f"{yrs}+ years"
        return f"{fallback_seniority} ({parsed})" if fallback_seniority else parsed

    # 3. X+ years of experience (e.g. "5+ years of experience", "3+ yrs exp")
    plus_match = re.search(
        r'\b(\d+)\+\s*(?:years?|yrs?)(?:\s+of)?\s*(?:relevant\s+)?(?:experience|exp)?\b',
        text_clean,
        re.IGNORECASE,
    )
    if plus_match:
        yrs = plus_match.group(1)
        parsed = f"{yrs}+ years"
        return f"{fallback_seniority} ({parsed})" if fallback_seniority else parsed

    # 4. Single number X years of experience (e.g. "3 years of experience")
    exact_match = re.search(
        r'\b(\d+)\s*(?:years?|yrs?)\s+of\s+(?:relevant\s+)?(?:experience|exp)?\b',
        text_clean,
        re.IGNORECASE,
    )
    if exact_match:
        yrs = exact_match.group(1)
        parsed = f"{yrs} years"
        return f"{fallback_seniority} ({parsed})" if fallback_seniority else parsed

    # 5. Entry level / No experience required
    entry_match = re.search(
        r'\b(?:entry\s*level|no\s*experience\s*required|no\s*prior\s*experience)\b',
        text_clean,
        re.IGNORECASE,
    )
    if entry_match:
        parsed = "0-1 years (Entry level)"
        return f"{fallback_seniority} ({parsed})" if fallback_seniority else parsed

    return fallback_seniority or "Not Specified"


def update_google_sheet(sheet_url: str, df: pd.DataFrame, creds_path: str = None) -> bool:
    """Updates/appends DataFrame rows to Google Sheet.
    
    Supports:
    1. Google Apps Script Web App URL (NO API KEY required!).
    2. gspread Service Account URL (requires credentials.json).
    """
    if not sheet_url or not isinstance(sheet_url, str):
        return False

    headers = df.columns.tolist()
    rows = df.astype(str).values.tolist()

    # Method A: Web App Webhook (No API key / credentials needed!)
    if "script.google.com" in sheet_url:
        try:
            payload = {"headers": headers, "rows": rows}
            resp = requests.post(sheet_url, json=payload, timeout=15, allow_redirects=True)
            if resp.status_code == 200:
                print(f"\n[Google Sheets] Successfully posted {len(df)} rows to Google Sheet Web App.")
                return True
            print(f"[Google Sheets Error] Web App returned status {resp.status_code}: {resp.text}")
            return False
        except Exception as exc:
            print(f"[Google Sheets Error] Web App request failed: {exc}")
            return False

    # Method B: gspread Service Account
    if gspread is None:
        print("gspread module not available.")
        return False

    root_dir = Path(__file__).resolve().parent.parent
    creds_file = creds_path or os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or str(root_dir / "credentials.json")

    try:
        if os.path.exists(creds_file):
            gc = gspread.service_account(filename=creds_file)
        elif os.getenv("GOOGLE_CREDENTIALS_JSON"):
            import json
            creds_data = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON"))
            gc = gspread.service_account_from_dict(creds_data)
        else:
            print(
                f"\n[Google Sheets] Note: No API key / credentials required if you use Google Apps Script Web App URL.\n"
                "Or place `credentials.json` in project root for gspread."
            )
            return False

        sheet = gc.open_by_url(sheet_url)
        worksheet = sheet.get_worksheet(0)

        existing_rows = worksheet.get_all_values()
        if not existing_rows:
            worksheet.append_row(headers)

        worksheet.append_rows(rows)
        print(f"\n[Google Sheets] Successfully appended {len(df)} rows to Google Sheet: {sheet.title}")
        return True

    except Exception as exc:
        print(f"[Google Sheets Error] Could not update Google Sheet: {exc}")
        return False
