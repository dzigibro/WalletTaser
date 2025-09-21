const STORAGE_KEY = "wallettaser-dashboard";

const API_PORT = 8000;
const API_BASE_URL = (() => {
  const { protocol, hostname } = window.location;
  if (!hostname || protocol === "file:") {
    return `http://127.0.0.1:${API_PORT}`;
  }
  const safeProtocol = protocol.startsWith("http") ? protocol : "http:";
  return `${safeProtocol}//${hostname}:${API_PORT}`;
})();

const elements = {
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

async function authFetch(path, options = {}) {
  const url = `${API_BASE_URL}${path}`;
  const headers = new Headers(options.headers || {});
  if (token) headers.set("Authorization", `Bearer ${token}`);
  return fetch(url, { ...options, headers });
}

function ensureLoggedIn() {
  return Boolean(token);
}

async function login(event) {
  event.preventDefault();
  const username = elements.username.value.trim();
  const password = elements.password.value;

  if (!username || !password) {
    setStatus(elements.authStatus, "Fill in all fields", { error: true });
    return;
  }

  const submitButton = elements.settingsForm.querySelector("button[type='submit']");
  submitButton.disabled = true;
  setStatus(elements.authStatus, "Signing in…");

  try {
    const response = await fetch(`${API_BASE_URL}/auth/token`, {
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
    saveConfig({ username, token });
    elements.password.value = "";
    await refreshJobList();
  } catch (error) {
    console.error(error);
    setStatus(elements.authStatus, error.message || "Failed to sign in", { error: true });
    token = null;
    toggleApp(false);
    saveConfig({ username });
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
  dismissedVendors.clear();
  saveConfig({ username: elements.username.value.trim() });
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
    if (summaryBtn) {
      summaryBtn.type = "button";
      summaryBtn.addEventListener("click", (event) => {
        event.preventDefault();
        loadSummary(job.job_id);
      });
    }

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

async function loadSummary(jobId) {
  if (!ensureLoggedIn()) return;
  dismissedVendors.clear();
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
    setStatus(elements.assetsStatus, "Loading receipts…");
    await loadAssets(jobId);
    await refreshVendorCoach(jobId, summary);
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

function formatCurrency(value) {
  if (!Number.isFinite(value)) return "—";
  return currencyFmt.format(Math.round(value));
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function computeMonthlySpend(summary) {
  const spend = summary?.monthly_spend ?? Math.abs(summary?.average_spend ?? 0);
  return Number.isFinite(spend) ? spend : 0;
}

function computeMonthlySavings(summary) {
  const savings = summary?.monthly_savings ?? summary?.average_savings ?? 0;
  return Number.isFinite(savings) ? savings : 0;
}

function computeNetFlow(summary) {
  if (typeof summary?.net_flow === "number") {
    return summary.net_flow;
  }
  const income = summary?.average_income ?? 0;
  const stocks = summary?.average_stock_investment ?? 0;
  const savings = computeMonthlySavings(summary);
  const spend = computeMonthlySpend(summary);
  return income + savings + stocks - spend;
}

function computeSavingsRate(summary) {
  if (typeof summary?.savings_rate === "number") {
    return summary.savings_rate;
  }
  const spend = computeMonthlySpend(summary);
  if (spend <= 0) return 1;
  return computeMonthlySavings(summary) / spend;
}

function computeSavingsPercentile(rate) {
  if (!Number.isFinite(rate)) return 95;
  if (rate <= 0) return 12;
  return clamp(Math.round(rate * 120), 15, 97);
}

function formatPercentage(value) {
  if (!Number.isFinite(value)) return "—";
  return `${Math.round(value)}%`;
}

function buildHeroSection(summary) {
  const hero = document.createElement("section");
  hero.className = "hero-grid";

  const monthlySpend = computeMonthlySpend(summary);
  const monthlySavings = computeMonthlySavings(summary);
  const netFlow = computeNetFlow(summary);
  const broke = netFlow < 0;
  const statusCard = createHeroCard({
    label: "Am I broke?",
    headline: broke
      ? `-${formatCurrency(Math.abs(netFlow))}/mo`
      : `+${formatCurrency(netFlow)}/mo`,
    subline: broke
      ? `You're burning ${formatCurrency(monthlySpend)} each month. Plug the leaks below.`
      : `You're stacking ${formatCurrency(monthlySpend)} of spending with cash to spare.`,
    variant: broke ? "negative" : "positive",
  });

  const savingsRate = computeSavingsRate(summary);
  const percentile = computeSavingsPercentile(savingsRate);
  const savingsCard = createHeroCard({
    label: "Monthly win",
    headline: monthlySavings > 0
      ? `${formatCurrency(monthlySavings)} saved`
      : "No savings yet",
    subline: monthlySavings > 0
      ? `You beat ${percentile}% of WalletTaser users this month.`
      : "Let's stash at least coffee money next month.",
    variant: monthlySavings > 0 ? "positive" : "neutral",
  });

  const projectedSavings = Array.isArray(summary?.projected_savings)
    ? summary.projected_savings.at(-1)
    : null;
  const fallbackProjection = monthlySavings * 12;
  const projectionValue = projectedSavings ?? fallbackProjection;
  const monthsAhead = Array.isArray(summary?.projected_savings)
    ? summary.projected_savings.length
    : 12;
  const projectionCard = createHeroCard({
    label: "Future you",
    headline: projectionValue
      ? `${formatCurrency(projectionValue)} potential`
      : "Momentum pending",
    subline: projectionValue
      ? `Keep this pace and you'll hit that in ${monthsAhead} months.`
      : "Add a statement to see your trajectory.",
    variant: projectionValue ? "neutral" : "muted",
  });

  hero.append(statusCard, savingsCard, projectionCard);
  return hero;
}

function createHeroCard({ label, headline, subline, variant = "neutral" }) {
  const card = document.createElement("div");
  card.className = `hero-card ${variant}`.trim();

  const headlineEl = document.createElement("div");
  headlineEl.className = "hero-value";
  headlineEl.textContent = headline;

  const labelEl = document.createElement("span");
  labelEl.className = "hero-label";
  labelEl.textContent = label;

  const subtitleEl = document.createElement("p");
  subtitleEl.className = "hero-subtitle";
  subtitleEl.textContent = subline;

  card.append(labelEl, headlineEl, subtitleEl);
  return card;
}

function buildStatsGrid(summary) {
  const stats = [];
  const monthlySpend = computeMonthlySpend(summary);
  stats.push({
    label: "Monthly burn",
    value: formatCurrency(monthlySpend),
    caption: "Across cards & cash",
    variant: "negative",
  });

  const savingsRate = computeSavingsRate(summary);
  const savingsPercent = clamp(Math.round(savingsRate * 100), -200, 200);
  stats.push({
    label: "Savings rate",
    value: formatPercentage(clamp(savingsPercent, -200, 200)),
    caption: "How much you keep vs. spend",
    variant: savingsPercent >= 50 ? "positive" : savingsPercent <= 0 ? "negative" : "neutral",
  });

  stats.push({
    label: "Last 7 days",
    value: formatCurrency(summary?.last_week_spend ?? 0),
    caption: "Fresh outflow",
    variant: "neutral",
  });

  const delta = summary?.delta_week_spend ?? 0;
  stats.push({
    label: "Week over week",
    value: `${delta >= 0 ? "+" : "-"}${formatCurrency(Math.abs(delta))}`,
    caption: delta >= 0 ? "You spent more than last week" : "You're slowing the leak",
    variant: delta > 0 ? "negative" : delta < 0 ? "positive" : "neutral",
  });

  const totalSpend = summary?.total_spend;
  if (Number.isFinite(totalSpend) && totalSpend > 0) {
    stats.push({
      label: "Total this month",
      value: formatCurrency(totalSpend),
      caption: "All debit outflows",
      variant: "neutral",
    });
  }

  if (!stats.length) return null;

  const grid = document.createElement("section");
  grid.className = "stat-grid";

  stats.forEach((item) => {
    grid.appendChild(createStatCard(item));
  });

  return grid;
}

function createStatCard({ label, value, caption, variant = "neutral" }) {
  const card = document.createElement("div");
  card.className = `stat-card ${variant}`.trim();

  const labelEl = document.createElement("span");
  labelEl.className = "stat-label";
  labelEl.textContent = label;

  const valueEl = document.createElement("div");
  valueEl.className = "stat-value";
  valueEl.textContent = value;

  const captionEl = document.createElement("p");
  captionEl.className = "stat-caption";
  captionEl.textContent = caption;

  card.append(labelEl, valueEl, captionEl);
  return card;
}

function buildNeedsWantsCard(summary) {
  const needs = Number(summary?.needs_spend ?? 0);
  const wants = Number(summary?.wants_spend ?? 0);
  const total = needs + wants;
  if (total <= 0) return null;

  const needsPercent = clamp(Math.round((needs / total) * 100), 0, 100);
  const wantsPercent = clamp(100 - needsPercent, 0, 100);

  const card = document.createElement("section");
  card.className = "needs-card";

  const header = document.createElement("header");
  header.innerHTML = "<h4>Needs vs wants</h4><span>Does your budget match your priorities?</span>";
  card.appendChild(header);

  const track = document.createElement("div");
  track.className = "split-bar";

  const needsFill = document.createElement("div");
  needsFill.className = "split-fill needs";
  needsFill.style.width = `${needsPercent}%`;
  track.appendChild(needsFill);

  const wantsFill = document.createElement("div");
  wantsFill.className = "split-fill wants";
  wantsFill.style.width = `${wantsPercent}%`;
  track.appendChild(wantsFill);

  card.appendChild(track);

  const legend = document.createElement("div");
  legend.className = "needs-legend";

  const needsItem = document.createElement("div");
  needsItem.className = "legend-item";
  needsItem.innerHTML = `<span class="dot needs"></span><strong>${needsPercent}%</strong><span>needs</span>`;

  const wantsItem = document.createElement("div");
  wantsItem.className = "legend-item";
  wantsItem.innerHTML = `<span class="dot wants"></span><strong>${wantsPercent}%</strong><span>wants</span>`;

  legend.append(needsItem, wantsItem);
  card.appendChild(legend);

  return card;
}

function buildClarityCard(summary) {
  const breakdown = Array.isArray(summary?.vampire_breakdown) && summary.vampire_breakdown.length
    ? summary.vampire_breakdown
    : Array.isArray(summary?.vampires)
      ? summary.vampires.map((vendor) => ({ vendor, share: 0, amount: null }))
      : [];

  if (!breakdown.length) return null;

  const card = document.createElement("section");
  card.className = "clarity-card";

  const header = document.createElement("header");
  header.className = "clarity-header";
  header.innerHTML = "<h4>Where your money really went 😈</h4><span>Top leaks to plug next month</span>";
  card.appendChild(header);

  const list = document.createElement("ul");
  list.className = "spend-list";

  breakdown.slice(0, 6).forEach((entry, index) => {
    const item = document.createElement("li");
    item.className = "spend-item";

    const rank = document.createElement("span");
    rank.className = "spend-rank";
    rank.textContent = ["😈", "🔥", "🍔", "☕", "🚕", "🎮"][index] || "•";

    const info = document.createElement("div");
    info.className = "spend-info";

    const name = document.createElement("strong");
    name.textContent = entry.vendor;

    const sharePercent = Number.isFinite(entry.share) ? Math.round(entry.share * 100) : null;
    const shareText = document.createElement("span");
    shareText.className = "spend-share";
    shareText.textContent = sharePercent ? `${sharePercent}% of your spend` : "Sneaky recurring spend";

    const amount = document.createElement("span");
    amount.className = "spend-amount";
    if (Number.isFinite(entry.amount)) {
      amount.textContent = formatCurrency(entry.amount);
    }

    info.append(name, shareText, amount);

    const bar = document.createElement("div");
    bar.className = "spend-bar";
    const barFill = document.createElement("div");
    barFill.className = "spend-bar-fill";
    const width = sharePercent !== null ? clamp(sharePercent, 6, 100) : 20;
    barFill.style.width = `${width}%`;
    bar.appendChild(barFill);

    item.append(rank, info, bar);
    list.appendChild(item);
  });

  card.appendChild(list);
  return card;
}

function renderSummary(summary) {
  elements.summaryContent.replaceChildren();
  const hero = buildHeroSection(summary);
  elements.summaryContent.appendChild(hero);

  const statsGrid = buildStatsGrid(summary);
  if (statsGrid) {
    elements.summaryContent.appendChild(statsGrid);
  }

  const needsCard = buildNeedsWantsCard(summary);
  if (needsCard) {
    elements.summaryContent.appendChild(needsCard);
  }

  const clarityCard = buildClarityCard(summary);
  if (clarityCard) {
    elements.summaryContent.appendChild(clarityCard);
  }

  const tagCard = createTagCoachSkeleton();
  elements.summaryContent.appendChild(tagCard);
}

function createTagCoachSkeleton() {
  const card = document.createElement("section");
  card.id = "tag-coach";
  card.className = "tag-card";

  const header = document.createElement("header");
  header.className = "tag-header";
  header.innerHTML = "<h4>Tag your regulars</h4><span>Tell WalletTaser what counts as a need vs. a want.</span>";
  card.appendChild(header);

  const statusLine = document.createElement("p");
  statusLine.className = "status tag-status";
  statusLine.textContent = "Checking your favourites…";
  card.appendChild(statusLine);

  const body = document.createElement("div");
  body.className = "tag-body";
  body.textContent = "Hang tight while we load your vendors.";
  card.appendChild(body);

  return card;
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
  setStatus(elements.assetsStatus, "Loading receipts…");
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
      actions.appendChild(createActionButton("Open", () => openImagePreview(jobId, asset.name), "primary"));
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
      actions.appendChild(createActionButton("Expand", () => openTextPreview(jobId, asset.name), "primary"));
    }

    actions.appendChild(createActionButton("Download", () => downloadAsset(jobId, asset.name), "ghost"));
    card.appendChild(actions);
    fragment.appendChild(card);
  });

  elements.assetsGrid.appendChild(fragment);
  if (previewPromises.length) {
    await Promise.allSettled(previewPromises);
  }
  const plural = assets.length === 1 ? "receipt" : "receipts";
  setStatus(elements.assetsStatus, `${assets.length} ${plural} ready. Tap to zoom or download.`);
}

async function refreshVendorCoach(jobId, summary) {
  const card = document.querySelector("#tag-coach");
  if (!card) return;
  const statusLine = card.querySelector(".tag-status");
  if (statusLine) {
    statusLine.classList.remove("error");
    statusLine.textContent = "Loading personalised tags…";
  }

  try {
    const query = jobId ? `?job_id=${encodeURIComponent(jobId)}` : "";
    const response = await authFetch(`/vendors${query}`);
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || response.statusText);
    }
    const payload = await response.json();
    const tags = Array.isArray(payload.tags) ? payload.tags : [];
    const rawUntagged = Array.isArray(payload.untagged) ? payload.untagged : [];
    const fallbackUntagged = Array.isArray(summary?.untagged_vendors) ? summary.untagged_vendors : [];
    const merged = [...new Set([...rawUntagged, ...fallbackUntagged])];
    const untagged = merged.filter((vendor) => !tags.some((tag) => tag.vendor === vendor));
    populateTagCoach(card, { tags, untagged }, jobId, summary);
  } catch (error) {
    console.error(error);
    if (statusLine) {
      statusLine.textContent = error.message || "Failed to load tags";
      statusLine.classList.add("error");
    } else {
      card.innerHTML = `<p class="status error">${error.message || "Failed to load tags"}</p>`;
    }
  }
}

function populateTagCoach(card, data, jobId, summary) {
  card.innerHTML = "";

  const header = document.createElement("header");
  header.className = "tag-header";
  header.innerHTML = "<h4>Tag your regulars</h4><span>Needs vs wants guides your future coaching.</span>";
  card.appendChild(header);

  const statusLine = document.createElement("p");
  statusLine.className = "status tag-status";
  card.appendChild(statusLine);

  const body = document.createElement("div");
  body.className = "tag-body";

  const untagged = (data.untagged || []).filter((vendor) => !dismissedVendors.has(vendor));
  if (untagged.length) {
    const list = document.createElement("ul");
    list.className = "untagged-list";
    untagged.slice(0, 6).forEach((vendor) => {
      const item = document.createElement("li");
      item.className = "tag-item";

      const name = document.createElement("strong");
      name.textContent = vendor;

      const actions = document.createElement("div");
      actions.className = "tag-actions";

      const needBtn = createActionButton("Need", () => classifyVendorTag(vendor, "NEEDS", jobId, summary, statusLine), "primary");
      const wantBtn = createActionButton("Want", () => classifyVendorTag(vendor, "WANTS", jobId, summary, statusLine), "primary");
      const skipBtn = createActionButton("Skip", () => skipVendorTag(vendor, item, statusLine), "ghost");

      actions.append(needBtn, wantBtn, skipBtn);
      item.append(name, actions);
      list.appendChild(item);
    });

    body.appendChild(list);
  } else {
    const empty = document.createElement("p");
    empty.className = "tag-empty";
    empty.textContent = "All your frequent vendors are tagged. Nice!";
    body.appendChild(empty);
  }
  statusLine.textContent = untagged.length
    ? "Pick Need or Want to train your budget coach."
    : "Nothing to tag right now.";

  const savedHeader = document.createElement("div");
  savedHeader.className = "tag-subheader";
  savedHeader.textContent = "Saved choices";
  body.appendChild(savedHeader);

  const tags = Array.isArray(data.tags) ? data.tags : [];
  if (tags.length) {
    const pillRow = document.createElement("div");
    pillRow.className = "tag-pill-row";
    tags.sort((a, b) => a.vendor.localeCompare(b.vendor)).forEach((entry) => {
      const pill = document.createElement("div");
      pill.className = "tag-pill";

      const vendorName = document.createElement("strong");
      vendorName.textContent = entry.vendor;

      const classLabel = document.createElement("span");
      classLabel.textContent = entry.classification === "NEEDS" ? "Need" : "Want";

      const deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.className = "pill-delete";
      deleteBtn.textContent = "×";
      deleteBtn.setAttribute("aria-label", `Delete tag for ${entry.vendor}`);
      deleteBtn.addEventListener("click", () => deleteVendorTag(entry.vendor, jobId, summary, statusLine));

      pill.append(vendorName, classLabel, deleteBtn);
      pillRow.appendChild(pill);
    });
    body.appendChild(pillRow);
  } else {
    const none = document.createElement("p");
    none.className = "tag-empty";
    none.textContent = "No custom tags yet. Teach WalletTaser what matters.";
    body.appendChild(none);
  }

  const footer = document.createElement("p");
  footer.className = "tag-footer";
  footer.textContent = "You can delete tags any time. Choices stay on your machine.";
  body.appendChild(footer);

  card.appendChild(body);
}

async function classifyVendorTag(vendor, classification, jobId, summary, statusLine) {
  if (!ensureLoggedIn()) return;
  dismissedVendors.delete(vendor);
  const label = classification === "NEEDS" ? "Need" : "Want";
  if (statusLine) {
    statusLine.classList.remove("error");
    statusLine.textContent = `Saving ${vendor} as ${label}…`;
  }
  try {
    const response = await authFetch(`/vendors`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ vendor, classification }),
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || response.statusText);
    }
    if (Array.isArray(summary?.untagged_vendors)) {
      summary.untagged_vendors = summary.untagged_vendors.filter((name) => name !== vendor);
    }
    if (statusLine) {
      statusLine.textContent = `${vendor} tagged as ${label}.`;
    }
    await refreshVendorCoach(jobId, summary);
  } catch (error) {
    console.error(error);
    if (statusLine) {
      statusLine.textContent = error.message || "Failed to save tag";
      statusLine.classList.add("error");
    }
  }
}

