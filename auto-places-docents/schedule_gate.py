#!/usr/bin/env python3
"""Gate for local Madrid slots: never mistake delayed GitHub schedules for fresh scans."""
import json
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")
HOURS = (9, 11, 14, 16)
MARKER = "auto-places-docents/state/external-trigger.txt"

def show(path):
    r = subprocess.run(["git", "show", "origin/main:" + path], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""

def read_json(path):
    try:
        return json.loads(show(path))
    except (ValueError, TypeError):
        return {}

def key_for(dt):
    return dt.astimezone(TZ).strftime("%Y-%m-%dT%H:00")

def valid_health(h, slot):
    try:
        gen = datetime.fromisoformat(h["generated_at"])
        audit = datetime.fromisoformat(h["audit_at"])
    except (KeyError, ValueError, TypeError):
        return False
    return (key_for(gen) == slot and key_for(audit) == slot and
            h.get("fresh") == 12 and h.get("total") == 12 and
            h.get("partial") == 0 and h.get("cache_obsoleta") == 0 and
            h.get("presence_authoritative") == 12 and
            h.get("audit_status") == "PASS" and h.get("audit_errors") == 0)

def parse_rescue(text):
    if not text.startswith("AUTO-PUBLIC scheduled-slot rescue\n"):
        return None
    m = re.search(r"(?m)^slot_local=(\S+)$", text)
    if not m:
        return None
    try:
        dt = datetime.fromisoformat(m.group(1))
        if dt.tzinfo is None:
            return None
        local = dt.astimezone(TZ)
        if dt.utcoffset() != local.utcoffset() or local.hour not in HOURS or local.minute != 0:
            return None
        return key_for(local)
    except ValueError:
        return None

def decide(event, cron, now, h, ledger, marker_changed=False, marker_text="",
           trigger_sha="", processed_sha="", request=True, force=False):
    if not request:
        return False, "disabled_by_input", "", "disabled"
    key, kind = "", "manual"
    local = now.astimezone(TZ)
    if event == "schedule":
        m = re.fullmatch(r"(5|22) (9|11|14|16) \* \* 1-5", cron.strip())
        if not m:
            return False, "unknown_schedule", "", "unknown"
        minute, hour = map(int, m.groups())
        if local.weekday() > 4 or local.hour != hour or local.minute < minute:
            return False, "stale_or_early_schedule", "", "stale"
        key = local.strftime("%Y-%m-%dT%H:00")
        kind = "backup" if minute == 22 else "primary"
    elif event == "push":
        if not force and trigger_sha and trigger_sha == processed_sha:
            return False, "duplicate_push", "", "push"
        if marker_changed:
            key = parse_rescue(marker_text) or ""
            kind = "rescue" if key else "push"
            if key:
                dt = datetime.fromisoformat(key).replace(tzinfo=TZ)
                if dt > local or (local - dt).total_seconds() >= 4 * 3600:
                    return False, "rescue_slot_expired", key, kind
    elif event != "workflow_dispatch":
        return False, "unsupported_event", "", "unknown"
    if key and not force:
        slots = ledger.get("slots", {})
        if isinstance(slots, dict):
            entry = slots.get(key, {})
            if (isinstance(entry, dict) and entry.get("status") == "PASS" and
                    entry.get("generated_at") == h.get("generated_at") and
                    entry.get("audit_at") == h.get("audit_at") and
                    entry.get("snapshot_run_id") and valid_health(h, key)):
                return False, "SKIPPED_ALREADY_VALID_LEDGER", key, kind
        if valid_health(h, key):
            return False, "SKIPPED_ALREADY_VALID_SNAPSHOT", key, kind
    return True, "RUN_SCAN", key, kind

def main():
    e = os.environ
    ev = e.get("EVENT_NAME", "")
    names = set()
    if ev == "push":
        result = subprocess.run(["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"],
                                capture_output=True, text=True)
        if result.returncode == 0:
            names = set(result.stdout.splitlines())
    changed = MARKER in names
    marker = Path(MARKER).read_text(encoding="utf-8") if changed else ""
    run, reason, slot, kind = decide(
        ev, e.get("SCHEDULE_CRON", ""), datetime.now(TZ),
        read_json("auto-places-docents/state/health.json"),
        read_json("auto-places-docents/state/slot-ledger.json"),
        changed, marker, e.get("TRIGGER_SHA", ""),
        show("auto-places-docents/state/processed-trigger-sha.txt").strip(),
        e.get("REQUEST_RUN", "true").lower() == "true",
        e.get("FORCE_RUN", "false").lower() == "true")
    output = {"run_monitor": str(run).lower(), "gate_reason": reason,
              "slot_key": slot, "slot_kind": kind}
    with open(e["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
        for k, v in output.items():
            f.write(f"{k}={v}\n")
    with open(e["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
        f.write(f"### AUTO gate: {reason}\n")
        f.write(f"- Actual scan: **{run}**; slot: {slot or 'none'}; event: {ev}\n")
    print(json.dumps(output))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
