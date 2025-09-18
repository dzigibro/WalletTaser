const STORAGE_KEY = "wallettaser-dashboard";

const elements = {
  baseUrl: document.querySelector("#base-url"),
  username: document.querySelector("#username"),
  password: document.querySelector("#password"),
  authStatus: document.querySelector("#auth-status"),
  settingsForm: document.querySelector("#settings-form"),
  appPanel: document.querySelector("#app-panel"),
  tenantLabel: document.querySelector("#tenant-label"),
  tokenPreview: document.querySelector("#token-preview"),
  logout: document.querySelector("#logout"),
  uploadForm: document.querySelector("#upload-form"),
  uploadStatus: document.querySelector("#upload-status"),
  statementFile: document.querySelector("#statement-file"),
  fxRate: document.querySelector("#fx-rate"),
  jobsTable: document.querySelector("#jobs-table tbody"),
  jobsStatus: document.querySelector("#jobs-status"),
  refreshJobs: document.querySelector("#refresh-jobs"),
  summaryCard: document.querySelector("#summary-card"),
  summaryJob: document.querySelector("#summary-job"),
  summaryContent: document.querySelector("#summary-content"),
  summaryStatus: document.querySelector("#summary-status"),
  jobRowTemplate: document.querySelector("#job-row-template"),
};

const currencyFmt = new Intl.NumberFormat(undefined, {
  style: "currency",
  currency: "RSD",
  maximumFractionDigits: 0,
});

let token = null;

function loadConfig() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    return JSON.parse(raw);
  } catch (error) {
    console.warn("Failed to parse config", error);
    return {};
  }
}

function saveConfig(config) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
}

function setStatus(target, message, { error = false } = {}) {
  if (!target) return;
  target.textContent = message ?? "";
  target.classList.toggle("error", Boolean(error));
}

function toggleApp(active) {
  elements.appPanel.hidden = !active;
}

function summarizeToken(tokenValue) {
  if (!tokenValue) return "";
  return `${tokenValue.slice(0, 6)}…${tokenValue.slice(-4)}`;
}

function currentConfig() {
  return {
    baseUrl: elements.baseUrl.value.trim().replace(/\/$/, ""),
    username: elements.username.value.trim(),
  };
}

async function authFetch(path, options = {}) {
  const { baseUrl } = currentConfig();
  const url = `${baseUrl}${path}`;
  const headers = new Headers(options.headers || {});
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(url, { ...options, headers });
}

function ensureLoggedIn() {
  return Boolean(token);
}

async function login(event) {
  event.preventDefault();
  const baseUrl = elements.baseUrl.value.trim();
  const username = elements.username.value.trim();
  const password = elements.password.value;

  if (!baseUrl || !username || !password) {
    setStatus(elements.authStatus, "Fill in all fields", { error: true });
    return;
  }

  const submitButton = elements.settingsForm.querySelector("button[type='submit']");
  submitButton.disabled = true;
  setStatus(elements.authStatus, "Signing in…");

  try {
    const response = await fetch(`${baseUrl.replace(/\/$/, "")}/auth/token`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ username, password }),
    });

    if (!response.ok) {
      const reason = await response.json().catch(() => ({}));
      throw new Error(reason.detail || response.statusText);
    }

    const payload = await response.json();
    token = payload.access_token;
    setStatus(elements.authStatus, "Authenticated");
    elements.tokenPreview.textContent = summarizeToken(token);
    elements.tenantLabel.textContent = `User: ${username}`;
    toggleApp(true);
    saveConfig({ baseUrl: baseUrl.replace(/\/$/, ""), username, token });
    elements.password.value = "";
    await refreshJobList();
  } catch (error) {
    console.error(error);
    setStatus(elements.authStatus, error.message || "Failed to sign in", { error: true });
    token = null;
    toggleApp(false);
    saveConfig({ baseUrl, username });
  } finally {
    submitButton.disabled = false;
  }
}

function logout() {
  token = null;
  toggleApp(false);
  setStatus(elements.authStatus, "Signed out");
  elements.tokenPreview.textContent = "";
  elements.summaryCard.hidden = true;
  elements.jobsTable.replaceChildren();
  const cfg = currentConfig();
  saveConfig({ ...cfg });
}

function renderJobs(jobs) {
  elements.jobsTable.replaceChildren();
  if (!jobs || jobs.length === 0) {
    setStatus(elements.jobsStatus, "No jobs yet. Upload a statement to get started.");
    return;
  }

  setStatus(elements.jobsStatus, `${jobs.length} job(s) loaded.`);

  jobs.forEach((job) => {
    const row = elements.jobRowTemplate.content.cloneNode(true);
    row.querySelector(".job-id").textContent = job.job_id;
    row.querySelector(".job-status").textContent = job.status;
    row.querySelector(".job-created").textContent = job.created_at
      ? new Date(job.created_at).toLocaleString()
      : "—";
    row.querySelector(".job-fx").textContent = job.fx_rate ? job.fx_rate.toFixed(2) : "—";

    const summaryBtn = row.querySelector(".view-summary");
    summaryBtn.addEventListener("click", () => loadSummary(job.job_id));

    const downloadLink = row.querySelector(".download");
    downloadLink.textContent = "Download";
    downloadLink.addEventListener("click", (event) => {
      event.preventDefault();
      downloadArchive(job.job_id, job.filename);
    });

    elements.jobsTable.appendChild(row);
  });
}

async function refreshJobList() {
  if (!ensureLoggedIn()) return;
  setStatus(elements.jobsStatus, "Loading jobs…");
  try {
    const response = await authFetch(`/statements`);
    if (!response.ok) {
      throw new Error(await response.text());
    }
    const jobs = await response.json();
    renderJobs(jobs);
  } catch (error) {
    console.error(error);
    setStatus(elements.jobsStatus, "Failed to load jobs", { error: true });
  }
}

