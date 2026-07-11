"""Local web UI for MoneyPrinterV2.

One-command control panel served at http://127.0.0.1:5757 —
per-brand "Generate" / "Generate & Post now" buttons, publish-slot editing,
live job logs, YouTube metrics refresh, and the analytics dashboard.

Run from the project root:
    python src/webui.py
"""

import json
import os
import re
import sys

# Allow running both as `python src/webui.py` and from tooling that doesn't
# set sys.path[0] to src/.
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from flask import Flask, jsonify, render_template, request

import webui_jobs
from analytics import get_dashboard_data
from brand_switcher import list_brands, load_brand
from performance_insights import get_insights_summary
from youtube_metrics import get_latest_channel_snapshots

app = Flask(__name__, template_folder=os.path.join(SRC_DIR, "templates"))

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@app.get("/")
def index():
    return render_template("webui.html")


@app.get("/api/overview")
def api_overview():
    days = int(request.args.get("days", 7))
    data = get_dashboard_data(days=days)
    data["channel_snapshots"] = get_latest_channel_snapshots()
    data["insights"] = {
        b["brand_id"]: get_insights_summary(b["brand_id"]) for b in data["brands"]
    }
    return jsonify(data)


@app.get("/api/brands")
def api_brands():
    brands = []
    for brand in list_brands():
        manifest = load_brand(brand["brand_id"]) or {}
        publishing = manifest.get("publishing", {})
        brands.append(
            {
                "brand_id": brand["brand_id"],
                "channel_name": brand.get("channel_name", brand["brand_id"]),
                "niche": brand.get("niche", ""),
                "is_active": brand.get("is_active", False),
                "channel_id": manifest.get("channel_id", ""),
                "pilot_mode": bool(
                    (manifest.get("production") or {}).get("pilot_mode", False)
                ),
                "publish_slots": publishing.get("publish_slots", {}),
                "shorts_per_day": publishing.get("shorts_per_day"),
                "default_visibility": publishing.get("default_visibility", ""),
            }
        )
    return jsonify(brands)


@app.post("/api/brands/<brand_id>/slots")
def api_update_slots(brand_id: str):
    """Update publish windows in the brand manifest.

    The scheduled runner re-reads `publishing.publish_slots` from the
    manifest on every run, so this changes actual publish times. The
    Windows Task Scheduler trigger only needs to START before the window
    opens (see scheduler_start_hint).
    """
    manifest = load_brand(brand_id)
    if not manifest:
        return jsonify({"error": f"Unknown brand: {brand_id}"}), 404

    slots_update = request.get_json(silent=True) or {}
    for slot_name, slot in slots_update.items():
        for key in ("window_start", "window_end", "scheduler_start_hint"):
            value = (slot or {}).get(key, "")
            if value and not _HHMM.match(value):
                return (
                    jsonify({"error": f"{slot_name}.{key} must be HH:MM (24h), got '{value}'"}),
                    400,
                )

    # Re-read the raw file so we never persist injected keys
    # (brand_id/_config_path added by load_brand).
    path = manifest["_config_path"]
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    publishing = raw.setdefault("publishing", {})
    slots = publishing.setdefault("publish_slots", {})
    for slot_name, slot in slots_update.items():
        target = slots.setdefault(slot_name, {})
        for key in ("window_start", "window_end", "scheduler_start_hint"):
            if (slot or {}).get(key):
                target[key] = slot[key]

    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2)
        f.write("\n")

    return jsonify({"ok": True, "publish_slots": slots})


@app.post("/api/generate")
def api_generate():
    payload = request.get_json(silent=True) or {}
    brand_id = payload.get("brand_id", "")
    upload = bool(payload.get("upload", False))

    if not load_brand(brand_id):
        return jsonify({"error": f"Unknown brand: {brand_id}"}), 404

    from archived_brands import is_brand_archived

    if is_brand_archived(brand_id):
        return jsonify({"error": f"Brand '{brand_id}' is archived and cannot run."}), 403

    args = [brand_id]
    env_extra = {}
    if upload:
        args.append("--upload")
        # The button click is the explicit human confirmation pilot mode
        # asks for on non-interactive runs (see review_gate.py).
        env_extra["MPV2_PILOT_UPLOAD_CONFIRMED"] = "1"

    label = f"{'Generate & post' if upload else 'Generate'} — {brand_id}"
    try:
        job = webui_jobs.run_python_script(
            "generate",
            label,
            os.path.join("scripts", "run_brand_short.py"),
            args,
            brand_id=brand_id,
            env_extra=env_extra,
        )
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 409
    return jsonify(job)


@app.post("/api/metrics/refresh")
def api_metrics_refresh():
    job = webui_jobs.run_python_script(
        "metrics",
        "Refresh YouTube metrics",
        os.path.join("src", "youtube_metrics.py"),
        [],
    )
    return jsonify(job)


@app.get("/api/jobs")
def api_jobs():
    return jsonify(webui_jobs.list_jobs())


@app.get("/api/jobs/<job_id>/log")
def api_job_log(job_id: str):
    offset = int(request.args.get("offset", 0))
    job = webui_jobs.get_job(job_id)
    if not job:
        return jsonify({"error": "Unknown job"}), 404
    result = webui_jobs.read_log(job_id, offset)
    result["status"] = job["status"]
    return jsonify(result)


@app.post("/api/jobs/<job_id>/cancel")
def api_job_cancel(job_id: str):
    if not webui_jobs.cancel_job(job_id):
        return jsonify({"error": "Job not found or not running"}), 404
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("MPV2_WEBUI_PORT", "5757"))
    print(f"MoneyPrinterV2 control panel: http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)
