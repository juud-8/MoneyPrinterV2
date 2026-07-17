/* EL JEFE — Pipeline jobs + SSE log streaming */
(function (global) {
  const M = global.MPV2;
  const { state, $, esc, durationBetween, toast, api, activeSection } = M;

  function selectJob(jobId) {
    state.selectedJob = jobId;
    state.logOffset = 0;
    const logEl = $("log-view");
    if (logEl) logEl.textContent = "";
    if (state.logSource) {
      try { state.logSource.close(); } catch (e) { /* ignore */ }
      state.logSource = null;
    }
    if (window.MPV2PipelineTheater) MPV2PipelineTheater.onJobSelected();
    renderJobs();
    startLogStream(jobId);
  }

  function anyJobRunning() {
    return state.jobsCache.some((j) => j.status === "running");
  }

  function renderJobs() {
    const body = $("jobs-body");
    if (!body) return;
    if (!state.jobsCache.length) {
      body.innerHTML = '<tr><td colspan="5" class="muted">No jobs yet — kick one off from the Command Deck or Ctrl+K.</td></tr>';
      return;
    }
    body.innerHTML = state.jobsCache
      .map((j) => {
        const pillClass =
          j.status === "running" ? "pill amber" : j.status === "succeeded" ? "pill green" : j.status === "interrupted" ? "pill gray" : "pill red";
        const cancel =
          j.status === "running"
            ? `<button class="danger small" data-action="cancel-job" data-job="${j.id}">Cancel</button>`
            : "";
        return `<tr class="selectable ${state.selectedJob === j.id ? "selected" : ""}" data-action="select-job" data-job="${j.id}">
          <td class="muted" style="white-space:nowrap">${esc(j.started_at)}</td>
          <td><span class="status-dot ${esc(j.status)}"></span>${esc(j.label)}</td>
          <td class="muted small">${esc(durationBetween(j.started_at, j.finished_at))}</td>
          <td><span class="${pillClass}">${esc(j.status)}</span></td>
          <td>${cancel}</td>
        </tr>`;
      })
      .join("");
  }

  function appendLogText(text) {
    const el = $("log-view");
    if (!text || !el) return;
    const stick = el.scrollTop + el.clientHeight >= el.scrollHeight - 24;
    el.textContent += text;
    if (stick) el.scrollTop = el.scrollHeight;
  }

  function notifyTheater() {
    if (!state.selectedJob || !window.MPV2PipelineTheater) return;
    MPV2PipelineTheater.onLogUpdate({
      fullText: ($("log-view") && $("log-view").textContent) || "",
      label: state.jobLabelMap[state.selectedJob] || "",
      status: state.jobStatusMap[state.selectedJob] || "",
    });
  }

  function startLogStream(jobId) {
    if (!jobId || typeof EventSource === "undefined") {
      pollLog();
      return;
    }
    try {
      const es = new EventSource(`/api/jobs/${jobId}/log/stream`);
      state.logSource = es;
      es.addEventListener("log", (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (data.text) appendLogText(data.text);
          if (data.offset != null) state.logOffset = data.offset;
          if (data.status) state.jobStatusMap[jobId] = data.status;
          notifyTheater();
        } catch (e) { /* ignore */ }
      });
      es.addEventListener("ping", (ev) => {
        try {
          const data = JSON.parse(ev.data);
          if (data.status) state.jobStatusMap[jobId] = data.status;
          if (data.offset != null) state.logOffset = data.offset;
          notifyTheater();
        } catch (e) { /* ignore */ }
      });
      es.addEventListener("end", (ev) => {
        try {
          const data = JSON.parse(ev.data || "{}");
          if (data.status) state.jobStatusMap[jobId] = data.status;
        } catch (e) { /* ignore */ }
        es.close();
        if (state.logSource === es) state.logSource = null;
        notifyTheater();
        refreshJobs();
      });
      es.onerror = () => {
        es.close();
        if (state.logSource === es) state.logSource = null;
        // Fallback to polling
        pollLog();
      };
    } catch (e) {
      pollLog();
    }
  }

  async function pollLog() {
    if (!state.selectedJob || document.hidden) return;
    try {
      const res = await api(`/api/jobs/${state.selectedJob}/log?offset=${state.logOffset}`);
      if (res.text) {
        appendLogText(res.text);
        state.logOffset = res.offset;
      }
      if (res.status) state.jobStatusMap[state.selectedJob] = res.status;
      notifyTheater();
    } catch (e) { /* ignore */ }
  }

  async function refreshJobs() {
    let jobs;
    try {
      jobs = await api("/api/jobs");
    } catch (e) {
      return;
    }
    for (const j of jobs) {
      const prev = state.jobStatusMap[j.id];
      if (prev === "running" && j.status !== "running") {
        toast(j.status === "succeeded" ? `Finished: ${j.label}` : `Ended (${j.status}): ${j.label}`, j.status !== "succeeded");
        if (M.refreshOverview) M.refreshOverview(true).catch(() => {});
        if (M.fetchHealth) M.fetchHealth().catch(() => {});
        if (M.loadArchiveSongs) M.loadArchiveSongs().catch(() => {});
      }
      state.jobStatusMap[j.id] = j.status;
      state.jobLabelMap[j.id] = j.label;
    }
    state.jobsCache = jobs;
    renderJobs();
    notifyTheater();
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

  async function startMetricsRefresh() {
    const btn = $("refresh-metrics");
    if (btn) btn.disabled = true;
    try {
      const job = await api("/api/metrics/refresh", { method: "POST" });
      toast("Metrics refresh started — overview reloads when it finishes.");
      selectJob(job.id);
      await refreshJobs();
      M.setSection("pipeline");
    } catch (e) {
      toast(e.message, true);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function jobsLoop() {
    const delay = anyJobRunning() || activeSection() === "pipeline" ? 2500 : 8000;
    setTimeout(async () => {
      if (!document.hidden) await refreshJobs().catch(() => {});
      jobsLoop();
    }, delay);
  }

  Object.assign(M, {
    selectJob,
    anyJobRunning,
    renderJobs,
    refreshJobs,
    cancelJob,
    pollLog,
    startLogStream,
    startMetricsRefresh,
    jobsLoop,
  });
})(window);
