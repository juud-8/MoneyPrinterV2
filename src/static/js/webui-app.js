/* EL JEFE — Mission Control application (MoneyPrinterV2). */
(function () {
  // ———— State ————
  let brandsCache = [];
  let overviewCache = null;
  let outputsCache = {};
  let healthCache = null;
  let jobsCache = [];
  let alertsCache = [];
  let selectedJob = null;
  let logOffset = 0;
  let windowDays = 7;
  let brandFilter = null;
  let jobStatusMap = {};
  let jobLabelMap = {};
  let lastDataHash = "";
  let lastSyncAt = null;
  let perfSort = { key: "date", dir: -1 };
  let perfBrand = null;
  let perfStatus = "";
  let perfQuery = "";
  let cmdkIndex = 0;
  let cmdkMatches = [];

  const $ = (id) => document.getElementById(id);
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );

  const PALETTE = ["#46d7ff", "#3ddc97", "#f5b950", "#ff5c5c", "#b98aff", "#39c5cf", "#f778ba", "#7ee787"];

  // ———— Formatting helpers ————
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
    const d = parseWhen(s);
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
    if (windowDays == null) return null;
    return new Date(Date.now() - windowDays * 86400000);
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

  // ———— Brand identity ————
  function allBrandIds() {
    const ids = new Set(brandsCache.map((b) => b.brand_id));
    for (const b of (overviewCache && overviewCache.brands) || []) ids.add(b.brand_id);
    return Array.from(ids).sort();
  }

  function brandColor(brandId) {
    const ids = allBrandIds();
    const idx = Math.max(0, ids.indexOf(brandId));
    return PALETTE[idx % PALETTE.length];
  }

  function brandName(brandId) {
    const b = brandsCache.find((x) => x.brand_id === brandId);
    if (b && b.channel_name) return b.channel_name;
    const s = ((overviewCache && overviewCache.brands) || []).find((x) => x.brand_id === brandId);
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
    return { colors, names, brandFilter, windowDays, cutoff: windowCutoff() };
  }

  // ———— Toast ————
  function toast(msg, isError) {
    const el = $("toast");
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

  // ———— Clock ————
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

  // ———— Systems health ————
  const HEALTH_ITEMS = [
    { key: "ollama", label: "Ollama (local LLM)" },
    { key: "gemini", label: "Gemini key" },
    { key: "youtube_data", label: "YouTube Data key" },
    { key: "tts", label: "TTS key (Fish/ElevenLabs)" },
    { key: "imagemagick", label: "ImageMagick" },
    { key: "profiles", label: "Firefox profiles" },
    { key: "metrics", label: "Metrics freshness" },
    { key: "disk", label: "Disk space" },
  ];

  function healthStates(h) {
    if (!h) return {};
    const keys = h.keys || {};
    const snapshotAgeH = (() => {
      const d = parseWhen(h.latest_channel_snapshot);
      return d ? (Date.now() - d.getTime()) / 3600000 : null;
    })();
    const profilesOk = (h.brand_profiles || []).every((p) => p.profile_ok);
    return {
      ollama: h.ollama && h.ollama.ok ? "ok" : "bad",
      gemini: keys.gemini ? "ok" : "bad",
      youtube_data: keys.youtube_data ? "ok" : "warn",
      tts: keys.fish_audio || keys.elevenlabs ? "ok" : "warn",
      imagemagick: h.imagemagick_ok ? "ok" : "bad",
      profiles: (h.brand_profiles || []).length === 0 ? "warn" : profilesOk ? "ok" : "bad",
      metrics: snapshotAgeH == null ? "warn" : snapshotAgeH <= 26 ? "ok" : snapshotAgeH <= 72 ? "warn" : "bad",
      disk: h.disk_free_gb == null ? "warn" : h.disk_free_gb > 10 ? "ok" : h.disk_free_gb > 3 ? "warn" : "bad",
    };
  }

  function healthDetail(key, h) {
    if (!h) return "";
    switch (key) {
      case "ollama": return h.ollama ? h.ollama.detail : "";
      case "metrics": {
        const d = parseWhen(h.latest_channel_snapshot);
        return d ? `last snapshot ${timeAgo(h.latest_channel_snapshot)}` : "no snapshots yet";
      }
      case "disk": return h.disk_free_gb != null ? `${h.disk_free_gb} GB free` : "";
      case "profiles": {
        const bad = (h.brand_profiles || []).filter((p) => !p.profile_ok).map((p) => p.brand_id);
        return bad.length ? `missing: ${bad.join(", ")}` : "all resolve";
      }
      default: return "";
    }
  }

  function renderHealth() {
    const leds = $("health-leds");
    const label = $("health-label");
    if (!leds || !label) return;
    if (!healthCache) {
      label.textContent = "SYSTEMS…";
      label.className = "health-label unknown";
      leds.innerHTML = HEALTH_ITEMS.map(() => '<span class="led"></span>').join("");
      return;
    }
    const states = healthStates(healthCache);
    leds.innerHTML = HEALTH_ITEMS.map((item) => {
      const st = states[item.key] || "warn";
      const detail = healthDetail(item.key, healthCache);
      return `<span class="led ${st}" title="${esc(item.label)}: ${st.toUpperCase()}${detail ? " — " + esc(detail) : ""}"></span>`;
    }).join("");
    const vals = Object.values(states);
    const bads = vals.filter((v) => v === "bad").length;
    const warns = vals.filter((v) => v === "warn").length;
    if (bads > 0) {
      label.textContent = "SYSTEMS: CRITICAL";
      label.className = "health-label critical";
    } else if (warns > 0) {
      label.textContent = "SYSTEMS: DEGRADED";
      label.className = "health-label degraded";
    } else {
      label.textContent = "SYSTEMS NOMINAL";
      label.className = "health-label";
    }
  }

  let healthRetryTimer = null;

  async function fetchHealth(force) {
    try {
      healthCache = await api(`/api/health${force ? "?force=1" : ""}`);
      renderHealth();
      const states = healthStates(healthCache);
      const failing = HEALTH_ITEMS.filter((i) => states[i.key] === "bad").map((i) => i.label);
      if (force) {
        toast(failing.length ? `Systems check: ${failing.join(" · ")} DOWN` : "Systems check: all nominal", failing.length > 0);
      }
      // A CRITICAL reading gets re-verified quickly instead of waiting for
      // the normal 90s poll — transient probe failures shouldn't linger.
      clearTimeout(healthRetryTimer);
      if (failing.length && !document.hidden) {
        healthRetryTimer = setTimeout(() => fetchHealth(true).catch(() => {}), 20000);
      }
    } catch (e) {
      healthCache = null;
      renderHealth();
    }
  }

  // ———— Sections ————
  function setSection(name) {
    document.querySelectorAll(".panel-section").forEach((sec) => {
      sec.classList.toggle("active", sec.dataset.section === name);
    });
    document.querySelectorAll(".nav-tabs button").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.section === name);
    });
    if (overviewCache && (name === "overview" || name === "spend")) {
      requestAnimationFrame(() => renderChartsAndHeroes(overviewCache));
    }
  }

  function activeSection() {
    const sec = document.querySelector(".panel-section.active");
    return sec ? sec.dataset.section : "overview";
  }

  // ———— Ops brief (today + publish windows) ————
  function nextWindowInfo(slots) {
    const now = new Date();
    let best = null;
    for (const [name, slot] of Object.entries(slots || {})) {
      const start = (slot || {}).window_start;
      if (!/^\d{2}:\d{2}$/.test(start || "")) continue;
      const end = (slot || {}).window_end;
      const mk = (hhmm, dayOffset) => {
        const [h, m] = hhmm.split(":").map(Number);
        const d = new Date(now);
        d.setDate(d.getDate() + dayOffset);
        d.setHours(h, m, 0, 0);
        return d;
      };
      let startAt = mk(start, 0);
      let endAt = end && /^\d{2}:\d{2}$/.test(end) ? mk(end, 0) : new Date(startAt.getTime() + 30 * 60000);
      if (endAt < startAt) endAt = new Date(endAt.getTime() + 86400000);
      let state, at;
      if (now >= startAt && now <= endAt) {
        state = "live";
        at = endAt;
      } else if (now < startAt) {
        state = "soon";
        at = startAt;
      } else {
        state = "next";
        at = mk(start, 1);
      }
      const cand = { name, state, at, start, end };
      if (!best || (state === "live" && best.state !== "live") || (best.state !== "live" && at < best.at)) best = cand;
    }
    return best;
  }

  function humanUntil(date) {
    const min = Math.max(0, Math.round((date - Date.now()) / 60000));
    if (min < 60) return `${min}m`;
    const h = Math.floor(min / 60);
    return `${h}h ${String(min % 60).padStart(2, "0")}m`;
  }

  function quotaBlocks(done, target) {
    const t = Math.max(target || 0, done || 0, 1);
    let out = "";
    for (let i = 0; i < Math.min(t, 8); i++) {
      out += `<span class="${i < done ? "q-done" : "q-todo"}">${i < done ? "▰" : "▱"}</span>`;
    }
    return out;
  }

  function renderOpsBrief() {
    const el = $("ops-brief");
    if (!el || !overviewCache) return;
    const opsDate = $("ops-date");
    if (opsDate) {
      opsDate.textContent = new Date()
        .toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" })
        .toUpperCase();
    }
    const today = todayStr();
    const videos = overviewCache.videos || [];
    const rows = [];
    const visible = brandsCache.length
      ? brandsCache
      : (overviewCache.brands || []).map((b) => ({ brand_id: b.brand_id, channel_name: b.channel_name }));
    for (const brand of visible) {
      const id = brand.brand_id;
      const todays = videos.filter((v) => v.brand_id === id && String(v.date || "").startsWith(today));
      const uploadedToday = todays.filter((v) => v.status === "uploaded").length;
      const target = Number(brand.shorts_per_day || 0);
      const win = nextWindowInfo(brand.publish_slots);
      let chip = `<span class="win-chip">no windows set</span>`;
      if (win) {
        if (win.state === "live") {
          chip = `<span class="win-chip live">● LIVE WINDOW · ${esc(win.name)} until ${esc(win.end || "")}</span>`;
        } else if (win.state === "soon") {
          chip = `<span class="win-chip soon">next: ${esc(win.name)} ${esc(win.start)} · in ${humanUntil(win.at)}</span>`;
        } else {
          chip = `<span class="win-chip">next: ${esc(win.name)} ${esc(win.start)} tomorrow</span>`;
        }
      }
      const quotaHtml = target
        ? `<span class="quota" title="uploaded today vs shorts_per_day">${quotaBlocks(uploadedToday, target)} ${uploadedToday}/${target}</span>`
        : `<span class="quota muted">${uploadedToday} today</span>`;
      rows.push(`
        <div class="ops-line">
          <span class="brand-dot" style="background:${brandColor(id)};box-shadow:0 0 8px ${brandColor(id)}66"></span>
          <span class="name">${esc(brandName(id))}</span>
          ${quotaHtml}
          ${todays.length > uploadedToday ? `<span class="pill">${todays.length - uploadedToday} generated</span>` : ""}
          ${chip}
        </div>`);
    }
    el.innerHTML = rows.join("") || `<div class="empty-state">No brands under <code>brands/</code>.</div>`;
  }

  // ———— Attention feed ————
  function computeAlerts() {
    const alerts = [];
    if (!overviewCache) return alerts;
    const videos = overviewCache.videos || [];

    const silent = videos.filter((v) => v.status === "uploaded" && !v.url);
    if (silent.length) {
      alerts.push({
        sev: "red",
        label: "UPLOAD",
        text: `${silent.length} upload(s) logged with no URL — possible silent failure. Latest: “${(silent[0].title || "").slice(0, 60)}”`,
        jump: "performance",
      });
    }

    const failedJobs = jobsCache.filter((j) => j.status === "failed");
    if (failedJobs.length) {
      alerts.push({
        sev: "red",
        label: "PIPELINE",
        text: `${failedJobs.length} failed job(s) in history — check the terminal log.`,
        jump: "pipeline",
      });
    }

    const spendAlert = overviewCache.spend_alert || {};
    if (spendAlert.triggered) {
      alerts.push({
        sev: "red",
        label: "SPEND",
        text: `Premium spend ${money(spendAlert.recent_spend_usd)} over the ${money(spendAlert.threshold_usd)} alert line.`,
        jump: "spend",
      });
    }

    if (healthCache) {
      const states = healthStates(healthCache);
      if (states.ollama === "bad") {
        alerts.push({ sev: "red", label: "SYSTEMS", text: "Ollama is unreachable — generation runs will fail or fall back.", jump: "help" });
      }
      if (states.gemini === "bad") {
        alerts.push({ sev: "amber", label: "SYSTEMS", text: "No Gemini key — quality LLM + image gen fall back to local models (llama-scripted shorts risk).", jump: "help" });
      }
      if (states.profiles === "bad") {
        alerts.push({ sev: "red", label: "SYSTEMS", text: `Firefox profile missing: ${healthDetail("profiles", healthCache)}`, jump: "brands" });
      }
    }

    const uploads = videos.filter((v) => v.url);
    if (uploads.length) {
      let newest = null;
      for (const v of uploads) {
        const d = parseWhen(v.metrics_updated_at);
        if (d && (!newest || d > newest)) newest = d;
      }
      const ageH = newest ? (Date.now() - newest.getTime()) / 3600000 : null;
      if (ageH == null || ageH > 26) {
        alerts.push({
          sev: "amber",
          label: "METRICS",
          text: ageH == null ? "Video metrics never refreshed — hit ⟳ Metrics." : `Metrics are ${Math.round(ageH)}h stale — hit ⟳ Metrics.`,
          action: "metrics",
        });
      }
    }

    const rej = overviewCache.rejection_summary || {};
    if ((rej.duration_aborts || 0) > 0) {
      alerts.push({
        sev: "amber",
        label: "QUALITY",
        text: `${rej.duration_aborts} generation(s) aborted by the duration gate in this window.`,
        jump: "spend",
      });
    }

    const backlog = videos.filter((v) => v.status !== "uploaded" && !v.url && inWindow(v.date));
    if (backlog.length) {
      alerts.push({
        sev: "info",
        label: "REVIEW",
        text: `${backlog.length} generated render(s) not uploaded yet — review under output/<brand>/.`,
        jump: "brands",
      });
    }

    return alerts;
  }

  function renderAlerts() {
    const el = $("ops-alerts");
    if (!el) return;
    alertsCache = computeAlerts();
    if (!alertsCache.length) {
      el.innerHTML = `<div class="all-clear">ALL CLEAR — NO ANOMALIES DETECTED</div>`;
      return;
    }
    el.innerHTML = alertsCache
      .slice(0, 6)
      .map(
        (a, i) => `
        <div class="alert-line ${a.sev}" ${a.jump ? `data-jump="${esc(a.jump)}"` : ""} ${a.action ? `data-alert-action="${esc(a.action)}"` : ""}>
          <span class="sev">${esc(a.label)}</span>
          <span>${esc(a.text)}</span>
        </div>`
      )
      .join("") + (alertsCache.length > 6 ? `<p class="muted small">+${alertsCache.length - 6} more</p>` : "");
  }

  // ———— KPI row ————
  function animateKpi(el) {
    el.style.transform = "scale(1.04)";
    setTimeout(() => (el.style.transform = "scale(1)"), 180);
  }

  function growthDelta(brandIds) {
    const growth = (overviewCache && overviewCache.channel_growth) || {};
    const cutoff = windowCutoff();
    let delta = 0;
    let has = false;
    for (const id of brandIds) {
      const series = (growth[id] || []).filter((p) => p.subscribers != null);
      if (series.length < 2) continue;
      const inWin = cutoff ? series.filter((p) => (parseWhen(p.date) || new Date(0)) >= cutoff) : series;
      const pts = inWin.length >= 2 ? inWin : series;
      delta += (pts[pts.length - 1].subscribers || 0) - (pts[0].subscribers || 0);
      has = true;
    }
    return has ? delta : null;
  }

  function renderTotals(data) {
    const totalsEl = $("totals");
    if (!totalsEl) return;
    const snaps = data.channel_snapshots || {};
    const brandIds = allBrandIds();
    const subsTotal = Object.values(snaps).reduce((acc, s) => acc + (Number(s.subscribers) || 0), 0);
    const chViews = Object.values(snaps).reduce((acc, s) => acc + (Number(s.total_views) || 0), 0);
    const delta = growthDelta(brandIds);
    const videos = data.videos || [];
    const winPosts = videos.filter((v) => inWindow(v.date));
    const winUploaded = winPosts.filter((v) => v.status === "uploaded").length;
    const today = todayStr();
    const uploadedToday = videos.filter((v) => String(v.date || "").startsWith(today) && v.status === "uploaded").length;
    const targetToday = brandsCache.reduce((acc, b) => acc + (Number(b.shorts_per_day) || 0), 0);
    const t = data.totals || {};
    const alerts = alertsCache;

    const items = [
      {
        value: fmt(subsTotal),
        label: "Subscribers",
        sub: delta == null ? "run ⟳ metrics for Δ" : `${delta >= 0 ? "+" : ""}${fmt(delta)} in ${windowLabel(data.window_days)}`,
        subClass: delta == null ? "" : delta >= 0 ? "up" : "down",
        accent: "var(--cyan)",
      },
      {
        value: fmt(chViews),
        label: "Channel views",
        sub: `${fmt(t.videos)} posts all-time`,
        accent: "var(--violet)",
      },
      {
        value: fmt(winPosts.length),
        label: `Posts · ${windowLabel(data.window_days)}`,
        sub: `${fmt(winUploaded)} uploaded`,
        accent: "var(--cyan)",
      },
      {
        value: targetToday ? `${uploadedToday}/${targetToday}` : fmt(uploadedToday),
        label: "Posted today",
        sub: targetToday ? "vs daily target" : "no targets set",
        subClass: targetToday && uploadedToday >= targetToday ? "up" : "",
        accent: "var(--green)",
      },
      {
        value: money(t.spend_window_usd),
        label: `Premium spend · ${windowLabel(data.window_days)}`,
        sub: `${money(t.spend_all_time_usd)} all-time`,
        accent: "var(--gold)",
      },
      {
        value: alerts.length ? String(alerts.length) : "CLEAR",
        label: "Attention",
        sub: alerts.length ? (alerts[0].text || "").slice(0, 42) + "…" : "no anomalies",
        subClass: alerts.length ? "down" : "up",
        accent: alerts.length ? "var(--red)" : "var(--green)",
      },
    ];

    totalsEl.innerHTML = items
      .map(
        (item) => `
        <div class="kpi" style="--kpi-accent:${item.accent}">
          <strong>${esc(item.value)}</strong>
          <span class="kpi-label">${esc(item.label)}</span>
          <span class="kpi-sub ${item.subClass || ""}">${esc(item.sub)}</span>
        </div>`
      )
      .join("");
    totalsEl.querySelectorAll("strong").forEach(animateKpi);
  }

  function renderSpendBanner(overview) {
    const alert = overview.spend_alert || {};
    const el = $("spend-alert");
    if (!el) return;
    if (alert.triggered) {
      el.classList.add("visible");
      el.textContent = `⚠ Premium spend ${money(alert.recent_spend_usd)} exceeds the ${money(alert.threshold_usd)} alert line (${windowLabel(overview.window_days)}). Review asset_strategy if unintended.`;
    } else {
      el.classList.remove("visible");
    }
  }

  // ———— Hero legend / charts ————
  function renderHeroLegend(overview) {
    const legend = $("hero-legend");
    const meta = $("hero-meta");
    if (!legend) return;
    const growth = overview.channel_growth || {};
    const snaps = overview.channel_snapshots || {};
    const ids = Object.keys(growth).length ? Object.keys(growth).sort() : allBrandIds();
    legend.innerHTML = ids
      .map((id) => {
        const snap = snaps[id];
        const delta = growthDelta([id]);
        const dim = brandFilter && brandFilter !== id;
        return `
          <div class="legend-row ${dim ? "dim" : ""}" data-action="filter-brand" data-brand="${esc(id)}" title="Click to focus ${esc(brandName(id))}">
            <span class="dot" style="background:${brandColor(id)};box-shadow:0 0 8px ${brandColor(id)}"></span>
            <span>${esc(brandName(id))}</span>
            <span class="val">${snap ? fmt(snap.subscribers) : "—"}</span>
            ${delta != null ? `<span class="delta ${delta >= 0 ? "up" : "down"}">${delta >= 0 ? "▲" : "▼"}${fmt(Math.abs(delta))}</span>` : ""}
          </div>`;
      })
      .join("");
    if (meta) {
      const snapCount = Object.values(growth).reduce((a, s) => a + s.length, 0);
      meta.textContent = `${snapCount} SNAPSHOTS · WINDOW ${windowLabel(overview.window_days)}`;
    }
    const filterLabel = $("brand-filter-label");
    if (filterLabel) {
      filterLabel.textContent = brandFilter ? `TRACKING: ${brandName(brandFilter).toUpperCase()}` : "TRACKING: ALL BRANDS";
    }
  }

  function renderChartsAndHeroes(overview) {
    const ctx = chartCtx();
    if (window.MPCharts) window.MPCharts.renderAll(overview, ctx);
    if (window.MPHeroes) {
      window.MPHeroes.render(overview, {
        ...ctx,
        onBrandSelect: (id) => {
          brandFilter = brandFilter === id ? null : id;
          renderChartsAndHeroes(overview);
          toast(brandFilter ? `Tracking ${brandName(brandFilter)}` : "Tracking all brands");
        },
      });
    }
    renderHeroLegend(overview);
    renderTopVideos(overview);
  }

  // ———— Top videos ————
  function renderTopVideos(overview) {
    const el = $("top-videos");
    if (!el) return;
    let rows = (overview.video_metrics_table || []).filter(
      (v) => v.views != null && (!brandFilter || v.brand_id === brandFilter)
    );
    const winRows = rows.filter((v) => inWindow(v.date));
    if (winRows.length >= 3) rows = winRows;
    rows = rows.slice().sort((a, b) => (b.views || 0) - (a.views || 0)).slice(0, 8);
    if (!rows.length) {
      el.innerHTML = `<div class="empty-state">No view data yet — upload and hit ⟳ Metrics.</div>`;
      return;
    }
    el.innerHTML = rows
      .map((v, i) => {
        const th = thumbUrl(v.url);
        return `
        <a class="tv-row" href="${esc(v.url || "#")}" target="_blank" rel="noopener">
          <span class="tv-rank">${String(i + 1).padStart(2, "0")}</span>
          ${th ? `<img class="tv-thumb" loading="lazy" src="${esc(th)}" alt="">` : `<span class="tv-thumb"></span>`}
          <span class="tv-title" title="${esc(v.title)}">${esc(v.title || "(untitled)")}</span>
          <span class="pill" style="background:${brandColor(v.brand_id)}22;color:${brandColor(v.brand_id)}">${esc(brandName(v.brand_id))}</span>
          <span class="tv-views">${fmt(v.views)}</span>
          <span class="tv-ret">${v.avg_view_pct != null ? fmt(v.avg_view_pct) + "%" : ""}</span>
        </a>`;
      })
      .join("");
  }

  // ———— Recent posts feed ————
  function renderRecentPosts(overview) {
    const el = $("recent-posts");
    if (!el) return;
    const items = (overview.videos || []).slice(0, 12);
    if (!items.length) {
      el.innerHTML = `<div class="empty-state">No posts logged yet.<br><code>Generate only</code> on a brand card, or run <code>scripts/run_brand_short.py</code></div>`;
      return;
    }
    el.innerHTML = `<div class="feed">${items
      .map((v) => {
        const th = thumbUrl(v.url);
        const color = brandColor(v.brand_id);
        return `
        <div class="feed-row">
          ${th ? `<img class="feed-thumb" loading="lazy" src="${esc(th)}" alt="">` : `<span class="feed-thumb ph">REC</span>`}
          <div class="feed-main">
            <div class="feed-title">${v.url ? `<a href="${esc(v.url)}" target="_blank" rel="noopener">${esc(v.title || "(untitled)")}</a>` : esc(v.title || "(untitled)")}</div>
            <div class="feed-meta">
              <span class="pill" style="background:${color}22;color:${color}">${esc(brandName(v.brand_id))}</span>
              <span class="pill ${v.status === "uploaded" ? "green" : "gray"}">${esc(v.status || "generated")}</span>
              <span class="when">${esc(timeAgo(v.date))}</span>
            </div>
          </div>
          <div class="feed-stats">
            ${v.views != null ? `${fmt(v.views)} views` : "—"}
            <span class="sub">${v.likes != null ? fmt(v.likes) + " likes" : ""}${v.avg_view_pct != null ? ` · ${fmt(v.avg_view_pct)}% ret` : ""}</span>
          </div>
        </div>`;
      })
      .join("")}</div>`;
  }

  // ———— Brands tab ————
  function slotEditor(brand) {
    const slots = brand.publish_slots || {};
    const names = Object.keys(slots).length ? Object.keys(slots) : ["early", "prime"];
    const rows = names
      .map((name) => {
        const s = slots[name] || {};
        return `
          <div class="slot-row" data-slot="${esc(name)}">
            <label>${esc(name)}</label>
            <input data-k="window_start" value="${esc(s.window_start || "")}" placeholder="HH:MM" title="Window start">
            <span class="muted">→</span>
            <input data-k="window_end" value="${esc(s.window_end || "")}" placeholder="HH:MM" title="Window end">
            <span class="muted small" title="Schedule the Windows Task ~30min before window start">task hint: ${esc(s.scheduler_start_hint || "—")}</span>
          </div>`;
      })
      .join("");
    return `
      <details class="slots">
        <summary>Publish times (windows the scheduler targets)</summary>
        ${rows}
        <div class="actions">
          <button data-action="save-slots" data-brand="${esc(brand.brand_id)}">Save publish times</button>
        </div>
        <p class="muted small">The daily runner picks a random moment inside each window. Keep Task Scheduler starting before the window opens.</p>
      </details>`;
  }

  function insightsBlock(ins) {
    if (!ins) return "";
    if (!ins.active) {
      return `<p class="muted small">Insights: ${ins.sample_size}/${ins.min_sample} videos with metrics — topic steering activates at ${ins.min_sample}+ uploads older than 48h.</p>`;
    }
    const top = ins.top
      .map(
        (v) =>
          `<li>▲ ${esc((v.title || "").slice(0, 70))} <span class="pill green">${fmt(v.views)} views</span>${v.avg_view_pct != null ? ` <span class="pill amber">${fmt(v.avg_view_pct)}% ret</span>` : ""}</li>`
      )
      .join("");
    const bottom = ins.bottom
      .map((v) => `<li>▼ ${esc((v.title || "").slice(0, 70))} <span class="pill red">${fmt(v.views)} views</span></li>`)
      .join("");
    return `<details class="slots"><summary>Performance insights (feeding topic generation)</summary><ul class="plain">${top}${bottom}</ul></details>`;
  }

  function recentPostsList(posts) {
    if (!posts || !posts.length) return `<li class="muted">No recent posts.</li>`;
    return posts
      .map((v) => {
        const pills = [
          `<span class="pill ${v.status === "uploaded" ? "green" : "gray"}">${esc(v.status || "generated")}</span>`,
          v.views != null ? `<span class="pill">${fmt(v.views)} views</span>` : "",
        ]
          .filter(Boolean)
          .join(" ");
        return `<li><span class="muted small">${esc((v.date || "").slice(5, 16))}</span> ${pills} ${esc((v.title || "").slice(0, 70))}${
          v.url ? ` <a href="${esc(v.url)}" target="_blank" rel="noopener">↗</a>` : ""
        }</li>`;
      })
      .join("");
  }

  function rendersBlock(brandId) {
    const files = outputsCache[brandId] || [];
    if (!files.length) return "";
    return `
      <div class="renders">
        <span class="muted small">LATEST RENDERS</span>
        ${files
          .map(
            (f) => `
          <div class="r-row">
            <span class="pill violet">mp4</span>
            <span class="fname" title="${esc(f.name)}">${esc(f.name)}</span>
            <span class="muted small">${esc(f.modified)} · ${f.size_mb} MB</span>
          </div>`
          )
          .join("")}
      </div>`;
  }

  function renderBrands(overview) {
    const container = $("brands");
    if (!container) return;
    if (!brandsCache.length) {
      container.innerHTML = `<div class="empty-state">No brands found under <code>brands/</code>.</div>`;
      return;
    }
    const summaries = Object.fromEntries((overview.brands || []).map((b) => [b.brand_id, b]));
    const snaps = overview.channel_snapshots || {};
    const insights = overview.insights || {};
    const today = todayStr();
    const videos = overview.videos || [];

    container.innerHTML = "";
    for (const brand of brandsCache) {
      const id = brand.brand_id;
      const s = summaries[id] || {};
      const snap = snaps[id];
      const color = brandColor(id);
      const delta = growthDelta([id]);
      const uploadedToday = videos.filter((v) => v.brand_id === id && String(v.date || "").startsWith(today) && v.status === "uploaded").length;
      const target = Number(brand.shorts_per_day || 0);
      const win = nextWindowInfo(brand.publish_slots);
      let winChip = "";
      if (win) {
        winChip =
          win.state === "live"
            ? `<span class="win-chip live">● LIVE · ${esc(win.name)} until ${esc(win.end || "")}</span>`
            : win.state === "soon"
              ? `<span class="win-chip soon">${esc(win.name)} ${esc(win.start)} · in ${humanUntil(win.at)}</span>`
              : `<span class="win-chip">${esc(win.name)} ${esc(win.start)} tomorrow</span>`;
      }

      const card = document.createElement("article");
      card.className = "card";
      card.innerHTML = `
        <div class="brand-head">
          <span class="brand-avatar" style="background:${color};box-shadow:0 0 16px ${color}55">${esc(monogram(brand.channel_name))}</span>
          <div class="titles">
            <h3>${esc(brand.channel_name)}</h3>
            <span class="bid">${esc(id)}${brand.niche ? ` · ${esc(brand.niche)}` : ""}</span>
          </div>
          <span>
            ${brand.is_active ? '<span class="pill green">active</span>' : ""}
            ${brand.pilot_mode ? '<span class="pill amber" title="Pilot mode: Generate &amp; Post confirms the pilot review gate.">pilot</span>' : ""}
            ${brand.default_visibility ? `<span class="pill gray">${esc(brand.default_visibility)}</span>` : ""}
          </span>
        </div>
        <div class="stats">
          <div><strong>${fmt(snap ? snap.subscribers : null)}${delta != null ? `<span class="delta ${delta >= 0 ? "up" : "down"}">${delta >= 0 ? "▲" : "▼"}${fmt(Math.abs(delta))}</span>` : ""}</strong><span>Subs</span></div>
          <div><strong>${fmt(snap ? snap.total_views : null)}</strong><span>Ch. views</span></div>
          <div><strong>${fmt(s.uploaded_count ?? 0)}</strong><span>Uploaded</span></div>
          <div><strong>${money(s.spend_window_usd ?? 0)}</strong><span>Spend ${windowLabel(overview.window_days)}</span></div>
        </div>
        <div class="ops-line" style="margin:2px 0 8px">
          <span class="quota">${target ? `${quotaBlocks(uploadedToday, target)} ${uploadedToday}/${target} today` : `${uploadedToday} today`}</span>
          ${winChip}
        </div>
        <div class="actions">
          <button data-action="generate" data-brand="${esc(id)}" data-upload="0">Generate only</button>
          <button class="gold" data-action="generate" data-brand="${esc(id)}" data-upload="1">Generate &amp; Post now</button>
          <button data-action="filter-brand" data-brand="${esc(id)}">Focus charts</button>
          <button class="ghost" data-action="open-output" data-brand="${esc(id)}" title="Open output/${esc(id)} in Explorer">Open folder</button>
          ${brand.channel_id ? `<a href="https://www.youtube.com/channel/${esc(brand.channel_id)}" target="_blank" rel="noopener"><button class="ghost" type="button">Channel ↗</button></a>` : ""}
        </div>
        ${rendersBlock(id)}
        ${insightsBlock(insights[id])}
        <details class="slots"><summary>Recent posts</summary><ul class="plain">${recentPostsList(s.recent_posts)}</ul></details>
        ${slotEditor(brand)}`;
      container.appendChild(card);
    }
  }

  // ———— Performance table ————
  function renderPerfChips() {
    const el = $("perf-brand-chips");
    if (!el || !overviewCache) return;
    const rows = overviewCache.video_metrics_table || [];
    const counts = {};
    for (const r of rows) counts[r.brand_id] = (counts[r.brand_id] || 0) + 1;
    const ids = Object.keys(counts).sort();
    el.innerHTML =
      `<button class="chip ${!perfBrand ? "active" : ""}" data-perf-brand="">ALL · ${rows.length}</button>` +
      ids
        .map(
          (id) =>
            `<button class="chip ${perfBrand === id ? "active" : ""}" data-perf-brand="${esc(id)}" style="${perfBrand === id ? `color:${brandColor(id)}` : ""}">${esc(brandName(id))} · ${counts[id]}</button>`
        )
        .join("");
  }

  function renderPerformance() {
    const body = $("perf-body");
    if (!body || !overviewCache) return;
    renderPerfChips();
    let rows = (overviewCache.video_metrics_table || []).slice();
    if (perfBrand) rows = rows.filter((r) => r.brand_id === perfBrand);
    if (perfStatus) rows = rows.filter((r) => (r.status || "generated") === perfStatus);
    if (perfQuery) {
      const q = perfQuery.toLowerCase();
      rows = rows.filter((r) => (r.title || "").toLowerCase().includes(q));
    }
    const { key, dir } = perfSort;
    rows.sort((a, b) => {
      let av = a[key], bv = b[key];
      if (key === "date") { av = a.date || ""; bv = b.date || ""; }
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "string") return av.localeCompare(bv) * dir;
      return (av - bv) * dir;
    });

    document.querySelectorAll(".perf-table th.sortable").forEach((th) => {
      th.classList.remove("sorted-asc", "sorted-desc");
      if (th.dataset.sort === key) th.classList.add(dir > 0 ? "sorted-asc" : "sorted-desc");
    });

    if (!rows.length) {
      body.innerHTML = `<tr><td colspan="9"><div class="empty-state">Nothing matches. Generate a Short, then refresh metrics.</div></td></tr>`;
      return;
    }
    body.innerHTML = rows
      .map((v) => {
        const title = esc((v.title || "").slice(0, 78));
        const link = v.url ? `<a href="${esc(v.url)}" target="_blank" rel="noopener">${title}</a>` : title;
        const th = thumbUrl(v.url);
        const color = brandColor(v.brand_id);
        return `<tr>
          <td class="muted small" style="white-space:nowrap">${esc((v.date || "").slice(0, 16))}</td>
          <td>${th ? `<img class="perf-thumb" loading="lazy" src="${esc(th)}" alt="">` : ""}</td>
          <td>${link}</td>
          <td><span class="pill" style="background:${color}22;color:${color}">${esc(brandName(v.brand_id))}</span></td>
          <td><span class="pill ${v.status === "uploaded" ? "green" : "gray"}">${esc(v.status || "")}</span></td>
          <td class="num">${fmt(v.views)}</td>
          <td class="num">${fmt(v.likes)}</td>
          <td class="num">${fmt(v.comments)}</td>
          <td class="num">${v.avg_view_pct != null ? fmt(v.avg_view_pct) + "%" : "—"}</td>
        </tr>`;
      })
      .join("");
  }

  // ———— Spend tab ————
  function renderSpend(overview) {
    const alert = overview.spend_alert || {};
    const spend = Number((overview.totals || {}).spend_window_usd || 0);
    const threshold = Number(alert.threshold_usd || 25);
    const pct = threshold > 0 ? Math.min(100, (spend / threshold) * 100) : 0;
    const ring = $("gauge-ring");
    if (ring) {
      ring.style.setProperty("--gauge-pct", pct.toFixed(1));
      ring.style.setProperty("--gauge-color", pct >= 100 ? "var(--red)" : pct >= 60 ? "var(--gold)" : "var(--cyan)");
    }
    const val = $("gauge-value");
    if (val) val.textContent = money(spend);
    const thr = $("gauge-threshold");
    if (thr) thr.textContent = `of ${money(threshold)} alert line`;
    const cap = $("gauge-caption");
    if (cap) cap.textContent = windowLabel(overview.window_days);

    const stats = $("gauge-stats");
    if (stats) {
      const recent = overview.recent_spend || [];
      const uploadsInWin = (overview.videos || []).filter((v) => v.status === "uploaded" && inWindow(v.date)).length;
      const perUpload = uploadsInWin ? spend / uploadsInWin : 0;
      stats.innerHTML = `
        <div><strong>${recent.length}</strong><span>premium assets</span></div>
        <div><strong>${money(recent.length ? spend / recent.length : 0)}</strong><span>avg / asset</span></div>
        <div><strong>${money(perUpload)}</strong><span>per upload</span></div>`;
    }

    const list = overview.recent_spend || [];
    const el = $("spend-list");
    if (!el) return;
    if (!list.length) {
      el.innerHTML = `<div class="empty-state">No premium asset spend in this window — everything ran on the standard tier.</div>`;
      return;
    }
    el.innerHTML = `<ul class="plain">${list
      .slice()
      .reverse()
      .slice(0, 25)
      .map(
        (e) => `<li>
          <span class="muted small">${esc(e.date || "")}</span>
          <span class="pill ${e.tier === "premium_video" ? "violet" : "amber"}">${esc(e.tier || "")}</span>
          <span class="pill">${esc(e.provider || "")}</span>
          <span class="pill amber">${money(e.cost_usd)}</span>
          <span class="pill" style="background:${brandColor(e.brand_id)}22;color:${brandColor(e.brand_id)}">${esc(brandName(e.brand_id))}</span>
          ${esc((e.video_title || "").slice(0, 60))}
        </li>`
      )
      .join("")}</ul>`;
  }

  // ———— Jobs / pipeline ————
  async function generate(brandId, upload, btn) {
    if (
      upload &&
      !confirm(
        `Generate AND upload a new Short for "${brandName(brandId)}" now?\n\nThis launches the full pipeline (LLM → TTS → images → video → Selenium upload).`
      )
    ) {
      return;
    }
    if (btn) btn.disabled = true;
    try {
      const job = await api("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ brand_id: brandId, upload }),
      });
      toast(`Started: ${job.label}`);
      selectJob(job.id);
      await refreshJobs();
      setSection("pipeline");
    } catch (e) {
      toast(e.message, true);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async function saveSlots(brandId, btn) {
    const details = btn.closest("details");
    const payload = {};
    for (const row of details.querySelectorAll(".slot-row")) {
      const slot = {};
      for (const input of row.querySelectorAll("input")) {
        if (input.value.trim()) slot[input.dataset.k] = input.value.trim();
      }
      if (Object.keys(slot).length) payload[row.dataset.slot] = slot;
    }
    btn.disabled = true;
    try {
      await api(`/api/brands/${brandId}/slots`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      toast("Publish times saved to brand manifest.");
    } catch (e) {
      toast(e.message, true);
    } finally {
      btn.disabled = false;
    }
  }

  async function openOutput(brandId) {
    try {
      await api(`/api/open-output/${encodeURIComponent(brandId)}`, { method: "POST" });
      toast(`Opened output/${brandId} in Explorer.`);
    } catch (e) {
      toast(e.message, true);
    }
  }

  async function startMetricsRefresh() {
    try {
      const job = await api("/api/metrics/refresh", { method: "POST" });
      toast("Metrics refresh started — overview reloads when it finishes.");
      selectJob(job.id);
      await refreshJobs();
      setSection("pipeline");
    } catch (e) {
      toast(e.message, true);
    }
  }

  function selectJob(jobId) {
    selectedJob = jobId;
    logOffset = 0;
    const logEl = $("log-view");
    if (logEl) logEl.textContent = "";
    if (window.MPV2PipelineTheater) MPV2PipelineTheater.onJobSelected();
    renderJobs();
  }

  function anyJobRunning() {
    return jobsCache.some((j) => j.status === "running");
  }

  function renderJobs() {
    const body = $("jobs-body");
    if (!body) return;
    if (!jobsCache.length) {
      body.innerHTML = '<tr><td colspan="5" class="muted">No jobs yet — kick one off from a brand card or Ctrl+K.</td></tr>';
      return;
    }
    body.innerHTML = jobsCache
      .map((j) => {
        const pillClass =
          j.status === "running" ? "pill amber" : j.status === "succeeded" ? "pill green" : j.status === "interrupted" ? "pill gray" : "pill red";
        const cancel =
          j.status === "running"
            ? `<button class="danger small" data-action="cancel-job" data-job="${j.id}">Cancel</button>`
            : "";
        return `<tr class="selectable ${selectedJob === j.id ? "selected" : ""}" data-action="select-job" data-job="${j.id}">
          <td class="muted" style="white-space:nowrap">${esc(j.started_at)}</td>
          <td><span class="status-dot ${esc(j.status)}"></span>${esc(j.label)}</td>
          <td class="muted small">${esc(durationBetween(j.started_at, j.finished_at))}</td>
          <td><span class="${pillClass}">${esc(j.status)}</span></td>
          <td>${cancel}</td>
        </tr>`;
      })
      .join("");
  }

  async function refreshJobs() {
    let jobs;
    try {
      jobs = await api("/api/jobs");
    } catch (e) {
      return;
    }
    for (const j of jobs) {
      const prev = jobStatusMap[j.id];
      if (prev === "running" && j.status !== "running") {
        toast(j.status === "succeeded" ? `Finished: ${j.label}` : `Ended (${j.status}): ${j.label}`, j.status !== "succeeded");
        refreshOverview(true).catch(() => {});
        fetchHealth().catch(() => {});
      }
      jobStatusMap[j.id] = j.status;
      jobLabelMap[j.id] = j.label;
    }
    jobsCache = jobs;
    renderJobs();

    if (selectedJob && window.MPV2PipelineTheater) {
      MPV2PipelineTheater.onLogUpdate({
        fullText: ($("log-view") && $("log-view").textContent) || "",
        label: jobLabelMap[selectedJob] || "",
        status: jobStatusMap[selectedJob] || "",
      });
    }
  }

  async function cancelJob(jobId) {
    try {
      await api(`/api/jobs/${jobId}/cancel`, { method: "POST" });
      toast("Job cancelled.");
      await refreshJobs();
    } catch (e) {
      toast(e.message, true);
    }
  }

  async function pollLog() {
    if (!selectedJob || document.hidden) return;
    try {
      const res = await api(`/api/jobs/${selectedJob}/log?offset=${logOffset}`);
      const el = $("log-view");
      if (res.text && el) {
        const stick = el.scrollTop + el.clientHeight >= el.scrollHeight - 24;
        el.textContent += res.text;
        logOffset = res.offset;
        if (stick) el.scrollTop = el.scrollHeight;
      }
      if (res.status) jobStatusMap[selectedJob] = res.status;
      if (window.MPV2PipelineTheater) {
        MPV2PipelineTheater.onLogUpdate({
          fullText: ($("log-view") && $("log-view").textContent) || "",
          label: jobLabelMap[selectedJob] || "",
          status: jobStatusMap[selectedJob] || res.status || "",
        });
      }
    } catch (e) {
      /* ignore */
    }
  }

  // ———— Overview refresh (hash-guarded, no flicker) ————
  function overviewUrl() {
    const q = windowDays == null ? "all" : String(windowDays);
    return `/api/overview?days=${encodeURIComponent(q)}`;
  }

  function renderSyncLabel() {
    const el = $("sync-label");
    if (!el) return;
    el.textContent = lastSyncAt ? `SYNCED ${timeAgo(lastSyncAt.toISOString())}`.toUpperCase() : "SYNCING…";
    const gen = $("generated-at");
    if (gen && overviewCache) gen.textContent = `Updated ${timeAgo(overviewCache.generated_at)}`;
  }

  async function refreshOverview(force) {
    const [overview, brands, outputs] = await Promise.all([
      api(overviewUrl()),
      api("/api/brands"),
      api("/api/outputs").catch(() => ({})),
    ]);
    const hash = JSON.stringify([overview, brands, outputs, windowDays, brandFilter]);
    lastSyncAt = new Date();
    renderSyncLabel();
    if (!force && hash === lastDataHash) return;
    lastDataHash = hash;
    brandsCache = brands;
    overviewCache = overview;
    outputsCache = outputs;

    renderAlerts();
    renderTotals(overview);
    renderSpendBanner(overview);
    renderOpsBrief();
    const brandsEl = $("brands");
    const editing = document.activeElement && brandsEl && brandsEl.contains(document.activeElement);
    if (!editing) renderBrands(overview);
    renderRecentPosts(overview);
    renderPerformance();
    renderSpend(overview);
    renderChartsAndHeroes(overview);
  }

  // ———— Command palette ————
  function paletteActions() {
    const actions = [];
    for (const b of brandsCache) {
      const name = b.channel_name || b.brand_id;
      actions.push({ ico: "▶", label: `Generate — ${name}`, hint: "render only", run: () => generate(b.brand_id, false) });
      actions.push({ ico: "⇧", label: `Generate & Post — ${name}`, hint: "full pipeline", danger: true, run: () => generate(b.brand_id, true) });
      actions.push({ ico: "◎", label: `Focus charts — ${name}`, hint: "filter", run: () => { brandFilter = b.brand_id; if (overviewCache) renderChartsAndHeroes(overviewCache); setSection("overview"); } });
      actions.push({ ico: "▤", label: `Open output folder — ${name}`, hint: "explorer", run: () => openOutput(b.brand_id) });
      if (b.channel_id) {
        actions.push({ ico: "↗", label: `Open channel — ${name}`, hint: "youtube", run: () => window.open(`https://www.youtube.com/channel/${b.channel_id}`, "_blank") });
      }
    }
    actions.push({ ico: "⟳", label: "Refresh YouTube metrics", hint: "M", run: startMetricsRefresh });
    actions.push({ ico: "⟲", label: "Re-sync dashboard data", hint: "R", run: () => refreshOverview(true).then(() => toast("Data re-synced.")).catch((e) => toast(e.message, true)) });
    actions.push({ ico: "♥", label: "Run systems check", hint: "health", run: () => fetchHealth(true) });
    for (const [i, sec] of ["overview", "brands", "performance", "spend", "pipeline", "help"].entries()) {
      actions.push({ ico: String(i + 1), label: `Go to ${sec[0].toUpperCase() + sec.slice(1)}`, hint: "tab", run: () => setSection(sec) });
    }
    for (const d of [7, 14, 30, null]) {
      actions.push({ ico: "◷", label: `Window: ${d == null ? "All-time" : d + " days"}`, hint: "range", run: () => setWindow(d) });
    }
    actions.push({ ico: "?", label: "Keyboard shortcuts", hint: "?", run: () => toggleOverlay("keys-overlay", true) });
    return actions;
  }

  function fuzzyScore(label, q) {
    const l = label.toLowerCase();
    if (!q) return 1;
    if (l.startsWith(q)) return 100;
    if (l.includes(q)) return 60;
    let li = 0;
    for (const ch of q) {
      li = l.indexOf(ch, li);
      if (li === -1) return 0;
      li++;
    }
    return 20;
  }

  function renderCmdk() {
    const input = $("cmdk-input");
    const list = $("cmdk-list");
    const q = (input.value || "").trim().toLowerCase();
    cmdkMatches = paletteActions()
      .map((a) => ({ a, score: fuzzyScore(a.label, q) }))
      .filter((x) => x.score > 0)
      .sort((x, y) => y.score - x.score)
      .slice(0, 12)
      .map((x) => x.a);
    cmdkIndex = Math.min(cmdkIndex, Math.max(0, cmdkMatches.length - 1));
    list.innerHTML = cmdkMatches
      .map(
        (a, i) =>
          `<li class="${i === cmdkIndex ? "active" : ""} ${a.danger ? "danger-item" : ""}" data-cmdk-i="${i}">
            <span class="ico">${esc(a.ico)}</span><span>${esc(a.label)}</span><span class="hint">${esc(a.hint || "")}</span>
          </li>`
      )
      .join("") || `<li class="muted" style="cursor:default">No matching commands.</li>`;
  }

  function toggleOverlay(id, show) {
    const el = $(id);
    if (!el) return;
    el.hidden = show === undefined ? !el.hidden : !show;
    if (id === "cmdk" && !el.hidden) {
      const input = $("cmdk-input");
      input.value = "";
      cmdkIndex = 0;
      renderCmdk();
      setTimeout(() => input.focus(), 10);
    }
  }

  function runCmdk(index) {
    const action = cmdkMatches[index];
    if (!action) return;
    toggleOverlay("cmdk", false);
    action.run();
  }

  function setWindow(days) {
    windowDays = days;
    document.querySelectorAll(".days-picker button").forEach((b) => {
      const v = b.dataset.days === "all" ? null : Number(b.dataset.days);
      b.classList.toggle("active", v === days || (v !== null && days !== null && v === days));
    });
    refreshOverview(true).catch((e) => toast(e.message, true));
  }

  // ———— Events ————
  function bindEvents() {
    document.querySelectorAll(".nav-tabs button").forEach((btn) => {
      btn.addEventListener("click", () => setSection(btn.dataset.section));
    });

    document.querySelectorAll(".days-picker button").forEach((btn) => {
      btn.addEventListener("click", () => {
        const val = btn.dataset.days;
        setWindow(val === "all" ? null : Number(val));
      });
    });

    $("refresh-metrics").addEventListener("click", async () => {
      const btn = $("refresh-metrics");
      btn.disabled = true;
      try {
        await startMetricsRefresh();
      } finally {
        btn.disabled = false;
      }
    });

    $("clear-filter")?.addEventListener("click", () => {
      brandFilter = null;
      if (overviewCache) renderChartsAndHeroes(overviewCache);
      toast("Tracking all brands");
    });

    $("health-strip")?.addEventListener("click", () => fetchHealth(true));
    $("cmdk-btn")?.addEventListener("click", () => toggleOverlay("cmdk"));

    $("cmdk-input")?.addEventListener("input", () => {
      cmdkIndex = 0;
      renderCmdk();
    });

    $("cmdk-input")?.addEventListener("keydown", (ev) => {
      if (ev.key === "ArrowDown") {
        ev.preventDefault();
        cmdkIndex = Math.min(cmdkIndex + 1, cmdkMatches.length - 1);
        renderCmdk();
      } else if (ev.key === "ArrowUp") {
        ev.preventDefault();
        cmdkIndex = Math.max(cmdkIndex - 1, 0);
        renderCmdk();
      } else if (ev.key === "Enter") {
        ev.preventDefault();
        runCmdk(cmdkIndex);
      }
    });

    $("cmdk")?.addEventListener("click", (ev) => {
      if (ev.target === $("cmdk")) toggleOverlay("cmdk", false);
      const li = ev.target.closest("[data-cmdk-i]");
      if (li) runCmdk(Number(li.dataset.cmdkI));
    });

    $("keys-overlay")?.addEventListener("click", (ev) => {
      if (ev.target === $("keys-overlay")) toggleOverlay("keys-overlay", false);
    });

    document.querySelectorAll(".perf-table th.sortable").forEach((th) => {
      th.addEventListener("click", () => {
        const key = th.dataset.sort;
        if (perfSort.key === key) perfSort.dir *= -1;
        else perfSort = { key, dir: key === "title" || key === "brand_id" || key === "status" ? 1 : -1 };
        renderPerformance();
      });
    });

    $("perf-status")?.addEventListener("change", (ev) => {
      perfStatus = ev.target.value;
      renderPerformance();
    });

    $("perf-search")?.addEventListener("input", (ev) => {
      perfQuery = ev.target.value;
      renderPerformance();
    });

    document.body.addEventListener("click", (ev) => {
      const jump = ev.target.closest("[data-jump]");
      if (jump && !ev.target.closest("[data-action]")) {
        setSection(jump.dataset.jump);
        return;
      }
      const alertAction = ev.target.closest("[data-alert-action]");
      if (alertAction && alertAction.dataset.alertAction === "metrics") {
        startMetricsRefresh();
        return;
      }
      const chip = ev.target.closest("[data-perf-brand]");
      if (chip) {
        perfBrand = chip.dataset.perfBrand || null;
        renderPerformance();
        return;
      }
      const btn = ev.target.closest("[data-action]");
      if (!btn) return;
      const action = btn.dataset.action;
      if (action === "generate") {
        generate(btn.dataset.brand, btn.dataset.upload === "1", btn);
      } else if (action === "save-slots") {
        saveSlots(btn.dataset.brand, btn);
      } else if (action === "cancel-job") {
        ev.stopPropagation();
        cancelJob(btn.dataset.job);
      } else if (action === "select-job") {
        selectJob(btn.dataset.job);
      } else if (action === "open-output") {
        openOutput(btn.dataset.brand);
      } else if (action === "filter-brand") {
        brandFilter = brandFilter === btn.dataset.brand ? null : btn.dataset.brand;
        if (overviewCache) renderChartsAndHeroes(overviewCache);
        if (btn.closest("#brands")) setSection("overview");
        toast(brandFilter ? `Tracking ${brandName(brandFilter)}` : "Tracking all brands");
      }
    });

    document.addEventListener("keydown", (ev) => {
      const inField = /^(INPUT|TEXTAREA|SELECT)$/.test((ev.target.tagName || "").toUpperCase());
      if (ev.key === "Escape") {
        toggleOverlay("cmdk", false);
        toggleOverlay("keys-overlay", false);
        if (inField) ev.target.blur();
        return;
      }
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "k") {
        ev.preventDefault();
        toggleOverlay("cmdk");
        return;
      }
      if (inField || ev.ctrlKey || ev.metaKey || ev.altKey) return;
      const sections = ["overview", "brands", "performance", "spend", "pipeline", "help"];
      if (/^[1-6]$/.test(ev.key)) {
        setSection(sections[Number(ev.key) - 1]);
      } else if (ev.key.toLowerCase() === "r") {
        refreshOverview(true).then(() => toast("Data re-synced.")).catch((e) => toast(e.message, true));
      } else if (ev.key.toLowerCase() === "m") {
        startMetricsRefresh();
      } else if (ev.key === "/") {
        ev.preventDefault();
        setSection("performance");
        setTimeout(() => $("perf-search")?.focus(), 30);
      } else if (ev.key === "?") {
        toggleOverlay("keys-overlay");
      }
    });
  }

  // ———— Pollers ————
  function jobsLoop() {
    const delay = anyJobRunning() || activeSection() === "pipeline" ? 2500 : 8000;
    setTimeout(async () => {
      if (!document.hidden) await refreshJobs().catch(() => {});
      jobsLoop();
    }, delay);
  }

  // Catch up the moment the tab becomes visible again (polling pauses while hidden).
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) return;
    refreshJobs().catch(() => {});
    pollLog();
    refreshOverview(false).catch(() => {});
    renderSyncLabel();
  });

  // ———— Boot ————
  bindEvents();
  tickClock();
  setInterval(tickClock, 1000);
  setSection("overview");
  refreshOverview(true).catch((e) => toast(e.message, true));
  fetchHealth().catch(() => {});
  refreshJobs().catch(() => {});
  jobsLoop();
  setInterval(pollLog, 1500);
  setInterval(() => refreshOverview(false).catch(() => {}), 45000);
  setInterval(() => fetchHealth().catch(() => {}), 90000);
  setInterval(renderSyncLabel, 5000);
  setInterval(() => { if (!document.hidden && overviewCache) renderOpsBrief(); }, 30000);
})();
