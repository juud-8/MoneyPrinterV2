# Long-Form Scheduling

Shorts run daily; long-form runs weekly. This document covers how the weekly
long-form job is registered, what it does on each firing, and how it stays out
of the daily shorts job's way.

## Why weekly, and why themed

The shorts topic generator hunts for one novel incident per video, and in a
narrow niche it saturates — new candidates keep colliding with the duplicate
guardrail. Long-form doesn't need a novel incident. It needs a theme broad
enough to sustain several minutes, and the best raw material is the back
catalogue: already researched, already published, already measured.

So the weekly job runs in `--theme` mode. `src/longform_theme.py` clusters
published shorts by keyword, ranks the clusters by proven reach, skips themes
already used, and emits a chaptered compilation subject. That subject is fed to
the pipeline as a preset topic, which bypasses the single-incident duplicate
check by design.

More shorts published means more clusters available, so the cadence is
self-feeding: the weekly job gets easier to satisfy the longer the daily job
runs.

## Register the task

Windows Task Scheduler, via the wrapper script:

```powershell
# Generate + upload, Sundays at 2:00 AM local
powershell -ExecutionPolicy Bypass -File scripts\run_longform_weekly.ps1 `
  -Register -BrandId my_brand -Upload

# Generate only (no upload), Wednesdays at 3:30 AM
powershell -ExecutionPolicy Bypass -File scripts\run_longform_weekly.ps1 `
  -Register -BrandId my_brand -DayOfWeek Wednesday -Time 03:30
```

Re-registering is idempotent — the existing task is deleted first. To remove:

```powershell
schtasks /Delete /TN MoneyPrinterV2LongformWeekly /F
```

`-BrandId` is required when registering. The task pins its brand and calls
`switch_brand()` explicitly rather than depending on whichever brand happens to
be active when the task fires.

To run it by hand exactly as the scheduler would:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_longform_weekly.ps1 -BrandId my_brand
```

Logs append to `.mp/logs/longform_weekly.log`.

## Picking a start time

A long-form render takes 30-60+ minutes, considerably longer if a brand opts
shots into premium video assets. Pick a slot that cannot overlap the daily
shorts task.

Overlap matters because `utils.rem_temp_files()` deletes every non-JSON file at
the top level of `.mp/`, and both jobs use that directory as scratch space for
in-flight WAV/PNG/MP4 files. Two concurrent runs delete each other's working
files, and the symptom looks like a corrupt render rather than a collision.

`src/run_lock.py` guards against this: a run takes `.mp/locks/generation.lock`
before generating, and a second run exits rather than proceeding. The lock is
PID-stamped and expires after four hours, so a crashed run can't wedge the
schedule permanently.

The long-form runner takes this lock already. **The daily shorts task needs the
same call to be fully protected** — a shorts run that doesn't take the lock will
still walk into a long-form run's scratch files. Brand-pinned shorts scripts
live under `brands/<brand_id>/` and are private by convention, so wrap the
generation call there:

```python
from run_lock import run_lock, RunLockBusy

try:
    with run_lock("generation", os.path.join(ROOT, ".mp", "locks")):
        ...  # existing generation + upload call
except RunLockBusy as busy:
    print(f"SKIPPED: {busy}")
    sys.exit(75)
```

## Exit codes

The wrapper distinguishes deliberate no-ops from real failures, so Task
Scheduler's "last result" column stays meaningful:

| Code | Meaning | Wrapper behavior |
|---|---|---|
| 0 | Ran and finished | logged as finished |
| 75 | Another generation run held the lock | logged as a skip, exits 0 |
| 66 | No unused theme with enough published episodes yet | logged as a skip, exits 0 |
| other | Real failure | logged with the code, exits non-zero |

Code 66 is normal once every eligible cluster has been made into an episode.
It resolves itself as the daily shorts job publishes more material.

## Uploads and the review gate

`-Upload` passes `--upload --unattended` to the runner. The `--unattended` flag
sets `MPV2_UNATTENDED_UPLOAD=1` and `MPV2_RUN_TASK=longform`, matching what
`src/cron.py` does for scheduled shorts.

This matters for brands running with `pilot_mode`. Without the unattended
marker, `review_gate.should_proceed_with_upload()` refuses an automated upload
outright — there's nobody at the keyboard to approve it. With it, the upload is
staged **private** for human review, and publishing stays a deliberate
visibility change in Studio.

Non-pilot brands are unaffected: `review_before_upload` has never had an
automated-run effect for them, and scheduled uploads proceed as before.

Manual runs of `scripts/run_brand_longform.py --upload` do *not* set the
unattended marker, so they keep using the brand's configured visibility.

## Runner flags

`scripts/run_brand_longform.py [brand_id] [flags]`

| Flag | Effect |
|---|---|
| *(none)* | Generates one long-form video, prints the output path, no upload |
| `--theme` | Builds the subject as a themed compilation of published shorts |
| `--upload` | Uploads through the review gate after generating |
| `--unattended` | Marks the run as scheduled — stages pilot uploads private |

Omitting `brand_id` falls back to the currently active brand.
