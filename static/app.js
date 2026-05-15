const state = {
  ready: false,
  defaultStore: "",
  currentItems: [],
};

const el = {
  storeId1: document.getElementById("storeId1"),
  startDate: document.getElementById("startDate"),
  endDate: document.getElementById("endDate"),
  searchBtn: document.getElementById("searchBtn"),
  downloadBtn: document.getElementById("downloadBtn"),
  clearBtn: document.getElementById("clearBtn"),
  message: document.getElementById("message"),
  resultCount: document.getElementById("resultCount"),
  resultBody: document.getElementById("resultBody"),
  // 標籤列印
  labelBtn: document.getElementById("labelBtn"),
  labelPanel: document.getElementById("labelPanel"),
  labelSheet: document.getElementById("labelSheet"),
  labelCount: document.getElementById("labelCount"),
  labelStartPos: document.getElementById("labelStartPos"),
  labelWeekInput: document.getElementById("labelWeekInput"),
  labelBorder: document.getElementById("labelBorder"),
  printBtn: document.getElementById("printBtn"),
  closeLabelBtn: document.getElementById("closeLabelBtn"),
  // 排版調整面板
  layoutToggleBtn: document.getElementById("layoutToggleBtn"),
  layoutPanel: document.getElementById("layoutPanel"),
  lpOffsetX: document.getElementById("lpOffsetX"),
  lpOffsetY: document.getElementById("lpOffsetY"),
  lpLeftPad: document.getElementById("lpLeftPad"),
  lpRightPad: document.getElementById("lpRightPad"),
  lpFirstTop: document.getElementById("lpFirstTop"),
  lpContentTop: document.getElementById("lpContentTop"),
  lpFont1: document.getElementById("lpFont1"),
  lpFont2: document.getElementById("lpFont2"),
  lpWeekFont: document.getElementById("lpWeekFont"),
  lpWeekTop: document.getElementById("lpWeekTop"),
  lpWeekRight: document.getElementById("lpWeekRight"),
  lpResetBtn: document.getElementById("lpResetBtn"),
  labelPrintArea: document.getElementById("labelPrintArea"),
  // 905 浮水印
  lpWmSize: document.getElementById("lpWmSize"),
  lpWmOpacity: document.getElementById("lpWmOpacity"),
  lpWmX: document.getElementById("lpWmX"),
  lpWmY: document.getElementById("lpWmY"),
};

const FIXED_HINT = "固定條件：調撥入庫 INVTRNIN｜來源倉 SA099 總公司倉｜原廠 APL 主機（類別1 含 1003/1001、類別2 = 2001、類別3 = 3001）";

function pad(value) {
  return String(value).padStart(2, "0");
}

