#!/usr/bin/env python3
"""Read-only GitHub Actions cron smoke probe; NEVER scans official sources."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

CRON = "7,37 * 25,26 10 *"
YEAR = 2026
DATES = {"2026-10-25", "2026-10-26"}
TZ = ZoneInfo("Europe/Madrid")


def inspect_run(event: str, expression: str, now: datetime, run_id: str = "",
                sha: str = "") -> dict:
    """Differentiate a genuinely delivered schedule from a push/manual smoke test."""
    if now.tzinfo is None:
        raise ValueError("timestamp_must_have_timezone")
    utc = now.astimezone(timezone.utc)
    madrid = now.astimezone(TZ)
    if event == "schedule":
        if expression != CRON:
            raise ValueError("unrecognized_scheduled_cron")
        # The repository cron is intentionally scoped to two test dates only.
        # A delayed delivery remains observable, without claiming on-time
        # execution. Do not infer scheduled nominal time from runner startup.
        nominal_window = utc.strftime("%Y-%m-%d") in DATES
        status = "SCHEDULE_DELIVERED" if nominal_window else "DELAYED_OUTSIDE_TEST_DATES"
    elif event in ("push", "workflow_dispatch"):
        if expression:
            raise ValueError("non_schedule_must_not_have_cron")
        status = "SMOKE_ONLY_NOT_SCHEDULE_EVIDENCE"
    else:
        raise ValueError("unexpected_event")
    return {
        "schema_version": 1,
        "status": status,
        "source_event": event,
        "schedule_expression": expression if event == "schedule" else None,
        "observed_at_utc": utc.isoformat(timespec="seconds"),
        "observed_at_madrid": madrid.isoformat(timespec="seconds"),
        "run_id": str(run_id),
        "head_sha": str(sha),
        "official_source_requests": 0,
        "github_dispatch_requests": 0,
        "persistent_writes": 0,
        "note": "Runner time is not proof of the scheduled nominal minute",
    }


def main() -> int:
    event = os.getenv("GITHUB_EVENT_NAME", "")
    expression = os.getenv("SCHEDULE_EXPRESSION", "")
    now = datetime.now(timezone.utc)
    record = inspect_run(event, expression, now,
                         os.getenv("GITHUB_RUN_ID", ""),
                         os.getenv("GITHUB_SHA", ""))
    report = Path(os.getenv("RUNNER_TEMP", "/tmp")) / "github-cron-30m-smoke.json"
    report.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n",
                      encoding="utf-8")
    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("### GitHub 30-minute no-scan cron probe\n")
            f.write(f"- **{record['status']}** (event: {event})\n")
            f.write(f"- UTC observed: `{record['observed_at_utc']}`\n")
            f.write(f"- Madrid observed: `{record['observed_at_madrid']}`\n")
            f.write("- No official sources, dispatch, secrets, or persistence accessed.\n")
    print(json.dumps(record, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
