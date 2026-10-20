#!/usr/bin/env python3
"""Finalize EDUBCN state with document-only target validation.

Rules:
- GENSEC base number is used only for freshness ordering.
- Full place code (including suffix such as _SCO) is used as placement identity.
- A 507/627/F57/F87 classification is VERIFIED only if the specialty code occurs
  in the same official call/result document.
- DOM-only candidates remain discoverable but are not counted as target places.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from coverage import classify as classify_coverage

TZ = ZoneInfo("Europe/Madrid")
ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "state" / "latest.json"
REPORT_FILE = ROOT / "state" / "latest.md"
TARGETS = ("507", "F57", "627", "F87")
TARGET_RE = re.compile(r"(?<![A-Z0-9])(507|627|F57|F87)(?![A-Z0-9])", re.I)
BASE_RE = re.compile(r"GENSEC[_-](\d{4})[_-](\d+)", re.I)
FULL_LINE_RE = re.compile(
    r"(?:CODI(?:\s+DE\s+LA\s+PLA[CÇ]A\s+A\s+COBRIR)?\s*:?\s*)"
    r"(GENSEC[_-]\d{4}[_-]\d+(?:[_-][A-Z0-9]+)?)",
    re.I,
)
URL_CODE_RE = re.compile(r"(GENSEC[_-]\d{4}[_-]\d+(?:[_-][A-Z0-9]+)?)", re.I)


def clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def normalize_code(code: str) -> str:
    parts = re.split(r"[_-]", code.upper())
    # GENSEC, 2627, 138, optional suffix
    if len(parts) >= 3:
        base = f"GENSEC_{parts[1]}_{int(parts[2]):03d}"
        if len(parts) >= 4 and parts[3]:
            base += f"_{parts[3]}"
        return base
    return code.upper().replace("-", "_")


def full_code(doc: dict) -> str | None:
    text = doc.get("text_excerpt") or ""
    m = FULL_LINE_RE.search(text)
    if m:
        return normalize_code(m.group(1))
    p = (doc.get("place") or {}).get("gensec")
    if p:
        # v3 may have collapsed suffixes, so prefer URL when it exposes one.
        um = URL_CODE_RE.search(doc.get("url") or "")
        if um:
            return normalize_code(um.group(1))
        return normalize_code(p)
    m = URL_CODE_RE.search(doc.get("url") or "")
    return normalize_code(m.group(1)) if m else None


def targets_in_doc(doc: dict) -> list[str]:
    text = doc.get("text_excerpt") or ""
    return sorted({m.group(1).upper() for m in TARGET_RE.finditer(text)}, key=lambda x: TARGETS.index(x))


def parse_field(text: str, rx: str) -> str | None:
    m = re.search(rx, text or "", re.I | re.M)
    return clean(m.group(1)) if m else None


def details_from_doc(doc: dict) -> dict:
    p = doc.get("place") or {}
    text = doc.get("text_excerpt") or ""
    return {
        "centre_code": p.get("centre_code") or parse_field(text, r"CODI\s+(?:DE\s+)?CENTRE\s*:?\s*([0-9]{8})"),
        "centre": p.get("centre") or parse_field(text, r"NOM\s+DE\s+CENTRE\s*:?\s*([^\n]+)"),
        "profile": p.get("profile") or parse_field(text, r"(?:^|\n)\s*NOM\s*:?\s*([^\n]+)"),
        "start": p.get("start") or parse_field(text, r"DATA\s+D['’]INICI\s*:?\s*([^\n]{1,80}?)(?=\s+DATA\s+(?:DE\s+)?FI|\n|$)"),
        "end": p.get("end") or parse_field(text, r"DATA\s+(?:DE\s+)?FI\s*:?\s*([^\n]{1,100}?)(?=\s+JORNADA|\n|$)"),
        "jornada": p.get("jornada") or parse_field(text, r"JORNADA\s*:?\s*([^\n]+)"),
    }


def main() -> int:
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    ed = state.get("territories", {}).get("EDUBCN", {})
    documents = ed.get("documents") or []

    groups: dict[str, dict] = {}
    for doc in documents:
        code = full_code(doc)
        if not code:
            continue
        g = groups.setdefault(code, {
            "place_code": code,
            "base_gensec": "_".join(code.split("_")[:3]),
            "documents": [],
            "target_codes": set(),
            "result_present": False,
            "result_document_present": False,
            "coverage_confirmed": False,
            "result_classification": "UNKNOWN",
        })
        g["documents"].append(doc)
        g["target_codes"].update(targets_in_doc(doc))
        # A RESULTAT document may say DESERTA. Only explicit positive
        # coverage evidence can close an offer, never mere document presence.
        if doc.get("role") == "result":
            g["result_document_present"] = True
            status = classify_coverage(doc.get("text_excerpt") or "")
            if status == "COVERED":
                g["coverage_confirmed"] = True
            elif status == "UNFILLED":
                g["result_classification"] = "UNFILLED"

    placements = []
    for code, g in groups.items():
        docs = g.pop("documents")
        # Prefer an offer/convocation document for descriptive fields, then result.
        ordered = sorted(docs, key=lambda d: 0 if d.get("role") == "offer" else 1)
        details = {}
        for doc in ordered:
            d = details_from_doc(doc)
            for k, v in d.items():
                if v and not details.get(k):
                    details[k] = v
        if g["coverage_confirmed"] and g["result_classification"] == "UNFILLED":
            # Conflicting outcomes: fail open, require manual verification.
            g["coverage_confirmed"] = False
            g["result_classification"] = "UNKNOWN"
        elif g["coverage_confirmed"]:
            g["result_classification"] = "COVERED"
        g["result_present"] = g["result_document_present"]
        placement = {
            **g,
            **details,
            "target_codes": sorted(g["target_codes"], key=lambda x: TARGETS.index(x)),
            "document_verified": True,
            "document_count": len(docs),
            "offer_urls": [d.get("url") for d in docs if d.get("role") == "offer"],
            "result_urls": [d.get("url") for d in docs if d.get("role") == "result"],
        }
        placements.append(placement)

    placements.sort(key=lambda p: (int(p["base_gensec"].rsplit("_", 1)[1]), p["place_code"]))
    verified_targets = [p for p in placements if p.get("target_codes")]

    # Keep DOM-only discoveries separately. They are NOT target-verified.
    old_placements = ed.get("placements") or []
    unverified = []
    verified_bases = {p["base_gensec"] for p in placements}
    for p in old_placements:
        base = p.get("gensec") or p.get("base_gensec")
        if not base or base in verified_bases:
            continue
        if p.get("document_count", 0) == 0:
            unverified.append({
                "base_gensec": base,
                "dom_target_hints": p.get("target_codes") or [],
                "status": "UNVERIFIED_DOM_ONLY",
                "reason": "No official Convocatòria/Resultat document was linked or retrieved for this code; not counted as a target place.",
            })

    # Explicitly retain 139 as unresolved if v3 saw it with no document.
    if any((p.get("gensec") == "GENSEC_2627_139" and p.get("document_count", 0) == 0) for p in old_placements):
        if not any(x.get("base_gensec") == "GENSEC_2627_139" for x in unverified):
            unverified.append({
                "base_gensec": "GENSEC_2627_139",
                "dom_target_hints": ["F87"],
                "status": "UNVERIFIED_DOM_ONLY",
                "reason": "F87 appears only in the same dynamic DOM container; no official 139 document is linked/retrieved, so it is not counted.",
            })

    ed["placements_document_verified"] = placements
    ed["target_placements"] = verified_targets
    ed["target_placements_document_verified"] = verified_targets
    ed["candidate_placements_unverified"] = unverified
    ed["target_by_code"] = {c: [p for p in verified_targets if c in p.get("target_codes", [])] for c in TARGETS}
    ed["classification_rule"] = "document-only; full place code identity including suffix; base GENSEC only for freshness"
    ed["finalized_at"] = datetime.now(TZ).isoformat(timespec="seconds")
    state["territories"]["EDUBCN"] = ed
    state["edubcn_finalize_at"] = ed["finalized_at"]
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    base = REPORT_FILE.read_text(encoding="utf-8") if REPORT_FILE.exists() else ""
    base = re.sub(r"\n## EDUBCN probe v4 final[\s\S]*$", "", base).rstrip()
    extra = [
        "", "## EDUBCN probe v4 final",
        "- Regla: especialitat target només si apareix al mateix document oficial de la plaça.",
        "- Identitat: es conserva el codi complet, inclosos sufixos (`_SCO`, etc.); el número base només serveix per frescor.",
        f"- Places documentals target verificades: {len(verified_targets)}",
    ]
    for p in verified_targets:
        extra.append(
            f"- `{p['place_code']}`: {','.join(p['target_codes'])} | {p.get('centre') or '?'} | "
            f"{p.get('jornada') or '?'} | fi {p.get('end') or '?'} | resultat={p.get('result_present')}"
        )
    for p in unverified:
        extra.append(
            f"- `{p['base_gensec']}`: **NO VERIFICADA COM A TARGET** | hints DOM={','.join(p.get('dom_target_hints') or []) or '—'} | {p['reason']}"
        )
    REPORT_FILE.write_text(base + "\n" + "\n".join(extra) + "\n", encoding="utf-8")

    focus138 = [p for p in placements if p.get("base_gensec") == "GENSEC_2627_138"]
    focus139 = [p for p in verified_targets if p.get("base_gensec") == "GENSEC_2627_139"]
    print(json.dumps({
        "verified_target_count": len(verified_targets),
        "GENSEC_2627_138_variants": focus138,
        "GENSEC_2627_139_verified": focus139,
        "GENSEC_2627_139_unverified": [p for p in unverified if p.get("base_gensec") == "GENSEC_2627_139"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

