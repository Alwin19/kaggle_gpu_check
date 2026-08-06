// ── Constants ────────────────────────────────────────────────────────────────
// Arc path: centre (130, 115), radius 90
// M 40 115  A 90 90 0 0 1 220 115
// Arc length = π × 90 ≈ 282.7
const ARC_LENGTH = Math.PI * 90; // 282.7

// localStorage key for the user's GitHub PAT
const TOKEN_KEY = "kaggle_dashboard_gh_token";

// ── State ────────────────────────────────────────────────────────────────────
let cfg = {};          // loaded from config.json
let refreshLocked = false;

// ── DOM refs ─────────────────────────────────────────────────────────────────
const els = {
  arcFill:        () => document.getElementById("arc-fill"),
  gaugePct:       () => document.getElementById("gauge-pct"),
  remainingHours: () => document.getElementById("remaining-hours"),
  totalHours:     () => document.getElementById("total-hours"),
  lastUpdated:    () => document.getElementById("last-updated"),
  banner:         () => document.getElementById("status-banner"),
  refreshBtn:     () => document.getElementById("refresh-btn"),
  refreshIcon:    () => document.getElementById("refresh-icon"),
  tokenPanel:     () => document.getElementById("token-panel"),
  tokenInput:     () => document.getElementById("gh-token-input"),
  clearTokenBtn:  () => document.getElementById("clear-token-btn"),
};

// ── Startup ───────────────────────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", async () => {
  await loadConfig();
  await loadStatus();
  updateClearTokenVisibility();
});

// ── Config ────────────────────────────────────────────────────────────────────
async function loadConfig() {
  try {
    const resp = await fetch("config.json?_=" + Date.now());
    cfg = await resp.json();
  } catch {
    // Non-fatal — Refresh button will still show the token panel.
    cfg = {};
  }
}

// ── Status ────────────────────────────────────────────────────────────────────
async function loadStatus() {
  try {
    const resp = await fetch("status.json?_=" + Date.now());
    const data = await resp.json();
    renderStatus(data);
  } catch (err) {
    showBanner("error", "Could not load status.json — make sure GitHub Pages is enabled.");
  }
}

function renderStatus(data) {
  const { status, remaining_hours, total_hours, percentage_remaining, last_updated, error } = data;

  // Last updated timestamp
  if (last_updated) {
    const d = new Date(last_updated);
    els.lastUpdated().textContent = d.toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });
  } else {
    els.lastUpdated().textContent = "never";
  }

  if (status === "error") {
    showBanner("error", error || "Unknown error from fetch_quota.py");
    setGauge(null);
    return;
  }

  if (status === "pending" || remaining_hours === null) {
    showBanner("info", "Data not yet fetched — trigger the workflow in GitHub Actions.");
    setGauge(null);
    return;
  }

  // Clear any banner
  hideBanner();

  // Populate stat cards
  els.remainingHours().textContent =
    remaining_hours !== null ? `${Number(remaining_hours).toFixed(1)} h` : "—";
  els.totalHours().textContent =
    total_hours !== null ? `${Number(total_hours).toFixed(0)} h` : "—";

  setGauge(percentage_remaining);
}

// ── Gauge animation ───────────────────────────────────────────────────────────
function setGauge(pct) {
  const arc   = els.arcFill();
  const label = els.gaugePct();
  const remainEl = els.remainingHours();
  const totalEl  = els.totalHours();

  if (pct === null || pct === undefined) {
    arc.style.strokeDashoffset = ARC_LENGTH;
    arc.style.stroke = "var(--border)";
    label.textContent = "—";
    label.className = "gauge-pct text-muted";
    return;
  }

  const clamped = Math.max(0, Math.min(100, pct));
  const offset  = ARC_LENGTH * (1 - clamped / 100);

  arc.style.strokeDashoffset = offset;

  let colour, cls;
  if (clamped > 60)      { colour = "var(--green)";  cls = "gauge-pct text-green"; }
  else if (clamped > 25) { colour = "var(--yellow)"; cls = "gauge-pct text-yellow"; }
  else                   { colour = "var(--red)";    cls = "gauge-pct text-red"; }

  arc.style.stroke = colour;
  label.textContent = `${Math.round(clamped)}%`;
  label.className = cls;

  // Also colour the remaining stat
  remainEl.className = "stat-value " + cls.split(" ")[1];
}

