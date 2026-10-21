#!/usr/bin/env python3
"""Remove verbatim document/browser text before committing PUBLIC scan snapshots.

Invoke only AFTER snapshot derivation, normalization and audit, and immediately
BEFORE historical packaging. Keep IDs, centre descriptions, URLs, fingerprints,
timestamps and technical HTTP metadata required for the next scan.
Existing Git history remains public: this protects NEW commits only.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "state"
SOURCE = ROOT / "latest.json"
# These key names contain unbounded source/browser text, including RESULTAT
# documents that may identify a selected applicant or contain personal data.
DROP_EXACT = {
    "row_samples", "rows", "body", "body_text", "raw_html", "raw_pdf",
    "raw_text", "html", "html_text", "response_text", "page_text",
    "document_text", "full_text", "search_results_html",
}


def unsafe_key(key: str) -> bool:
    lowered = str(key).lower()
    return (lowered in DROP_EXACT or
            lowered.endswith("_excerpt") or
            lowered.endswith("_snippet") or
            lowered == "snippet" or
            lowered.startswith("raw_") and lowered not in {"raw_target_hits"})


def sanitize(value):
    if isinstance(value, list):
        return [sanitize(entry) for entry in value]
    if isinstance(value, dict):
        return {
            key: sanitize(child)
            for key, child in value.items()
            if not unsafe_key(key)
        }
    return value


def audit_absence(value, path=""):
    if isinstance(value, dict):
        for key, child in value.items():
            if unsafe_key(key):
                raise ValueError("Unsafe content key retained: " + path + "/" + key)
            audit_absence(child, path + "/" + key)
    elif isinstance(value, list):
        for i, child in enumerate(value):
            audit_absence(child, path + "/" + str(i))


def main() -> int:
    before = json.loads(SOURCE.read_text(encoding="utf-8"))
    after = sanitize(before)
    audit_absence(after)
    for required in ("generated_at", "run_id", "territories", "active_snapshot"):
        if before.get(required) != after.get(required):
            if required in ("generated_at", "run_id"):
                raise SystemExit("Sanitizer unexpectedly changed " + required)
            if required in ("territories", "active_snapshot"):
                if not isinstance(after.get(required), dict) or not after[required]:
                    raise SystemExit("Sanitizer erased " + required)
    # Avoid preserving unredacted text on disk after serialization.
    temporary = SOURCE.with_suffix(".redacted.tmp")
    temporary.write_text(json.dumps(after, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(SOURCE)
    print(json.dumps({
        "sanitized": True, "previous_bytes": len(json.dumps(before, ensure_ascii=False)),
        "public_bytes": SOURCE.stat().st_size,
        "territories": len(after["territories"]),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
