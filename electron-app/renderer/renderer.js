const state = {
  mode: "public",
  running: false,
  lastRecords: [],
  lastKeywords: "",
};

const els = {
  tabs: document.querySelectorAll(".tab"),
  modeNote: document.getElementById("modeNote"),
  authControls: document.getElementById("authControls"),
  loginBtn: document.getElementById("loginBtn"),
  loginStatus: document.getElementById("loginStatus"),
  form: document.getElementById("scrapeForm"),
  keywords: document.getElementById("keywords"),
  location: document.getElementById("location"),
  experienceLevel: document.getElementById("experienceLevel"),
  experienceYears: document.getElementById("experienceYears"),
  postedWithinHours: document.getElementById("postedWithinHours"),
  maxJobs: document.getElementById("maxJobs"),
  startBtn: document.getElementById("startBtn"),
  stopBtn: document.getElementById("stopBtn"),
  liveBadge: document.getElementById("liveBadge"),
  viewUrl: document.getElementById("viewUrl"),
  log: document.getElementById("log"),
  exportBtn: document.getElementById("exportBtn"),
  resultCount: document.getElementById("resultCount"),
  resultsBody: document.querySelector("#resultsTable tbody"),
};

const MODE_NOTES = {
  public:
    "Scrapes LinkedIn's logged-out job search pages. Lower risk, still against LinkedIn's ToS — keep volume low.",
  auth:
    "Uses your own logged-in LinkedIn session in the panel on the right. Log in there manually, then start the scrape. Higher risk to your account — keep volume low.",
};

function logLine(message, kind = "info") {
  if (els.log.querySelector(".log-empty")) els.log.innerHTML = "";
  const line = document.createElement("div");
  line.className = `log-line kind-${kind}`;
  const time = new Date().toLocaleTimeString();
  line.innerHTML = `<span class="log-time">${time}</span>${escapeHtml(message)}`;
  els.log.appendChild(line);
  els.log.scrollTop = els.log.scrollHeight;
}

function setRunning(running) {
  state.running = running;
  els.startBtn.disabled = running;
  els.stopBtn.disabled = !running;
  els.liveBadge.classList.toggle("running", running);
  els.liveBadge.innerHTML = running ? '<span class="dot"></span>Live' : '<span class="dot"></span>Idle';
}

async function switchMode(mode) {
  state.mode = mode;
  els.tabs.forEach((t) => t.classList.toggle("active", t.dataset.mode === mode));
  els.modeNote.textContent = MODE_NOTES[mode];
  els.authControls.classList.toggle("hidden", mode !== "auth");
  const result = await window.scrapeApi.setMode(mode);
  if (mode === "auth") updateLoginStatus(result.loggedIn);
}

function updateLoginStatus(loggedIn) {
  els.loginStatus.classList.remove("ok", "no", "unknown");
  if (loggedIn === true) {
    els.loginStatus.classList.add("ok");
    els.loginStatus.innerHTML = '<span class="dot"></span>Logged in';
  } else if (loggedIn === false) {
    els.loginStatus.classList.add("no");
    els.loginStatus.innerHTML = '<span class="dot"></span>Not logged in';
  } else {
    els.loginStatus.classList.add("unknown");
    els.loginStatus.innerHTML = '<span class="dot"></span>Login status unknown';
  }
}

function formatUrl(url) {
  if (!url || url.startsWith("file://")) return "Not started yet";
  return url;
}

els.tabs.forEach((tab) => {
  tab.addEventListener("click", () => switchMode(tab.dataset.mode));
});

els.loginBtn.addEventListener("click", async () => {
  logLine("Opening LinkedIn login in the live view — sign in manually over there.");
  await window.scrapeApi.openLogin();
  setTimeout(async () => {
    const { loggedIn } = await window.scrapeApi.checkLogin();
    updateLoginStatus(loggedIn);
  }, 4000);
});

