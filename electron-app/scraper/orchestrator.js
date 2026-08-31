// Drives the live BrowserView: navigates it to real LinkedIn pages, scrolls it,
// and reads the DOM to collect job cards + details. The same view the user is
// watching is the one being scraped, so scraping *is* the live view.
//
// Selectors mirror the ones already used by ../../src/scraper/public_scraper.py
// (logged-out "guest" markup) and ../../src/scraper/auth_scraper.py (logged-in
// markup) — LinkedIn's DOM changes over time, so if extraction starts coming
// back empty, these are the first place to check.

// LinkedIn's job search "experience level" filter codes (f_E).
const EXPERIENCE_LEVEL_CODES = {
  internship: "1",
  entry: "2",
  associate: "3",
  "mid-senior": "4",
  director: "5",
  executive: "6",
};

function buildSearchUrl(keywords, location, { experienceLevel, postedWithinHours } = {}) {
  const params = new URLSearchParams({ keywords, location });
  const expCode = EXPERIENCE_LEVEL_CODES[experienceLevel];
  if (expCode) params.set("f_E", expCode);
  const hours = Number(postedWithinHours);
  if (hours > 0) params.set("f_TPR", `r${Math.round(hours * 3600)}`);
  return `https://www.linkedin.com/jobs/search/?${params.toString()}`;
}

const PUBLIC_SEARCH_URL = buildSearchUrl;
const AUTH_SEARCH_URL = buildSearchUrl; // same path; content differs by session
const LOGIN_URL = "https://www.linkedin.com/login";
const PUBLIC_JOB_VIEW_URL = (jobId) => `https://www.linkedin.com/jobs/view/${jobId}/`;
const AUTH_JOB_VIEW_URL = PUBLIC_JOB_VIEW_URL;

const PUBLIC_LIST_EXTRACT_JS = `
(() => {
  const cards = Array.from(document.querySelectorAll('div.base-card, li.jobs-search__results-list > li'));
  return cards.map(card => {
    const urn = card.getAttribute('data-entity-urn') || '';
    let jobId = urn.includes(':') ? urn.split(':').pop() : null;
    const link = card.querySelector('a.base-card__full-link') || card.querySelector('a');
    let sourceUrl = link ? (link.href || '').split('?')[0] : null;
    if (!jobId && sourceUrl) {
      const last = sourceUrl.replace(/\\/$/, '').split('/').pop() || '';
      const digits = last.replace(/\\D/g, '');
      jobId = digits || null;
    }
    if (!jobId) return null;
    const title = card.querySelector('h3.base-search-card__title');
    const company = card.querySelector('h4.base-search-card__subtitle');
    const loc = card.querySelector('span.job-search-card__location');
    const dateEl = card.querySelector('time');
    return {
      job_id: jobId,
      title: title ? title.textContent.trim() : null,
      company_name: company ? company.textContent.trim() : null,
      location: loc ? loc.textContent.trim() : null,
      source_url: sourceUrl || ('https://www.linkedin.com/jobs/view/' + jobId + '/'),
      posted_date: dateEl ? dateEl.getAttribute('datetime') : null,
    };
  }).filter(Boolean);
})()
`;

const PUBLIC_SCROLL_JS = `window.scrollBy(0, 900); true;`;

const PUBLIC_DETAIL_EXTRACT_JS = `
(() => {
  const descEl = document.querySelector('div.show-more-less-html__markup, div.description__text');
  const details = {
    description: descEl ? descEl.textContent.trim() : null,
    employment_type: null,
    required_experience: null,
    function: null,
    industry: null,
  };
  const labelMap = {
    'seniority level': 'required_experience',
    'employment type': 'employment_type',
    'job function': 'function',
    'industries': 'industry',
  };
  document.querySelectorAll('li.description__job-criteria-item').forEach(item => {
    const h = item.querySelector('h3');
    const v = item.querySelector('span');
    if (!h || !v) return;
    const field = labelMap[h.textContent.trim().toLowerCase()];
    if (field) details[field] = v.textContent.trim();
  });
  return details;
})()
`;

