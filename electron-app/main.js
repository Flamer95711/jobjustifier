const electron = require("electron");
const path = require("path");
const fs = require("fs");
const { spawn } = require("child_process");
const ExcelJS = require("exceljs");

// If executed with plain 'node main.js' or 'nodemon main.js', auto-spawn electron binary
if (typeof electron === "string" || !electron.app) {
  console.log("Launching via Electron binary...");
  const child = spawn(electron, [__dirname, "--no-sandbox"], { stdio: "inherit" });
  child.on("close", (code) => process.exit(code || 0));
  return;
}

const { app, BrowserWindow, BrowserView, ipcMain, dialog } = electron;

if (app && app.commandLine) {
  app.commandLine.appendSwitch("disable-gpu-shader-disk-cache");
  app.commandLine.appendSwitch("disable-gpu");
}

const orchestrator = require("./scraper/orchestrator");
const { scoreRecords } = require("./python/bridge");

const PROJECT_ROOT = path.resolve(__dirname, "..");
const SCRAPED_DIR = path.join(PROJECT_ROOT, "data", "scraped");

const SIDEBAR_WIDTH = 320;
const RIGHT_PANEL_WIDTH = 400;
const TOPBAR_HEIGHT = 48;
const JOB_PROFILE_MAX_CHARS = 300;

function truncateText(text, maxChars = JOB_PROFILE_MAX_CHARS) {
  if (!text) return "";
  const collapsed = String(text).replace(/\s+/g, " ").trim();
  if (collapsed.length <= maxChars) return collapsed;
  return collapsed.slice(0, maxChars).trimEnd() + "…";
}

function riskLevel(prob) {
  if (prob === null || prob === undefined) return "Unscored";
  if (prob >= 0.65) return "High";
  if (prob >= 0.3) return "Medium";
  return "Low";
}

let mainWindow = null;
let publicView = null;
let authView = null;
let currentMode = "public";
let stopRequested = false;
let scrapeInFlight = false;

function activeView() {
  return currentMode === "auth" ? authView : publicView;
}

function layoutViews() {
  if (!mainWindow) return;
  const [width, height] = mainWindow.getContentSize();
  const bounds = {
    x: SIDEBAR_WIDTH,
    y: TOPBAR_HEIGHT,
    width: Math.max(0, width - SIDEBAR_WIDTH - RIGHT_PANEL_WIDTH),
    height: Math.max(0, height - TOPBAR_HEIGHT),
  };
  if (publicView) publicView.setBounds(bounds);
  if (authView) authView.setBounds(bounds);
}

function sendViewUrl(view) {
  if (mainWindow && !mainWindow.isDestroyed() && view === activeView()) {
    mainWindow.webContents.send("view:url", view.webContents.getURL());
  }
}

function wireViewEvents(view) {
  view.webContents.on("did-navigate", () => sendViewUrl(view));
  view.webContents.on("did-navigate-in-page", () => sendViewUrl(view));
}

function attachActiveView() {
  if (!mainWindow) return;
  for (const view of [publicView, authView]) {
    if (view && mainWindow.getBrowserViews().includes(view)) {
      mainWindow.removeBrowserView(view);
    }
  }
  const view = activeView();
  if (view) {
    mainWindow.addBrowserView(view);
    layoutViews();
    sendViewUrl(view);
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 940,
    minWidth: 1000,
    minHeight: 640,
    title: "LinkedIn Job Scraper — Live View",
    backgroundColor: "#1e1e1e",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));

  const placeholderPath = path.join(__dirname, "renderer", "placeholder.html");
  publicView = new BrowserView({
    webPreferences: { partition: "linkedin-public", contextIsolation: true },
  });
  authView = new BrowserView({
    webPreferences: { partition: "persist:linkedin-auth", contextIsolation: true },
  });
  publicView.setBackgroundColor("#1e1e1e");
  authView.setBackgroundColor("#1e1e1e");
  publicView.webContents.loadFile(placeholderPath);
  authView.webContents.loadFile(placeholderPath);
  wireViewEvents(publicView);
  wireViewEvents(authView);

  attachActiveView();

  mainWindow.on("resize", layoutViews);
  mainWindow.on("closed", () => {
    mainWindow = null;
    publicView = null;
    authView = null;
  });
}

app.whenReady().then(createWindow);

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

function sendProgress(event) {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send("scrape:progress", event);
  }
}

ipcMain.handle("ui:set-mode", async (_evt, mode) => {
  currentMode = mode === "auth" ? "auth" : "public";
  attachActiveView();
  return { mode: currentMode, loggedIn: currentMode === "auth" ? orchestrator.currentIsLoggedIn(authView) : null };
});

ipcMain.handle("ui:open-login", async () => {
  if (!authView) return { ok: false };
  await orchestrator.openLogin(authView);
  return { ok: true, url: authView.webContents.getURL() };
});

ipcMain.handle("ui:check-login", async () => {
  if (!authView) return { loggedIn: false };
  return { loggedIn: orchestrator.currentIsLoggedIn(authView), url: authView.webContents.getURL() };
});