els.form.addEventListener("submit", (evt) => {
  evt.preventDefault();
  const keywords = els.keywords.value.trim();
  if (!keywords) return;
  const location = els.location.value.trim();
  const experienceLevel = els.experienceLevel.value;
  const experienceYears = els.experienceYears.value ? Number(els.experienceYears.value) : null;
  const postedWithinHours = els.postedWithinHours.value ? Number(els.postedWithinHours.value) : null;
  const maxJobs = Math.max(1, Math.min(100, Number(els.maxJobs.value) || 15));

  state.lastKeywords = keywords;
  els.resultsBody.innerHTML = '<tr class="empty-row"><td colspan="3">Scraping in progress …</td></tr>';
  els.resultCount.textContent = "0";
  els.exportBtn.disabled = true;
  els.log.innerHTML = "";
  setRunning(true);
  const filterBits = [];
  if (experienceLevel) filterBits.push(experienceLevel);
  if (experienceYears) filterBits.push(`${experienceYears}+ yrs`);
  if (postedWithinHours) filterBits.push(`posted within ${postedWithinHours}h`);
  const filterNote = filterBits.length ? ` [${filterBits.join(", ")}]` : "";
  logLine(`Starting ${state.mode} scrape: "${keywords}"${location ? " in " + location : ""}${filterNote} (max ${maxJobs} jobs)`);

  window.scrapeApi.startScrape({ mode: state.mode, keywords, location, experienceLevel, experienceYears, postedWithinHours, maxJobs });
});

els.stopBtn.addEventListener("click", () => {
  logLine("Stopping ...");
  window.scrapeApi.stopScrape();
});

els.exportBtn.addEventListener("click", async () => {
  if (!state.lastRecords.length) return;
  try {
    const result = await window.scrapeApi.exportExcel(state.lastRecords, state.lastKeywords);
    if (result.ok) logLine(`Exported to ${result.path}`, "detail");
  } catch (err) {
    logLine(`Export failed: ${err.message}`, "error");
  }
});

function riskBadge(prob) {
  if (prob === null || prob === undefined) return { label: "Unscored", cls: "unknown" };
  const pct = Math.round(prob * 100);
  if (prob >= 0.65) return { label: `High ${pct}%`, cls: "high" };
  if (prob >= 0.3) return { label: `Medium ${pct}%`, cls: "med" };
  return { label: `Low ${pct}%`, cls: "low" };
}

function renderResults(records) {
  els.resultsBody.innerHTML = "";
  els.resultCount.textContent = String(records.length);
  if (records.length === 0) {
    els.resultsBody.innerHTML = '<tr class="empty-row"><td colspan="3">No results yet — run a scrape to see scored postings here.</td></tr>';
    return;
  }
  for (const rec of records) {
    const tr = document.createElement("tr");
    const badge = riskBadge(rec.fraud_probability);
    tr.innerHTML = `<td>${escapeHtml(rec.title || "—")}</td><td>${escapeHtml(rec.company_name || "—")}</td><td><span class="risk-badge ${badge.cls}">${badge.label}</span></td>`;
    els.resultsBody.appendChild(tr);
  }
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]));
}

window.scrapeApi.onProgress((event) => {
  switch (event.type) {
    case "status":
      setRunning(event.status === "running");
      break;
    case "log":
      logLine(event.message, "info");
      break;
    case "scroll":
      logLine(`Scrolling... found ${event.found}/${event.target} job cards`, "scroll");
      break;
    case "detail":
      logLine(`[${event.index}/${event.total}] ${event.title || "(untitled)"} @ ${event.company_name || "?"}`, "detail");
      break;
    case "done":
      state.lastRecords = event.records;
      state.lastKeywords = event.keywords;
      renderResults(event.records);
      els.exportBtn.disabled = event.records.length === 0;
      logLine(`Done — ${event.records.length} postings scored.`, "detail");
      break;
    case "error":
      logLine(event.message, "error");
      break;
    default:
      break;
  }
});

window.scrapeApi.onViewUrl((url) => {
  els.viewUrl.textContent = formatUrl(url);
  els.viewUrl.title = url || "";
});

switchMode("public");
