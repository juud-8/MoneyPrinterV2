/* Chart.js helpers for the MoneyPrinterV2 control panel. */
(function (global) {
  const PALETTE = ["#58a6ff", "#3fb950", "#d29922", "#f85149", "#a371f7", "#39c5cf", "#f778ba"];
  const charts = {};

  const axisOpts = {
    x: { ticks: { color: "#8b949e" }, grid: { color: "#2a3444" } },
    y: { ticks: { color: "#8b949e" }, grid: { color: "#2a3444" } },
  };

  function destroy(id) {
    if (charts[id]) {
      charts[id].destroy();
      delete charts[id];
    }
  }

  function draw(id, type, labels, values, label, extra) {
    const el = document.getElementById(id);
    if (!el || typeof Chart === "undefined") return;
    destroy(id);
    if (!labels || !labels.length) return;

    const colors = labels.map((_, i) => PALETTE[i % PALETTE.length]);
    const dataset = {
      label: label || "",
      data: values,
      backgroundColor: type === "line" ? "rgba(88,166,255,0.18)" : colors,
      borderColor: type === "line" ? "#58a6ff" : colors,
      borderWidth: type === "line" ? 2 : 1,
      fill: type === "line",
      tension: 0.3,
      pointRadius: type === "line" ? 3 : 0,
      ...(extra && extra.dataset ? extra.dataset : {}),
    };

    charts[id] = new Chart(el, {
      type,
      data: { labels, datasets: [dataset] },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        animation: { duration: 550, easing: "easeOutQuart" },
        plugins: {
          legend: {
            display: type !== "bar" && type !== "line",
            labels: { color: "#e6edf3" },
          },
        },
        scales: type === "doughnut" || type === "pie" ? {} : axisOpts,
        ...(extra && extra.options ? extra.options : {}),
      },
    });
  }

  function drawMultiLine(id, labels, series) {
    const el = document.getElementById(id);
    if (!el || typeof Chart === "undefined") return;
    destroy(id);
    if (!labels.length || !series.length) return;

    charts[id] = new Chart(el, {
      type: "line",
      data: {
        labels,
        datasets: series.map((s, i) => ({
          label: s.label,
          data: s.values,
          borderColor: PALETTE[i % PALETTE.length],
          backgroundColor: "transparent",
          tension: 0.3,
          pointRadius: 2,
          borderWidth: 2,
        })),
      },
      options: {
        responsive: true,
        animation: { duration: 550 },
        plugins: { legend: { labels: { color: "#e6edf3" } } },
        scales: axisOpts,
      },
    });
  }

  function renderAll(overview, brandFilter) {
    const byDay = {};
    for (const v of overview.videos || []) {
      if (brandFilter && v.brand_id !== brandFilter) continue;
      const d = (v.date || "").slice(0, 10);
      if (d) byDay[d] = (byDay[d] || 0) + 1;
    }
    const days = Object.keys(byDay).sort();
    draw("timelineChart", "bar", days, days.map((d) => byDay[d]), "Posts");

    const tiers = overview.spend_by_tier || {};
    draw("tierChart", "doughnut", Object.keys(tiers), Object.values(tiers), "USD");

    const providers = overview.spend_by_provider || {};
    draw("providerChart", "pie", Object.keys(providers), Object.values(providers), "USD");

    const ranked = (overview.video_metrics_table || [])
      .filter((v) => v.views != null && (!brandFilter || v.brand_id === brandFilter))
      .sort((a, b) => (b.views || 0) - (a.views || 0))
      .slice(0, 10);
    draw(
      "leaderboardChart",
      "bar",
      ranked.map((v) => (v.title || "").slice(0, 28) || v.brand_id),
      ranked.map((v) => v.views || 0),
      "Views",
      {
        options: {
          indexAxis: "y",
          plugins: { legend: { display: false } },
        },
      }
    );

    const status = overview.status_counts || {};
    const statusLabels = Object.keys(status).filter((k) => status[k] > 0);
    draw("statusChart", "doughnut", statusLabels, statusLabels.map((k) => status[k]), "Count");

    const rej = overview.rejection_summary || {};
    draw(
      "rejectionChart",
      "bar",
      ["Topic skips", "Duration retries", "Duration aborts"],
      [rej.topic_rejections || 0, rej.duration_retries || 0, rej.duration_aborts || 0],
      "Count",
      { options: { plugins: { legend: { display: false } } } }
    );

    const growth = overview.channel_growth || {};
    const brandIds = brandFilter
      ? [brandFilter].filter((id) => growth[id])
      : Object.keys(growth);
    const allDates = new Set();
    for (const id of brandIds) {
      for (const point of growth[id] || []) {
        const d = (point.date || "").slice(0, 10);
        if (d) allDates.add(d);
      }
    }
    const labels = Array.from(allDates).sort();
    const series = brandIds.map((id) => {
      const map = {};
      for (const point of growth[id] || []) {
        const d = (point.date || "").slice(0, 10);
        if (d) map[d] = point.subscribers;
      }
      return {
        label: id,
        values: labels.map((d) => (map[d] != null ? map[d] : null)),
      };
    });
    drawMultiLine("growthChart", labels, series);
  }

  global.MPCharts = { renderAll, destroy, charts, PALETTE };
})(window);
