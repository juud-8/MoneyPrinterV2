"""Local web UI for MoneyPrinterV2 — "EL JEFE" mission control.

One-command control panel served at http://127.0.0.1:5757 —
per-brand "Generate" / "Generate & Post now" buttons, publish-slot editing,
live job logs, YouTube metrics refresh, systems health, and the analytics
dashboard.

Run from the project root:
    python src/webui.py
"""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request

# Allow running both as `python src/webui.py` and from tooling that doesn't
# set sys.path[0] to src/.
SRC_DIR = os.path.dirname(os.path.abspath(__file__))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

import webui_jobs
from analytics import (
    get_dashboard_data,
    get_weekly_summary,
    set_video_retention,
)
from brand_switcher import list_brands, load_brand
from performance_insights import get_insights_summary
from trend_discovery import fetch_trending_topics
from youtube_metrics import get_latest_channel_snapshots

app = Flask(
    __name__,
    template_folder=os.path.join(SRC_DIR, "templates"),
    static_folder=os.path.join(SRC_DIR, "static"),
    static_url_path="/static",
)

ROOT_DIR = os.path.dirname(SRC_DIR)

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

# —— Systems health ——————————————————————————————————————————————
# Cached so the LED strip in the header can poll without hammering
# Ollama or re-reading config on every overview refresh.
_HEALTH_TTL_SECONDS = 45
_health_cache: dict = {"at": 0.0, "data": None}
_health_lock = threading.Lock()


