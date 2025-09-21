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
  assetsStatus: document.querySelector("#assets-status"),
  assetsGrid: document.querySelector("#assets-grid"),
  deleteJob: document.querySelector("#delete-job"),
  lightbox: document.querySelector("#lightbox"),
  lightboxImage: document.querySelector("#lightbox-image"),
  lightboxText: document.querySelector("#lightbox-text"),
  lightboxCaption: document.querySelector("#lightbox-caption"),
  lightboxClose: document.querySelector("#lightbox-close"),
  jobRowTemplate: document.querySelector("#job-row-template"),
};

const currencyFmt = new Intl.NumberFormat(undefined, {
  style: "currency",
  currency: "RSD",
  maximumFractionDigits: 0,
});

let token = null;
const assetPreviewCache = new Map();
let currentJobId = null;

if (elements.deleteJob) {
  elements.deleteJob.disabled = true;
}

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

function clearAssetPreviews() {
  assetPreviewCache.forEach((entry) => {
    if (entry && entry.url) {
      URL.revokeObjectURL(entry.url);
    }
  });
  assetPreviewCache.clear();
  if (elements.assetsGrid) {
    elements.assetsGrid.replaceChildren();
  }
  closeLightbox(true);
}

function formatBytes(size) {
  if (!Number.isFinite(size) || size <= 0) {
    return "";
  }
  const units = ["B", "KB", "MB", "GB"];
  let value = size;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const decimals = value >= 10 || unitIndex === 0 ? 0 : 1;
  return `${value.toFixed(decimals)} ${units[unitIndex]}`;
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
  clearAssetPreviews();
  setStatus(elements.assetsStatus, "");
  currentJobId = null;
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
    currentJobId = jobId;
    if (elements.deleteJob) {
      elements.deleteJob.disabled = false;
    }
    await loadAssets(jobId);
  } catch (error) {
    console.error(error);
    setStatus(elements.summaryStatus, error.message || "Failed to load summary", { error: true });
    clearAssetPreviews();
    setStatus(elements.assetsStatus, "", { error: false });
    currentJobId = null;
    if (elements.deleteJob) {
      elements.deleteJob.disabled = true;
    }
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

async function loadAssets(jobId) {
  setStatus(elements.assetsStatus, "Loading assets…");
  elements.assetsGrid.replaceChildren();
  try {
    const response = await authFetch(`/statements/${jobId}/assets`);
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || response.statusText);
    }
    const payload = await response.json();
    const assets = payload.assets || [];
    await renderAssets(jobId, assets);
  } catch (error) {
    console.error(error);
    setStatus(elements.assetsStatus, error.message || "Failed to load assets", { error: true });
  }
}

async function renderAssets(jobId, assets) {
  clearAssetPreviews();
  if (elements.assetsGrid) {
    elements.assetsGrid.replaceChildren();
  }
  if (!assets.length) {
    setStatus(elements.assetsStatus, "No report assets available yet.");
    return;
  }

  const fragment = document.createDocumentFragment();
  const previewPromises = [];

  assets.forEach((asset) => {
    const card = document.createElement("div");
    card.className = "asset-card";

    const header = document.createElement("header");
    const title = document.createElement("strong");
    title.textContent = asset.name;
    const meta = document.createElement("div");
    meta.className = "asset-meta";

    const typeLabel = formatAssetType(asset);
    if (typeLabel) {
      const badge = createBadge(typeLabel, "type");
      if (badge) meta.appendChild(badge);
    }

    const sizeLabel = formatBytes(asset.size);
    if (sizeLabel) {
      const badge = createBadge(sizeLabel, "size");
      if (badge) meta.appendChild(badge);
    }

    header.append(title, meta);
    card.appendChild(header);

    const actions = document.createElement("div");
    actions.className = "asset-actions";

    if (isImageAsset(asset)) {
      const img = document.createElement("img");
      img.alt = asset.name;
      img.loading = "lazy";
      card.appendChild(img);
      const previewPromise = ensureAssetUrl(jobId, asset.name)
        .then((url) => {
          img.src = url;
        })
        .catch((error) => {
          console.error("Failed to render asset", asset.name, error);
          img.replaceWith(document.createTextNode("Preview unavailable"));
        });
      previewPromises.push(previewPromise);
      img.addEventListener("click", () => openImagePreview(jobId, asset.name));
      actions.appendChild(createActionButton("Open", () => openImagePreview(jobId, asset.name)));
    } else if (isPreviewableTextAsset(asset)) {
      const preview = document.createElement("pre");
      preview.className = "asset-preview";
      preview.textContent = "Loading preview…";
      card.appendChild(preview);
      const previewPromise = ensureAssetText(jobId, asset.name)
        .then((entry) => {
          preview.textContent = entry.snippet;
        })
        .catch((error) => {
          console.error("Failed to render asset", asset.name, error);
          preview.textContent = `Preview unavailable: ${error.message}`;
        });
      previewPromises.push(previewPromise);
      actions.appendChild(createActionButton("Expand", () => openTextPreview(jobId, asset.name)));
    }

    actions.appendChild(createActionButton("Download", () => downloadAsset(jobId, asset.name)));
    card.appendChild(actions);
    fragment.appendChild(card);
  });

  elements.assetsGrid.appendChild(fragment);
  if (previewPromises.length) {
    await Promise.allSettled(previewPromises);
  }
  setStatus(elements.assetsStatus, `${assets.length} asset(s) ready.`);
}

