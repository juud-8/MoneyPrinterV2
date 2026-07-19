/* EL JEFE — Performance table with virtualization + inline retention */
(function (global) {
  const M = global.MPV2;
  const { state, $, esc, fmt, brandColor, brandName, thumbUrl, ytId, toast, api } = M;

  const ROW_H = 48;
  const BUFFER = 12;

  function filteredRows() {
    if (!state.overviewCache) return [];
    let rows = (state.overviewCache.video_metrics_table || []).slice();
    if (state.perfBrand) rows = rows.filter((r) => r.brand_id === state.perfBrand);
    if (state.perfStatus) rows = rows.filter((r) => (r.status || "generated") === state.perfStatus);
    if (state.perfQuery) {
      const q = state.perfQuery.toLowerCase();
      rows = rows.filter((r) => (r.title || "").toLowerCase().includes(q));
    }
    const { key, dir } = state.perfSort;
    rows.sort((a, b) => {
      let av = a[key], bv = b[key];
      if (key === "date") {
        av = a.date || "";
        bv = b.date || "";
      }
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === "string") return av.localeCompare(bv) * dir;
      return (av - bv) * dir;
    });
    return rows;
  }

  function renderPerfChips() {
    const el = $("perf-brand-chips");
    if (!el || !state.overviewCache) return;
    const rows = state.overviewCache.video_metrics_table || [];
    const counts = {};
    for (const r of rows) counts[r.brand_id] = (counts[r.brand_id] || 0) + 1;
    const ids = Object.keys(counts).sort();
    el.innerHTML =
      `<button class="chip ${!state.perfBrand ? "active" : ""}" data-perf-brand="">ALL · ${rows.length}</button>` +
      ids
        .map(
          (id) =>
            `<button class="chip ${state.perfBrand === id ? "active" : ""}" data-perf-brand="${esc(id)}" style="${state.perfBrand === id ? `color:${brandColor(id)}` : ""}">${esc(brandName(id))} · ${counts[id]}</button>`
        )
        .join("");
  }

  function rowHtml(v) {
    const title = esc((v.title || "").slice(0, 78));
    const link = v.url ? `<a href="${esc(v.url)}" target="_blank" rel="noopener">${title}</a>` : title;
    const th = thumbUrl(v.url);
    const color = brandColor(v.brand_id);
    const id = ytId(v.url) || "";
    const needle = id || (v.title || "").slice(0, 40);
    return `<tr data-vid="${esc(id)}" style="height:${ROW_H}px">
      <td class="muted small" style="white-space:nowrap">${esc((v.date || "").slice(0, 16))}</td>
      <td>${th ? `<img class="perf-thumb" loading="lazy" src="${esc(th)}" alt="">` : ""}</td>
      <td>${link}</td>
      <td><span class="pill" style="background:${color}22;color:${color}">${esc(brandName(v.brand_id))}</span></td>
      <td><span class="pill ${v.status === "uploaded" ? "green" : "gray"}">${esc(v.status || "")}</span></td>
      <td class="num">${fmt(v.views)}</td>
      <td class="num">${fmt(v.likes)}</td>
      <td class="num">${fmt(v.comments)}</td>
      <td class="num">
        <input class="ret-input" type="number" min="0" max="100" step="0.1" value="${v.avg_view_pct != null ? esc(v.avg_view_pct) : ""}" data-needle="${esc(needle)}" title="Studio avg % viewed" placeholder="—">
      </td>
      <td>
        <button class="ghost small" data-action="copy-id" data-id="${esc(id || needle)}" title="Copy id/title">ID</button>
        ${v.url ? `<a href="${esc(v.url)}" target="_blank" rel="noopener"><button class="ghost small" type="button">YT</button></a>` : ""}
        <button class="ghost small" data-action="save-ret" data-needle="${esc(needle)}">Save</button>
      </td>
    </tr>`;
  }

  function renderPerformance() {
    const body = $("perf-body");
    const wrap = $("perf-wrap");
    if (!body || !state.overviewCache) return;
    renderPerfChips();
    const rows = filteredRows();
    state.perfRows = rows;

    document.querySelectorAll(".perf-table th.sortable").forEach((th) => {
      th.classList.remove("sorted-asc", "sorted-desc");
      if (th.dataset.sort === state.perfSort.key) {
        th.classList.add(state.perfSort.dir > 0 ? "sorted-asc" : "sorted-desc");
      }
    });

    if (!rows.length) {
      body.innerHTML = `<tr><td colspan="10"><div class="empty-state">Nothing matches. Generate a Short, then refresh metrics.</div></td></tr>`;
      return;
    }

    if (rows.length <= 100 || !wrap) {
      body.innerHTML = rows.map(rowHtml).join("");
      return;
    }

    const scrollTop = wrap.scrollTop;
    const viewH = wrap.clientHeight || 400;
    const start = Math.max(0, Math.floor(scrollTop / ROW_H) - BUFFER);
    const end = Math.min(rows.length, Math.ceil((scrollTop + viewH) / ROW_H) + BUFFER);
    const topPad = start * ROW_H;
    const bottomPad = (rows.length - end) * ROW_H;
    const slice = rows.slice(start, end);
    body.innerHTML =
      (topPad ? `<tr style="height:${topPad}px"><td colspan="10"></td></tr>` : "") +
      slice.map(rowHtml).join("") +
      (bottomPad ? `<tr style="height:${bottomPad}px"><td colspan="10"></td></tr>` : "");
  }

  async function saveRetention(needle, pct, btn) {
    if (!needle) {
      toast("No video id/title for retention", true);
      return;
    }
    if (btn) btn.disabled = true;
    try {
      const res = await api("/api/retention", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ needle, avg_view_pct: Number(pct) }),
      });
      toast(`Retention ${pct}% saved (${res.updated} row(s))`);
      if (M.refreshOverview) await M.refreshOverview(true);
    } catch (e) {
      toast(e.message, true);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function bindPerfScroll() {
    const wrap = $("perf-wrap");
    if (!wrap || wrap._mpv2Bound) return;
    wrap._mpv2Bound = true;
    let ticking = false;
    wrap.addEventListener("scroll", () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        ticking = false;
        if (state.perfRows.length > 100) renderPerformance();
      });
    });
  }

  Object.assign(M, { renderPerformance, saveRetention, bindPerfScroll });
})(window);
