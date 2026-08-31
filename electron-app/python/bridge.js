// Spawns the existing Python model to score scraped records. Keeps the
// trained sklearn pipeline as the single source of truth for fraud scoring
// instead of re-implementing feature engineering in JS.

const { spawn } = require("child_process");
const path = require("path");

const PROJECT_ROOT = path.resolve(__dirname, "..", "..");
const SCORE_SCRIPT = path.join(PROJECT_ROOT, "src", "score_records.py");

function pickPython() {
  return process.env.PYTHON_BIN || "python3";
}

function scoreRecords(records, { threshold = 0.5 } = {}) {
  return new Promise((resolve, reject) => {
    if (!records || records.length === 0) {
      resolve([]);
      return;
    }
    const proc = spawn(pickPython(), [SCORE_SCRIPT, "--threshold", String(threshold)], {
      cwd: PROJECT_ROOT,
    });

    let stdout = "";
    let stderr = "";
    proc.stdout.on("data", (chunk) => (stdout += chunk));
    proc.stderr.on("data", (chunk) => (stderr += chunk));

    proc.on("error", (err) => reject(new Error(`Failed to launch ${pickPython()}: ${err.message}`)));

    proc.on("close", (code) => {
      if (code !== 0) {
        reject(new Error(stderr.trim() || `score_records.py exited with code ${code}`));
        return;
      }
      try {
        const parsed = JSON.parse(stdout);
        if (parsed && parsed.error) {
          reject(new Error(parsed.error));
          return;
        }
        resolve(parsed);
      } catch (err) {
        reject(new Error(`Could not parse scoring output: ${err.message}\n${stdout}`));
      }
    });

    proc.stdin.write(JSON.stringify(records));
    proc.stdin.end();
  });
}

module.exports = { scoreRecords };
