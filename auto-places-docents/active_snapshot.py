#!/usr/bin/env python3
"""Build the authoritative active-position snapshot from the current official sources.

Activity rule agreed with the user:
- a target placement is active while it is present in the CURRENT official offer PDF/list;
- an expired application deadline does not remove it if it is still present;
- when it disappears from a current FRESH offer PDF/list, it leaves the active snapshot;
- never prune from a PARCIAL/CACHE OBSOLETA/regressed source;
- RESULTAT/coverage still closes a placement when explicitly known;
- EDUBCN uses document-verified target placements only.

Raw specialty hit counts remain diagnostics only. They are not position counts.
"""
from __future__ import annotations

import hashlib
import gzip
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")
ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "state" / "latest.json"
REPORT_FILE = ROOT / "state" / "latest.md"
HEALTH_FILE = ROOT / "state" / "health.json"
HISTORY_DIR = ROOT / "state" / "history"
TARGETS = ("507", "F57", "627", "F87")

# Exact-ish result markers. In particular, do NOT treat "dificil-cobertura" as
# a result merely because it contains the substring "cobert".
RESULT_RE = re.compile(
    r"(?:\bresultats?\b|\badjudic\w*\b|\bresoluci[oó]\w*\b|"
    r"\bcobert(?:a|es|s)?\b|vacants?[-_ ]cobert(?:a|es|s)?)",
    re.I,
)
OFFER_RE = re.compile(r"(?:\boferta\w*\b|\bvacant\w*\b|\bsubstit\w*\b|\bplaces?\b)", re.I)
PFI_RE = re.compile(r"(?:\bPFI\b|\bIFE\b|\bPTT\b|\bF57\b|\bF87\b)", re.I)

ID_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("GENSEC", re.compile(r"\bGENSEC[_-]\d{4}[_-]\d+(?:[_-][A-Z0-9]+)?\b", re.I)),
    ("APA", re.compile(r"\bAPA[-_]\d{4}[-_]S\d+\b", re.I)),
    ("SEC", re.compile(r"\b20\d{2}/SEC(?:/PFI)?/\d+\b", re.I)),
    ("GIRONA", re.compile(r"\b\d{1,3}S/20\d{2}-20\d{2}\b", re.I)),
]
NUMERIC_PLACE_RE = re.compile(r"\b(?:19|20)\d{6}\b")
CENTRE_RE = re.compile(r"\b0\d{7}\b")
FITXA_RE = re.compile(r"\bfitxa\s+(\d+)\b", re.I)


