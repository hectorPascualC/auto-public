#!/usr/bin/env python3
"""Read-only evidence of a REAL GitHub scheduled event, never a vacancy scan."""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("Europe/Madrid")
EXPECTED_CRON = "27,57 * 25-26 10 *"
FIRST_DAY = date(2026, 10, 25)
LAST_DAY = date(2026, 10, 26)
EVIDENCE_FILE = Path("cron30-evidence.json")


def classify(event_name: str, event_schedule: str, observed_at: datetime) -> str:
    if observed_at.tzinfo is None:
        raise ValueError("timezone_required")
    if event_name == "schedule":
        if event_schedule != EXPECTED_CRON:
            raise ValueError("unexpected_cron_fail_closed")
        local_day = observed_at.astimezone(ZONE).date()
        if not FIRST_DAY <= local_day <= LAST_DAY:
            return "EXPIRED_INERT"
        return "SCHEDULE_FIRED"
    if event_name in {"push", "workflow_dispatch"}:
        return "SMOKE_ONLY_NOT_SCHEDULE"
    raise ValueError("unexpected_event_fail_closed")


def main() -> int:
    event_name = os.environ.get("GITHUB_EVENT_NAME", "")
    event_path = Path(os.environ.get("GITHUB_EVENT_PATH", "/nonexistent-event"))
    event = json.loads(event_path.read_text(encoding="utf-8"))
    event_schedule = event.get("schedule", "")
    observed_at = datetime.now(timezone.utc)
    outcome = classify(event_name, event_schedule, observed_at)
    evidence = {
        "schema_version": 1,
        "probe": "synthetic-cron-30m",
        "result": outcome,
        "event_name": event_name,
        "schedule": event_schedule if event_name == "schedule" else None,
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
        "sha": os.environ.get("GITHUB_SHA", ""),
        "observed_at_utc": observed_at.isoformat(timespec="seconds"),
        "observed_at_madrid": observed_at.astimezone(ZONE).isoformat(timespec="seconds"),
        "read_only": True,
        "official_source_fetches": 0,
        "github_dispatch_posts": 0,
        "cloudflare_calls": 0,
    }
    EVIDENCE_FILE.write_text(json.dumps(evidence, sort_keys=True, indent=2) + "\n",
                             encoding="utf-8")
    print("CRON30_EVIDENCE=" + json.dumps(evidence, sort_keys=True))
    summary = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("### Synthetic GitHub 30-minute cron (read-only)\n")
            handle.write("- GitHub event: **" + event_name + "**\n")
            handle.write("- Outcome: **" + outcome + "**\n")
            handle.write("- Real scheduled event demonstrated: **" +
                         ("YES" if outcome == "SCHEDULE_FIRED" else "NO") + "**\n")
            handle.write("- Observed Madrid time: " +
                         evidence["observed_at_madrid"] + "\n")
            handle.write("- No vacancy scans, API dispatches or Cloudflare calls.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