def _read_config() -> dict:
    path = os.path.join(ROOT_DIR, "config.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _check_ollama(base_url: str) -> dict:
    # Two attempts: a busy Ollama (mid-generation) can miss a short timeout,
    # and one flaky probe shouldn't paint the whole panel CRITICAL.
    last_error = ""
    for attempt, timeout in enumerate((1.5, 3.0)):
        try:
            with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/version", timeout=timeout) as res:
                version = json.loads(res.read().decode("utf-8", "replace")).get("version", "")
                return {"ok": True, "detail": f"v{version}" if version else "reachable"}
        except Exception as e:  # noqa: BLE001 — any failure means "down" here
            last_error = str(e.__class__.__name__)
    return {"ok": False, "detail": last_error}


def _build_health() -> dict:
    config = _read_config()

    def key_present(name: str, env: str | None = None) -> bool:
        value = str(config.get(name, "") or "").strip()
        if not value and env:
            value = os.environ.get(env, "").strip()
        return bool(value)

    keys = {
        "gemini": key_present("gemini_api_key", "GEMINI_API_KEY")
        or key_present("nanobanana2_api_key"),
        "youtube_data": key_present("youtube_api_key"),
        "fish_audio": key_present("fish_audio_api_key", "FISH_AUDIO_API_KEY"),
        "elevenlabs": key_present("elevenlabs_api_key", "ELEVENLABS_API_KEY"),
        "fal": key_present("fal_api_key", "FAL_KEY"),
        "post_bridge": key_present("post_bridge_api_key", "POST_BRIDGE_API_KEY"),
    }

    imagemagick = str(config.get("imagemagick_path", "") or "")
    ollama_url = str(config.get("ollama_base_url", "") or "http://127.0.0.1:11434")

    brand_profiles = []
    for brand in list_brands():
        manifest = load_brand(brand["brand_id"]) or {}
        profile = str(manifest.get("firefox_profile", "") or config.get("firefox_profile", ""))
        brand_profiles.append(
            {
                "brand_id": brand["brand_id"],
                "profile_ok": bool(profile) and os.path.isdir(profile),
            }
        )

    # Metrics freshness — latest snapshot date across brands.
    snapshots = get_latest_channel_snapshots()
    latest_snapshot = max((s.get("date", "") for s in snapshots.values()), default="")

    try:
        usage = shutil.disk_usage(ROOT_DIR)
        disk_free_gb = round(usage.free / (1024**3), 1)
    except OSError:
        disk_free_gb = None

    return {
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "keys": keys,
        "ollama": _check_ollama(ollama_url),
        "imagemagick_ok": bool(imagemagick) and os.path.isfile(imagemagick),
        "brand_profiles": brand_profiles,
        "latest_channel_snapshot": latest_snapshot,
        "disk_free_gb": disk_free_gb,
        "config_present": bool(config),
    }


@app.get("/api/health")
def api_health():
    force = request.args.get("force") in ("1", "true")
    now = time.monotonic()
    with _health_lock:
        fresh = _health_cache["data"] is not None and (now - _health_cache["at"]) < _HEALTH_TTL_SECONDS
        if fresh and not force:
            return jsonify(_health_cache["data"])
    data = _build_health()
    with _health_lock:
        _health_cache["data"] = data
        _health_cache["at"] = time.monotonic()
    return jsonify(data)


# —— Finished renders on disk ————————————————————————————————————
def _safe_brand_output_dir(brand_id: str) -> str | None:
    """Resolve output/<brand_id> and refuse anything that escapes output/."""
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", brand_id or ""):
        return None
    base = os.path.realpath(os.path.join(ROOT_DIR, "output"))
    path = os.path.realpath(os.path.join(base, brand_id))
    if os.path.commonpath([base, path]) != base:
        return None
    return path


@app.get("/api/outputs")
def api_outputs():
    """Newest finished renders per brand from output/<brand_id>/."""
    result: dict[str, list[dict]] = {}
    out_root = os.path.join(ROOT_DIR, "output")
    if not os.path.isdir(out_root):
        return jsonify(result)
    for brand_id in sorted(os.listdir(out_root)):
        folder = _safe_brand_output_dir(brand_id)
        if not folder or not os.path.isdir(folder):
            continue
        files = []
        try:
            for name in os.listdir(folder):
                if not name.lower().endswith((".mp4", ".mov", ".webm")):
                    continue
                full = os.path.join(folder, name)
                try:
                    stat = os.stat(full)
                except OSError:
                    continue
                files.append(
                    {
                        "name": name,
                        "size_mb": round(stat.st_size / (1024**2), 1),
                        "mtime": stat.st_mtime,
                    }
                )
        except OSError:
            continue
        files.sort(key=lambda f: f["mtime"], reverse=True)
        for f in files:
            f["modified"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(f.pop("mtime")))
        result[brand_id] = files[:3]
    return jsonify(result)


@app.post("/api/open-output/<brand_id>")
def api_open_output(brand_id: str):
    """Open the brand's output folder in the OS file manager (local tool)."""
    folder = _safe_brand_output_dir(brand_id)
    if not folder:
        return jsonify({"error": f"Invalid brand id: {brand_id}"}), 400
    os.makedirs(folder, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(folder)  # noqa: S606 — local operator tool by design
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except OSError as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True, "path": folder})


def _parse_days_arg(raw: str | None) -> int | None:
    """Parse ?days= for overview. 'all' / 0 → None (all-time). Default 7."""
    if raw is None or raw == "":
        return 7
    text = str(raw).strip().lower()
    if text in ("all", "0", "none"):
        return None
    try:
        value = int(text)
    except ValueError:
        return 7
    if value <= 0:
        return None
    return min(value, 3650)


@app.get("/")
def index():
    return render_template("webui.html")


@app.get("/api/overview")
def api_overview():
    days = _parse_days_arg(request.args.get("days"))
    data = get_dashboard_data(days=days)
    data["channel_snapshots"] = get_latest_channel_snapshots()
    data["insights"] = {
        b["brand_id"]: get_insights_summary(b["brand_id"]) for b in data["brands"]
    }
    return jsonify(data)