def clean(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def document_kind(doc: dict) -> str:
    """Reclassify links without the old `cobert`/`cobertura` substring bug."""
    s = clean(f"{doc.get('label','')} {doc.get('text','')} {doc.get('url','')}")
    if RESULT_RE.search(s):
        return "result"
    if PFI_RE.search(s):
        return "pfi"
    if OFFER_RE.search(s):
        return "offer"
    role = (doc.get("role") or "").lower()
    # Existing role=result is not trusted because the old classifier could
    # misread `dificil-cobertura`. Other roles are safe fallbacks.
    if role in {"offer", "pfi"}:
        return role
    return "other"


def normalize_identifier(raw: str, kind: str) -> str:
    raw = clean(raw).upper()
    if kind == "GENSEC":
        return raw.replace("-", "_")
    return raw


def identifier_from_snippet(snippet: str) -> tuple[str | None, str | None]:
    text = snippet or ""
    # "fitxa N / centre" is a stable identity in Catalunya Central when present.
    fm = FITXA_RE.search(text)
    if fm:
        centre = CENTRE_RE.search(text)
        return (f"fitxa {int(fm.group(1))}" + (f" / {centre.group(0)}" if centre else ""), "FITXA")

    for kind, rx in ID_PATTERNS:
        m = rx.search(text)
        if m:
            return normalize_identifier(m.group(0), kind), kind

    # The standard Generalitat sheets use an 8-digit numeric placement id
    # beginning 19/20. Centre codes usually begin 08/17/25/etc., so this avoids
    # confusing centre codes with placement identifiers.
    m = NUMERIC_PLACE_RE.search(text)
    if m:
        return m.group(0), "NUMERIC"

    # Last-resort stable key for a direct HTML/table listing that exposes a
    # centre code but no separate placement id. Keep specialty in the key.
    cm = CENTRE_RE.search(text)
    if cm:
        return cm.group(0), "CENTRE"
    return None, None


def target_counts(positions: list[dict]) -> dict[str, int]:
    return {c: sum(1 for p in positions if c in (p.get("target_codes") or [])) for c in TARGETS}


def merge_position(out: dict[str, dict], *, pid: str, id_kind: str, code: str, source: dict, hit: dict, source_kind: str) -> None:
    # Centre-code fallback needs the specialty to avoid cross-specialty collisions.
    key = f"{pid}:{code}" if id_kind == "CENTRE" else pid
    rec = out.setdefault(key, {
        "placement_id": key,
        "display_id": pid,
        "id_kind": id_kind,
        "target_codes": [],
        "source_urls": [],
        "source_kinds": [],
        "evidence_snippets": [],
    })
    if code not in rec["target_codes"]:
        rec["target_codes"].append(code)
    url = source.get("url") or source.get("logical_url") or source.get("fetch", {}).get("final_url")
    if url and url not in rec["source_urls"]:
        rec["source_urls"].append(url)
    if source_kind not in rec["source_kinds"]:
        rec["source_kinds"].append(source_kind)
    snip = clean(hit.get("snippet"))[:800]
    if snip and snip not in rec["evidence_snippets"]:
        rec["evidence_snippets"].append(snip)


def derive_non_edubcn(rec: dict) -> dict:
    freshness = rec.get("freshness", "PARCIAL")
    docs = [d for d in (rec.get("documents") or []) if not d.get("error")]
    current_offer_docs = [d for d in docs if document_kind(d) in {"offer", "pfi"}]
    source_mode = "offer-documents" if current_offer_docs else "none"
    sources = current_offer_docs

    # Some territories publish current vacancies directly in HTML rather than
    # a separate offer PDF. Use landing hits only when no current offer doc was
    # recoverable; this avoids double counting links/archives.
    if not sources:
        landing_sources = [l for l in (rec.get("landings") or []) if not l.get("error") and (l.get("target_hits") or [])]
        if landing_sources:
            sources = landing_sources
            source_mode = "landing-fallback"

    positions: dict[str, dict] = {}
    unidentified: list[dict] = []
    raw_offer_hits = 0
    for src in sources:
        sk = document_kind(src) if src in current_offer_docs else "landing"
        for hit in src.get("target_hits") or []:
            code = (hit.get("code") or "").upper()
            if code not in TARGETS:
                continue
            raw_offer_hits += 1
            pid, id_kind = identifier_from_snippet(hit.get("snippet") or "")
            if not pid:
                unidentified.append({
                    "target_code": code,
                    "source_url": src.get("url") or src.get("logical_url"),
                    "snippet": clean(hit.get("snippet"))[:800],
                })
                continue
            merge_position(positions, pid=pid, id_kind=id_kind or "UNKNOWN", code=code, source=src, hit=hit, source_kind=sk)

    explicit_no_places = any(
        phrase in (rec.get("landing_text_excerpt") or "").lower()
        for phrase in ("no hi ha places", "no hi ha cap plaça", "sense places")
    )
    have_current_source = bool(current_offer_docs) or source_mode == "landing-fallback" or explicit_no_places
    authoritative = freshness == "FRESC" and have_current_source and not unidentified
    reason = None
    if freshness != "FRESC":
        reason = f"source freshness is {freshness}; disappearance cannot prune"
    elif not have_current_source:
        reason = "no current offer PDF/list could be identified; disappearance cannot prune"
    elif unidentified:
        reason = f"{len(unidentified)} target hit(s) in current offer source have no stable placement id; disappearance cannot prune safely"

    pos = list(positions.values())
    for p in pos:
        p["target_codes"].sort(key=TARGETS.index)
    pos.sort(key=lambda p: p["placement_id"])
    return {
        "source_freshness": freshness,
        "presence_authoritative": authoritative,
        "source_mode": source_mode if have_current_source else "none",
        "current_target_placements": pos,
        "current_target_counts": target_counts(pos),
        "raw_target_hits_in_current_offer_sources": raw_offer_hits,
        "unidentified_target_hits": unidentified,
        "prune_rule": "prune only when presence_authoritative=true and placement is absent from current_target_placements",
        "status_note": reason,
    }


def derive_edubcn(rec: dict) -> dict:
    verified = rec.get("target_placements_document_verified")
    classification = rec.get("classification_rule") or ""
    pos = []
    if isinstance(verified, list):
        for p in verified:
            # Explicit RESULTAT closes the place even if the historical document remains retrievable.
            if p.get("coverage_confirmed"):
                continue
            codes = [c for c in (p.get("target_codes") or []) if c in TARGETS]
            if not codes:
                continue
            pid = p.get("place_code")
            if not pid:
                continue
            pos.append({
                "placement_id": pid,
                "display_id": pid,
                "id_kind": "GENSEC",
                "target_codes": sorted(codes, key=TARGETS.index),
                "centre": p.get("centre"),
                "centre_code": p.get("centre_code"),
                "profile": p.get("profile"),
                "start": p.get("start"),
                "end": p.get("end"),
                "jornada": p.get("jornada"),
                "result_present": bool(p.get("result_document_present")),
                "result_document_present": bool(p.get("result_document_present")),
                "result_classification": p.get("result_classification", "UNKNOWN"),
                "coverage_confirmed": False,
                "source_urls": p.get("offer_urls") or [],
                "source_kinds": ["document-verified"],
            })
    pos.sort(key=lambda p: p["placement_id"])
    freshness = rec.get("freshness", "PARCIAL")
    authoritative = freshness == "FRESC" and isinstance(verified, list) and "document-only" in classification
    note = None if authoritative else "EDUBCN document-only snapshot is not fully fresh/verified; disappearance cannot prune"
    return {
        "source_freshness": freshness,
        "presence_authoritative": authoritative,
        "source_mode": "edubcn-document-verified",
        "current_target_placements": pos,
        "current_target_counts": target_counts(pos),
        "raw_target_hits_in_current_offer_sources": None,
        "unidentified_target_hits": [],
        "prune_rule": "document-verified target only; RESULTAT closes; unverified DOM-only never counts",
        "status_note": note,
    }


def derive_territory(name: str, rec: dict) -> dict:
    return derive_edubcn(rec) if name == "EDUBCN" else derive_non_edubcn(rec)


def previous_state(current_run_id: str | None) -> dict | None:
    """Only compare against the canonical final previous state, never provisional JSON."""
    backup = ROOT / "state" / "_previous_final.json"
    if backup.exists():
        try:
            d = json.loads(backup.read_text(encoding="utf-8"))
            if d.get("run_id") != current_run_id and d.get("active_snapshot") and d.get("edubcn_finalize_at"):
                return d
        except (OSError, ValueError):
            pass
    if not HISTORY_DIR.exists():
        return None
    files = sorted([*HISTORY_DIR.glob("*.json"), *HISTORY_DIR.glob("*.json.gz")], reverse=True)
    for path in files:
        try:
            if path.suffix == ".gz":
                with gzip.open(path, "rt", encoding="utf-8") as fp: data = json.load(fp)
            else:
                with path.open("r", encoding="utf-8") as fp: data = json.load(fp)
        except (OSError, ValueError):
            continue
        if data.get("run_id") != current_run_id and data.get("active_snapshot") and data.get("edubcn_finalize_at"):
            return data
    return None


def append_removed(snapshot: dict, previous: dict | None) -> None:
    prev_territories = (previous or {}).get("territories", {})
    for name, cur in snapshot["territories"].items():
        cur["removed_since_previous"] = []
        if not cur.get("presence_authoritative"):
            continue
        prev_rec = prev_territories.get(name)
        if not prev_rec:
            continue
        prev = derive_territory(name, prev_rec)
        if not prev.get("presence_authoritative"):
            continue
        old = {p["placement_id"]: p for p in prev.get("current_target_placements", [])}
        new_ids = {p["placement_id"] for p in cur.get("current_target_placements", [])}
        cur["removed_since_previous"] = [old[k] for k in sorted(old.keys() - new_ids)]


def report_section(snapshot: dict) -> str:
    lines = [
        "## Presència activa v1 — autoritativa",
        "- Regla: una plaça continua activa mentre apareix al PDF/llistat oficial ACTUAL, encara que el termini de sol·licitud hagi vençut.",
        "- Si desapareix d'una font **FRESCA** i la presència és autoritativa, surt de la llista activa.",
        "- Si la font és PARCIAL/CACHE OBSOLETA o l'extracció no és segura, **no es poda** per desaparició.",
        "- Els `hits` bruts són només diagnòstic; el recompte següent és de **places úniques actuals**.",
        "",
        "| Àmbit | Frescor | Autoritativa | 507 | F57 | 627 | F87 | Mode |",
        "|---|---|---|---:|---:|---:|---:|---|",
    ]
    for name, rec in snapshot["territories"].items():
        c = rec["current_target_counts"]
        lines.append(
            f"| {name} | {rec['source_freshness']} | {'sí' if rec['presence_authoritative'] else 'no'} | "
            f"{c['507']} | {c['F57']} | {c['627']} | {c['F87']} | {rec['source_mode']} |"
        )
    lines += ["", "### Places actuals detectades"]
    for name, rec in snapshot["territories"].items():
        ids = [f"`{p['placement_id']}` ({','.join(p['target_codes'])})" for p in rec["current_target_placements"]]
        lines.append(f"- **{name}**: " + (", ".join(ids) if ids else "cap"))
        if rec.get("status_note"):
            lines.append(f"  - ⚠ {rec['status_note']}")
        if rec.get("removed_since_previous"):
            lines.append("  - Desaparegudes des de la passada anterior: " + ", ".join(f"`{p['placement_id']}`" for p in rec["removed_since_previous"]))
    return "\n".join(lines) + "\n"


def main() -> int:
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    snapshot = {
        "generated_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "source_generated_at": state.get("generated_at"),
        "rule_version": 1,
        "rule": "current-presence: keep while present in current official offer PDF/list even after deadline; remove on disappearance only from authoritative FRESH current source",
        "territories": {},
    }
    for name, rec in (state.get("territories") or {}).items():
        snapshot["territories"][name] = derive_territory(name, rec)

    prev = previous_state(state.get("run_id"))
    append_removed(snapshot, prev)
    state["active_snapshot"] = snapshot
    state["activity_rule"] = snapshot["rule"]
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if HEALTH_FILE.exists():
        try:
            health = json.loads(HEALTH_FILE.read_text(encoding="utf-8"))
        except Exception:
            health = {}
        health["active_snapshot_at"] = snapshot["generated_at"]
        health["presence_authoritative"] = sum(1 for r in snapshot["territories"].values() if r["presence_authoritative"])
        health["presence_non_authoritative"] = sum(1 for r in snapshot["territories"].values() if not r["presence_authoritative"])
        HEALTH_FILE.write_text(json.dumps(health, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    base = REPORT_FILE.read_text(encoding="utf-8") if REPORT_FILE.exists() else ""
    base = re.sub(r"\n## Presència activa v1 — autoritativa[\s\S]*$", "", base).rstrip()
    base = base.replace("| Àmbit | Frescor | 507 hits | F57 hits | 627 hits | F87 hits | Àncora global |",
                        "| Àmbit | Frescor | 507 hits (diag.) | F57 hits (diag.) | 627 hits (diag.) | F87 hits (diag.) | Àncora global |")
    REPORT_FILE.write_text(base + "\n\n" + report_section(snapshot), encoding="utf-8")

    print(json.dumps({
        "active_snapshot_at": snapshot["generated_at"],
        "authoritative_scopes": sum(1 for r in snapshot["territories"].values() if r["presence_authoritative"]),
        "positions": {name: rec["current_target_counts"] for name, rec in snapshot["territories"].items()},
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