function todayInput() {
  const d = new Date();
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {"Content-Type": "application/json", ...(options.headers || {})},
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

function setMessage(message, kind = "info") {
  el.message.textContent = message || FIXED_HINT;
  el.message.classList.toggle("error", kind === "error");
}

const ALLOWED_STORES = ["SA004", "SA068"];

async function loadStores() {
  const payload = await api("/api/stores");
  el.storeId1.innerHTML = `<option value="">全部倉</option>` + (payload.items || [])
    .filter((item) => ALLOWED_STORES.includes(item.storeId))
    .map((item) => `<option value="${escapeHtml(item.storeId)}">${escapeHtml(item.storeId)} ${escapeHtml(item.name)}</option>`)
    .join("");
  state.defaultStore = payload.defaultStore || "SA004";
  el.storeId1.value = state.defaultStore;
  state.ready = true;
}

function collectQuery() {
  return {
    storeId1: el.storeId1.value,
    startDate: el.startDate.value,
    endDate: el.endDate.value,
  };
}

async function searchPurchase() {
  setMessage("查詢中...");
  el.searchBtn.disabled = true;
  clearResults("查詢中...");
  try {
    const payload = await api("/api/purchase", {
      method: "POST",
      body: JSON.stringify(collectQuery()),
    });
    renderResults(payload);
  } catch (error) {
    setMessage(error.message, "error");
    clearResults("查詢失敗。");
  } finally {
    el.searchBtn.disabled = false;
  }
}

function renderResults(payload) {
  el.resultCount.textContent = `${payload.rowCount} 筆`;
  setMessage(payload.rowCount >= payload.limit ? `只顯示前 ${payload.limit} 筆，請縮小日期範圍。` : "查詢完成。");
  if (!payload.items.length) {
    state.currentItems = [];
    el.labelBtn.disabled = true;
    clearResults("查無資料（此期間此倉無 APL主機 調撥入庫）。");
    return;
  }
  state.currentItems = payload.items;
  el.labelBtn.disabled = false;
  el.resultBody.innerHTML = payload.items.map((item) => `
    <tr>
      <td data-label="單據日期">${escapeHtml(item.docDate)}</td>
      <td data-label="來源單據代碼">${escapeHtml(item.docId)}</td>
      <td data-label="品牌代碼">${escapeHtml(item.brandId)}</td>
      <td data-label="存貨代碼">${escapeHtml(item.stkId)}</td>
      <td data-label="型號">${escapeHtml(item.model)}</td>
      <td data-label="存貨名稱">${escapeHtml(item.name)}</td>
      <td data-label="存貨數量">${formatNumber(item.stkQty)}</td>
      <td data-label="來源倉">${escapeHtml(item.sourceStore)}</td>
    </tr>
  `).join("");
}

async function downloadExcel() {
  setMessage("正在產生 Excel...");
  el.downloadBtn.disabled = true;
  try {
    const response = await fetch("/api/purchase/export", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(collectQuery()),
    });
    if (!response.ok) {
      const errorPayload = await response.json().catch(() => ({}));
      throw new Error(errorPayload.error || `HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filenameFromDisposition(response.headers.get("Content-Disposition"));
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    setMessage("Excel 已下載。");
  } catch (error) {
    setMessage(error.message, "error");
  } finally {
    el.downloadBtn.disabled = false;
  }
}

function filenameFromDisposition(value) {
  const match = /filename\*=UTF-8''([^;]+)/i.exec(value || "");
  if (match) return decodeURIComponent(match[1]);
  return "門市進貨查詢.xlsx";
}

function clearFilters() {
  el.storeId1.value = state.defaultStore;
  el.startDate.value = todayInput();
  el.endDate.value = todayInput();
  setMessage("");
  clearResults("已重設日期。");
}

function clearResults(message) {
  el.resultCount.textContent = "0 筆";
  el.resultBody.innerHTML = `<tr><td colspan="8" class="empty">${escapeHtml(message)}</td></tr>`;
  state.currentItems = [];
  el.labelBtn.disabled = true;
  el.labelPanel.classList.add("hidden");
}

function formatNumber(value) {
  const text = String(value ?? "");
  if (/^-?\d+(\.\d+)?$/.test(text)) {
    return Number(text).toLocaleString("zh-TW", {maximumFractionDigits: 0});
  }
  return escapeHtml(text);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

// ─── 排版調整（Layout Panel）────────────────────────────────

const LP_LAYOUT_KEY = "purchaseAppLabelLayout";
const DEFAULT_LAYOUT = {
  offsetX: 0, offsetY: 7,
  leftPad: 5, rightPad: 6,
  firstTop: 2, contentTop: 2,
  font1: 10, font2: 10,
  weekFont: 5, weekTop: 1, weekRight: 1.5,
  wmSize: 13, wmOpacity: 0.35, wmX: 50, wmY: 50,
};

function applyLayout(layout) {
  const vars = {
    "--offset-x": layout.offsetX + "mm",
    "--offset-y": layout.offsetY + "mm",
    "--label-left-pad": layout.leftPad + "mm",
    "--label-right-pad": layout.rightPad + "mm",
    "--label-first-top": layout.firstTop + "mm",
    "--label-content-top": layout.contentTop + "mm",
    "--label-first-font": layout.font1 + "pt",
    "--label-second-font": layout.font2 + "pt",
    "--label-week-font": layout.weekFont + "pt",
    "--label-week-top": layout.weekTop + "mm",
    "--label-week-right": layout.weekRight + "mm",
    "--watermark-size": layout.wmSize + "pt",
    "--watermark-opacity": String(layout.wmOpacity),
    "--watermark-x": layout.wmX + "%",
    "--watermark-y": layout.wmY + "%",
  };
  for (const [k, v] of Object.entries(vars)) {
    el.labelPrintArea.style.setProperty(k, v);
  }
}

function readLayout() {
  return {
    offsetX:    parseFloat(el.lpOffsetX.value)    || 0,
    offsetY:    parseFloat(el.lpOffsetY.value)    || 0,
    leftPad:    parseFloat(el.lpLeftPad.value)    || 0,
    rightPad:   parseFloat(el.lpRightPad.value)   || 0,
    firstTop:   parseFloat(el.lpFirstTop.value)   || 0,
    contentTop: parseFloat(el.lpContentTop.value) || 0,
    font1:      parseFloat(el.lpFont1.value)      || 10,
    font2:      parseFloat(el.lpFont2.value)      || 10,
    weekFont:   parseFloat(el.lpWeekFont.value)   || 5,
    weekTop:    parseFloat(el.lpWeekTop.value)    || 0,
    weekRight:  parseFloat(el.lpWeekRight.value)  || 0,
    wmSize:     parseFloat(el.lpWmSize.value)     || 13,
    wmOpacity:  parseFloat(el.lpWmOpacity.value)  || 0.35,
    wmX:        parseFloat(el.lpWmX.value)        || 50,
    wmY:        parseFloat(el.lpWmY.value)        || 50,
  };
}

function fillLayoutInputs(layout) {
  el.lpOffsetX.value    = layout.offsetX;
  el.lpOffsetY.value    = layout.offsetY;
  el.lpLeftPad.value    = layout.leftPad;
  el.lpRightPad.value   = layout.rightPad;
  el.lpFirstTop.value   = layout.firstTop;
  el.lpContentTop.value = layout.contentTop;
  el.lpFont1.value      = layout.font1;
  el.lpFont2.value      = layout.font2;
  el.lpWeekFont.value   = layout.weekFont;
  el.lpWeekTop.value    = layout.weekTop;
  el.lpWeekRight.value  = layout.weekRight;
  el.lpWmSize.value     = layout.wmSize;
  el.lpWmOpacity.value  = layout.wmOpacity;
  el.lpWmX.value        = layout.wmX;
  el.lpWmY.value        = layout.wmY;
}

function saveLayout() {
  try {
    localStorage.setItem(LP_LAYOUT_KEY, JSON.stringify(readLayout()));
  } catch (_) {}
}

function loadLayout() {
  try {
    const saved = JSON.parse(localStorage.getItem(LP_LAYOUT_KEY) || "null");
    const layout = saved ? {...DEFAULT_LAYOUT, ...saved} : {...DEFAULT_LAYOUT};
    fillLayoutInputs(layout);
    applyLayout(layout);
  } catch (_) {
    fillLayoutInputs({...DEFAULT_LAYOUT});
    applyLayout({...DEFAULT_LAYOUT});
  }
}

function resetLayout() {
  fillLayoutInputs({...DEFAULT_LAYOUT});
  applyLayout({...DEFAULT_LAYOUT});
  saveLayout();
}

function toggleLayoutPanel() {
  const collapsed = el.layoutPanel.classList.toggle("lp-collapsed");
  el.layoutToggleBtn.textContent = collapsed ? "排版調整 ▾" : "排版調整 ▴";
}

// ─── 標籤列印 ────────────────────────────────────────────────

function currentWeekLabel() {
  const d = new Date();
  const utc = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = utc.getUTCDay() || 7;
  utc.setUTCDate(utc.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(utc.getUTCFullYear(), 0, 1));
  const week = Math.ceil(((utc - yearStart) / 86400000 + 1) / 7);
  return "W" + String(week).padStart(2, "0");
}

function generateLabels() {
  const labels = expandToLabels(state.currentItems);
  if (!labels.length) {
    setMessage("此查詢結果無可產生的標籤（僅 Mac 商品）。", "error");
    return;
  }
  const startPos = Math.min(95, Math.max(1, parseInt(el.labelStartPos.value) || 1));
  buildLabelSheet(labels, startPos);
  el.labelCount.textContent = `${labels.length} 張`;
  el.labelPanel.classList.remove("hidden");
  el.labelPanel.scrollIntoView({behavior: "smooth", block: "start"});
}

function buildLabelSheet(labels, startPos) {
  const weekLabel = el.labelWeekInput.value.trim() || currentWeekLabel();
  const showBorder = el.labelBorder.checked;
  const COLS = 5, ROWS = 19, PER_PAGE = COLS * ROWS;
  const offset = startPos - 1;
  const totalPages = Math.ceil((labels.length + offset) / PER_PAGE);
  el.labelSheet.innerHTML = "";

  for (let page = 0; page < totalPages; page++) {
    const pageDiv = document.createElement("div");
    pageDiv.className = "label-page";
    for (let r = 0; r < ROWS; r++) {
      const rowDiv = document.createElement("div");
      rowDiv.className = "label-row-grid";
      for (let c = 0; c < COLS; c++) {
        const slotIdx = page * PER_PAGE + r * COLS + c;
        const idx = slotIdx - offset;
        const cellDiv = document.createElement("div");
        cellDiv.className = "label-cell";
        if (idx >= 0 && idx < labels.length) {
          if (showBorder) cellDiv.classList.add("has-border");
          const lbl = labels[idx];
          if (lbl.brand === "905") cellDiv.classList.add("brand-905");
          cellDiv.innerHTML = (lbl.brand === "905" ? `<div class="label-watermark">905</div>` : "") +
            `<div class="label-week">${escapeHtml(weekLabel)}</div>
            <div class="label-line primary">
              <span class="label-left">${escapeHtml(lbl.right2 || "")}</span>
              <span class="label-right">${escapeHtml(lbl.product || "")}</span>
            </div>
            <div class="label-line secondary">
              <span class="label-left">${escapeHtml(lbl.color || "")}</span>
              <span class="label-right">${escapeHtml(lbl.right1 || "")}</span>
            </div>`;
        }
        rowDiv.appendChild(cellDiv);
      }
      pageDiv.appendChild(rowDiv);
    }
    el.labelSheet.appendChild(pageDiv);
  }
}

function printLabels() {
  document.body.classList.add("print-labels");
  window.print();
  window.addEventListener("afterprint", function handler() {
    document.body.classList.remove("print-labels");
    window.removeEventListener("afterprint", handler);
  });
}

async function init() {
  el.startDate.value = todayInput();
  el.endDate.value = todayInput();
  el.searchBtn.addEventListener("click", searchPurchase);
  el.downloadBtn.addEventListener("click", downloadExcel);
  el.clearBtn.addEventListener("click", clearFilters);
  el.labelBtn.addEventListener("click", generateLabels);
  el.printBtn.addEventListener("click", printLabels);
  el.closeLabelBtn.addEventListener("click", () => el.labelPanel.classList.add("hidden"));
  el.layoutToggleBtn.addEventListener("click", toggleLayoutPanel);
  el.lpResetBtn.addEventListener("click", resetLayout);
  for (const input of [el.lpOffsetX, el.lpOffsetY, el.lpLeftPad, el.lpRightPad, el.lpFirstTop,
      el.lpContentTop, el.lpFont1, el.lpFont2, el.lpWeekFont, el.lpWeekTop, el.lpWeekRight,
      el.lpWmSize, el.lpWmOpacity, el.lpWmX, el.lpWmY]) {
    input.addEventListener("input", () => { applyLayout(readLayout()); saveLayout(); });
  }
  el.labelStartPos.addEventListener("change", () => {
    if (!el.labelPanel.classList.contains("hidden") && state.currentItems.length) {
      const labels = expandToLabels(state.currentItems);
      const startPos = Math.min(95, Math.max(1, parseInt(el.labelStartPos.value) || 1));
      buildLabelSheet(labels, startPos);
    }
  });
  el.labelWeekInput.addEventListener("change", () => {
    if (!el.labelPanel.classList.contains("hidden") && state.currentItems.length) {
      const labels = expandToLabels(state.currentItems);
      const startPos = Math.min(95, Math.max(1, parseInt(el.labelStartPos.value) || 1));
      buildLabelSheet(labels, startPos);
    }
  });
  el.labelBorder.addEventListener("change", () => {
    if (!el.labelPanel.classList.contains("hidden") && state.currentItems.length) {
      const labels = expandToLabels(state.currentItems);
      const startPos = Math.min(95, Math.max(1, parseInt(el.labelStartPos.value) || 1));
      buildLabelSheet(labels, startPos);
    }
  });
  // 設定週數預設值
  el.labelWeekInput.value = currentWeekLabel();
  loadLayout();
  setMessage("");
  try {
    await loadStores();
  } catch (error) {
    setMessage(error.message, "error");
  }
}

init();
