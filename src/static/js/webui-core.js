/* EL JEFE — shared state + helpers */
(function (global) {
  const state = {
    brandsCache: [],
    overviewCache: null,
    opsCache: null,
    outputsCache: {},
    healthCache: null,
    jobsCache: [],
    alertsCache: [],
    archiveSongs: [],
    crossPlatformCache: null,
    weeklyCache: null,
    selectedJob: null,
    logOffset: 0,
    windowDays: 7,
    brandFilter: null,
    jobStatusMap: {},
    jobLabelMap: {},
    lastDataHash: "",
    lastOpsHash: "",
    lastSyncAt: null,
    perfSort: { key: "date", dir: -1 },
    perfBrand: null,
    perfStatus: "",
    perfQuery: "",
    perfRows: [],
    cmdkIndex: 0,
    cmdkMatches: [],
    terrainCollapsed: localStorage.getItem("mpv2_terrain_collapsed") === "1",
    logSource: null,
  };

  const PALETTE = ["#c9a227", "#3ecf8e", "#e85d4c", "#9a8cff", "#46d7ff", "#e0c45a", "#7ee787", "#f778ba"];

  const $ = (id) => document.getElementById(id);
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );

  function fmt(n) {
    if (n === null || n === undefined) return "—";
    const num = Number(n);
    if (!isFinite(num)) return String(n);
    if (Math.abs(num) >= 10000) return num.toLocaleString();
    return String(num);
  }

  function money(n) {
    return `$${Number(n || 0).toFixed(2)}`;
  }

  function parseWhen(s) {
    if (!s) return null;
    const d = new Date(String(s).includes("T") ? s : String(s).replace(" ", "T"));
    return isNaN(d.getTime()) ? null : d;
  }

  function timeAgo(s) {
    const d = typeof s === "string" ? parseWhen(s) : s instanceof Date ? s : parseWhen(s);
    if (!d) return "";
    const sec = Math.max(0, (Date.now() - d.getTime()) / 1000);
    if (sec < 60) return `${Math.floor(sec)}s ago`;
    if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
    if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
    return `${Math.floor(sec / 86400)}d ago`;
  }

  function durationBetween(a, b) {
    const start = parseWhen(a);
    if (!start) return "";
    const end = parseWhen(b) || new Date();
    const sec = Math.max(0, Math.round((end - start) / 1000));
    if (sec < 60) return `${sec}s`;
    const m = Math.floor(sec / 60);
    return `${m}m ${sec % 60}s`;
  }

  function todayStr() {
    const d = new Date();
    const p = (x) => String(x).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }

  function windowLabel(days) {
    return days == null ? "ALL-TIME" : `${days}D`;
  }

  function windowCutoff() {
    if (state.windowDays == null) return null;
    return new Date(Date.now() - state.windowDays * 86400000);
  }

  function inWindow(dateStr) {
    const cutoff = windowCutoff();
    if (!cutoff) return true;
    const d = parseWhen(dateStr);
    return d ? d >= cutoff : true;
  }

  function ytId(url) {
    const m = String(url || "").match(/(?:shorts\/|watch\?v=|youtu\.be\/)([\w-]{6,})/);
    return m ? m[1] : "";
  }

  function thumbUrl(url) {
    const id = ytId(url);
    return id ? `https://i.ytimg.com/vi/${id}/mqdefault.jpg` : "";
  }

  function allBrandIds() {
    const ids = new Set(state.brandsCache.map((b) => b.brand_id));
    for (const b of (state.overviewCache && state.overviewCache.brands) || []) ids.add(b.brand_id);
    return Array.from(ids).sort();
  }

  function brandColor(brandId) {
    const ids = allBrandIds();
    const idx = Math.max(0, ids.indexOf(brandId));
    return PALETTE[idx % PALETTE.length];
  }

  function brandName(brandId) {
    const b = state.brandsCache.find((x) => x.brand_id === brandId);
    if (b && b.channel_name) return b.channel_name;
    const s = ((state.overviewCache && state.overviewCache.brands) || []).find((x) => x.brand_id === brandId);
    if (s && s.channel_name) return s.channel_name;
    return String(brandId || "unknown").replace(/_/g, " ");
  }

  function monogram(name) {
    const parts = String(name || "?").trim().split(/\s+/);
    return ((parts[0] || "")[0] || "?").toUpperCase() + (((parts[1] || "")[0]) || "").toUpperCase();
  }

  function chartCtx() {
    const colors = {};
    const names = {};
    for (const id of allBrandIds()) {
      colors[id] = brandColor(id);
      names[id] = brandName(id);
    }
    return { colors, names, brandFilter: state.brandFilter, windowDays: state.windowDays, cutoff: windowCutoff() };
  }

  function toast(msg, isError) {
    const el = $("toast");
    if (!el) return;
    el.textContent = msg;
    el.style.borderLeftColor = isError ? "var(--red)" : "var(--green)";
    el.style.display = "block";
    clearTimeout(el._t);
    el._t = setTimeout(() => (el.style.display = "none"), 5000);
  }

  async function api(path, opts) {
    const res = await fetch(path, opts);
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || res.statusText);
    return body;
  }

  function tickClock() {
    const d = new Date();
    const p = (x) => String(x).padStart(2, "0");
    const t = $("clock-time");
    if (t) t.textContent = `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
    const dateEl = $("clock-date");
    if (dateEl) {
      dateEl.textContent = d
        .toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })
        .toUpperCase();
    }
  }

  function overviewUrl() {
    const q = state.windowDays == null ? "all" : String(state.windowDays);
    return `/api/overview?days=${encodeURIComponent(q)}`;
  }

  function opsUrl() {
    const q = state.windowDays == null ? "all" : String(state.windowDays);
    return `/api/ops?days=${encodeURIComponent(q)}`;
  }

  function activeSection() {
    const sec = document.querySelector(".panel-section.active");
    return sec ? sec.dataset.section : "overview";
  }

  function updateHeroVisibility() {
    const onOverview = activeSection() === "overview";
    const visible = onOverview && !document.hidden && !state.terrainCollapsed;
    if (window.MPHeroes) window.MPHeroes.setVisible(visible);
    const card = $("hero-card");
    if (card) card.classList.toggle("collapsed", state.terrainCollapsed);
    const btn = $("toggle-terrain");
    if (btn) btn.textContent = state.terrainCollapsed ? "Expand" : "Collapse";
  }

  function setSection(name) {
    document.querySelectorAll(".panel-section").forEach((sec) => {
      sec.classList.toggle("active", sec.dataset.section === name);
    });
    document.querySelectorAll(".nav-tabs button").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.section === name);
    });
    updateHeroVisibility();
    if (state.overviewCache && (name === "overview" || name === "spend")) {
      requestAnimationFrame(() => {
        if (global.MPV2.renderChartsAndHeroes) global.MPV2.renderChartsAndHeroes(state.overviewCache);
      });
    }
    if (name === "review" && global.MPV2.loadWeekly) global.MPV2.loadWeekly(false);
    if (name === "performance" && global.MPV2.renderPerformance) global.MPV2.renderPerformance();
  }

  function toggleOverlay(id, show) {
    const el = $(id);
    if (!el) return;
    const open = show === undefined ? el.hidden : show;
    el.hidden = !open;
    if (id === "cmdk" && open) {
      const input = $("cmdk-input");
      if (input) {
        input.value = "";
        state.cmdkIndex = 0;
        if (global.MPV2.renderCmdk) global.MPV2.renderCmdk();
        setTimeout(() => input.focus(), 10);
      }
    }
    if (open && (id === "cmdk" || id === "keys-overlay" || id === "health-overlay")) {
      trapFocus(el);
    }
  }

  function trapFocus(backdrop) {
    const panel = backdrop.querySelector(".cmdk-panel");
    if (!panel) return;
    const focusables = panel.querySelectorAll("button, input, select, [tabindex]:not([tabindex='-1'])");
    if (!focusables.length) return;
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    function onKey(ev) {
      if (backdrop.hidden) {
        backdrop.removeEventListener("keydown", onKey);
        return;
      }
      if (ev.key !== "Tab") return;
      if (ev.shiftKey && document.activeElement === first) {
        ev.preventDefault();
        last.focus();
      } else if (!ev.shiftKey && document.activeElement === last) {
        ev.preventDefault();
        first.focus();
      }
    }
    backdrop.addEventListener("keydown", onKey);
  }

  global.MPV2 = {
    state,
    PALETTE,
    $,
    esc,
    fmt,
    money,
    parseWhen,
    timeAgo,
    durationBetween,
    todayStr,
    windowLabel,
    windowCutoff,
    inWindow,
    ytId,
    thumbUrl,
    allBrandIds,
    brandColor,
    brandName,
    monogram,
    chartCtx,
    toast,
    api,
    tickClock,
    overviewUrl,
    opsUrl,
    activeSection,
    setSection,
    toggleOverlay,
    updateHeroVisibility,
  };
})(window);
