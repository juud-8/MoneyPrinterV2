/* EL JEFE — Brands tab + charts/heroes glue */
(function (global) {
  const M = global.MPV2;
  const {
    state, $, esc, fmt, money, todayStr, windowLabel, brandColor, brandName, monogram,
    thumbUrl, timeAgo, chartCtx, toast, api, nextWindowInfo, humanUntil, quotaBlocks, growthDelta,
  } = M;

  function renderHeroLegend(overview) {
    const legend = $("hero-legend");
    const meta = $("hero-meta");
    if (!legend) return;
    const growth = overview.channel_growth || {};
    const snaps = overview.channel_snapshots || {};
    const ids = Object.keys(growth).length ? Object.keys(growth).sort() : M.allBrandIds();
    legend.innerHTML = ids
      .map((id) => {
        const snap = snaps[id];
        const delta = growthDelta([id]);
        const dim = state.brandFilter && state.brandFilter !== id;
        return `
          <div class="legend-row ${dim ? "dim" : ""}" data-action="filter-brand" data-brand="${esc(id)}" title="Click to focus ${esc(brandName(id))}">
            <span class="dot" style="background:${brandColor(id)}"></span>
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
      filterLabel.textContent = state.brandFilter ? `TRACKING: ${brandName(state.brandFilter).toUpperCase()}` : "TRACKING: ALL BRANDS";
    }
  }

  function renderChartsAndHeroes(overview) {
    if (!overview) return;
    const ctx = chartCtx();
    if (window.MPCharts) window.MPCharts.renderAll(overview, ctx);
    M.updateHeroVisibility();
    if (window.MPHeroes && !state.terrainCollapsed) {
      window.MPHeroes.render(overview, {
        ...ctx,
        onBrandSelect: (id) => {
          state.brandFilter = state.brandFilter === id ? null : id;
          renderChartsAndHeroes(overview);
          toast(state.brandFilter ? `Tracking ${brandName(state.brandFilter)}` : "Tracking all brands");
        },
      });
    }
    renderHeroLegend(overview);
    renderTopVideos(overview);
  }

  function renderTopVideos(overview) {
    const el = $("top-videos");
    if (!el) return;
    let rows = (overview.video_metrics_table || []).filter(
      (v) => v.views != null && (!state.brandFilter || v.brand_id === state.brandFilter)
    );
    const winRows = rows.filter((v) => M.inWindow(v.date));
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

  function renderRecentPosts(overview) {
    const el = $("recent-posts");
    if (!el) return;
    const items = (overview.videos || []).slice(0, 12);
    if (!items.length) {
      el.innerHTML = `<div class="empty-state">No posts logged yet.<br>Use <strong>Generate only</strong> on the Command Deck, or run <code>scripts/run_brand_short.py</code></div>`;
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
    const files = state.outputsCache[brandId] || [];
    if (!files.length) return "";
    return `
      <div class="renders">
        <span class="muted small">LATEST RENDERS · REVIEW BAY</span>
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
        <div class="actions">
          <button class="ghost small" data-action="open-output" data-brand="${esc(brandId)}">Open folder</button>
          <button class="gold small" data-action="generate" data-brand="${esc(brandId)}" data-upload="1">Approve &amp; Post</button>
        </div>
      </div>`;
  }

  function renderBrands(overview) {
    const container = $("brands");
    if (!container) return;
    if (!state.brandsCache.length) {
      container.innerHTML = `<div class="empty-state">No brands found under <code>brands/</code>.</div>`;
      return;
    }
    const summaries = Object.fromEntries((overview.brands || []).map((b) => [b.brand_id, b]));
    const snaps = overview.channel_snapshots || {};
    const insights = overview.insights || {};
    const today = todayStr();
    const videos = overview.videos || [];

    container.innerHTML = "";
    for (const brand of state.brandsCache) {
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
        const hint = win.hint ? ` · task ${esc(win.hint)}` : "";
        winChip =
          win.state === "live"
            ? `<span class="win-chip live">● LIVE · ${esc(win.name)} until ${esc(win.end || "")}${hint}</span>`
            : win.state === "soon"
              ? `<span class="win-chip soon">${esc(win.name)} ${esc(win.start)} · in ${humanUntil(win.at)}${hint}</span>`
              : `<span class="win-chip">${esc(win.name)} ${esc(win.start)} tomorrow${hint}</span>`;
      }

      const card = document.createElement("article");
      card.className = "card";
      card.innerHTML = `
        <div class="brand-head">
          <span class="brand-avatar" style="background:${color}">${esc(monogram(brand.channel_name))}</span>
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
        <div class="gen-controls">
          <input class="topic-input" type="text" placeholder="Topic (optional) — blank = AI picks">
          <button class="ghost small" data-action="suggest-trends" data-brand="${esc(id)}" title="Suggest a topic from current Google Trends for this brand's niche">✨ Trends</button>
          <select class="provider-select" title="Image provider for this run only — leave on Default to use the brand's configured provider">
            <option value="">Image: default</option>
            <option value="gemini">Image: Gemini</option>
            <option value="fal">Image: fal.ai (cheap)</option>
          </select>
        </div>
        <div class="gen-controls">
          <input class="schedule-input" type="datetime-local" title="Publish time for Generate &amp; Schedule (local time)">
          <button class="ghost" data-action="generate" data-brand="${esc(id)}" data-upload="1" data-schedule="1" title="Generate now, upload private, and let YouTube publish it at the chosen time (requires upload_backend: api)">Generate &amp; Schedule</button>
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

  async function generate(brandId, upload, btn) {
    const card = btn && btn.closest(".card");
    const topic = ((card && card.querySelector(".topic-input")?.value) || "").trim();
    const imageProvider = ((card && card.querySelector(".provider-select")?.value) || "").trim();
    const isSchedule = btn && btn.dataset.schedule === "1";
    let publishAt = "";
    if (isSchedule) {
      publishAt = ((card && card.querySelector(".schedule-input")?.value) || "").trim();
      if (!publishAt) {
        toast("Pick a publish date/time first (the field next to Generate & Schedule).", true);
        return;
      }
      if (new Date(publishAt) <= new Date()) {
        toast("Publish time must be in the future.", true);
        return;
      }
    }
    const confirmMsg = isSchedule
      ? `Generate a new Short for "${brandName(brandId)}" and schedule it to publish at ${new Date(publishAt).toLocaleString()}?\n\nIt uploads private via the YouTube API and goes public automatically at that time.${topic ? `\n\nTopic: ${topic}` : ""}`
      : `Generate AND upload a new Short for "${brandName(brandId)}" now?\n\nThis launches the full pipeline (LLM → TTS → images → video → Selenium upload).${topic ? `\n\nTopic: ${topic}` : ""}`;
    if (upload && !confirm(confirmMsg)) {
      return;
    }
    if (btn) {
      btn.disabled = true;
      btn.dataset.busy = "1";
    }
    try {
      const body = { brand_id: brandId, upload };
      if (publishAt) body.publish_at = publishAt;
      if (topic) body.topic = topic;
      if (imageProvider) body.image_provider = imageProvider;
      const job = await api("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      toast(`Started: ${job.label}`);
      if (M.selectJob) M.selectJob(job.id);
      if (M.refreshJobs) await M.refreshJobs();
      M.setSection("pipeline");
    } catch (e) {
      toast(e.message, true);
    } finally {
      if (btn) {
        btn.disabled = false;
        delete btn.dataset.busy;
      }
    }
  }

  async function suggestTrends(brandId, btn) {
    const card = btn && btn.closest(".card");
    const input = card && card.querySelector(".topic-input");
    if (btn) btn.disabled = true;
    try {
      const res = await api(`/api/brands/${encodeURIComponent(brandId)}/trending-topics`, { method: "POST" });
      const topics = res.topics || [];
      if (!topics.length) {
        toast("No trending topics found for this brand's niche right now.", true);
        return;
      }
      if (input) {
        input.value = topics[0];
        input.title = topics.length > 1 ? `Other candidates:\n${topics.slice(1).join("\n")}` : "";
      }
      toast(`Suggested: ${topics[0]}`);
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

  async function openEpisode(brandId, episodeId) {
    try {
      await api(`/api/open-episode/${encodeURIComponent(brandId)}/${encodeURIComponent(episodeId)}`, { method: "POST" });
      toast(`Opened episode ${episodeId}`);
    } catch (e) {
      toast(e.message, true);
    }
  }

  Object.assign(M, {
    renderChartsAndHeroes,
    renderTopVideos,
    renderRecentPosts,
    renderBrands,
    generate,
    suggestTrends,
    saveSlots,
    openOutput,
    openEpisode,
  });
})(window);
