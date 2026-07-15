"""Background job runner for the local web UI.

Runs pipeline commands (generate, generate+upload, metrics refresh) as
subprocesses with output captured to per-job log files under
`.mp/logs/webui/`, so the UI can stream progress live. A small index in
`.mp/logs/webui/jobs.json` keeps job history (and their logs) visible
across control-panel restarts.

Generation jobs are serialized globally: `switch_brand()` writes the shared
`.mp/active_brand.json` and generation grabs a Firefox profile, so two
concurrent runs would trample each other.
"""

import json
import os
import subprocess
import sys
import threading
import uuid
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(ROOT_DIR, ".mp", "logs", "webui")
INDEX_PATH = os.path.join(LOG_DIR, "jobs.json")
HISTORY_LIMIT = 100

_jobs: dict[str, dict] = {}
_processes: dict[str, subprocess.Popen] = {}
_lock = threading.Lock()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _persist_locked() -> None:
    """Write the job index. Caller must hold _lock."""
    jobs = sorted(_jobs.values(), key=lambda j: j["started_at"], reverse=True)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(INDEX_PATH, "w", encoding="utf-8") as f:
            json.dump(jobs[:HISTORY_LIMIT], f, indent=2)
    except OSError:
        pass  # history is best-effort; never fail a job over it


def _load_history() -> None:
    """Load prior sessions' jobs. Anything still 'running' was orphaned by
    a server restart — its subprocess is no longer ours to track."""
    if not os.path.isfile(INDEX_PATH):
        return
    try:
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            saved = json.load(f)
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(saved, list):
        return
    with _lock:
        for job in saved:
            if not isinstance(job, dict) or not job.get("id"):
                continue
            if job.get("status") == "running":
                job["status"] = "interrupted"
            _jobs.setdefault(job["id"], job)


_load_history()


def has_running_generation() -> bool:
    with _lock:
        return any(
            j["kind"] == "generate" and j["status"] == "running"
            for j in _jobs.values()
        )


def start_job(
    kind: str,
    label: str,
    cmd: list[str],
    brand_id: str = "",
    env_extra: dict | None = None,
) -> dict:
    """Spawn a subprocess job. Raises RuntimeError if a generation job is
    already running and another generation is requested."""
    if kind == "generate" and has_running_generation():
        raise RuntimeError(
            "A generation job is already running. Wait for it to finish — "
            "runs share the active-brand state and Firefox profile."
        )

    job_id = uuid.uuid4().hex[:12]
    os.makedirs(LOG_DIR, exist_ok=True)
    log_path = os.path.join(LOG_DIR, f"{job_id}.log")

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    if env_extra:
        env.update(env_extra)

    log_file = open(log_path, "w", encoding="utf-8", errors="replace")
    log_file.write(f"[{_now()}] $ {' '.join(cmd)}\n")
    log_file.flush()

    process = subprocess.Popen(
        cmd,
        cwd=ROOT_DIR,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=env,
    )

    job = {
        "id": job_id,
        "kind": kind,
        "label": label,
        "brand_id": brand_id,
        "status": "running",
        "started_at": _now(),
        "finished_at": None,
        "returncode": None,
        "log_path": log_path,
    }
    with _lock:
        _jobs[job_id] = job
        _processes[job_id] = process
        _persist_locked()

    def _wait() -> None:
        returncode = process.wait()
        log_file.close()
        with _lock:
            job["returncode"] = returncode
            job["finished_at"] = _now()
            if job["status"] != "cancelled":
                job["status"] = "succeeded" if returncode == 0 else "failed"
            _processes.pop(job_id, None)
            _persist_locked()

    threading.Thread(target=_wait, daemon=True).start()
    return dict(job)


def cancel_job(job_id: str) -> bool:
    with _lock:
        process = _processes.get(job_id)
        job = _jobs.get(job_id)
        if not process or not job:
            return False
        job["status"] = "cancelled"
        _persist_locked()
    process.terminate()
    return True


def list_jobs() -> list[dict]:
    with _lock:
        jobs = [dict(j) for j in _jobs.values()]
    jobs.sort(key=lambda j: j["started_at"], reverse=True)
    return jobs


def get_job(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def read_log(job_id: str, offset: int = 0) -> dict:
    """Return log text from byte offset onward plus the new offset."""
    job = get_job(job_id)
    if not job or not os.path.isfile(job["log_path"]):
        return {"text": "", "offset": offset}
    with open(job["log_path"], "r", encoding="utf-8", errors="replace") as f:
        f.seek(offset)
        text = f.read()
        return {"text": text, "offset": f.tell()}


def run_python_script(
    kind: str,
    label: str,
    script_relpath: str,
    args: list[str],
    brand_id: str = "",
    env_extra: dict | None = None,
) -> dict:
    """Convenience: run a repo script with the current Python interpreter."""
    cmd = [sys.executable, os.path.join(ROOT_DIR, script_relpath), *args]
    return start_job(kind, label, cmd, brand_id=brand_id, env_extra=env_extra)
