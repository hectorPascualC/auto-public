#!/usr/bin/env python3
"""Gate for local Madrid slots: never mistake delayed GitHub schedules for fresh scans."""
import json
import os
import re
import subprocess
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")
HOURS = (8, 11, 13, 17)
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
    """Validate a PASS snapshot for a nominal slot, including pre-hour scans."""
    try:
        generated = datetime.fromisoformat(h["generated_at"])
        audited = datetime.fromisoformat(h["audit_at"])
        nominal = datetime.strptime(slot, "%Y-%m-%dT%H:00").replace(tzinfo=TZ)
        if generated.tzinfo is None or audited.tzinfo is None:
            return False
        generated, audited = generated.astimezone(TZ), audited.astimezone(TZ)
    except (ValueError, TypeError, KeyError):
        return False
    return (nominal - timedelta(minutes=25) <= generated <
            nominal + timedelta(minutes=45) and
            generated <= audited <= generated + timedelta(minutes=35) and
            h.get("fresh") == 12 and h.get("total") == 12 and
            h.get("partial") == 0 and h.get("cache_obsoleta") == 0 and
            h.get("presence_authoritative") == 12 and
            h.get("audit_status") == "PASS" and h.get("audit_errors") == 0)

def parse_rescue(text):
    if not text.startswith("AUTO-PUBLIC scheduled-slot rescue\n"):
        return None
    if not re.search(r"(?m)^public_data_only=true$", text):
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
           trigger_sha="", processed_sha="", request=True, force=False,
           slot_input="", attempt_input=""):
    if not request:
        return False, "disabled_by_input", "", "disabled"
    key, kind = "", "manual"
    local = now.astimezone(TZ)
    if event == "schedule":
        # Cloudflare is no longer the owner of weekday scans. GitHub Actions
        # schedules each local Madrid slot at four distinct non-round minutes:
        # one primary, a conditional backup, and two recovery opportunities.
        # Enforce a bounded health window and skip any old/stale UTC cron.
        if cron.strip() == "27 8-21 * * 6":
            return False, "saturday_probe_superseded_by_cloudflare", "", "saturday_probe"
        cron_kind_and_offset = {
            "37 7,10,12,16 * * 1-5": ("primary", -23),
            "49 7,10,12,16 * * 1-5": ("backup", -11),
            "13 8,11,13,17 * * 1-5": ("recovery", 13),
            "27 8,11,13,17 * * 1-5": ("recovery_late", 27),
        }
        cfg = cron_kind_and_offset.get(cron.strip())
        if cfg is None:
            return False, "unknown_schedule", "", "unknown"
        kind, earliest_minutes = cfg
        if local.weekday() > 4:
            return False, "stale_or_offseason_schedule", "", "stale"
        # GitHub does not guarantee delivery at the cron minute. Reconcile a
        # delayed trigger against the actual local slot, never invent a future
        # or expired slot. A late trigger can recover a missed earlier run.
        due = []
        for hour in HOURS:
            nominal = local.replace(hour=hour, minute=0, second=0, microsecond=0)
            delta = (local - nominal).total_seconds() / 60
            if earliest_minutes <= delta < 45:
                due.append(nominal)
        if len(due) != 1:
            return False, "stale_or_offseason_schedule", "", "stale"
        key = due[0].strftime("%Y-%m-%dT%H:00")
    elif event == "push":
        # Code/workflow pushes on the date-guarded weekend must not compete
        # with Cloudflare-scheduled scans. An explicit external-trigger
        # marker is the only allowed manual rescue on these two dates.
        if local.date() in (date(2026, 10, 24), date(2026, 10, 25)) and not marker_changed:
            return False, "weekend_cloudflare_exclusive", "", "push"
        if not force and trigger_sha and trigger_sha == processed_sha:
            return False, "duplicate_push", "", "push"
        if marker_changed and marker_text.startswith("AUTO-PUBLIC scheduled-slot rescue"):
            # Never reinterpret a malformed rescue as a generic unslotted push.
            # Existing ordinary manual markers remain supported.
            key = parse_rescue(marker_text)
            if not key:
                return False, "invalid_rescue_marker", "", "invalid"
            kind = "rescue"
            dt = datetime.fromisoformat(key).replace(tzinfo=TZ)
            if dt > local or (local - dt).total_seconds() >= 4 * 3600:
                return False, "rescue_slot_expired", key, kind
    elif event == "workflow_dispatch" and slot_input:
        one_day_probe = slot_input == "2026-10-22T20:00"
        weekend_hourly = re.fullmatch(r"2026-10-(24|25)T(09|1[0-9]|2[0-3]):00", slot_input)
        if not (one_day_probe or weekend_hourly or
                re.fullmatch(r"\d{4}-\d{2}-\d{2}T(08|11|13|17):00", slot_input)):
            return False, "invalid_v2_slot", "", "invalid"
        if attempt_input not in ("primary", "backup"):
            return False, "invalid_v2_attempt", "", "invalid"
        try:
            nominal = datetime.strptime(slot_input, "%Y-%m-%dT%H:%M").replace(tzinfo=TZ)
        except ValueError:
            return False, "invalid_v2_slot", "", "invalid"
        # Only 24–25 Oct 2026 are allowed to claim hourly weekend V2
        # slots; all subsequent weekends remain fail-closed.
        weekend_live_test = (nominal.date() in (date(2026, 10, 24), date(2026, 10, 25))
                             and nominal.weekday() in (5, 6))
        if (nominal.weekday() > 4 and not weekend_live_test) or not (
                nominal - timedelta(minutes=25) <= local <
                nominal + timedelta(minutes=45)):
            return False, "stale_v2_slot", slot_input, "stale"
        key, kind = slot_input, "v2_" + attempt_input
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
        # A fresh unslotted push/legacy snapshot is NOT an exact V2 receipt.
        # Without matching ledger, V2 must scan and produce its own provenance.
        if not kind.startswith("v2_") and valid_health(h, key):
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
        e.get("FORCE_RUN", "false").lower() == "true",
        e.get("SLOT_INPUT", ""), e.get("ATTEMPT_INPUT", ""))
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
