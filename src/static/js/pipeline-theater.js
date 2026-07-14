/* Pipeline Archivist Filing Theater — stage-aware loading view. */
(function (global) {
  const STORAGE_KEY = "mpv2.pipelineView";
  const GENERATE_STAGES = [
    { id: "topic", label: "Topic" },
    { id: "research", label: "Research" },
    { id: "script", label: "Script" },
    { id: "assets", label: "Assets" },
    { id: "compose", label: "Compose" },
    { id: "upload", label: "Upload" },
    { id: "done", label: "Done" },
  ];
  const METRICS_STAGES = [
    { id: "start", label: "Start" },
    { id: "refresh", label: "Refresh" },
    { id: "done", label: "Done" },
  ];

  let viewMode = localStorage.getItem(STORAGE_KEY) || "theater";
  let forcedTerminal = false;
  let lastStatus = "";
  let lastParsed = null;

  function $(id) {
    return document.getElementById(id);
  }

  function isMetricsJob(label) {
    return /metric/i.test(label || "");
  }

  function stagesFor(label) {
    return isMetricsJob(label) ? METRICS_STAGES : GENERATE_STAGES;
  }

  function parseMoviePyPercent(text) {
    if (!text) return null;
    let m = text.match(/(\d{1,3})%\s*\|/);
    if (m) return Math.min(100, Number(m[1]));
    m = text.match(/\b(\d+)\s*\/\s*(\d+)\b/);
    if (m) {
      const cur = Number(m[1]);
      const total = Number(m[2]);
      if (total > 0) return Math.min(100, (100 * cur) / total);
    }
    return null;
  }

  function parseStages(fullLog, label) {
    const text = fullLog || "";
    const metrics = isMetricsJob(label);
    const hits = {};

    function mark(id, re) {
      if (re.test(text)) hits[id] = true;
    }

    if (metrics) {
      mark("start", /Refresh YouTube metrics|youtube_metrics|Starting/i);
      mark("refresh", /channel_snapshots|Updated|subscribers|video_count|Fetched/i);
      mark("done", /complete|succeeded|done|exit/i);
    } else {
      mark("topic", /Picked best|Using preset topic|Switched to:/i);
      mark("research", /Grounded research|Topic research failed|retrying research/i);
      mark("script", /Generated Image Prompts|Picked best of .* title/i);
      mark("assets", /Wrote standard image|Wrote TTS|Wrote premium/i);
      mark(
        "compose",
        /Combining images|Appending brand outro|MoviePy|frame_index|\d+\s*\/\s*\d+/i
      );
      mark(
        "upload",
        /Setting title|Setting visibility|Setting as unlisted|Uploaded Video|UPLOAD:/i
      );
      mark("done", /GENERATION COMPLETE|UPLOAD: success|UPLOAD: failed|UPLOAD: skipped/i);
    }

    const order = stagesFor(label).map((s) => s.id);
    let activeIdx = 0;
    for (let i = 0; i < order.length; i++) {
      if (hits[order[i]]) activeIdx = i;
    }

    // If compose is active, prefer MoviePy % from the tail of the log.
    const tail = text.slice(-4000);
    const renderPct = hits.compose ? parseMoviePyPercent(tail) : null;

    let tip = "Filing in progress…";
    if (hits.done && /UPLOAD: failed|Traceback|ERROR:/i.test(text)) {
      tip = "Run failed — open terminal for the traceback.";
    } else if (/UPLOAD: success/i.test(text)) {
      tip = "Upload reported success.";
    } else if (/GENERATION COMPLETE/i.test(text) && !/UPLOAD:/i.test(text)) {
      tip = "Generation complete.";
    } else if (hits.upload) {
      tip = "Publishing in YouTube Studio…";
    } else if (hits.compose && renderPct != null) {
      tip = `Compositing frames · ${Math.round(renderPct)}%`;
    } else if (hits.compose) {
      tip = "Compositing video (MoviePy)…";
    } else if (hits.assets) {
      tip = "Generating images & voice…";
    } else if (hits.research) {
      tip = "Grounding claims in sources…";
    } else if (hits.topic) {
      tip = "Choosing the next file from the archive…";
    } else if (metrics && hits.refresh) {
      tip = "Pulling public YouTube stats…";
    }

    const titleMatch = text.match(/TITLE:\s*(.+)/);
    const urlMatch = text.match(/URL:\s*(https?:\/\/\S+)/);
    const videoMatch = text.match(/VIDEO:\s*(.+)/);

    return {
      activeIdx,
      hits,
      renderPct,
      tip,
      title: titleMatch ? titleMatch[1].trim() : "",
      url: urlMatch ? urlMatch[1].trim() : "",
      videoPath: videoMatch ? videoMatch[1].trim() : "",
      failed: /UPLOAD: failed|Traceback \(most recent call last\)/i.test(text),
      succeeded:
        /UPLOAD: success/i.test(text) ||
        (/GENERATION COMPLETE/i.test(text) && !/UPLOAD: failed/i.test(text)),
    };
  }

  function preferredView() {
    if (forcedTerminal) return "terminal";
    return viewMode;
  }

  function setView(mode, { persist = true } = {}) {
    if (mode !== "theater" && mode !== "terminal") return;
    viewMode = mode;
    if (persist) localStorage.setItem(STORAGE_KEY, mode);
    applyView();
  }

  function applyView() {
    const theater = $("pipeline-theater");
    const log = $("log-view");
    const btn = $("toggle-pipeline-view");
    const mode = preferredView();
    if (!theater || !log || !btn) return;
    const showTheater = mode === "theater";
    theater.hidden = !showTheater;
    log.hidden = showTheater;
    btn.textContent = showTheater ? "See terminal" : "Theater";
  }

  function renderTheater(parsed, label, status) {
    const root = $("pipeline-theater");
    const stageLabel = $("pipeline-stage-label");
    if (!root) return;

    const stages = stagesFor(label);
    const active = Math.min(parsed.activeIdx, stages.length - 1);
    if (stageLabel) {
      stageLabel.textContent =
        status === "running"
          ? `Stage: ${stages[active].label}`
          : status
            ? `Job ${status}`
            : "Idle";
    }

    const rail = stages
      .map((s, i) => {
        let cls = "stage-pill";
        if (i < active) cls += " done";
        if (i === active) cls += " active";
        return `<span class="${cls}" data-stage="${s.id}">${s.label}</span>`;
      })
      .join('<span class="stage-sep" aria-hidden="true"></span>');

    const pct =
      parsed.renderPct != null
        ? `<div class="render-bar"><div class="render-bar-fill" style="width:${Math.round(
            parsed.renderPct
          )}%"></div><span>${Math.round(parsed.renderPct)}% render</span></div>`
        : "";

    let outcome = "";
    if (status === "succeeded" || (status !== "running" && parsed.succeeded)) {
      outcome = `<div class="theater-outcome ok">
        <strong>Filed.</strong>
        ${parsed.title ? `<div>${escapeHtml(parsed.title)}</div>` : ""}
        ${parsed.url ? `<div><a href="${escapeAttr(parsed.url)}" target="_blank" rel="noopener">${escapeHtml(parsed.url)}</a></div>` : ""}
        ${parsed.videoPath && !parsed.url ? `<div class="muted small">${escapeHtml(parsed.videoPath)}</div>` : ""}
      </div>`;
    } else if (status === "failed" || parsed.failed) {
      outcome = `<div class="theater-outcome bad"><strong>Failed.</strong> Switch to terminal for details.</div>`;
    }

    root.innerHTML = `
      <div class="theater-cabinet" aria-hidden="true">
        <div class="drawer-slot"><div class="drawer-face"></div></div>
        <div class="drawer-slot"><div class="drawer-face delay"></div></div>
        <div class="drawer-slot"><div class="drawer-face delay2"></div></div>
        <div class="stamp-pulse"></div>
      </div>
      <div class="theater-rail">${rail}</div>
      ${pct}
      <p class="theater-tip">${escapeHtml(parsed.tip)}</p>
      ${outcome}
    `;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function escapeAttr(s) {
    return escapeHtml(s).replace(/'/g, "&#39;");
  }

  function onJobSelected() {
    forcedTerminal = false;
    lastParsed = null;
    lastStatus = "";
    const tip = $("pipeline-stage-label");
    if (tip) tip.textContent = "Waiting for log…";
    applyView();
  }

  function onLogUpdate({ fullText, label, status }) {
    const parsed = parseStages(fullText || "", label || "");
    lastParsed = parsed;
    lastStatus = status || "";

    if (status === "failed" || parsed.failed) {
      forcedTerminal = true;
    } else if (status === "running") {
      forcedTerminal = false;
    }

    renderTheater(parsed, label || "", status || "");
    applyView();
  }

  function bindToggle() {
    const btn = $("toggle-pipeline-view");
    if (!btn || btn.dataset.bound) return;
    btn.dataset.bound = "1";
    btn.addEventListener("click", () => {
      forcedTerminal = false;
      setView(preferredView() === "theater" ? "terminal" : "theater");
    });
  }

  bindToggle();
  applyView();

  global.MPV2PipelineTheater = {
    onJobSelected,
    onLogUpdate,
    setView,
    parseStages,
    preferredView,
  };
})(window);