const AUTH_LIST_EXTRACT_JS = `
(() => {
  const cards = Array.from(document.querySelectorAll('li[data-occludable-job-id], li.jobs-search-results__list-item'));
  return cards.map(card => {
    let jobId = card.getAttribute('data-occludable-job-id') || card.getAttribute('data-job-id');
    if (jobId && jobId.includes(':')) jobId = jobId.split(':').pop();
    const link = card.querySelector("a[href*='/jobs/view/']");
    if (!jobId && link) {
      const href = link.getAttribute('href') || '';
      const last = href.replace(/\\/$/, '').split('/').pop() || '';
      const digits = last.replace(/\\D/g, '');
      jobId = digits || null;
    }
    if (!jobId) return null;
    const title = card.querySelector('a.job-card-list__title') || link;
    const company = card.querySelector('span.job-card-container__primary-description, .job-card-container__company-name');
    const loc = card.querySelector('li.job-card-container__metadata-item');
    return {
      job_id: jobId,
      title: title ? title.textContent.trim() : null,
      company_name: company ? company.textContent.trim() : null,
      location: loc ? loc.textContent.trim() : null,
      source_url: 'https://www.linkedin.com/jobs/view/' + jobId + '/',
      posted_date: null,
    };
  }).filter(Boolean);
})()
`;

const AUTH_SCROLL_JS = `
(() => {
  const selectors = ['div.jobs-search-results-list', 'div.scaffold-layout__list'];
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el) { el.scrollBy(0, 900); return true; }
  }
  window.scrollBy(0, 900);
  return true;
})()
`;

const AUTH_DETAIL_EXTRACT_JS = `
(() => {
  const descEl = document.querySelector('div.jobs-description__content, div.jobs-box__html-content, article');
  const insightEls = Array.from(document.querySelectorAll('li.job-details-jobs-unified-top-card__job-insight, span.ui-label'));
  const insightText = insightEls.map(el => el.textContent.trim()).filter(Boolean).join(' | ');
  return {
    description: descEl ? descEl.textContent.trim() : null,
    employment_type: insightText || null,
    required_experience: null,
    function: null,
    industry: null,
  };
})()
`;

const EMPTY_JOB_RECORD_FIELDS = [
  "title", "location", "department", "salary_range", "company_profile",
  "description", "requirements", "benefits", "telecommuting", "has_company_logo",
  "has_questions", "employment_type", "required_experience", "required_education",
  "industry", "function", "job_id", "company_name", "source_url", "posted_date", "scraped_at",
];

function emptyRecord() {
  const rec = {};
  for (const f of EMPTY_JOB_RECORD_FIELDS) rec[f] = null;
  return rec;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function randomDelay(minMs, maxMs) {
  return minMs + Math.random() * (maxMs - minMs);
}

function waitForLoad(view, timeoutMs = 20000) {
  return new Promise((resolve) => {
    let done = false;
    const finish = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      view.webContents.removeListener("did-finish-load", finish);
      view.webContents.removeListener("did-fail-load", finish);
      resolve();
    };
    const timer = setTimeout(finish, timeoutMs);
    view.webContents.once("did-finish-load", finish);
    view.webContents.once("did-fail-load", finish);
  });
}

async function navigate(view, url) {
  const loadDone = waitForLoad(view);
  await view.webContents.loadURL(url);
  await loadDone;
}

function openLogin(view) {
  return navigate(view, LOGIN_URL);
}

function currentIsLoggedIn(view) {
  const url = view.webContents.getURL() || "";
  return url.includes("linkedin.com") && !url.includes("/login") && !url.includes("/checkpoint");
}

