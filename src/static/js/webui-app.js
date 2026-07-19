/* EL JEFE — bootstrap / events / refresh loop */
(function (global) {
  const M = global.MPV2;
  const { state, $, toast, api, overviewUrl, opsUrl, setSection, toggleOverlay, tickClock, updateHeroVisibility } = M;

  function renderSyncLabel() {
    const el = $("sync-label");
    if (!el) return;
    el.textContent = state.lastSyncAt ? `SYNCED ${M.timeAgo(state.lastSyncAt)}`.toUpperCase() : "SYNCING…";
    const gen = $("generated-at");
    if (gen && state.overviewCache) gen.textContent = `Updated ${M.timeAgo(state.overviewCache.generated_at)}`;
  }

  async function refreshOps() {
    try {
      const ops = await api(opsUrl());
      const hash = JSON.stringify([ops.generated_at, ops.totals, ops.spend_alert, state.windowDays]);
      state.opsCache = ops;
      state.lastSyncAt = new Date();
      renderSyncLabel();
      if (hash === state.lastOpsHash && state.overviewCache) {
        M.renderOpsBrief();
        M.renderAlerts();
        M.renderDeckCtas();
        return;
      }
      state.lastOpsHash = hash;
      if (!state.brandsCache.length && ops.brands_meta) {
        state.brandsCache = ops.brands_meta;
      }
      M.renderOpsBrief();
      M.renderAlerts();
      M.renderTotals(ops);
      M.renderSpendBanner(ops);
      M.renderDeckCtas();
      M.renderReviewBay();
      M.renderSongBay();
    } catch (e) {
      /* ignore soft poll errors */
    }
  }

  async function refreshOverview(force) {
    const [overview, brands, outputs] = await Promise.all([
      api(overviewUrl()),
      api("/api/brands"),
      api("/api/outputs").catch(() => ({})),
    ]);
    const hash = JSON.stringify([overview.generated_at, brands.length, Object.keys(outputs).length, state.windowDays, state.brandFilter]);
    state.lastSyncAt = new Date();
    renderSyncLabel();
    if (!force && hash === state.lastDataHash) {
      M.renderOpsBrief();
      M.renderAlerts();
      return;
    }
    state.lastDataHash = hash;
    state.brandsCache = brands;
    state.overviewCache = overview;
    state.outputsCache = outputs;

    M.renderAlerts();
    M.renderTotals(overview);
    M.renderSpendBanner(overview);
    M.renderOpsBrief();
    M.renderDeckCtas();
    M.renderReviewBay();
    const brandsEl = $("brands");
    const editing = document.activeElement && brandsEl && brandsEl.contains(document.activeElement);
    if (!editing) M.renderBrands(overview);
    M.renderRecentPosts(overview);
    M.renderPerformance();
    M.renderSpend(overview);
    M.renderChartsAndHeroes(overview);
  }

  function setWindow(days) {
    state.windowDays = days;
    document.querySelectorAll(".days-picker button").forEach((b) => {
      const v = b.dataset.days === "all" ? null : Number(b.dataset.days);
      b.classList.toggle("active", (v === null && days === null) || v === days);
    });
    refreshOverview(true).catch((e) => toast(e.message, true));
    refreshOps();
  }

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

    $("refresh-metrics")?.addEventListener("click", () => M.startMetricsRefresh());
    $("resync-btn")?.addEventListener("click", () => {
      refreshOverview(true).then(() => toast("Data re-synced.")).catch((e) => toast(e.message, true));
    });

    $("clear-filter")?.addEventListener("click", () => {
      state.brandFilter = null;
      if (state.overviewCache) M.renderChartsAndHeroes(state.overviewCache);
      toast("Tracking all brands");
    });

    $("toggle-terrain")?.addEventListener("click", () => {
      state.terrainCollapsed = !state.terrainCollapsed;
      localStorage.setItem("mpv2_terrain_collapsed", state.terrainCollapsed ? "1" : "0");
      updateHeroVisibility();
      if (!state.terrainCollapsed && state.overviewCache) M.renderChartsAndHeroes(state.overviewCache);
    });

    $("health-strip")?.addEventListener("click", () => {
      M.renderHealthModal();
      toggleOverlay("health-overlay", true);
    });

    $("run-preflight")?.addEventListener("click", () => M.runPreflight());
    $("health-recheck")?.addEventListener("click", () => M.fetchHealth(true).then(() => M.renderHealthModal()));
    $("weekly-refresh")?.addEventListener("click", () => M.loadWeekly(true));
    $("weekly-copy")?.addEventListener("click", async () => {
      const text = ($("weekly-text") && $("weekly-text").textContent) || "";
      try {
        await navigator.clipboard.writeText(text);
        toast("Weekly review copied");
      } catch (e) {
        toast("Copy failed", true);
      }
    });

    $("cmdk-btn")?.addEventListener("click", () => toggleOverlay("cmdk"));
    $("cmdk-input")?.addEventListener("input", () => {
      state.cmdkIndex = 0;
      M.renderCmdk();
    });
    $("cmdk-input")?.addEventListener("keydown", (ev) => {
      if (ev.key === "ArrowDown") {
        ev.preventDefault();
        state.cmdkIndex = Math.min(state.cmdkIndex + 1, state.cmdkMatches.length - 1);
        M.renderCmdk();
      } else if (ev.key === "ArrowUp") {
        ev.preventDefault();
        state.cmdkIndex = Math.max(state.cmdkIndex - 1, 0);
        M.renderCmdk();
      } else if (ev.key === "Enter") {
        ev.preventDefault();
        M.runCmdk(state.cmdkIndex);
      }
    });

    $("cmdk")?.addEventListener("click", (ev) => {
      if (ev.target === $("cmdk")) toggleOverlay("cmdk", false);
      const li = ev.target.closest("[data-cmdk-i]");
      if (li) M.runCmdk(Number(li.dataset.cmdkI));
    });

    ["keys-overlay", "health-overlay"].forEach((id) => {
      $(id)?.addEventListener("click", (ev) => {
        if (ev.target === $(id)) toggleOverlay(id, false);
      });
    });

    document.querySelectorAll("[data-close-overlay]").forEach((btn) => {
      btn.addEventListener("click", () => toggleOverlay(btn.dataset.closeOverlay, false));
    });

    document.querySelectorAll(".perf-table th.sortable").forEach((th) => {
      th.addEventListener("click", () => {
        const key = th.dataset.sort;
        if (state.perfSort.key === key) state.perfSort.dir *= -1;
        else state.perfSort = { key, dir: key === "title" || key === "brand_id" || key === "status" ? 1 : -1 };
        M.renderPerformance();
      });
    });

    $("perf-status")?.addEventListener("change", (ev) => {
      state.perfStatus = ev.target.value;
      M.renderPerformance();
    });
    $("perf-search")?.addEventListener("input", (ev) => {
      state.perfQuery = ev.target.value;
      M.renderPerformance();
    });

    M.bindPerfScroll();

    document.body.addEventListener("click", (ev) => {
      const jump = ev.target.closest("[data-jump]");
      if (jump && !ev.target.closest("[data-action]")) {
        setSection(jump.dataset.jump);
        return;
      }
      const alertAction = ev.target.closest("[data-alert-action]");
      if (alertAction) {
        const act = alertAction.dataset.alertAction;
        if (act === "metrics") M.startMetricsRefresh();
        else if (act === "health") {
          M.renderHealthModal();
          toggleOverlay("health-overlay", true);
        } else if (act === "songs") {
          setSection("overview");
          M.loadArchiveSongs();
        }
        return;
      }
      const chip = ev.target.closest("[data-perf-brand]");
      if (chip) {
        state.perfBrand = chip.dataset.perfBrand || null;
        M.renderPerformance();
        return;
      }
      const btn = ev.target.closest("[data-action]");
      if (!btn) return;
      const action = btn.dataset.action;
      if (action === "generate") {
        M.generate(btn.dataset.brand, btn.dataset.upload === "1", btn);
      } else if (action === "suggest-trends") {
        M.suggestTrends(btn.dataset.brand, btn);
      } else if (action === "save-slots") {
        M.saveSlots(btn.dataset.brand, btn);
      } else if (action === "cancel-job") {
        ev.stopPropagation();
        M.cancelJob(btn.dataset.job);
      } else if (action === "select-job") {
        M.selectJob(btn.dataset.job);
      } else if (action === "open-output") {
        M.openOutput(btn.dataset.brand);
      } else if (action === "open-episode") {
        M.openEpisode(btn.dataset.brand, btn.dataset.episode);
      } else if (action === "metrics-refresh") {
        M.startMetricsRefresh();
      } else if (action === "open-health") {
        M.renderHealthModal();
        toggleOverlay("health-overlay", true);
      } else if (action === "filter-brand") {
        state.brandFilter = state.brandFilter === btn.dataset.brand ? null : btn.dataset.brand;
        if (state.overviewCache) M.renderChartsAndHeroes(state.overviewCache);
        if (btn.closest("#brands")) setSection("overview");
        toast(state.brandFilter ? `Tracking ${M.brandName(state.brandFilter)}` : "Tracking all brands");
      } else if (action === "copy-id") {
        const id = btn.dataset.id || "";
        navigator.clipboard.writeText(id).then(() => toast(`Copied ${id}`)).catch(() => toast("Copy failed", true));
      } else if (action === "save-ret") {
        const needle = btn.dataset.needle;
        const row = btn.closest("tr");
        const input = row && row.querySelector(".ret-input");
        const pct = input && input.value;
        if (pct === "" || pct == null) {
          toast("Enter retention %", true);
          return;
        }
        M.saveRetention(needle, pct, btn);
      }
    });

    document.addEventListener("keydown", (ev) => {
      const inField = /^(INPUT|TEXTAREA|SELECT)$/.test((ev.target.tagName || "").toUpperCase());
      if (ev.key === "Escape") {
        toggleOverlay("cmdk", false);
        toggleOverlay("keys-overlay", false);
        toggleOverlay("health-overlay", false);
        if (inField) ev.target.blur();
        return;
      }
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "k") {
        ev.preventDefault();
        toggleOverlay("cmdk");
        return;
      }
      if (inField || ev.ctrlKey || ev.metaKey || ev.altKey) return;
      const sections = ["overview", "brands", "performance", "spend", "pipeline", "review", "help"];
      if (/^[1-7]$/.test(ev.key)) {
        setSection(sections[Number(ev.key) - 1]);
      } else if (ev.key.toLowerCase() === "r") {
        refreshOverview(true).then(() => toast("Data re-synced.")).catch((e) => toast(e.message, true));
      } else if (ev.key.toLowerCase() === "m") {
        M.startMetricsRefresh();
      } else if (ev.key === "/") {
        ev.preventDefault();
        setSection("performance");
        setTimeout(() => $("perf-search")?.focus(), 30);
      } else if (ev.key === "?") {
        toggleOverlay("keys-overlay");
      }
    });
  }

  Object.assign(M, { refreshOverview, refreshOps, setWindow, renderSyncLabel });

  // Boot
  bindEvents();
  tickClock();
  setInterval(tickClock, 1000);
  updateHeroVisibility();
  setSection("overview");
  refreshOverview(true).catch((e) => toast(e.message, true));
  refreshOps();
  M.fetchHealth().catch(() => {});
  M.refreshJobs().catch(() => {});
  M.loadArchiveSongs().catch(() => {});
  M.jobsLoop();
  setInterval(() => {
    if (!state.logSource) M.pollLog();
  }, 2000);
  setInterval(() => refreshOps(), 15000);
  setInterval(() => {
    if (!document.hidden && M.activeSection() === "overview") {
      refreshOverview(false).catch(() => {});
    }
  }, 45000);
  setInterval(() => M.fetchHealth().catch(() => {}), 90000);
  setInterval(renderSyncLabel, 5000);
  setInterval(() => {
    if (!document.hidden && (state.overviewCache || state.opsCache)) M.renderOpsBrief();
  }, 30000);

  document.addEventListener("visibilitychange", () => {
    updateHeroVisibility();
    if (document.hidden) return;
    M.refreshJobs().catch(() => {});
    if (!state.logSource) M.pollLog();
    refreshOps();
    renderSyncLabel();
  });
})(window);
