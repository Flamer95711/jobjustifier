# Job Posting Fraud Detector

Three tools:
1. A classifier trained on the Kaggle "Fake Job Postings" dataset that predicts whether a posting is fraudulent.
2. LinkedIn scrapers (public + authenticated) that fetch live postings and score them with the trained model.
3. An Electron desktop app (`electron-app/`) with a live browser view of the scrape in progress, for both
   the public and authenticated modes — see [4. Live-view Electron app](#4-live-view-electron-app).

## Setup

```bash
pip install -r requirements.txt
```

## 1. Train the model

```bash
python3 src/train.py
```

Trains on `fake-job-posting/job_postings_train.csv` (12,000 labeled rows, ~5% fraudulent),
prints validation metrics, and saves the pipeline to `models/fake_job_classifier.joblib`.

Current validation performance (80/20 held-out split): ROC-AUC ~0.98, recall ~0.86 on the
fraudulent class (catches ~86% of fakes), precision ~0.51 (about half of what it flags is
actually fake — expected given only 5% of postings are fraudulent; tune `--threshold` in
the scoring script to trade off precision/recall).

## 2. Predict on the Kaggle test set

```bash
python3 src/predict.py
```

Writes `data/predictions/submission.csv` (id, fraudulent) and
`data/predictions/test_predictions.csv` (with probabilities, sorted most-suspicious first).

## 3. Scrape LinkedIn + score postings

**Public (no login), low risk:**
```bash
python3 src/score_scraped_jobs.py --mode public --keywords "data analyst" --location "United States" --max-jobs 25
```

**Authenticated (your own account), higher risk — see warnings in `src/scraper/auth_scraper.py`:**
```bash
cp .env.example .env   # fill in LINKEDIN_EMAIL / LINKEDIN_PASSWORD
python3 src/score_scraped_jobs.py --mode auth --keywords "data analyst" --location "United States" --max-jobs 15
```

Both write an Excel workbook to `data/scraped/scored_<keywords>_<timestamp>.xlsx`, sorted most-suspicious
first, with one row per posting and just these columns: Job Role, Company Name, Apply Link (clickable),
Job Profile (description, trimmed to 300 characters so long postings don't blow up the sheet), Required
Experience, Risk Level (Low/Medium/High), and Fraud %.

## 4. Live-view Electron app

`electron-app/` is a desktop GUI with a real, visible browser panel so you can watch the scrape happen —
pages loading, the list scrolling, job detail pages opening — for both modes:

- **Public tab**: navigates the live view to LinkedIn's logged-out job search pages, no login involved.
- **Authenticated tab**: click "Open LinkedIn Login" and sign in *manually* in the live view (your own
  credentials never touch the app's code — this just shows LinkedIn's real login page in an embedded
  browser, same as a normal browser tab). The session persists across app restarts. Once logged in,
  start the scrape from the sidebar.

Under the hood, the same panel you're watching is what gets scraped (via `webContents.executeJavaScript`
reading the DOM) — there's no separate hidden scraper. Extracted postings are sent to the existing trained
model (`src/score_records.py`, spawned as a Python subprocess) for fraud scoring, shown live in a results
table, and can be exported to `.xlsx` via the "Export to Excel" button (uses `exceljs`, no CSV involved) —
same trimmed column set as the CLI: Job Role, Company Name, Apply Link, Job Profile, Required Experience,
Risk Level, Fraud %.

Setup and run:

```bash
cd electron-app
npm install
npm start
```

Notes:
- Requires Node.js and npm. `npm install` downloads the Electron binary from GitHub releases; if your
  network blocks `github.com` (common on corporate/firewalled networks — this happened during development
  here, behind a Sophos-inspected connection), retry with an alternate mirror:
  `ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/" npm install`.
- On Linux, Electron's sandbox binary (`chrome-sandbox`) usually isn't installed setuid-root by npm, so
  `npm start` runs with `--no-sandbox` (see `package.json`). If you'd rather keep Chromium's OS sandbox
  enabled, run `sudo chown root:root node_modules/electron/dist/chrome-sandbox && sudo chmod 4755
  node_modules/electron/dist/chrome-sandbox` once, then remove `--no-sandbox` from the `start` script.
- Same ToS caveats as the CLI scrapers apply (see below) — keep job counts low, keep the built-in delays.

## Important caveats

- **LinkedIn ToS**: both scrapers violate LinkedIn's Terms of Service. The public one scrapes
  logged-out pages (lower risk, still against ToS); the authenticated one logs into your own
  account (higher risk — can get the account restricted). Keep volume low, keep the built-in
  delays, and use for personal/educational purposes only.
- **Fragility**: LinkedIn's HTML/DOM changes often. If scrapers stop finding job cards or
  descriptions, the CSS selectors in `src/scraper/public_scraper.py` / `auth_scraper.py` likely
  need updating.
- **Model scope**: the classifier was trained on 2014-era Indeed/Kaggle postings. Wording and
  fraud patterns evolve, so treat scores as a triage signal, not ground truth — review anything
  flagged before acting on it.

## Project layout

```
fake-job-posting/          Kaggle train/test/sample_submission CSVs (provided)
src/
  features.py               shared feature engineering + model pipeline definition
  train.py                  trains + saves the model
  predict.py                scores the Kaggle test set (writes .xlsx)
  score_scraped_jobs.py     scrape + score pipeline (entry point for LinkedIn data, CLI, writes .xlsx)
  score_records.py          JSON-in/JSON-out scoring bridge used by the Electron app
  scraper/
    public_scraper.py       no-login scraper (CLI)
    auth_scraper.py         Selenium login-based scraper (CLI)
    schema.py                shared record shape
models/                     saved model (fake_job_classifier.joblib)
data/
  predictions/               Kaggle test set predictions (.xlsx)
  scraped/                   scored LinkedIn scrape outputs (.xlsx)
electron-app/               live-view GUI (public + authenticated), exports .xlsx
  main.js                    window/BrowserView management, IPC, Excel export
  preload.js                 contextBridge API exposed to the renderer
  scraper/orchestrator.js    navigates + scrolls + reads the DOM of the live view
  python/bridge.js           spawns src/score_records.py for fraud scoring
  renderer/                  sidebar UI (tabs, controls, log, results table)
```