@app.get("/api/ops")
def api_ops():
    """Cheap poll payload for Command Deck (ops brief + alerts + KPIs)."""
    days = _parse_days_arg(request.args.get("days"))
    data = get_dashboard_data(days=days)
    videos = data.get("videos") or []
    brands_meta = []
    for brand in list_brands():
        manifest = load_brand(brand["brand_id"]) or {}
        publishing = manifest.get("publishing", {}) or {}
        brands_meta.append(
            {
                "brand_id": brand["brand_id"],
                "channel_name": brand.get("channel_name", brand["brand_id"]),
                "shorts_per_day": publishing.get("shorts_per_day"),
                "publish_slots": publishing.get("publish_slots", {}),
                "pilot_mode": bool(
                    (manifest.get("production") or {}).get("pilot_mode", False)
                ),
                "is_active": brand.get("is_active", False),
            }
        )
    insights = {
        b["brand_id"]: get_insights_summary(b["brand_id"]) for b in data.get("brands", [])
    }
    return jsonify(
        {
            "generated_at": data.get("generated_at"),
            "window_days": data.get("window_days"),
            "totals": data.get("totals"),
            "spend_alert": data.get("spend_alert"),
            "rejection_summary": data.get("rejection_summary"),
            "channel_snapshots": get_latest_channel_snapshots(),
            "brands_summary": data.get("brands"),
            "brands_meta": brands_meta,
            "videos": videos[:40],
            "insights": insights,
            "status_counts": data.get("status_counts"),
        }
    )


@app.post("/api/retention")
def api_retention():
    payload = request.get_json(silent=True) or {}
    needle = str(payload.get("needle") or "").strip()
    try:
        pct = float(payload.get("avg_view_pct"))
    except (TypeError, ValueError):
        return jsonify({"error": "avg_view_pct must be a number 0-100"}), 400
    if not needle:
        return jsonify({"error": "needle is required"}), 400
    try:
        count = set_video_retention(needle, pct)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not count:
        return jsonify({"error": f"No videos matched '{needle}'", "updated": 0}), 404
    return jsonify({"ok": True, "updated": count, "avg_view_pct": pct})


@app.get("/api/weekly")
def api_weekly():
    data = get_dashboard_data(days=7)
    totals = data.get("totals") or {}
    uploaded = int(totals.get("uploaded") or 0)
    spend = float(totals.get("spend_window_usd") or 0.0)
    cost_per = round(spend / uploaded, 4) if uploaded > 0 else None
    recent = (data.get("videos") or [])[:20]
    return jsonify(
        {
            "generated_at": data.get("generated_at"),
            "window_days": 7,
            "totals": totals,
            "spend_alert": data.get("spend_alert"),
            "rejection_summary": data.get("rejection_summary"),
            "cost_per_uploaded_short_usd": cost_per,
            "recent_videos": recent,
            "text": get_weekly_summary(),
            "brands": data.get("brands") or [],
        }
    )


def _scan_archive_songs() -> list[dict]:
    """Find archive-song episodes paused at awaiting_song_audio."""
    out_root = os.path.join(ROOT_DIR, "output")
    results: list[dict] = []
    if not os.path.isdir(out_root):
        return results
    for brand_id in sorted(os.listdir(out_root)):
        brand_dir = _safe_brand_output_dir(brand_id)
        if not brand_dir:
            continue
        episodes_dir = os.path.join(brand_dir, "episodes")
        if not os.path.isdir(episodes_dir):
            continue
        try:
            episode_names = os.listdir(episodes_dir)
        except OSError:
            continue
        for episode_id in episode_names:
            if not re.fullmatch(r"[A-Za-z0-9_\-]+", episode_id or ""):
                continue
            ep_dir = os.path.realpath(os.path.join(episodes_dir, episode_id))
            if os.path.commonpath([brand_dir, ep_dir]) != brand_dir:
                continue
            state_path = os.path.join(ep_dir, "archive_song_state.json")
            if not os.path.isfile(state_path):
                continue
            try:
                with open(state_path, "r", encoding="utf-8") as f:
                    state = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            status = str((state or {}).get("status") or "")
            if status != "awaiting_song_audio":
                continue
            results.append(
                {
                    "brand_id": brand_id,
                    "episode_id": episode_id,
                    "status": status,
                    "path": ep_dir,
                    "topic": (state or {}).get("topic") or "",
                }
            )
    return results


@app.get("/api/archive-songs")
def api_archive_songs():
    return jsonify(_scan_archive_songs())