async function collectJobCards(view, { mode, keywords, location, experienceLevel, experienceYears, postedWithinHours, maxJobs, delayRange, onProgress, shouldStop }) {
  // LinkedIn's search URL has no numeric "years of experience" filter (only the
  // f_E level buckets), so years get folded into the free-text query instead —
  // same as typing "data analyst 3+ years experience" into LinkedIn's own search box.
  const effectiveKeywords = experienceYears > 0 ? `${keywords} ${experienceYears}+ years experience` : keywords;

  const searchUrl = mode === "auth"
    ? AUTH_SEARCH_URL(effectiveKeywords, location, { experienceLevel, postedWithinHours })
    : PUBLIC_SEARCH_URL(effectiveKeywords, location, { experienceLevel, postedWithinHours });
  const listJs = mode === "auth" ? AUTH_LIST_EXTRACT_JS : PUBLIC_LIST_EXTRACT_JS;
  const scrollJs = mode === "auth" ? AUTH_SCROLL_JS : PUBLIC_SCROLL_JS;

  const filterBits = [];
  if (experienceLevel) filterBits.push(experienceLevel);
  if (experienceYears > 0) filterBits.push(`${experienceYears}+ yrs`);
  if (postedWithinHours > 0) filterBits.push(`posted within ${postedWithinHours}h`);
  const filterNote = filterBits.length ? ` [${filterBits.join(", ")}]` : "";
  onProgress({ type: "log", message: `Opening search results for "${effectiveKeywords}"${location ? " in " + location : ""}${filterNote} ...` });
  await navigate(view, searchUrl);
  await sleep(randomDelay(...delayRange));

  const jobs = new Map();
  let stalledRounds = 0;
  while (jobs.size < maxJobs && stalledRounds < 5) {
    if (shouldStop()) {
      onProgress({ type: "log", message: "Stopped by user." });
      break;
    }
    let found = [];
    try {
      found = await view.webContents.executeJavaScript(listJs, true);
    } catch (err) {
      onProgress({ type: "log", message: `Extraction error: ${err.message}` });
    }
    const before = jobs.size;
    for (const job of found) {
      if (jobs.size >= maxJobs) break;
      if (!jobs.has(job.job_id)) jobs.set(job.job_id, job);
    }
    stalledRounds = jobs.size === before ? stalledRounds + 1 : 0;
    onProgress({ type: "scroll", found: jobs.size, target: maxJobs });

    if (jobs.size >= maxJobs) break;
    try {
      await view.webContents.executeJavaScript(scrollJs, true);
    } catch (_) {
      // ignore, page may be mid-navigation
    }
    await sleep(randomDelay(...delayRange));
  }

  return Array.from(jobs.values()).slice(0, maxJobs);
}

async function fetchJobDetails(view, mode, jobId, delayRange) {
  const url = mode === "auth" ? AUTH_JOB_VIEW_URL(jobId) : PUBLIC_JOB_VIEW_URL(jobId);
  await navigate(view, url);
  await sleep(randomDelay(...delayRange));
  const detailJs = mode === "auth" ? AUTH_DETAIL_EXTRACT_JS : PUBLIC_DETAIL_EXTRACT_JS;
  try {
    return await view.webContents.executeJavaScript(detailJs, true);
  } catch (err) {
    return { description: null, employment_type: null, required_experience: null, function: null, industry: null };
  }
}

async function runScrape(view, { mode, keywords, location, experienceLevel, experienceYears, postedWithinHours, maxJobs, delayRange }, { onProgress, shouldStop }) {
  const cards = await collectJobCards(view, { mode, keywords, location, experienceLevel, experienceYears, postedWithinHours, maxJobs, delayRange, onProgress, shouldStop });
  onProgress({ type: "log", message: `Found ${cards.length} job cards. Fetching details ...` });

  const records = [];
  for (let i = 0; i < cards.length; i++) {
    if (shouldStop()) {
      onProgress({ type: "log", message: "Stopped by user." });
      break;
    }
    const card = cards[i];
    const record = emptyRecord();
    Object.assign(record, card);
    const details = await fetchJobDetails(view, mode, card.job_id, delayRange);
    for (const [k, v] of Object.entries(details)) {
      if (v) record[k] = v;
    }
    record.scraped_at = new Date().toISOString();
    records.push(record);
    onProgress({
      type: "detail",
      index: i + 1,
      total: cards.length,
      title: record.title,
      company_name: record.company_name,
      record,
    });
    await sleep(randomDelay(...delayRange));
  }

  return records;
}

module.exports = {
  PUBLIC_SEARCH_URL,
  AUTH_SEARCH_URL,
  LOGIN_URL,
  openLogin,
  navigate,
  currentIsLoggedIn,
  runScrape,
};
