/* Chart.js helpers for EL JEFE mission control (MoneyPrinterV2). */
(function (global) {
  const PALETTE = ["#c9a227", "#3ecf8e", "#e85d4c", "#9a8cff", "#46d7ff", "#e0c45a", "#7ee787", "#f778ba"];
  const TEXT = "#6e8499";
  const GRID = "rgba(70, 130, 180, 0.10)";
  const MONO = "'Cascadia Code', 'Cascadia Mono', Consolas, monospace";
  const charts = {};

  if (typeof Chart !== "undefined") {
    Chart.defaults.color = TEXT;
    Chart.defaults.font.family = MONO;
    Chart.defaults.font.size = 10;
    Chart.defaults.borderColor = GRID;
    Chart.defaults.plugins.tooltip.backgroundColor = "rgba(6, 13, 22, 0.94)";
    Chart.defaults.plugins.tooltip.borderColor = "#1e4a66";
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.plugins.tooltip.titleColor = "#d8e8f6";
    Chart.defaults.plugins.tooltip.bodyColor = "#9fb6c9";
    Chart.defaults.plugins.tooltip.padding = 10;
    Chart.defaults.plugins.tooltip.cornerRadius = 8;
  }

  const axisOpts = {
    x: { ticks: { color: TEXT, maxRotation: 0, autoSkip: true, maxTicksLimit: 10 }, grid: { color: GRID } },
    y: { ticks: { color: TEXT, precision: 0 }, grid: { color: GRID }, beginAtZero: true },
  };

  function destroy(id) {
    if (charts[id]) {
      charts[id].destroy();
      delete charts[id];
    }
  }

  function niceDate(d) {
    const dt = new Date(`${d}T00:00:00`);
    if (isNaN(dt.getTime())) return d;
    return dt.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  }

  function hexToRgba(hex, a) {
    const m = String(hex).replace("#", "");
    const n = parseInt(m.length === 3 ? m.split("").map((c) => c + c).join("") : m, 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
  }

  function make(id, config) {
    const el = document.getElementById(id);
    if (!el || typeof Chart === "undefined") return;
    destroy(id);
    charts[id] = new Chart(el, config);
  }

  // Stacked posts-per-day, one dataset per brand.
  function drawTimeline(overview, ctx) {
    const { colors, names, brandFilter, cutoff } = ctx;
    const byBrandDay = {};
    const daysSet = new Set();
    for (const v of overview.videos || []) {
      if (brandFilter && v.brand_id !== brandFilter) continue;
      if (cutoff) {
        const d = new Date(String(v.date || "").replace(" ", "T"));
        if (!isNaN(d.getTime()) && d < cutoff) continue;
      }
      const day = (v.date || "").slice(0, 10);
      if (!day) continue;
      daysSet.add(day);
      const key = v.brand_id || "unknown";
      byBrandDay[key] = byBrandDay[key] || {};
      byBrandDay[key][day] = (byBrandDay[key][day] || 0) + 1;
    }
    const days = Array.from(daysSet).sort();
    const brandIds = Object.keys(byBrandDay).sort();
    const el = document.getElementById("timelineChart");
    if (!el || typeof Chart === "undefined") return;
    destroy("timelineChart");
    if (!days.length) return;

    make("timelineChart", {
      type: "bar",
      data: {
        labels: days.map(niceDate),
        datasets: brandIds.map((id) => ({
          label: names[id] || id,
          data: days.map((d) => byBrandDay[id][d] || 0),
          backgroundColor: hexToRgba(colors[id] || PALETTE[0], 0.75),
          borderColor: colors[id] || PALETTE[0],
          borderWidth: 1,
          borderRadius: 3,
          stack: "posts",
        })),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 400, easing: "easeOutQuart" },
        plugins: { legend: { display: brandIds.length > 1, labels: { boxWidth: 10, boxHeight: 10 } } },
        scales: {
          x: { ...axisOpts.x, stacked: true },
          y: { ...axisOpts.y, stacked: true },
        },
      },
    });
  }

  function drawGrowth(overview, ctx) {
    const { colors, names, brandFilter } = ctx;
    const growth = overview.channel_growth || {};
    const brandIds = (brandFilter ? [brandFilter] : Object.keys(growth)).filter((id) => (growth[id] || []).length);
    const el = document.getElementById("growthChart");
    if (!el || typeof Chart === "undefined") return;
    destroy("growthChart");
    if (!brandIds.length) return;

    const allDates = new Set();
    for (const id of brandIds) {
      for (const p of growth[id] || []) {
        const d = (p.date || "").slice(0, 10);
        if (d) allDates.add(d);
      }
    }
    const labels = Array.from(allDates).sort();

    make("growthChart", {
      type: "line",
      data: {
        labels: labels.map(niceDate),
        datasets: brandIds.map((id) => {
          const map = {};
          for (const p of growth[id] || []) {
            const d = (p.date || "").slice(0, 10);
            if (d) map[d] = p.subscribers;
          }
          const color = colors[id] || PALETTE[0];
          return {
            label: names[id] || id,
            data: labels.map((d) => (map[d] != null ? map[d] : null)),
            borderColor: color,
            backgroundColor: hexToRgba(color, 0.12),
            fill: brandIds.length === 1,
            tension: 0.35,
            spanGaps: true,
            pointRadius: 2,
            pointHoverRadius: 5,
            borderWidth: 2,
          };
        }),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 400 },
        plugins: { legend: { display: brandIds.length > 1, labels: { boxWidth: 10, boxHeight: 10 } } },
        scales: axisOpts,
      },
    });
  }

  function drawStatus(overview) {
    const status = overview.status_counts || {};
    const entries = [
      ["uploaded", "#3ddc97"],
      ["generated", "#c9a227"],
      ["other", "#6e8499"],
    ].filter(([k]) => (status[k] || 0) > 0);
    const el = document.getElementById("statusChart");
    if (!el || typeof Chart === "undefined") return;
    destroy("statusChart");
    if (!entries.length) return;

    make("statusChart", {
      type: "doughnut",
      data: {
        labels: entries.map(([k]) => k),
        datasets: [
          {
            data: entries.map(([k]) => status[k]),
            backgroundColor: entries.map(([, c]) => hexToRgba(c, 0.75)),
            borderColor: entries.map(([, c]) => c),
            borderWidth: 1,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "68%",
        animation: { duration: 400 },
        plugins: { legend: { position: "bottom", labels: { boxWidth: 10, boxHeight: 10 } } },
      },
    });
  }

  const TIER_COLORS = { standard: "#c9a227", premium_image: "#e0c45a", premium_video: "#9a8cff", unknown: "#8a8478" };

  function drawSpendBreakdowns(overview) {
    const tiers = overview.spend_by_tier || {};
    const tierKeys = Object.keys(tiers);
    destroy("tierChart");
    if (tierKeys.length) {
      make("tierChart", {
        type: "doughnut",
        data: {
          labels: tierKeys,
          datasets: [
            {
              data: tierKeys.map((k) => tiers[k]),
              backgroundColor: tierKeys.map((k) => hexToRgba(TIER_COLORS[k] || "#39c5cf", 0.75)),
              borderColor: tierKeys.map((k) => TIER_COLORS[k] || "#39c5cf"),
              borderWidth: 1,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          cutout: "60%",
          plugins: { legend: { position: "bottom", labels: { boxWidth: 10, boxHeight: 10 } } },
        },
      });
    }

    const providers = overview.spend_by_provider || {};
    const provKeys = Object.keys(providers);
    destroy("providerChart");
    if (provKeys.length) {
      make("providerChart", {
        type: "bar",
        data: {
          labels: provKeys,
          datasets: [
            {
              data: provKeys.map((k) => providers[k]),
              backgroundColor: provKeys.map((_, i) => hexToRgba(PALETTE[i % PALETTE.length], 0.7)),
              borderColor: provKeys.map((_, i) => PALETTE[i % PALETTE.length]),
              borderWidth: 1,
              borderRadius: 4,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          indexAxis: "y",
          plugins: { legend: { display: false } },
          scales: { x: { ...axisOpts.x, ticks: { callback: (v) => `$${v}` } }, y: axisOpts.y },
        },
      });
    }

    const rej = overview.rejection_summary || {};
    destroy("rejectionChart");
    make("rejectionChart", {
      type: "bar",
      data: {
        labels: ["Topic skips", "Duration retries", "Duration aborts"],
        datasets: [
          {
            data: [rej.topic_rejections || 0, rej.duration_retries || 0, rej.duration_aborts || 0],
            backgroundColor: [hexToRgba("#c9a227", 0.7), hexToRgba("#e0c45a", 0.7), hexToRgba("#e85d4c", 0.7)],
            borderColor: ["#c9a227", "#e0c45a", "#e85d4c"],
            borderWidth: 1,
            borderRadius: 4,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: axisOpts,
      },
    });
  }

  function renderAll(overview, ctx) {
    ctx = ctx || { colors: {}, names: {}, brandFilter: null, cutoff: null };
    drawTimeline(overview, ctx);
    drawGrowth(overview, ctx);
    drawStatus(overview);
    drawSpendBreakdowns(overview);
  }

  global.MPCharts = { renderAll, destroy, charts, PALETTE };
})(window);