@app.post("/api/open-episode/<brand_id>/<episode_id>")
def api_open_episode(brand_id: str, episode_id: str):
    brand_dir = _safe_brand_output_dir(brand_id)
    if not brand_dir:
        return jsonify({"error": f"Invalid brand id: {brand_id}"}), 400
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", episode_id or ""):
        return jsonify({"error": f"Invalid episode id: {episode_id}"}), 400
    folder = os.path.realpath(os.path.join(brand_dir, "episodes", episode_id))
    if os.path.commonpath([brand_dir, folder]) != brand_dir:
        return jsonify({"error": "Path escapes brand output"}), 400
    if not os.path.isdir(folder):
        return jsonify({"error": "Episode folder not found"}), 404
    try:
        if sys.platform == "win32":
            os.startfile(folder)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except OSError as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True, "path": folder})


@app.post("/api/preflight")
def api_preflight():
    job = webui_jobs.run_python_script(
        "preflight",
        "Run preflight",
        os.path.join("scripts", "preflight_local.py"),
        [],
    )
    return jsonify(job)


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


@app.post("/api/brands/<brand_id>/trending-topics")
def api_trending_topics(brand_id: str):
    """Suggest topic candidates from current search trends for a brand's niche.

    Manual-trigger only — a quick in-process fetch + LLM rank, not routed
    through webui_jobs (no Selenium/profile-lock concern here). Never 500s
    on a trend-source failure; fetch_trending_topics degrades to [] itself.
    """
    manifest = load_brand(brand_id)
    if not manifest:
        return jsonify({"error": f"Unknown brand: {brand_id}"}), 404

    niche = manifest.get("niche", "")
    topics = fetch_trending_topics(niche)
    return jsonify({"topics": topics})


@app.post("/api/generate")
def api_generate():
    payload = request.get_json(silent=True) or {}
    brand_id = payload.get("brand_id", "")
    upload = bool(payload.get("upload", False))
    topic = str(payload.get("topic") or "").strip()
    image_provider = str(payload.get("image_provider") or "").strip().lower()

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
    if topic:
        args += ["--topic", topic]
    if image_provider in ("gemini", "fal"):
        # One-off override for this run only — see config.get_standard_image_provider().
        env_extra["MPV2_IMAGE_PROVIDER_OVERRIDE"] = image_provider

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


@app.get("/api/jobs/<job_id>/log/stream")
def api_job_log_stream(job_id: str):
    """Server-Sent Events tail of a job log (fallback: client can poll /log)."""
    job = webui_jobs.get_job(job_id)
    if not job:
        return jsonify({"error": "Unknown job"}), 404

    def generate():
        offset = 0
        idle_ticks = 0
        while True:
            current = webui_jobs.get_job(job_id)
            if not current:
                yield "event: end\ndata: {\"error\":\"gone\"}\n\n"
                break
            chunk = webui_jobs.read_log(job_id, offset)
            text = chunk.get("text") or ""
            offset = int(chunk.get("offset") or offset)
            status = current.get("status") or ""
            if text:
                idle_ticks = 0
                payload = json.dumps({"text": text, "offset": offset, "status": status})
                yield f"event: log\ndata: {payload}\n\n"
            else:
                idle_ticks += 1
                yield f"event: ping\ndata: {json.dumps({'status': status, 'offset': offset})}\n\n"
            if status != "running":
                yield f"event: end\ndata: {json.dumps({'status': status, 'offset': offset})}\n\n"
                break
            if idle_ticks > 600:
                yield "event: end\ndata: {\"status\":\"timeout\"}\n\n"
                break
            time.sleep(0.75)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.post("/api/jobs/<job_id>/cancel")
def api_job_cancel(job_id: str):
    if not webui_jobs.cancel_job(job_id):
        return jsonify({"error": "Job not found or not running"}), 404
    return jsonify({"ok": True})


if __name__ == "__main__":
    port = int(os.environ.get("MPV2_WEBUI_PORT", "5757"))
    print(f"EL JEFE mission control (MoneyPrinterV2): http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)
