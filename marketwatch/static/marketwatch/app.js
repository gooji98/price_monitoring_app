const cards = document.querySelector("#cards");
const symbolFilter = document.querySelector("#symbol-filter");
const statusFilter = document.querySelector("#status-filter");
const fullscreenToggle = document.querySelector("#fullscreen-toggle");

let pollSeconds = Number(document.body.dataset.pollInterval || 5);
let timerId = null;
let latestRows = [];
let draggedSymbol = null;
const orderStorageKey = "price-monitor-card-order";

symbolFilter.addEventListener("input", () => renderCards(latestRows));
statusFilter.addEventListener("change", () => renderCards(latestRows));
fullscreenToggle.addEventListener("click", toggleFullscreen);
document.addEventListener("fullscreenchange", syncFullscreenState);

async function loadSnapshot() {
  clearTimeout(timerId);

  try {
    const response = await fetch("/api/snapshot/", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();

    pollSeconds = Number(data.pollIntervalSeconds || pollSeconds);
    latestRows = data.rows || [];
    renderCards(latestRows);
  } catch (error) {
    cards.innerHTML = `<div class="page-error">Failed to fetch data: ${escapeHtml(error.message)}</div>`;
  } finally {
    scheduleNext(pollSeconds * 1000);
  }
}

function scheduleNext(delay) {
  clearTimeout(timerId);
  timerId = setTimeout(loadSnapshot, delay);
}

function renderCards(rows) {
  const filteredRows = applyFilters(applySavedOrder(rows));
  cards.innerHTML = filteredRows.map((row) => {
    const isError = row.errors && row.errors.length;
    const tone = isError ? "error" : row.status;
    const spreadAbs = row.spreadAbs === null ? "-" : formatNumber(row.spreadAbs);
    const spread = row.spreadPercent === null ? "-" : `${signed(formatPercent(row.spreadPercent))}%`;
    const sourceLabel = row.sourceExchange || "Wallex";
    const referenceLabel = row.referenceExchange || "-";
    const errorText = isError ? `<div class="error-text">${escapeHtml(row.errors.join(" | "))}</div>` : "";
    const normalColor = row.normalColor || "green";

    return `
      <article class="price-card ${tone} normal-${normalColor}" draggable="true" data-symbol="${escapeHtml(row.symbol)}">
        <div class="card-head">
          <h2>${escapeHtml(row.displaySymbol)}</h2>
          <span class="pulse"></span>
        </div>
        <dl>
          <div><dt>${sourceLabel}</dt><dd>${formatNumber(row.wallexPrice)}</dd></div>
          <div><dt>${referenceLabel}</dt><dd>${formatNumber(row.referencePrice)}</dd></div>
          <div><dt>Gap Amount</dt><dd>${spreadAbs}</dd></div>
          <div><dt>Gap %</dt><dd>${spread}</dd></div>
        </dl>
        <dl class="meta">
          <div><dt>Last sync</dt><dd>${formatTradeTime(row.lastSyncedAt)}</dd></div>
        </dl>
        ${errorText}
      </article>
    `;
  }).join("");

  if (!filteredRows.length) {
    cards.innerHTML = `<div class="page-error">No cards match the selected filters.</div>`;
    return;
  }

  bindDragAndDrop();
}

function applyFilters(rows) {
  const symbolNeedle = symbolFilter.value.trim().toLowerCase();
  const statusValue = statusFilter.value;

  return rows.filter((row) => {
    const rowStatus = row.errors && row.errors.length ? "error" : row.status;
    const matchesSymbol =
      !symbolNeedle ||
      String(row.symbol || "").toLowerCase().includes(symbolNeedle) ||
      String(row.displaySymbol || "").toLowerCase().includes(symbolNeedle);
    const matchesStatus = statusValue === "all" || rowStatus === statusValue;
    return matchesSymbol && matchesStatus;
  });
}

function applySavedOrder(rows) {
  const savedOrder = readSavedOrder();
  if (!savedOrder.length) return rows;

  const orderIndex = new Map(savedOrder.map((symbol, index) => [symbol, index]));
  return [...rows].sort((a, b) => {
    const aIndex = orderIndex.has(a.symbol) ? orderIndex.get(a.symbol) : Number.MAX_SAFE_INTEGER;
    const bIndex = orderIndex.has(b.symbol) ? orderIndex.get(b.symbol) : Number.MAX_SAFE_INTEGER;
    return aIndex - bIndex;
  });
}

function bindDragAndDrop() {
  cards.querySelectorAll(".price-card").forEach((card) => {
    card.addEventListener("dragstart", () => {
      draggedSymbol = card.dataset.symbol;
      card.classList.add("dragging");
    });
    card.addEventListener("dragend", () => {
      draggedSymbol = null;
      card.classList.remove("dragging");
      saveVisibleOrder();
    });
    card.addEventListener("dragover", (event) => {
      event.preventDefault();
      const draggedCard = cards.querySelector(".dragging");
      if (!draggedCard || draggedCard === card) return;

      const rect = card.getBoundingClientRect();
      const shouldPlaceAfter = event.clientY > rect.top + rect.height / 2;
      cards.insertBefore(draggedCard, shouldPlaceAfter ? card.nextSibling : card);
    });
  });
}

function saveVisibleOrder() {
  const visibleOrder = [...cards.querySelectorAll(".price-card")].map((card) => card.dataset.symbol);
  const savedOrder = readSavedOrder().filter((symbol) => !visibleOrder.includes(symbol));
  localStorage.setItem(orderStorageKey, JSON.stringify([...visibleOrder, ...savedOrder]));
}

function readSavedOrder() {
  try {
    const value = JSON.parse(localStorage.getItem(orderStorageKey) || "[]");
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  const fractionDigits = Math.abs(number) >= 100 ? 2 : 6;
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: fractionDigits,
  }).format(number);
}

function formatPercent(value) {
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 2,
  }).format(number);
}

function signed(value) {
  return String(value).startsWith("-") ? value : `+${value}`;
}

function formatClock(value) {
  const date = value ? new Date(value) : new Date();
  return date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function formatTradeTime(value) {
  if (!value) return "-";
  if (/^\d+$/.test(String(value))) {
    const stamp = Number(value);
    return formatClock(stamp < 10_000_000_000 ? stamp * 1000 : stamp);
  }
  return formatClock(value);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function toggleFullscreen() {
  try {
    if (document.fullscreenElement) {
      await document.exitFullscreen();
    } else {
      await document.documentElement.requestFullscreen();
    }
  } catch {
    document.body.classList.toggle("wallboard-mode");
    updateFullscreenButton();
  }
}

function syncFullscreenState() {
  document.body.classList.toggle("wallboard-mode", Boolean(document.fullscreenElement));
  updateFullscreenButton();
}

function updateFullscreenButton() {
  const isFullscreen = document.body.classList.contains("wallboard-mode");
  fullscreenToggle.textContent = isFullscreen ? "Exit" : "Full";
  fullscreenToggle.title = isFullscreen ? "Exit fullscreen" : "Fullscreen";
  fullscreenToggle.setAttribute("aria-label", fullscreenToggle.title);
}

loadSnapshot();
