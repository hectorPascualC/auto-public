#!/usr/bin/env python3
"""Bounded, deterministic repair harness. Never deploys or triggers a scan.

Known safe action: rebuild an inconsistent derived consumer snapshot from an
audited, authoritative 12-source canonical state. Unknown defects fail closed.
The local --apply-safe result is an artifact/candidate, NOT a GitHub production fix.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

from normalize_report import build_consumer_state


def load(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("Expected JSON object: " + path.name)
    return obj


def canonical_candidate(root: Path) -> dict:
    state = load(root / "latest.json")
    health = load(root / "health.json")
    audit = load(root / "audit.json")
    if (audit.get("status") != "PASS"
            or audit.get("generated_at") != health.get("audit_at")
            or health.get("audit_status") != "PASS"):
        raise ValueError("Source audit is not authoritative")
    if (not state.get("run_id") or state.get("run_id") != health.get("run_id", state.get("run_id"))
            or state.get("generated_at") != health.get("generated_at")):
        raise ValueError("Run identity or timestamps disagree")
    if (any(health.get(key) != 12 for key in ("fresh", "total", "presence_authoritative"))
            or any(health.get(key) != 0 for key in ("partial", "cache_obsoleta", "audit_errors"))
            or len(state.get("territories") or {}) != 12):
        raise ValueError("Canonical source is partial, unverified or incomplete")
    return build_consumer_state(state, health)


def diagnose(root: Path, report_path: Path) -> dict:
    try:
        report = load(report_path)
        checks = {c["name"]: c["status"] for c in report["checks"]}
    except (OSError, ValueError, KeyError, TypeError):
        checks = {}
        report = {}
    result = {"schema_version": 1, "policy": "bounded-fail-closed",
              "max_attempts": 1, "production_write": False,
              "action": "investigate", "reason": "Unclassified or unreadable audit"}
    if checks.get("Latest due slot receipt") == "FAIL":
        result.update(action="existing_rescue_only",
                      reason="Missing due slot: only the existing timed, deduplicated ChatGPT rescue can act")
    elif checks.get("12 official sources") == "FAIL" or checks.get("Source audit") == "FAIL":
        result.update(action="investigate_sources", reason="Never repair using non-authoritative data")
    elif checks.get("Consumer snapshot") == "FAIL":
        try:
            expected = canonical_candidate(root)
            result.update(action="rebuild_consumer", reason="Verified canonical snapshot can regenerate derived consumer",
                          expected_hash=hashlib.sha256(
                              json.dumps(expected, sort_keys=True, ensure_ascii=False).encode()).hexdigest())
        except (OSError, ValueError, KeyError, TypeError) as error:
            result.update(action="investigate", reason="Repair guard failed: " + str(error))
    elif checks.get("Actual GitHub scan steps") in ("FAIL", "BLOCKED"):
        result.update(action="investigate_scan", reason="Unverified run steps require diagnosis; no blind retry")
    elif report.get("overall") == "PASS":
        result.update(action="none", reason="No repair needed")
    return result


def apply_safe(root: Path, plan: dict) -> str:
    """One allowlisted local repair, with post-write readback. No network, no git."""
    if plan.get("action") != "rebuild_consumer":
        return "NO_SAFE_ACTION"
    expected = canonical_candidate(root)  # Recheck all preconditions at application time.
    target = root / "consumer.json"
    try:
        if load(target) == expected:
            return "ALREADY_CORRECT"
    except (OSError, ValueError):
        pass
    text = json.dumps(expected, ensure_ascii=False, indent=2) + "\n"
    if len(text.encode("utf-8")) >= 512 * 1024:
        raise ValueError("Consumer exceeds public API size bound")
    fd, temp_path = tempfile.mkstemp(prefix=".consumer-repair-", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, target)
        if load(target) != expected:
            raise RuntimeError("Post-write consumer verification failed")
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    return "LOCAL_CANDIDATE_VERIFIED"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-dir", default="auto-places-docents/state")
    parser.add_argument("--audit-report", default="sre-audit-report.json")
    parser.add_argument("--apply-safe", action="store_true")
    args = parser.parse_args()
    root = Path(args.state_dir)
    plan = diagnose(root, Path(args.audit_report))
    plan["outcome"] = "DRY_RUN"
    if args.apply_safe:
        try:
            plan["outcome"] = apply_safe(root, plan)
        except (OSError, ValueError, RuntimeError) as error:
            plan["outcome"] = "BLOCKED: " + str(error)
    Path("repair-incident.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n",
                                            encoding="utf-8")
    print("Repair harness: " + plan["action"] + " / " + plan["outcome"])
    return 1 if plan["outcome"].startswith("BLOCKED") else 0


if __name__ == "__main__":
    raise SystemExit(main())