ipcMain.on("ui:start-scrape", async (_evt, payload) => {
  if (scrapeInFlight) {
    sendProgress({ type: "log", message: "A scrape is already running." });
    return;
  }
  const { mode, keywords, location, experienceLevel, experienceYears, postedWithinHours, maxJobs } = payload;
  const view = mode === "auth" ? authView : publicView;
  if (!view) return;

  if (mode === "auth" && !orchestrator.currentIsLoggedIn(view)) {
    sendProgress({ type: "error", message: "Not logged in. Click 'Open LinkedIn Login', sign in in the live view, then start the scrape." });
    return;
  }

  stopRequested = false;
  scrapeInFlight = true;
  sendProgress({ type: "status", status: "running" });

  try {
    const records = await orchestrator.runScrape(
      view,
      {
        mode,
        keywords,
        location,
        experienceLevel,
        experienceYears,
        postedWithinHours,
        maxJobs,
        delayRange: mode === "auth" ? [3000, 6000] : [1500, 3500],
      },
      { onProgress: sendProgress, shouldStop: () => stopRequested }
    );

    if (records.length === 0) {
      sendProgress({ type: "status", status: "idle" });
      sendProgress({ type: "log", message: "No jobs scraped." });
      scrapeInFlight = false;
      return;
    }

    sendProgress({ type: "log", message: `Scoring ${records.length} postings with the trained model ...` });
    let scored;
    try {
      scored = await scoreRecords(records);
    } catch (err) {
      sendProgress({ type: "error", message: `Scoring failed: ${err.message}` });
      scored = records.map((r) => ({ ...r, fraud_probability: null, fraudulent: null }));
    }

    scored.sort((a, b) => (b.fraud_probability || 0) - (a.fraud_probability || 0));
    sendProgress({ type: "done", records: scored, keywords });
  } catch (err) {
    sendProgress({ type: "error", message: err.message });
  } finally {
    sendProgress({ type: "status", status: "idle" });
    scrapeInFlight = false;
  }
});

function loadEnvFile() {
  const envPath = path.join(PROJECT_ROOT, ".env");
  if (fs.existsSync(envPath)) {
    const content = fs.readFileSync(envPath, "utf8");
    for (const line of content.split("\n")) {
      const match = line.match(/^\s*([\w.-]+)\s*=\s*(.*)?\s*$/);
      if (match) {
        const key = match[1];
        let val = (match[2] || "").trim();
        if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
          val = val.slice(1, -1);
        }
        if (!process.env[key]) process.env[key] = val;
      }
    }
  }
}

loadEnvFile();

ipcMain.handle("ui:export-excel", async (_evt, { records, keywords }) => {
  if (!records || records.length === 0) {
    throw new Error("No records to export.");
  }

  const sheetUrl = process.env.GOOGLE_SHEET_URL || "https://script.google.com/macros/s/AKfycbwGGwGhRbaPeiyxB9TldAkF3Z8OS3OWk_kh5zE5gdKJG4EzpCzf4oZqxjs27xkoOeCM/exec";

  if (sheetUrl && sheetUrl.startsWith("http")) {
    try {
      const headers = ["Job Role", "Company Name", "Apply Link", "Job Profile", "Required Experience", "Risk Level", "Fraud %"];
      const rows = records.map((record) => [
        record.title || "",
        record.company_name || "",
        record.source_url || "",
        truncateText(record.description),
        record.required_experience || "",
        riskLevel(record.fraud_probability),
        record.fraud_probability != null ? (record.fraud_probability * 100).toFixed(1) : "0.0",
      ]);

      const response = await fetch(sheetUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ headers, rows }),
      });

      if (response.ok) {
        return { ok: true, path: `Google Sheet (${records.length} rows updated)` };
      }
    } catch (err) {
      console.error("Google Sheet export failed, writing Excel fallback:", err);
    }
  }

  fs.mkdirSync(SCRAPED_DIR, { recursive: true });
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-");
  const safeKeywords = (keywords || "jobs").replace(/\s+/g, "_").slice(0, 30);
  const defaultPath = path.join(SCRAPED_DIR, `scored_${safeKeywords}_${timestamp}.xlsx`);

  const { canceled, filePath } = await dialog.showSaveDialog(mainWindow, {
    title: "Export scraped + scored jobs",
    defaultPath,
    filters: [{ name: "Excel Workbook", extensions: ["xlsx"] }],
  });
  if (canceled || !filePath) return { ok: false };

  const workbook = new ExcelJS.Workbook();
  const sheet = workbook.addWorksheet("Jobs");
  sheet.columns = [
    { header: "Job Role", key: "jobRole", width: 32 },
    { header: "Company Name", key: "companyName", width: 24 },
    { header: "Apply Link", key: "applyLink", width: 38 },
    { header: "Job Profile", key: "jobProfile", width: 60 },
    { header: "Required Experience", key: "requiredExperience", width: 20 },
    { header: "Risk Level", key: "riskLevel", width: 12 },
    { header: "Fraud %", key: "fraudPct", width: 10 },
  ];
  sheet.getRow(1).font = { bold: true };
  sheet.getColumn("jobProfile").alignment = { wrapText: true, vertical: "top" };

  for (const record of records) {
    const row = sheet.addRow({
      jobRole: record.title || "",
      companyName: record.company_name || "",
      jobProfile: truncateText(record.description),
      requiredExperience: record.required_experience || "",
      riskLevel: riskLevel(record.fraud_probability),
      fraudPct: record.fraud_probability != null ? Math.round(record.fraud_probability * 1000) / 10 : null,
    });
    const applyCell = row.getCell("applyLink");
    if (record.source_url) {
      applyCell.value = { text: record.source_url, hyperlink: record.source_url };
      applyCell.font = { color: { argb: "FF3860F2" }, underline: true };
    }
  }

  await workbook.xlsx.writeFile(filePath);
  return { ok: true, path: filePath };
});
