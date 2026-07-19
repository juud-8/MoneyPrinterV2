/* EL JEFE — health, ops brief, attention, command deck */
(function (global) {
  const M = global.MPV2;
  const { state, $, esc, fmt, money, parseWhen, timeAgo, todayStr, windowLabel, windowCutoff, brandColor, brandName, toast, api } = M;

  const HEALTH_ITEMS = [
    { key: "ollama", label: "Ollama (local LLM)", fix: "Start Ollama: scripts\\ensure_ollama.ps1" },
    { key: "gemini", label: "Gemini key", fix: "Set gemini_api_key in config.json or GEMINI_API_KEY" },
    { key: "youtube_data", label: "YouTube Data key", fix: "Set youtube_api_key (YouTube Data API v3) in config.json" },
    { key: "tts", label: "TTS key (Fish/ElevenLabs)", fix: "Optional: fish_audio_api_key or elevenlabs_api_key" },
    { key: "imagemagick", label: "ImageMagick", fix: "Set imagemagick_path to magick.exe in config.json" },
    { key: "profiles", label: "Firefox profiles", fix: "Set firefox_profile in brand manifest or config.json" },
    { key: "metrics", label: "Metrics freshness", fix: "Hit ⟳ Metrics or run src/youtube_metrics.py" },
    { key: "disk", label: "Disk space", fix: "Free space under the project drive (need >3 GB)" },
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
    if (!state.healthCache) {
      label.textContent = "SYSTEMS…";
      label.className = "health-label unknown";
      leds.innerHTML = HEALTH_ITEMS.map(() => '<span class="led"></span>').join("");
      return;
    }
    const states = healthStates(state.healthCache);
    leds.innerHTML = HEALTH_ITEMS.map((item) => {
      const st = states[item.key] || "warn";
      const detail = healthDetail(item.key, state.healthCache);
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

  function renderHealthModal() {
    const rows = $("health-detail-rows");
    if (!rows) return;
    const h = state.healthCache;
    if (!h) {
      rows.innerHTML = `<div class="muted">No health data yet.</div>`;
      return;
    }
    const states = healthStates(h);
    rows.innerHTML = HEALTH_ITEMS.map((item) => {
      const st = states[item.key] || "warn";
      const detail = healthDetail(item.key, h);
      return `<div class="health-row">
        <span class="led ${st}"></span>
        <div>
          <strong>${esc(item.label)}</strong> · ${st.toUpperCase()}
          ${detail ? `<div class="fix">${esc(detail)}</div>` : ""}
          ${st !== "ok" ? `<div class="fix">Fix: ${esc(item.fix)}</div>` : ""}
        </div>
      </div>`;
    }).join("");
  }

  let healthRetryTimer = null;

  async function fetchHealth(force) {
    try {
      state.healthCache = await api(`/api/health${force ? "?force=1" : ""}`);
      renderHealth();
      const states = healthStates(state.healthCache);
      const failing = HEALTH_ITEMS.filter((i) => states[i.key] === "bad").map((i) => i.label);
      if (force) {
        toast(failing.length ? `Systems check: ${failing.join(" · ")} DOWN` : "Systems check: all nominal", failing.length > 0);
      }
      clearTimeout(healthRetryTimer);
      if (failing.length && !document.hidden) {
        healthRetryTimer = setTimeout(() => fetchHealth(true).catch(() => {}), 20000);
      }
    } catch (e) {
      state.healthCache = null;
      renderHealth();
    }
  }

  function nextWindowInfo(slots) {
    const now = new Date();
    let best = null;
    for (const [name, slot] of Object.entries(slots || {})) {
      const start = (slot || {}).window_start;
      if (!/^\d{2}:\d{2}$/.test(start || "")) continue;
      const end = (slot || {}).window_end;
      const hint = (slot || {}).scheduler_start_hint;
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
      let st, at;
      if (now >= startAt && now <= endAt) {
        st = "live";
        at = endAt;
      } else if (now < startAt) {
        st = "soon";
        at = startAt;
      } else {
        st = "next";
        at = mk(start, 1);
      }
      const cand = { name, state: st, at, start, end, hint };
      if (!best || (st === "live" && best.state !== "live") || (best.state !== "live" && at < best.at)) best = cand;
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

  function brandsForOps() {
    if (state.brandsCache.length) return state.brandsCache;
    const meta = (state.opsCache && state.opsCache.brands_meta) || [];
    if (meta.length) return meta;
    return ((state.overviewCache && state.overviewCache.brands) || []).map((b) => ({
      brand_id: b.brand_id,
      channel_name: b.channel_name,
    }));
  }

  function videosForOps() {
    if (state.overviewCache && state.overviewCache.videos) return state.overviewCache.videos;
    return (state.opsCache && state.opsCache.videos) || [];
  }

  function renderOpsBrief() {
    const el = $("ops-brief");
    if (!el) return;
    const opsDate = $("ops-date");
    if (opsDate) {
      opsDate.textContent = new Date()
        .toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" })
        .toUpperCase();
    }
    const today = todayStr();
    const videos = videosForOps();
    const rows = [];
    const visible = brandsForOps();
    for (const brand of visible) {
      const id = brand.brand_id;
      const todays = videos.filter((v) => v.brand_id === id && String(v.date || "").startsWith(today));
      const uploadedToday = todays.filter((v) => v.status === "uploaded").length;
      const target = Number(brand.shorts_per_day || 0);
      const win = nextWindowInfo(brand.publish_slots);
      let chip = `<span class="win-chip">no windows set</span>`;
      if (win) {
        const hint = win.hint ? ` · task ${esc(win.hint)}` : "";
        if (win.state === "live") {
          chip = `<span class="win-chip live">● LIVE · ${esc(win.name)} until ${esc(win.end || "")}${hint}</span>`;
        } else if (win.state === "soon") {
          chip = `<span class="win-chip soon">next: ${esc(win.name)} ${esc(win.start)} · in ${humanUntil(win.at)}${hint}</span>`;
        } else {
          chip = `<span class="win-chip">next: ${esc(win.name)} ${esc(win.start)} tomorrow${hint}</span>`;
        }
      }
      const quotaHtml = target
        ? `<span class="quota" title="uploaded today vs shorts_per_day">${quotaBlocks(uploadedToday, target)} ${uploadedToday}/${target}</span>`
        : `<span class="quota muted">${uploadedToday} today</span>`;
      rows.push(`
        <div class="ops-line">
          <span class="brand-dot" style="background:${brandColor(id)}"></span>
          <span class="name">${esc(brandName(id))}</span>
          ${quotaHtml}
          ${todays.length > uploadedToday ? `<span class="pill">${todays.length - uploadedToday} generated</span>` : ""}
          ${chip}
        </div>`);
    }
    el.innerHTML = rows.join("") || `<div class="empty-state">No brands under <code>brands/</code>. Add a manifest to start.</div>`;
  }

  function computeAlerts() {
    const alerts = [];
    const videos = videosForOps();
    const spendAlert = (state.overviewCache && state.overviewCache.spend_alert) || (state.opsCache && state.opsCache.spend_alert) || {};
    const rej = (state.overviewCache && state.overviewCache.rejection_summary) || (state.opsCache && state.opsCache.rejection_summary) || {};

    const silent = videos.filter((v) => v.status === "uploaded" && !v.url);
    if (silent.length) {
      alerts.push({
        sev: "red",
        label: "UPLOAD",
        text: `${silent.length} upload(s) logged with no URL — possible silent failure.`,
        jump: "performance",
      });
    }

    const failedJobs = state.jobsCache.filter((j) => j.status === "failed");
    if (failedJobs.length) {
      alerts.push({
        sev: "red",
        label: "PIPELINE",
        text: `${failedJobs.length} failed job(s) in history — check the terminal log.`,
        jump: "pipeline",
      });
    }

    if (spendAlert.triggered) {
      alerts.push({
        sev: "red",
        label: "SPEND",
        text: `Premium spend ${money(spendAlert.recent_spend_usd)} over the ${money(spendAlert.threshold_usd)} alert line.`,
        jump: "spend",
      });
    }

    if (state.healthCache) {
      const states = healthStates(state.healthCache);
      if (states.ollama === "bad") {
        alerts.push({ sev: "red", label: "SYSTEMS", text: "Ollama is unreachable — generation will fail or fall back.", action: "health" });
      }
      if (states.gemini === "bad") {
        alerts.push({ sev: "amber", label: "SYSTEMS", text: "No Gemini key — quality LLM + image gen degraded.", action: "health" });
      }
      if (states.profiles === "bad") {
        alerts.push({ sev: "red", label: "SYSTEMS", text: `Firefox profile missing: ${healthDetail("profiles", state.healthCache)}`, action: "health" });
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

    if ((rej.duration_aborts || 0) > 0) {
      alerts.push({
        sev: "amber",
        label: "QUALITY",
        text: `${rej.duration_aborts} generation(s) aborted by the duration gate in this window.`,
        jump: "spend",
      });
    }

    const backlog = videos.filter((v) => v.status !== "uploaded" && !v.url);
    if (backlog.length) {
      alerts.push({
        sev: "info",
        label: "REVIEW",
        text: `${backlog.length} generated render(s) not uploaded — use Review Bay.`,
        jump: "brands",
      });
    }

    if (state.archiveSongs.length) {
      alerts.push({
        sev: "amber",
        label: "SONG",
        text: `${state.archiveSongs.length} archive-song episode(s) awaiting audio — place song.wav then resume CLI.`,
        action: "songs",
      });
    }

    return alerts;
  }

  function renderAlerts() {
    const el = $("ops-alerts");
    if (!el) return;
    const prevLen = state.alertsCache.length;
    state.alertsCache = computeAlerts();
    if (!state.alertsCache.length) {
      el.innerHTML = `<div class="all-clear">ALL CLEAR — NO ANOMALIES DETECTED</div>`;
      return;
    }
    const pulse = state.alertsCache.length > prevLen && prevLen > 0;
    el.innerHTML =
      state.alertsCache
        .slice(0, 6)
        .map(
          (a, i) => `
        <div class="alert-line ${a.sev}${pulse && i === 0 ? " new-pulse" : ""}" ${a.jump ? `data-jump="${esc(a.jump)}"` : ""} ${a.action ? `data-alert-action="${esc(a.action)}"` : ""}>
          <span class="sev">${esc(a.label)}</span>
          <span>${esc(a.text)}</span>
        </div>`
        )
        .join("") + (state.alertsCache.length > 6 ? `<p class="muted small">+${state.alertsCache.length - 6} more</p>` : "");
  }

  function animateKpi(el) {
    el.style.transform = "scale(1.04)";
    setTimeout(() => (el.style.transform = "scale(1)"), 180);
  }

  function growthDelta(brandIds) {
    const growth = (state.overviewCache && state.overviewCache.channel_growth) || {};
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
    if (!totalsEl || !data) return;
    const snaps = data.channel_snapshots || (state.opsCache && state.opsCache.channel_snapshots) || {};
    const brandIds = M.allBrandIds();
    const subsTotal = Object.values(snaps).reduce((acc, s) => acc + (Number(s.subscribers) || 0), 0);
    const chViews = Object.values(snaps).reduce((acc, s) => acc + (Number(s.total_views) || 0), 0);
    const delta = growthDelta(brandIds);
    const videos = data.videos || videosForOps();
    const winPosts = videos.filter((v) => M.inWindow(v.date));
    const winUploaded = winPosts.filter((v) => v.status === "uploaded").length;
    const today = todayStr();
    const uploadedToday = videos.filter((v) => String(v.date || "").startsWith(today) && v.status === "uploaded").length;
    const targetToday = brandsForOps().reduce((acc, b) => acc + (Number(b.shorts_per_day) || 0), 0);
    const t = data.totals || {};
    const alerts = state.alertsCache;

    const items = [
      {
        value: fmt(subsTotal),
        label: "Subscribers",
        sub: delta == null ? "run ⟳ metrics for Δ" : `${delta >= 0 ? "+" : ""}${fmt(delta)} in ${windowLabel(data.window_days)}`,
        subClass: delta == null ? "" : delta >= 0 ? "up" : "down",
        accent: "var(--brass)",
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
        accent: "var(--brass)",
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
        accent: "var(--brass)",
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
    const alert = (overview && overview.spend_alert) || {};
    const el = $("spend-alert");
    if (!el) return;
    if (alert.triggered) {
      el.classList.add("visible");
      el.textContent = `Premium spend ${money(alert.recent_spend_usd)} exceeds the ${money(alert.threshold_usd)} alert line (${windowLabel(overview.window_days)}). Review asset_strategy if unintended.`;
    } else {
      el.classList.remove("visible");
    }
  }

  function renderDeckCtas() {
    const el = $("deck-ctas");
    if (!el) return;
    const brands = brandsForOps();
    const primary = brands.find((b) => b.is_active) || brands[0];
    const parts = [];
    if (primary) {
      parts.push(`<button class="primary" data-action="generate" data-brand="${esc(primary.brand_id)}" data-upload="0">Generate — ${esc(brandName(primary.brand_id))}</button>`);
      parts.push(`<button class="gold" data-action="generate" data-brand="${esc(primary.brand_id)}" data-upload="1">Generate &amp; Post — ${esc(brandName(primary.brand_id))}</button>`);
    }
    parts.push(`<button class="ghost" data-action="metrics-refresh">⟳ Metrics</button>`);
    parts.push(`<button class="ghost" data-action="open-health">Systems</button>`);
    el.innerHTML = parts.join("");

    const insightsEl = $("insights-cta");
    if (!insightsEl) return;
    const insights = (state.overviewCache && state.overviewCache.insights) || (state.opsCache && state.opsCache.insights) || {};
    const active = Object.entries(insights).filter(([, v]) => v && v.active && v.top && v.top.length);
    if (!active.length) {
      insightsEl.hidden = true;
      insightsEl.innerHTML = "";
      return;
    }
    insightsEl.hidden = false;
    insightsEl.innerHTML = active
      .slice(0, 3)
      .map(([id, ins]) => {
        const top = ins.top[0];
        return `<button class="ghost" data-action="generate" data-brand="${esc(id)}" data-upload="0" title="Insights steering is already on for this brand">Double down — ${esc(brandName(id))}: “${esc((top.title || "").slice(0, 40))}”</button>`;
      })
      .join("");
  }

  function renderReviewBay() {
    const el = $("review-bay-overview");
    if (!el) return;
    const brands = brandsForOps();
    const rows = [];
    for (const b of brands) {
      const files = state.outputsCache[b.brand_id] || [];
      if (!files.length) continue;
      const f = files[0];
      rows.push(`
        <div class="review-row">
          <span class="pill" style="background:${brandColor(b.brand_id)}22;color:${brandColor(b.brand_id)}">${esc(brandName(b.brand_id))}</span>
          <span class="fname" style="font-family:var(--mono);font-size:0.78rem">${esc(f.name)}</span>
          <span class="muted small">${esc(f.modified)} · ${f.size_mb} MB</span>
          <button class="ghost small" data-action="open-output" data-brand="${esc(b.brand_id)}">Open folder</button>
          <button class="gold small" data-action="generate" data-brand="${esc(b.brand_id)}" data-upload="1">Approve &amp; Post</button>
        </div>`);
    }
    if (!rows.length) {
      el.innerHTML = "";
      return;
    }
    el.innerHTML = `<div class="band-label" style="margin-top:8px">Review Bay</div>${rows.join("")}`;
  }

  function renderSongBay() {
    const el = $("song-bay");
    if (!el) return;
    if (!state.archiveSongs.length) {
      el.innerHTML = "";
      return;
    }
    el.innerHTML =
      `<div class="band-label" style="margin-top:8px">Archive Song — awaiting audio</div>` +
      state.archiveSongs
        .map(
          (s) => `
        <div class="song-row">
          <span class="pill amber">awaiting_song_audio</span>
          <span class="pill">${esc(s.brand_id)}</span>
          <span style="font-family:var(--mono);font-size:0.78rem">${esc(s.episode_id)}</span>
          ${s.topic ? `<span class="muted small">${esc(String(s.topic).slice(0, 50))}</span>` : ""}
          <button class="ghost small" data-action="open-episode" data-brand="${esc(s.brand_id)}" data-episode="${esc(s.episode_id)}">Open episode folder</button>
        </div>`
        )
        .join("");
  }

  async function loadArchiveSongs() {
    try {
      state.archiveSongs = await api("/api/archive-songs");
    } catch (e) {
      state.archiveSongs = [];
    }
    renderSongBay();
  }

  async function runPreflight() {
    try {
      const job = await api("/api/preflight", { method: "POST" });
      toast("Preflight started");
      if (M.selectJob) M.selectJob(job.id);
      if (M.refreshJobs) await M.refreshJobs();
      M.setSection("pipeline");
    } catch (e) {
      toast(e.message, true);
    }
  }

  async function loadWeekly(force) {
    if (state.weeklyCache && !force) {
      renderWeekly(state.weeklyCache);
      return;
    }
    try {
      state.weeklyCache = await api("/api/weekly");
      renderWeekly(state.weeklyCache);
    } catch (e) {
      toast(e.message, true);
    }
  }

  function renderWeekly(data) {
    const cards = $("weekly-cards");
    const text = $("weekly-text");
    if (text) text.textContent = data.text || "";
    if (!cards) return;
    const t = data.totals || {};
    const rej = data.rejection_summary || {};
    cards.innerHTML = `
      <div class="card"><h3>Posts (7d)</h3><strong style="font-family:var(--mono);font-size:1.6rem">${fmt((data.recent_videos || []).length)}</strong><p class="muted small">${fmt(t.uploaded)} uploaded all-time tracked</p></div>
      <div class="card"><h3>Premium spend (7d)</h3><strong style="font-family:var(--mono);font-size:1.6rem">${money(t.spend_window_usd)}</strong><p class="muted small">${money(t.spend_all_time_usd)} all-time</p></div>
      <div class="card"><h3>Cost / uploaded short</h3><strong style="font-family:var(--mono);font-size:1.6rem">${data.cost_per_uploaded_short_usd != null ? money(data.cost_per_uploaded_short_usd) : "—"}</strong><p class="muted small">proxy · window spend ÷ uploaded count</p></div>
      <div class="card"><h3>Quality gates</h3><strong style="font-family:var(--mono);font-size:1.6rem">${fmt(rej.duration_aborts || 0)}</strong><p class="muted small">${fmt(rej.topic_rejections || 0)} topic rejects · ${fmt(rej.duration_retries || 0)} retries</p></div>`;
  }

  Object.assign(M, {
    HEALTH_ITEMS,
    healthStates,
    healthDetail,
    renderHealth,
    renderHealthModal,
    fetchHealth,
    nextWindowInfo,
    humanUntil,
    quotaBlocks,
    renderOpsBrief,
    computeAlerts,
    renderAlerts,
    growthDelta,
    renderTotals,
    renderSpendBanner,
    renderDeckCtas,
    renderReviewBay,
    renderSongBay,
    loadArchiveSongs,
    runPreflight,
    loadWeekly,
    renderWeekly,
  });
})(window);
