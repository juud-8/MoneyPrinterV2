"""Machine-parseable pipeline stage markers for the dashboard's live progress view.

Emits one tagged line per major generation milestone so the dashboard's
pipeline-theater view can track real progress instead of guessing from raw
log text via regex. Gated behind MPV2_STAGE_EVENTS so interactive/cron runs
stay visually clean — only dashboard-launched jobs (webui_jobs.start_job())
set that env var.
"""

from __future__ import annotations

import json
import os

STAGE_TAG = "##MPV2_STAGE##"


def emit_stage(stage: str, **extra) -> None:
    """Print a machine-parseable stage marker, if enabled for this run."""
    if os.environ.get("MPV2_STAGE_EVENTS") != "1":
        return
    payload = {"stage": stage}
    payload.update(extra)
    print(f"{STAGE_TAG}{json.dumps(payload)}")