function createSummaryEntry(label, value) {
  const div = document.createElement("div");
  div.className = "summary-item";
  const heading = document.createElement("h4");
  heading.textContent = label;
  const body = document.createElement("div");
  body.className = "value";
  body.textContent = value;
  div.append(heading, body);
  return div;
}

function describeArray(label, values) {
  const container = document.createElement("div");
  container.className = "summary-item";
  const heading = document.createElement("h4");
  heading.textContent = label;
  const list = document.createElement("div");
  list.className = "value";
  list.textContent = values.join(", ");
  container.append(heading, list);
  return container;
}

async function loadSummary(jobId) {
  if (!ensureLoggedIn()) return;
  elements.summaryCard.hidden = false;
  elements.summaryJob.textContent = jobId;
  setStatus(elements.summaryStatus, "Loading summary…");
  elements.summaryContent.replaceChildren();

  try {
    const response = await authFetch(`/statements/${jobId}/summary`);
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || response.statusText);
    }
    const payload = await response.json();
    const summary = payload.summary;
    renderSummary(summary);
    setStatus(elements.summaryStatus, "Summary loaded.");
  } catch (error) {
    console.error(error);
    setStatus(elements.summaryStatus, error.message || "Failed to load summary", { error: true });
  }
}

function renderSummary(summary) {
  const items = [];
  items.push(createSummaryEntry("Months Observed", summary.months_observed ?? "—"));
  items.push(createSummaryEntry("Avg Income", currencyFmt.format(summary.average_income ?? 0)));
  items.push(createSummaryEntry("Avg Spend", currencyFmt.format(Math.abs(summary.average_spend ?? 0))));
  items.push(createSummaryEntry("Avg Savings", currencyFmt.format(summary.average_savings ?? 0)));
  items.push(createSummaryEntry("Avg Stocks", currencyFmt.format(summary.average_stock_investment ?? 0)));
  items.push(createSummaryEntry("Last Week Spend", currencyFmt.format(summary.last_week_spend ?? 0)));
  items.push(createSummaryEntry("Prior Week Spend", currencyFmt.format(summary.previous_week_spend ?? 0)));
  items.push(createSummaryEntry("Delta Week", currencyFmt.format(summary.delta_week_spend ?? 0)));

  if (Array.isArray(summary.projected_net)) {
    const last = summary.projected_net.at(-1);
    items.push(createSummaryEntry("Projected Net (12 mo)", currencyFmt.format(last ?? 0)));
  }

  if (Array.isArray(summary.projected_savings)) {
    const lastSave = summary.projected_savings.at(-1);
    items.push(createSummaryEntry("Savings (12 mo)", currencyFmt.format(lastSave ?? 0)));
  }

  if (Array.isArray(summary.vampires) && summary.vampires.length > 0) {
    items.push(describeArray("Vampire Vendors", summary.vampires));
  }

  if (summary.fx_rate) {
    items.push(createSummaryEntry("FX Rate", summary.fx_rate.toFixed(2)));
  }

  elements.summaryContent.replaceChildren(...items);
}

async function uploadStatement(event) {
  event.preventDefault();
  if (!ensureLoggedIn()) {
    setStatus(elements.uploadStatus, "Sign in first", { error: true });
    return;
  }

  const file = elements.statementFile.files[0];
  if (!file) {
    setStatus(elements.uploadStatus, "Choose a statement file", { error: true });
    return;
  }

  const formData = new FormData();
  formData.append("file", file);
  const fxValue = elements.fxRate.value.trim();
  if (fxValue) {
    formData.append("fx_rate", fxValue);
  }

  const button = elements.uploadForm.querySelector("button[type='submit']");
  button.disabled = true;
  setStatus(elements.uploadStatus, "Uploading…");

  try {
    const response = await authFetch(`/statements/upload`, {
      method: "POST",
      body: formData,
    });

    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || response.statusText);
    }

    const payload = await response.json();
    setStatus(elements.uploadStatus, `Queued job ${payload.job_id}`);
    elements.statementFile.value = "";
    elements.fxRate.value = "";
    await refreshJobList();
  } catch (error) {
    console.error(error);
    setStatus(elements.uploadStatus, error.message || "Upload failed", { error: true });
  } finally {
    button.disabled = false;
  }
}

async function downloadArchive(jobId, filename) {
  if (!ensureLoggedIn()) return;
  setStatus(elements.jobsStatus, `Downloading ${jobId}…`);
  try {
    const response = await authFetch(`/statements/${jobId}/result`);
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || response.statusText);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename ? `${jobId}-${filename}.zip` : `${jobId}.zip`;
    anchor.click();
    URL.revokeObjectURL(url);
    setStatus(elements.jobsStatus, `Downloaded ${jobId}.`);
  } catch (error) {
    console.error(error);
    setStatus(elements.jobsStatus, error.message || "Download failed", { error: true });
  }
}

function restoreFromConfig() {
  const config = loadConfig();
  if (config.baseUrl) elements.baseUrl.value = config.baseUrl;
  if (config.username) elements.username.value = config.username;
  if (config.token) {
    token = config.token;
    elements.tokenPreview.textContent = summarizeToken(token);
    elements.tenantLabel.textContent = `User: ${config.username || "tenant"}`;
    toggleApp(true);
    refreshJobList();
  }
}

elements.settingsForm.addEventListener("submit", login);
elements.logout.addEventListener("click", logout);
elements.uploadForm.addEventListener("submit", uploadStatement);
elements.refreshJobs.addEventListener("click", refreshJobList);

restoreFromConfig();
