#!/usr/bin/env python3
"""Fail closed on 12/12 contract, then store immutable FULL FINAL audit history."""
from __future__ import annotations
import gzip
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "state"
def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))

def main():
    data, health, audit, consumer = (load(n) for n in
                                  ("latest.json", "health.json", "audit.json", "consumer.json"))
    stamp = data.get("generated_at")
    run = data.get("run_id")
    if not stamp or not run or len((data.get("territories") or {})) != 12:
        raise SystemExit("Final state is not a complete 12-scope scan")
    if (health.get("generated_at") != stamp or consumer.get("generated_at") != stamp
            or consumer.get("run_id") != run
            or audit.get("source_generated_at") != stamp):
        raise SystemExit("Cross-file timestamp and run-id mismatch")
    if (health.get("audit_status") != "PASS" or audit.get("status") != "PASS"
            or health.get("fresh") != 12 or health.get("presence_authoritative") != 12
            or health.get("partial") != 0 or health.get("cache_obsoleta") != 0
            or health.get("audit_errors") != 0 or audit.get("errors")
            or audit.get("scopes_checked") != 12):
        raise SystemExit("Fail-closed: 12/12 PASS audit and authority required")
    if not data.get("edubcn_finalize_at") or not data.get("active_snapshot"):
        raise SystemExit("EDUBCN finalization/current presence missing")
    latest = datetime.fromisoformat(stamp)
    audited = datetime.fromisoformat(health["audit_at"])
    if audited < latest or (audited - latest).total_seconds() > 35*60:
        raise SystemExit("Snapshot/audit timestamps outside scan interval")
    data["final_audit"] = audit
    history = ROOT / "history"
    history.mkdir(parents=True, exist_ok=True)
    final = history / (run + ".json.gz")
    # Serialize deterministically so repeated attempts are idempotent.
    blob = (json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    with final.open("wb") as fp:
        # gzip.compress supports deterministic mtime and preserves all evidence.
        fp.write(gzip.compress(blob, compresslevel=6, mtime=0))
    (ROOT / "_previous_final.json").unlink(missing_ok=True)
    print(json.dumps({"finalized_run": run, "history": str(final),
                      "bytes": len(blob), "gzip_bytes": final.stat().st_size,
                      "fresh": 12, "authoritative": 12, "audit": "PASS"}))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
