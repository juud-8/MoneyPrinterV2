/* EL JEFE — Spend tab */
(function (global) {
  const M = global.MPV2;
  const { state, $, money, windowLabel, brandColor, brandName, esc, inWindow } = M;

  function renderSpend(overview) {
    if (!overview) return;
    const alert = overview.spend_alert || {};
    const spend = Number((overview.totals || {}).spend_window_usd || 0);
    const threshold = Number(alert.threshold_usd || 25);
    const pct = threshold > 0 ? Math.min(100, (spend / threshold) * 100) : 0;
    const ring = $("gauge-ring");
    if (ring) {
      ring.style.setProperty("--gauge-pct", pct.toFixed(1));
      ring.style.setProperty("--gauge-color", pct >= 100 ? "var(--red)" : pct >= 60 ? "var(--brass)" : "var(--green)");
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
        <div><strong>${money(perUpload)}</strong><span>per upload</span></div>
        <div><strong>${uploadsInWin}</strong><span>uploads in win</span></div>`;
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

  Object.assign(M, { renderSpend });
})(window);