function getAssetKey(jobId, assetName) {
  return `${jobId}:${assetName}`;
}

function isImageAsset(asset) {
  return Boolean(asset?.content_type && asset.content_type.startsWith("image/"));
}

function isPreviewableTextAsset(asset) {
  const contentType = asset?.content_type?.toLowerCase() ?? "";
  const name = asset?.name?.toLowerCase() ?? "";
  if (contentType.includes("json") || contentType.includes("csv")) return true;
  return name.endsWith(".json") || name.endsWith(".csv");
}

function getFileExtension(name) {
  if (!name) return "";
  const parts = name.split(".");
  return parts.length > 1 ? parts.pop().toLowerCase() : "";
}

function formatAssetType(asset) {
  const ext = getFileExtension(asset?.name);
  const type = asset?.content_type?.toLowerCase() ?? "";
  if (type.includes("png")) return "PNG";
  if (type.includes("jpeg")) return "JPG";
  if (type.includes("json")) return "JSON";
  if (type.includes("csv")) return "CSV";
  if (ext) return ext.toUpperCase();
  return type ? type.toUpperCase() : "";
}

function createBadge(label, kind) {
  if (!label) return null;
  const span = document.createElement("span");
  span.className = "asset-badge";
  if (kind) span.dataset.kind = kind;
  span.textContent = label;
  return span;
}

function createActionButton(label, handler, className = "ghost") {
  const button = document.createElement("button");
  button.className = className;
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", handler);
  return button;
}

async function ensureAssetUrl(jobId, assetName) {
  const key = getAssetKey(jobId, assetName);
  const cached = assetPreviewCache.get(key);
  if (cached?.url) return cached.url;
  const blob = await fetchAssetBlob(jobId, assetName);
  const url = URL.createObjectURL(blob);
  const next = { ...(cached || {}), url };
  assetPreviewCache.set(key, next);
  return url;
}

function buildTextPreview(fullText) {
  const lines = fullText.split(/\r?\n/);
  const snippetLines = lines.slice(0, 12);
  let snippet = snippetLines.join("\n");
  if (!snippet.trim()) {
    snippet = fullText.slice(0, 400);
  }
  if (!snippet.trim()) {
    snippet = "(empty file)";
  }
  if (lines.length > snippetLines.length) {
    snippet += `\n… (${lines.length - snippetLines.length} more lines)`;
  }
  const maxChars = 8000;
  let truncated = fullText;
  if (fullText.length > maxChars) {
    truncated = `${fullText.slice(0, maxChars)}\n… [truncated]`;
  }
  return { snippet, fullText: truncated };
}

async function ensureAssetText(jobId, assetName) {
  const key = getAssetKey(jobId, assetName);
  const cached = assetPreviewCache.get(key);
  if (cached?.text) return cached;
  const blob = await fetchAssetBlob(jobId, assetName);
  const fullText = await blob.text();
  const processed = buildTextPreview(fullText);
  const next = { ...(cached || {}), text: processed.fullText, snippet: processed.snippet };
  assetPreviewCache.set(key, next);
  return next;
}

async function openImagePreview(jobId, assetName) {
  try {
    const url = await ensureAssetUrl(jobId, assetName);
    openLightbox({ title: assetName, url });
  } catch (error) {
    console.error(error);
    setStatus(elements.summaryStatus, error.message || "Failed to open image", { error: true });
  }
}

async function openTextPreview(jobId, assetName) {
  try {
    const entry = await ensureAssetText(jobId, assetName);
    openLightbox({ title: assetName, text: entry.text });
  } catch (error) {
    console.error(error);
    setStatus(elements.summaryStatus, error.message || "Failed to open preview", { error: true });
  }
}

