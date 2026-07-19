/* EL JEFE — Command palette */
(function (global) {
  const M = global.MPV2;
  const { state, $, esc, brandName, toast, toggleOverlay } = M;

  function paletteActions() {
    const actions = [];
    for (const b of state.brandsCache) {
      const name = b.channel_name || b.brand_id;
      actions.push({ ico: "▶", label: `Generate — ${name}`, hint: "render only", run: () => M.generate(b.brand_id, false) });
      actions.push({ ico: "⇧", label: `Generate & Post — ${name}`, hint: "full pipeline", danger: true, run: () => M.generate(b.brand_id, true) });
      actions.push({ ico: "◎", label: `Focus charts — ${name}`, hint: "filter", run: () => { state.brandFilter = b.brand_id; if (state.overviewCache) M.renderChartsAndHeroes(state.overviewCache); M.setSection("overview"); } });
      actions.push({ ico: "▤", label: `Open output folder — ${name}`, hint: "explorer", run: () => M.openOutput(b.brand_id) });
      if (b.channel_id) {
        actions.push({ ico: "↗", label: `Open channel — ${name}`, hint: "youtube", run: () => window.open(`https://www.youtube.com/channel/${b.channel_id}`, "_blank") });
      }
    }
    actions.push({ ico: "⟳", label: "Refresh YouTube metrics", hint: "M", run: () => M.startMetricsRefresh() });
    actions.push({ ico: "⟲", label: "Re-sync dashboard data", hint: "R", run: () => M.refreshOverview(true).then(() => toast("Data re-synced.")).catch((e) => toast(e.message, true)) });
    actions.push({ ico: "♥", label: "Systems health / fixes", hint: "health", run: () => { M.renderHealthModal(); toggleOverlay("health-overlay", true); } });
    actions.push({ ico: "✓", label: "Run preflight", hint: "preflight", run: () => M.runPreflight() });
    actions.push({ ico: "▤", label: "Weekly review", hint: "tab", run: () => { M.setSection("review"); M.loadWeekly(true); } });
    actions.push({ ico: "♪", label: "Archive song handoffs", hint: "songs", run: () => { M.setSection("overview"); M.loadArchiveSongs(); } });
    for (const [i, sec] of ["overview", "brands", "performance", "spend", "pipeline", "review", "help"].entries()) {
      actions.push({ ico: String(i + 1), label: `Go to ${sec[0].toUpperCase() + sec.slice(1)}`, hint: "tab", run: () => M.setSection(sec) });
    }
    for (const d of [7, 14, 30, null]) {
      actions.push({ ico: "◷", label: `Window: ${d == null ? "All-time" : d + " days"}`, hint: "range", run: () => M.setWindow(d) });
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
    if (!input || !list) return;
    const q = (input.value || "").trim().toLowerCase();
    state.cmdkMatches = paletteActions()
      .map((a) => ({ a, score: fuzzyScore(a.label, q) }))
      .filter((x) => x.score > 0)
      .sort((x, y) => y.score - x.score)
      .slice(0, 12)
      .map((x) => x.a);
    state.cmdkIndex = Math.min(state.cmdkIndex, Math.max(0, state.cmdkMatches.length - 1));
    list.innerHTML = state.cmdkMatches
      .map(
        (a, i) =>
          `<li class="${i === state.cmdkIndex ? "active" : ""} ${a.danger ? "danger-item" : ""}" data-cmdk-i="${i}">
            <span class="ico">${esc(a.ico)}</span><span>${esc(a.label)}</span><span class="hint">${esc(a.hint || "")}</span>
          </li>`
      )
      .join("") || `<li class="muted" style="cursor:default">No matching commands.</li>`;
  }

  function runCmdk(index) {
    const action = state.cmdkMatches[index];
    if (!action) return;
    toggleOverlay("cmdk", false);
    action.run();
  }

  Object.assign(M, { paletteActions, renderCmdk, runCmdk });
})(window);
