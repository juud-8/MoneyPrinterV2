/* MoneyPrinterV2 control panel application. */
(function () {
  let brandsCache = [];
  let overviewCache = null;
  let selectedJob = null;
  let logOffset = 0;
  let windowDays = 7;
  let brandFilter = null;
  let jobStatusMap = {};
  let jobLabelMap = {};
  let overviewTimer = null;

  const $ = (id) => document.getElementById(id);
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );

  function toast(msg, isError) {
    const el = $("toast");
    el.textContent = msg;
    el.style.borderColor = isError ? "var(--red)" : "var(--green)";
    el.style.display = "block";
    clearTimeout(el._t);
    el._t = setTimeout(() => {
      el.style.display = "none";
    }, 5000);
  }

  async function api(path, opts) {
    const res = await fetch(path, opts);
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || res.statusText);
    return body;
  }

  function fmt(n) {
    if (n === null || n === undefined) return "—";
    return Number(n) >= 1000 ? Number(n).toLocaleString() : String(n);
  }

  function windowLabel(days) {
    return days == null ? "all" : `${days}d`;
  }

  function overviewUrl() {
    const q = windowDays == null ? "all" : String(windowDays);
    return `/api/overview?days=${encodeURIComponent(q)}`;
  }

  function animateKpi(el, valueText) {
    el.textContent = valueText;
    el.style.transform = "scale(1.04)";
    setTimeout(() => {
      el.style.transform = "scale(1)";
    }, 180);
  }

  function setSection(name) {
    document.querySelectorAll(".panel-section").forEach((sec) => {
      sec.classList.toggle("active", sec.dataset.section === name);
    });
    document.querySelectorAll(".nav-tabs button").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.section === name);
    });
    // Re-draw after tab becomes visible so Chart.js/Three get real dimensions.
    if (overviewCache && (name === "overview" || name === "spend")) {
      requestAnimationFrame(() => renderChartsAndHeroes(overviewCache));
    }
  }

  function renderAlert(overview) {
    const alert = overview.spend_alert || {};
    const el = $("spend-alert");
    if (!el) return;
    if (alert.triggered) {
      el.classList.add("visible");
      el.textContent = `Premium spend $${Number(alert.recent_spend_usd || 0).toFixed(2)} exceeds alert threshold $${Number(alert.threshold_usd || 0).toFixed(2)} (${windowLabel(overview.window_days)}). Review asset_strategy if unintended.`;
    } else {
      el.classList.remove("visible");
    }
  }

  function renderTotals(data) {
    const t = data.totals || {};
    $("generated-at").textContent = `Updated ${data.generated_at} · window ${windowLabel(data.window_days)}`;
    const items = [
      { label: "Posts (deduped)", value: fmt(t.videos) },
      { label: "Uploaded", value: fmt(t.uploaded) },
      {
        label: `Premium spend (${windowLabel(data.window_days)})`,
        value: `$${Number(t.spend_window_usd || 0).toFixed(2)}`,
      },
      {
        label: "Premium spend (all time)",
        value: `$${Number(t.spend_all_time_usd || 0).toFixed(2)}`,
      },
    ];
    $("totals").innerHTML = items
      .map(
        (item) =>
          `<div class="kpi"><strong style="transition:transform .18s ease">${esc(item.value)}</strong><span>${esc(item.label)}</span></div>`
      )
      .join("");
    $("totals").querySelectorAll("strong").forEach((node) => animateKpi(node, node.textContent));
  }

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
      return `<p class="muted small">Insights: ${ins.sample_size}/${ins.min_sample} videos with metrics — topic steering activates at ${ins.min_sample}+ videos older than 48h.</p>`;
    }
    const top = ins.top
      .map(
        (v) =>
          `<li>▲ ${esc((v.title || "").slice(0, 70))} <span class="pill green">${fmt(v.views)} views</span>${v.avg_view_pct != null ? ` <span class="pill">${fmt(v.avg_view_pct)}% ret</span>` : ""}</li>`
      )
      .join("");
    const bottom = ins.bottom
      .map(
        (v) =>
          `<li>▼ ${esc((v.title || "").slice(0, 70))} <span class="pill red">${fmt(v.views)} views</span></li>`
      )
      .join("");
    return `<details class="slots open"><summary>Performance insights (feeding topic generation)</summary><ul class="plain">${top}${bottom}</ul></details>`;
  }

  function recentPostsList(posts) {
    if (!posts || !posts.length) return `<li class="muted">No recent posts.</li>`;
    return posts
      .map((v) => {
        const pills = [
          `<span class="pill">${esc(v.status || "generated")}</span>`,
          v.views != null ? `<span class="pill green">${fmt(v.views)} views</span>` : "",
          v.likes != null ? `<span class="pill">${fmt(v.likes)} likes</span>` : "",
          v.avg_view_pct != null ? `<span class="pill amber">${fmt(v.avg_view_pct)}% ret</span>` : "",
        ]
          .filter(Boolean)
          .join(" ");
        return `<li><span class="muted">${esc(v.date || "")}</span> ${pills} ${esc((v.title || "").slice(0, 70))}${
          v.url ? `<br><a href="${esc(v.url)}" target="_blank" rel="noopener">${esc(v.url)}</a>` : ""
        }</li>`;
      })
      .join("");
  }

  function renderBrands(overview) {
    const container = $("brands");
    if (!brandsCache.length) {
      container.innerHTML = `<div class="empty-state">No brands found under <code>brands/</code>.</div>`;
      return;
    }
    const summaries = Object.fromEntries((overview.brands || []).map((b) => [b.brand_id, b]));
    const snaps = overview.channel_snapshots || {};
    const insights = overview.insights || {};

    container.innerHTML = "";
    for (const brand of brandsCache) {
      const s = summaries[brand.brand_id] || {};
      const snap = snaps[brand.brand_id];
      const card = document.createElement("article");
      card.className = "card";
      card.innerHTML = `
        <div class="flex-between">
          <h3>${esc(brand.channel_name)}</h3>
          <span>
            ${brand.is_active ? '<span class="pill green">active</span>' : ""}
            ${brand.pilot_mode ? '<span class="pill amber" title="Pilot mode: Generate &amp; Post confirms the pilot review gate.">pilot</span>' : ""}
          </span>
        </div>
        <p class="muted small">${esc(brand.brand_id)}</p>
        <div class="stats">
          <div><strong>${fmt(snap ? snap.subscribers : null)}</strong><span>Subs</span></div>
          <div><strong>${fmt(snap ? snap.total_views : null)}</strong><span>Channel views</span></div>
          <div><strong>${fmt(s.uploaded_count ?? 0)}</strong><span>Uploaded</span></div>
          <div><strong>$${Number(s.spend_window_usd ?? 0).toFixed(2)}</strong><span>Spend (${windowLabel(overview.window_days)})</span></div>
        </div>
        <p class="muted small">Posts ${fmt(s.post_count ?? 0)} · Metrics filled ${fmt(s.metrics_filled ?? 0)}${snap ? ` · Snapshot ${esc(snap.date)}` : " · No channel snapshot yet"}</p>
        <div class="actions">
          <button data-action="generate" data-brand="${esc(brand.brand_id)}" data-upload="0">Generate only</button>
          <button class="primary" data-action="generate" data-brand="${esc(brand.brand_id)}" data-upload="1">Generate &amp; Post now</button>
          <button data-action="filter-brand" data-brand="${esc(brand.brand_id)}">Focus charts</button>
        </div>
        ${insightsBlock(insights[brand.brand_id])}
        <details class="slots"><summary>Recent posts</summary><ul class="plain">${recentPostsList(s.recent_posts)}</ul></details>
        ${slotEditor(brand)}`;
      container.appendChild(card);
    }
  }

  function renderRecentPosts(overview) {
    const items = (overview.videos || []).slice(0, 15);
    if (!items.length) {
      $("recent-posts").innerHTML =
        '<div class="empty-state">No posts logged yet.<br><code>Generate only</code> on a brand card, or run <code>scripts/run_brand_short.py</code></div>';
      return;
    }
    $("recent-posts").innerHTML = `<ul class="plain">${items
      .map((v) => {
        return `<li>
          <span class="muted">${esc(v.date || "")}</span>
          <span class="pill">${esc(v.status || "generated")}</span>
          <span class="pill">${esc(v.brand_id || "")}</span>
          ${v.views != null ? `<span class="pill green">${fmt(v.views)} views</span>` : ""}
          ${v.likes != null ? `<span class="pill">${fmt(v.likes)} likes</span>` : ""}
          ${esc((v.title || "").slice(0, 85))}
          ${v.url ? `<br><a href="${esc(v.url)}" target="_blank" rel="noopener">${esc(v.url)}</a>` : ""}
        </li>`;
      })
      .join("")}</ul>`;
  }

  function renderPerformance(overview) {
    const rows = overview.video_metrics_table || [];
    const body = $("perf-body");
    if (!rows.length) {
      body.innerHTML = `<tr><td colspan="8"><div class="empty-state">No video rows yet. Generate a Short, then refresh metrics.</div></td></tr>`;
      return;
    }
    body.innerHTML = rows
      .map((v) => {
        const title = esc((v.title || "").slice(0, 70));
        const link = v.url
          ? `<a href="${esc(v.url)}" target="_blank" rel="noopener">${title}</a>`
          : title;
        return `<tr>
          <td class="muted small">${esc((v.date || "").slice(0, 16))}</td>
          <td><span class="pill">${esc(v.brand_id || "")}</span></td>
          <td>${link}</td>
          <td><span class="pill">${esc(v.status || "")}</span></td>
          <td>${fmt(v.views)}</td>
          <td>${fmt(v.likes)}</td>
          <td>${fmt(v.comments)}</td>
          <td>${v.avg_view_pct != null ? fmt(v.avg_view_pct) + "%" : "—"}</td>
        </tr>`;
      })
      .join("");
  }

  function renderSpendList(overview) {
    const list = overview.recent_spend || [];
    const el = $("spend-list");
    if (!list.length) {
      el.innerHTML = `<div class="empty-state">No premium asset spend in this window.</div>`;
      return;
    }
    el.innerHTML = `<ul class="plain">${list
      .slice()
      .reverse()
      .slice(0, 25)
      .map(
        (e) => `<li>
          <span class="muted">${esc(e.date || "")}</span>
          <span class="pill">${esc(e.tier || "")}</span>
          <span class="pill">${esc(e.provider || "")}</span>
          <span class="pill amber">$${Number(e.cost_usd || 0).toFixed(2)}</span>
          ${esc(e.brand_id || "")} · ${esc((e.video_title || "").slice(0, 60))}
        </li>`
      )
      .join("")}</ul>`;
  }

  function renderChartsAndHeroes(overview) {
    if (window.MPCharts) window.MPCharts.renderAll(overview, brandFilter);
    if (window.MPHeroes) {
      window.MPHeroes.render(overview, {
        brandFilter,
        onBrandSelect: (id) => {
          brandFilter = brandFilter === id ? null : id;
          renderChartsAndHeroes(overview);
          toast(brandFilter ? `Filtered to ${brandFilter}` : "Cleared brand filter");
        },
      });
    }
    const filterLabel = $("brand-filter-label");
    if (filterLabel) {
      filterLabel.textContent = brandFilter ? `Filter: ${brandFilter}` : "Filter: all brands";
    }
  }

  async function generate(brandId, upload, btn) {
    if (
      upload &&
      !confirm(
        `Generate AND upload a new Short for "${brandId}" now?\n\nThis launches the full pipeline (LLM → TTS → images → video → Selenium upload).`
      )
    ) {
      return;
    }
    btn.disabled = true;
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
      btn.disabled = false;
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

  function selectJob(jobId) {
    selectedJob = jobId;
    logOffset = 0;
    const logEl = $("log-view");
    if (logEl) logEl.textContent = "";
    if (window.MPV2PipelineTheater) {
      MPV2PipelineTheater.onJobSelected();
    }
  }

  async function refreshJobs() {
    const jobs = await api("/api/jobs");
    const body = $("jobs-body");
    if (!jobs.length) {
      body.innerHTML = '<tr><td colspan="4" class="muted">No jobs yet this session.</td></tr>';
      return;
    }

    // Detect finished jobs → refresh overview
    for (const j of jobs) {
      const prev = jobStatusMap[j.id];
      if (prev === "running" && j.status !== "running") {
        toast(
          j.status === "succeeded"
            ? `Finished: ${j.label}`
            : `Ended (${j.status}): ${j.label}`,
          j.status !== "succeeded"
        );
        refreshOverview().catch(() => {});
      }
      jobStatusMap[j.id] = j.status;
      jobLabelMap[j.id] = j.label;
    }

    body.innerHTML = jobs
      .map((j) => {
        const pill =
          j.status === "running" ? "pill amber" : j.status === "succeeded" ? "pill green" : "pill red";
        const cancel =
          j.status === "running"
            ? `<button class="danger" data-action="cancel-job" data-job="${j.id}">Cancel</button>`
            : "";
        return `<tr class="selectable" data-action="select-job" data-job="${j.id}">
          <td class="muted">${esc(j.started_at)}</td>
          <td>${esc(j.label)}</td>
          <td><span class="${pill}">${esc(j.status)}</span></td>
          <td>${cancel}</td>
        </tr>`;
      })
      .join("");

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
    if (!selectedJob) return;
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
          fullText: (el && el.textContent) || "",
          label: jobLabelMap[selectedJob] || "",
          status: jobStatusMap[selectedJob] || res.status || "",
        });
      }
    } catch (e) {
      /* ignore */
    }
  }

  async function refreshOverview() {
    const [overview, brands] = await Promise.all([api(overviewUrl()), api("/api/brands")]);
    brandsCache = brands;
    overviewCache = overview;
    renderTotals(overview);
    renderAlert(overview);
    const editing = document.activeElement && $("brands").contains(document.activeElement);
    if (!editing) renderBrands(overview);
    renderRecentPosts(overview);
    renderPerformance(overview);
    renderSpendList(overview);
    renderChartsAndHeroes(overview);
  }

  function bindEvents() {
    document.querySelectorAll(".nav-tabs button").forEach((btn) => {
      btn.addEventListener("click", () => setSection(btn.dataset.section));
    });

    document.querySelectorAll(".days-picker button").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const val = btn.dataset.days;
        windowDays = val === "all" ? null : Number(val);
        document.querySelectorAll(".days-picker button").forEach((b) => {
          b.classList.toggle("active", b === btn);
        });
        try {
          await refreshOverview();
        } catch (e) {
          toast(e.message, true);
        }
      });
    });

    $("refresh-metrics").addEventListener("click", async () => {
      const btn = $("refresh-metrics");
      btn.disabled = true;
      try {
        const job = await api("/api/metrics/refresh", { method: "POST" });
        toast("Metrics refresh started — overview reloads when it finishes.");
        selectJob(job.id);
        await refreshJobs();
        setSection("pipeline");
      } catch (e) {
        toast(e.message, true);
      } finally {
        btn.disabled = false;
      }
    });

    $("clear-filter")?.addEventListener("click", () => {
      brandFilter = null;
      if (overviewCache) renderChartsAndHeroes(overviewCache);
      toast("Cleared brand filter");
    });

    document.body.addEventListener("click", (ev) => {
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
      } else if (action === "filter-brand") {
        brandFilter = btn.dataset.brand;
        if (overviewCache) renderChartsAndHeroes(overviewCache);
        setSection("overview");
        toast(`Filtered charts to ${brandFilter}`);
      }
    });
  }

  bindEvents();
  setSection("overview");
  refreshOverview().catch((e) => toast(e.message, true));
  refreshJobs().catch(() => {});
  setInterval(() => refreshJobs().catch(() => {}), 3000);
  setInterval(pollLog, 1500);
  overviewTimer = setInterval(() => refreshOverview().catch(() => {}), 60000);
})();