const LIGHTBOX_FADE_MS = 200;
const onLightboxKeydown = (event) => {
  if (event.key === "Escape") {
    closeLightbox();
  }
};

function openLightbox({ title, url, text }) {
  if (!elements.lightbox) return;
  if (elements.lightboxImage) {
    if (url) {
      elements.lightboxImage.hidden = false;
      elements.lightboxImage.src = url;
    } else {
      elements.lightboxImage.hidden = true;
      elements.lightboxImage.removeAttribute("src");
    }
  }
  if (elements.lightboxText) {
    if (text) {
      elements.lightboxText.hidden = false;
      elements.lightboxText.textContent = text;
    } else {
      elements.lightboxText.hidden = true;
      elements.lightboxText.textContent = "";
    }
  }
  if (elements.lightboxCaption) {
    elements.lightboxCaption.textContent = title;
  }
  elements.lightbox.hidden = false;
  requestAnimationFrame(() => {
    elements.lightbox.classList.add("visible");
  });
  document.body.style.overflow = "hidden";
  document.addEventListener("keydown", onLightboxKeydown);
}

function closeLightbox(immediate = false) {
  if (!elements.lightbox || elements.lightbox.hidden) return;
  elements.lightbox.classList.remove("visible");
  document.body.style.overflow = "";
  document.removeEventListener("keydown", onLightboxKeydown);

  const finalize = () => {
    if (!elements.lightbox) return;
    elements.lightbox.hidden = true;
    if (elements.lightboxImage) {
      elements.lightboxImage.removeAttribute("src");
      elements.lightboxImage.hidden = true;
    }
    if (elements.lightboxText) {
      elements.lightboxText.textContent = "";
      elements.lightboxText.hidden = true;
    }
    if (elements.lightboxCaption) {
      elements.lightboxCaption.textContent = "";
    }
  };

  if (immediate) {
    finalize();
  } else {
    setTimeout(finalize, LIGHTBOX_FADE_MS);
  }
}
async function fetchAssetBlob(jobId, assetName) {
  const response = await authFetch(`/statements/${jobId}/asset?name=${encodeURIComponent(assetName)}`);
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || response.statusText);
  }
  return response.blob();
}

async function downloadAsset(jobId, assetName) {
  if (!ensureLoggedIn()) return;
  setStatus(elements.assetsStatus, `Downloading ${assetName}…`);
  try {
    const response = await authFetch(`/statements/${jobId}/asset?name=${encodeURIComponent(assetName)}`);
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || response.statusText);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = assetName.split("/").pop() || assetName;
    anchor.click();
    URL.revokeObjectURL(url);
    setStatus(elements.assetsStatus, `Downloaded ${assetName}.`);
  } catch (error) {
    console.error(error);
    setStatus(elements.assetsStatus, error.message || "Download failed", { error: true });
  }
}

async function deleteCurrentJob() {
  if (!ensureLoggedIn()) {
    setStatus(elements.summaryStatus, "Sign in first", { error: true });
    return;
  }
  if (!currentJobId) {
    setStatus(elements.summaryStatus, "No report selected", { error: true });
    return;
  }
  const confirmed = window.confirm("Delete this report and all generated files? This cannot be undone.");
  if (!confirmed) return;

  setStatus(elements.summaryStatus, "Deleting report…");
  try {
    const response = await authFetch(`/statements/${currentJobId}`, { method: "DELETE" });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || response.statusText);
    }
    setStatus(elements.summaryStatus, "Report deleted.");
    clearAssetPreviews();
    setStatus(elements.assetsStatus, "");
    elements.summaryCard.hidden = true;
    elements.summaryJob.textContent = "";
    currentJobId = null;
    if (elements.deleteJob) {
      elements.deleteJob.disabled = true;
    }
    await refreshJobList();
  } catch (error) {
    console.error(error);
    setStatus(elements.summaryStatus, error.message || "Failed to delete report", { error: true });
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
if (elements.deleteJob) {
  elements.deleteJob.addEventListener("click", deleteCurrentJob);
}
if (elements.lightbox) {
  elements.lightbox.addEventListener("click", (event) => {
    if (event.target === elements.lightbox) {
      closeLightbox();
    }
  });
}
if (elements.lightboxClose) {
  elements.lightboxClose.addEventListener("click", () => closeLightbox());
}

restoreFromConfig();