function skipVendorTag(vendor, element, statusLine) {
  dismissedVendors.add(vendor);
  if (element) {
    element.remove();
  }
  if (statusLine) {
    statusLine.classList.remove("error");
    statusLine.textContent = `Okay, we'll ask about ${vendor} later.`;
  }
}

async function deleteVendorTag(vendor, jobId, summary, statusLine) {
  if (!ensureLoggedIn()) return;
  if (statusLine) {
    statusLine.classList.remove("error");
    statusLine.textContent = `Deleting tag for ${vendor}…`;
  }
  try {
    const response = await authFetch(`/vendors/${encodeURIComponent(vendor)}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      const detail = await response.json().catch(() => ({}));
      throw new Error(detail.detail || response.statusText);
    }
    dismissedVendors.delete(vendor);
    if (Array.isArray(summary?.untagged_vendors) && !summary.untagged_vendors.includes(vendor)) {
      summary.untagged_vendors.push(vendor);
    }
    if (statusLine) {
      statusLine.textContent = `${vendor} removed. We'll ask again next time.`;
    }
    await refreshVendorCoach(jobId, summary);
  } catch (error) {
    console.error(error);
    if (statusLine) {
      statusLine.textContent = error.message || "Failed to delete tag";
      statusLine.classList.add("error");
    }
  }
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

function createActionButton(label, handler, ...classes) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  const applied = classes.length ? classes : ["ghost"];
  button.classList.add(...applied);
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
      elements.lightboxImage.removeAttribute("hidden");
      elements.lightboxImage.src = url;
    } else {
      elements.lightboxImage.hidden = true;
      elements.lightboxImage.removeAttribute("src");
    }
  }
  if (elements.lightboxText) {
    if (text) {
      elements.lightboxText.hidden = false;
      elements.lightboxText.removeAttribute("hidden");
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
  elements.lightbox.removeAttribute("hidden");
  elements.lightbox.classList.add("visible");
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
    dismissedVendors.clear();
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
