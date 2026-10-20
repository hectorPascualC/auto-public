#!/usr/bin/env python3
"""Persist a merged exact-slot PASS ledger, never regressing the rescue trigger."""
from __future__ import annotations
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")
def load(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}

def main():
    state_dir = Path(os.environ.get("STATE_DIR", "auto-places-docents/state"))
    slot = os.environ.get("SLOT_KEY", "")
    health = load(state_dir / "health.json")
    consumer = load(state_dir / "consumer.json")
    p = state_dir / "slot-ledger.json"
    ledger = load(p)
    slots = ledger.get("slots") if isinstance(ledger.get("slots"), dict) else {}
    if not slot:
        print("Unslotted manual/code push: no scheduled PASS slot claimed")
        return 0
    try:
        generated = datetime.fromisoformat(health["generated_at"]).astimezone(TZ)
        audited = datetime.fromisoformat(health["audit_at"]).astimezone(TZ)
    except (TypeError, ValueError, KeyError):
        raise SystemExit("Missing timestamps for slot ledger")
    actual = generated.strftime("%Y-%m-%dT%H:00")
    valid = (
        actual == slot and audited >= generated and
        health.get("fresh") == 12 and health.get("presence_authoritative") == 12 and
        health.get("audit_status") == "PASS" and health.get("audit_errors") == 0 and
        consumer.get("generated_at") == health.get("generated_at"))
    if not valid:
        print(f"No slot claimed: candidate/remote validated data is not this slot ({slot} != {actual})")
        return 0
    slots[slot] = {
        "status": "PASS",
        "scan_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "snapshot_run_id": consumer.get("run_id"),
        "trigger_sha": os.environ.get("TRIGGER_SHA", ""),
        "kind": os.environ.get("SLOT_KIND", ""),
        "generated_at": health.get("generated_at"),
        "audit_at": health.get("audit_at"),
    }
    # Bounded and canonical: older slots remain in compressed immutable history.
    ledger = {"schema_version": 1, "timezone": "Europe/Madrid",
              "slots": {k: slots[k] for k in sorted(slots)[-120:]}}
    p.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PASS slot ledger updated: {slot}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
