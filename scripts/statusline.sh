#!/usr/bin/env node
// Antigravity CLI Custom Statusline Script
// High-performance, multi-session state tracking with per-conversation auto-reset.

const fs = require("fs");
const path = require("path");
const os = require("os");

const stateFile = path.join(os.homedir(), ".gemini", "antigravity-cli", ".statusline_state.json");

function readStdin() {
  try {
    return fs.readFileSync(0, "utf-8");
  } catch (_) {
    return "{}";
  }
}

const raw = readStdin();
let data = {};
try {
  data = JSON.parse(raw);
} catch (_) {}

let allStates = {};
try {
  if (fs.existsSync(stateFile)) {
    allStates = JSON.parse(fs.readFileSync(stateFile, "utf-8"));
  }
} catch (_) {}

const now = Math.floor(Date.now() / 1000);
const convId = data.conversation_id || "default";
const modelInfo = data.model || {};
const modelName = modelInfo.display_name || modelInfo.id || "Gemini";
const modelId = modelInfo.id || "";

const ctx = data.context_window || {};
const totalIn = Number(ctx.total_input_tokens) || 0;
const totalOut = Number(ctx.total_output_tokens) || 0;
const currentTokens = totalIn + totalOut;
const maxTokens = Number(ctx.context_window_size) || 200000;

// Extract quota info
const quotaData = data.quota || {};
let remainingFraction = null;
let resetSecs = null;

if (typeof quotaData === "object" && quotaData !== null) {
  if ("remaining_fraction" in quotaData || "reset_in_seconds" in quotaData) {
    remainingFraction = quotaData.remaining_fraction;
    resetSecs = quotaData.reset_in_seconds;
  } else if (modelId && quotaData[modelId]) {
    remainingFraction = quotaData[modelId].remaining_fraction;
    resetSecs = quotaData[modelId].reset_in_seconds;
  } else {
    for (const v of Object.values(quotaData)) {
      if (typeof v === "object" && v !== null && ("remaining_fraction" in v || "reset_in_seconds" in v)) {
        remainingFraction = v.remaining_fraction;
        resetSecs = v.reset_in_seconds;
        break;
      }
    }
  }
}

// Get session-specific state
const sessState = allStates[convId] || { baseline_tokens: 0, reset_timestamp: null, last_reset_time: null };

let baselineTokens = Number(sessState.baseline_tokens) || 0;
let savedResetTs = sessState.reset_timestamp ? Number(sessState.reset_timestamp) : null;

// Update target reset timestamp if provided
if (resetSecs !== null && resetSecs !== undefined) {
  const rSec = Number(resetSecs);
  if (rSec > 0) {
    savedResetTs = now + rSec;
    sessState.reset_timestamp = savedResetTs;
  } else if (rSec <= 0) {
    savedResetTs = now - 1;
  }
}

// Check if timer expired
let timerJustExpired = false;
if (savedResetTs !== null && now >= savedResetTs) {
  timerJustExpired = true;
  baselineTokens = currentTokens;
  sessState.baseline_tokens = baselineTokens;
  sessState.last_reset_time = now;
  sessState.reset_timestamp = null;
  savedResetTs = null;
  remainingFraction = 1.0;
}

if (currentTokens < baselineTokens) {
  baselineTokens = 0;
  sessState.baseline_tokens = 0;
}

// Effective session token usage
const effectiveTokens = Math.max(0, currentTokens - baselineTokens);
const effectivePct = maxTokens > 0 ? (effectiveTokens / maxTokens) * 100 : 0;

// Save per-session state
allStates[convId] = sessState;
try {
  fs.mkdirSync(path.dirname(stateFile), { recursive: true });
  fs.writeFileSync(stateFile, JSON.stringify(allStates));
} catch (_) {}

// Format helpers
function fmtK(num) {
  if (num >= 1000000) return (num / 1000000).toFixed(1) + "M";
  if (num >= 1000) return Math.round(num / 1000) + "k";
  return String(num);
}

function makeBar(pct, length = 8, inverse = false) {
  const clamped = Math.max(0, Math.min(100, pct));
  const filled = Math.max(0, Math.min(length, Math.round(length * (clamped / 100))));
  const empty = length - filled;

  let color = "";
  if (inverse) {
    if (clamped >= 50) color = "\x1b[38;2;52;211;153m";
    else if (clamped >= 20) color = "\x1b[38;2;251;191;36m";
    else color = "\x1b[38;2;248;113;113m";
  } else {
    if (clamped < 60) color = "\x1b[38;2;52;211;153m";
    else if (clamped < 85) color = "\x1b[38;2;251;191;36m";
    else color = "\x1b[38;2;248;113;113m";
  }

  const reset = "\x1b[0m";
  const dim = "\x1b[2m";
  return {
    str: color + "█".repeat(filled) + dim + "░".repeat(empty) + reset,
    color,
    reset,
  };
}

// Session Bar
const sBar = makeBar(effectivePct, 8, false);
const tokStr = `${fmtK(effectiveTokens)}/${fmtK(maxTokens)}`;
const sessionStr = `Session: [${sBar.str}] ${sBar.color}${Math.round(effectivePct)}%${sBar.reset} (${tokStr})`;

// Restore indicator
let restoreStr = "";
if (savedResetTs !== null && savedResetTs > now) {
  const diff = savedResetTs - now;
  const hours = Math.floor(diff / 3600);
  const mins = Math.floor((diff % 3600) / 60);
  const d = new Date(savedResetTs * 1000);
  const clock = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;

  let dur = "";
  if (hours > 24) dur = `${Math.floor(hours / 24)}d ${hours % 24}h`;
  else if (hours > 0) dur = `${hours}h ${mins}m`;
  else if (mins > 0) dur = `${mins}m`;
  else dur = `${diff}s`;

  restoreStr = `\x1b[38;2;56;189;248m↻ in ${dur} (@ ${clock})\x1b[0m`;
} else if (timerJustExpired || (sessState.last_reset_time && now - sessState.last_reset_time < 600)) {
  restoreStr = "\x1b[38;2;52;211;153m✓ Quota Restored\x1b[0m";
}

// Weekly Bar
let remPct = remainingFraction !== null && remainingFraction !== undefined ? Number(remainingFraction) * 100 : 95;
if (isNaN(remPct)) remPct = 95;
const wBar = makeBar(remPct, 8, true);
const weeklyStr = `Weekly: [${wBar.str}] ${wBar.color}${Math.round(remPct)}% left${wBar.reset}`;

const bold = "\x1b[1m";
const dim = "\x1b[2m";
const reset = "\x1b[0m";

const parts = [`${bold}⚡ ${modelName}${reset}`, sessionStr];
if (restoreStr) parts.push(restoreStr);
parts.push(weeklyStr);

console.log(parts.join(` ${dim}│${reset} `));
