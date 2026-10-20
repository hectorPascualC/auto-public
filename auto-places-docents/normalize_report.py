#!/usr/bin/env python3
"""Normalize latest.md from the final compact state.

The first monitor pass writes a provisional freshness table before the robust EDUBCN
probe/finalizer runs. This final step rewrites the human-readable freshness summary
from latest.json after active_snapshot_v2 has completed, so latest.md cannot display
a stale provisional EDUBCN status while health.json/latest.json already say FRESC.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "state" / "latest.json"
REPORT_FILE = ROOT / "state" / "latest.md"
HEALTH_FILE = ROOT / "state" / "health.json"
CONSUMER_FILE = ROOT / "state" / "consumer.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_consumer_state(state: dict, health: dict) -> dict:
    """Small, stable state for ChatGPT/other consumers.

    latest.json remains the full scanner state needed by the next run for
    fingerprints, validators, document evidence and anti-regression.  This file
    intentionally contains only final health + authoritative active placements,
    so GitHub's Contents API can return it reliably even when latest.json exceeds
    the connector/API inline-content limit.
    """
    active = (state.get("active_snapshot") or {}).get("territories") or {}
    territories = state.get("territories") or {}
    out = {
        "schema_version": 1,
        "generated_at": state.get("generated_at"),
        "run_id": state.get("run_id"),
        "source_strategy": state.get("source_strategy"),
        "activity_rule": state.get("activity_rule"),
        "health": health,
        "territories": {},
    }
    for name, rec in territories.items():
        a = active.get(name) or {}
        out["territories"][name] = {
            "freshness": rec.get("freshness"),
            "freshness_notes": rec.get("freshness_notes") or [],
            "error": rec.get("error"),
            "presence_authoritative": bool(a.get("presence_authoritative")),
            "source_mode": a.get("source_mode"),
            "current_target_counts": a.get("current_target_counts") or {},
            "current_target_placements": a.get("current_target_placements") or [],
            "removed_since_previous": a.get("removed_since_previous") or [],
            "covered_by_results": a.get("covered_by_results") or [],
            "unresolved_result_ids": a.get("unresolved_result_ids") or [],
            "source_selection_diagnostics": rec.get("selection_diagnostics") or {},
            "discovery_diagnostics": rec.get("discovery_diagnostics") or {},
            "status_note": a.get("status_note"),
        }
    return out


def final_notes(territories: dict[str, dict]) -> str:
    lines = ["## Notes de frescor"]
    issues = []
    for name, rec in territories.items():
        freshness = rec.get("freshness") or "PARCIAL"
        if freshness == "FRESC":
            continue
        notes = [str(x).strip() for x in (rec.get("freshness_notes") or []) if str(x).strip()]
        if rec.get("error"):
            notes.append(str(rec["error"]).strip())
        detail = "; ".join(dict.fromkeys(notes)) or "estat final no fresc"
        issues.append(f"- **{name}**: {freshness} — {detail}")
    if issues:
        lines.extend(issues)
    else:
        lines.append("- Cap incidència final de frescor.")
    return "\n".join(lines)


def main() -> int:
    state = load_json(STATE_FILE)
    health = load_json(HEALTH_FILE)
    report = REPORT_FILE.read_text(encoding="utf-8")
    territories = state.get("territories") or {}
    ed = territories.get("EDUBCN") or {}
    ed_freshness = ed.get("freshness")
    if ed_freshness not in {"FRESC", "PARCIAL", "CACHE OBSOLETA"}:
        raise RuntimeError(f"EDUBCN final freshness missing/invalid: {ed_freshness!r}")

    # Rewrite only the first/provisional EDUBCN row. Numeric hit columns and anchor
    # remain diagnostic; final active counts are already rendered later by the
    # authoritative active-snapshot section.
    notes_pos = report.find("\n## Notes de frescor")
    if notes_pos < 0:
        raise RuntimeError("latest.md has no Notes de frescor section")
    prefix, suffix = report[:notes_pos], report[notes_pos:]
    row_rx = re.compile(
        r"(?m)^\| EDUBCN \| \*\*(?:FRESC|PARCIAL|CACHE OBSOLETA)\*\* \|"
    )
    prefix, n = row_rx.subn(f"| EDUBCN | **{ed_freshness}** |", prefix, count=1)
    if n != 1:
        raise RuntimeError(f"expected exactly one provisional EDUBCN row, replaced {n}")
    report = prefix + suffix

    # Replace provisional notes (including multiline timeout call logs) with notes
    # derived exclusively from the final territory state.
    report, n = re.subn(
        r"## Notes de frescor[\s\S]*?(?=\n## Ús)",
        final_notes(territories),
        report,
        count=1,
    )
    if n != 1:
        raise RuntimeError(f"expected one Notes de frescor section, replaced {n}")

    # Fail closed if the three canonical representations disagree.
    active_ed = ((state.get("active_snapshot") or {}).get("territories") or {}).get("EDUBCN") or {}
    active_freshness = active_ed.get("source_freshness")
    if active_freshness and active_freshness != ed_freshness:
        raise RuntimeError(
            f"EDUBCN mismatch: territory={ed_freshness}, active_snapshot={active_freshness}"
        )

    vals = list(territories.values())
    expected_health = {
        "fresh": sum(1 for x in vals if x.get("freshness") == "FRESC"),
        "partial": sum(1 for x in vals if x.get("freshness") == "PARCIAL"),
        "cache_obsoleta": sum(1 for x in vals if x.get("freshness") == "CACHE OBSOLETA"),
        "total": len(vals),
    }
    for key, expected in expected_health.items():
        if int(health.get(key, -1)) != expected:
            raise RuntimeError(
                f"health mismatch for {key}: health={health.get(key)!r}, state={expected}"
            )

    # Verify the rewritten top row itself before writing.
    check_prefix = report[: report.find("\n## Notes de frescor")]
    m = re.search(
        r"(?m)^\| EDUBCN \| \*\*(FRESC|PARCIAL|CACHE OBSOLETA)\*\* \|",
        check_prefix,
    )
    if not m or m.group(1) != ed_freshness:
        raise RuntimeError("latest.md EDUBCN summary did not normalize to final freshness")

    REPORT_FILE.write_text(report, encoding="utf-8")

    consumer = build_consumer_state(state, health)
    CONSUMER_FILE.write_text(
        json.dumps(consumer, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    consumer_size = CONSUMER_FILE.stat().st_size
    # Keep a generous safety margin below GitHub Contents API's 1 MiB inline
    # content boundary. If this ever grows unexpectedly, fail before persistence.
    if consumer_size >= 512 * 1024:
        raise RuntimeError(f"consumer.json unexpectedly large: {consumer_size} bytes")
    print(json.dumps({
        "normalized": True,
        "edubcn_freshness": ed_freshness,
        "active_snapshot_freshness": active_freshness,
        "health": expected_health,
        "consumer_file": str(CONSUMER_FILE),
        "consumer_bytes": consumer_size,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