// ── Banner helpers ────────────────────────────────────────────────────────────
function showBanner(type, msg) {
  const b = els.banner();
  b.textContent = msg;
  b.className = "status-banner " + type;
}

function hideBanner() {
  const b = els.banner();
  b.className = "status-banner";
}

// ── Refresh button ────────────────────────────────────────────────────────────
async function triggerRefresh() {
  if (refreshLocked) return;

  const token = localStorage.getItem(TOKEN_KEY);

  if (!token) {
    // First time — ask for token
    toggleTokenPanel(true);
    return;
  }

  await dispatchWorkflow(token);
}

async function dispatchWorkflow(token) {
  const { repo_owner, repo_name, workflow_id, branch = "main" } = cfg;

  if (!repo_owner || repo_owner === "YOUR_GITHUB_USERNAME" || !repo_name || repo_name === "YOUR_REPO_NAME") {
    showBanner("error",
      "config.json is not configured. " +
      "Replace YOUR_GITHUB_USERNAME and YOUR_REPO_NAME, then re-push."
    );
    return;
  }

  setRefreshLoading(true);
  showBanner("info", "Triggering refresh…");

  try {
    const resp = await fetch(
      `https://api.github.com/repos/${repo_owner}/${repo_name}/actions/workflows/${workflow_id}/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ ref: branch }),
      }
    );

    if (resp.status === 204) {
      showBanner("success", "Workflow triggered! Data will update in ~1–2 minutes. Reload this page then.");
      // Lock button for 90 s to prevent spam
      lockRefreshFor(90_000);
    } else if (resp.status === 401 || resp.status === 403) {
      localStorage.removeItem(TOKEN_KEY);
      updateClearTokenVisibility();
      showBanner("error", "Token rejected (401/403). Enter a new one below.");
      toggleTokenPanel(true);
    } else {
      const body = await resp.text();
      showBanner("error", `GitHub API returned ${resp.status}: ${body.slice(0, 120)}`);
    }
  } catch (err) {
    showBanner("error", `Network error: ${err.message}`);
  } finally {
    setRefreshLoading(false);
  }
}

function lockRefreshFor(ms) {
  refreshLocked = true;
  const btn = els.refreshBtn();
  btn.disabled = true;
  setTimeout(() => {
    refreshLocked = false;
    btn.disabled = false;
  }, ms);
}

function setRefreshLoading(loading) {
  const icon = els.refreshIcon();
  icon.classList.toggle("spinning", loading);
  els.refreshBtn().disabled = loading;
}

// ── Token panel ───────────────────────────────────────────────────────────────
function toggleTokenPanel(show) {
  els.tokenPanel().classList.toggle("visible", show);
  if (show) els.tokenInput().focus();
}

function saveToken() {
  const raw = els.tokenInput().value.trim();
  if (!raw) return;
  localStorage.setItem(TOKEN_KEY, raw);
  els.tokenInput().value = "";
  toggleTokenPanel(false);
  updateClearTokenVisibility();
  dispatchWorkflow(raw);
}

// Allow Enter key in the input box
document.addEventListener("DOMContentLoaded", () => {
  els.tokenInput().addEventListener("keydown", (e) => {
    if (e.key === "Enter") saveToken();
  });
});

function clearSavedToken() {
  localStorage.removeItem(TOKEN_KEY);
  updateClearTokenVisibility();
  showBanner("info", "Saved token cleared.");
}

function updateClearTokenVisibility() {
  const hasToken = !!localStorage.getItem(TOKEN_KEY);
  els.clearTokenBtn().style.display = hasToken ? "inline" : "none";
}
