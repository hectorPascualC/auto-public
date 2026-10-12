#!/usr/bin/env python3
"""Presence snapshot v2.

Extends active_snapshot.py with source-classification, identifier corrections and a
fail-closed audit for every territorial service:
- a current difficult-coverage PDF linked by the live territorial page is an offer/list
  source unless its own label/URL explicitly identifies it as RESULTAT/adjudicada/coberta;
- standard numeric placement ids are accepted even when PDF extraction glues them to
  the preceding specialty text;
- territorial ids such as `507-21/09`, `627-Mataró`, Girona/SEC/APA ids, and locally
  labelled slot numbers are recognized without hard-coding one SSTT;
- after building the snapshot, every one of the 11 SSTT is audited. A FRESH current
  offer source with an unidentified target hit makes the workflow fail instead of
  silently publishing an incomplete active snapshot.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import urlparse

import active_snapshot as core


EXPECTED_SSTT = (
    "Alt Pirineu i Aran",
    "Baix Llobregat",
    "Barcelonès",
    "Catalunya Central",
    "Girona",
    "Lleida",
    "Maresme-Vallès Oriental",
    "Penedès",
    "Tarragona",
    "Terres de l'Ebre",
    "Vallès Occidental",
)
AUDIT_FILE = core.ROOT / "state" / "audit.json"


def current_document_kind(doc: dict) -> str:
    s = core.clean(f"{doc.get('label','')} {doc.get('text','')} {doc.get('url','')}")
    if core.RESULT_RE.search(s):
        return "result"
    if core.PFI_RE.search(s):
        return "pfi"
    if core.OFFER_RE.search(s):
        return "offer"

    url = (doc.get("url") or "").lower()
    label = (doc.get("label") or doc.get("text") or "").lower()
    path = urlparse(url).path.lower()
    is_pdf = path.endswith(".pdf") or "pdf" in (doc.get("fetch", {}).get("content_type") or "").lower()

    # Live territorial difficult-coverage pages often link the current offer PDF
    # with a generic label such as "Difícil cobertura secundària 10/09/2026".
    # It is an offer source unless explicit result markers above say otherwise.
    difficult_context = (
        "dificil-cobertura" in path
        or "difícil cobertura" in label
        or "dificil cobertura" in label
        or "/provisio-vacants" in path
        or "dc-sec" in path
    )
    if is_pdf and difficult_context:
        return "offer"

    role = (doc.get("role") or "").lower()
    # Never trust old role=result blindly: the old monitor classifier matched
    # the substring "cobert" inside "cobertura". offer/pfi are safe fallbacks.
    if role in {"offer", "pfi"}:
        return role
    return "other"


# Some territorial services publish the official placement identity as specialty +
# publication date, optionally with a sequence number, e.g. `627-21/09` or
# `507-09/09 (4)`. These are explicitly printed under `Identificador de la plaça`.
LOCAL_DATED_ID_BODY = r"(?:507|627|F57|F87)\s*[-–—]\s*\d{1,2}\s*/\s*\d{1,2}(?:\s*/\s*\d{2,4})?(?:\s*\(\s*\d+\s*\))?"
LOCAL_DATED_ID_RE = re.compile(rf"(?<![A-Z0-9])({LOCAL_DATED_ID_BODY})(?![A-Z0-9])", re.I)
LOCAL_DATED_LABELED_RE = re.compile(
    rf"Identificador\s+de\s+la\s+pla[cç]a\b.{{0,220}}?({LOCAL_DATED_ID_BODY})",
    re.I | re.S,
)

# Catalunya Central has also used a short local slot number immediately after a
# placement label (including the historical typo `Identificacor Plaça`). It is only
# accepted when the integer follows that label directly, so ordinary dates/numbers
# elsewhere in the page cannot be mistaken for a placement id.
LOCAL_SLOT_LABELED_RE = re.compile(
    r"\bIdentifica(?:dor|cor)\s+(?:de\s+la\s+)?Pla[cç]a\s*:?\s*(\d{1,5})\b(?!\s*/)",
    re.I,
)

# Generic territorial pattern: several SSTT put a local identifier in the first
# column and repeat the specialty code in the second column, e.g.
#   627-Mataró   627- Sistemes i Aplicacions Informàtiques
#   507-21/09    507- Informàtica
# The repeated same code is the important guard: it lets us support municipality or
# other local suffixes without treating arbitrary `627-...` prose as an identifier.
CODE_PREFIX_PAIR_RE = re.compile(
    r"(?<![A-Z0-9])(?P<code>507|F57|627|F87)\s*[-–—]\s*"
    r"(?P<suffix>.{1,80}?)\s+(?=(?P=code)\s*[-–—]\s*)",
    re.I | re.S,
)


def normalize_local_dated_id(raw: str) -> str:
    s = core.clean(raw).upper()
    s = re.sub(r"\s*[-–—]\s*", "-", s)
    s = re.sub(r"\s*/\s*", "/", s)
    s = re.sub(r"\s*\(\s*(\d+)\s*\)", r" (\1)", s)
    return s


def normalize_code_prefixed_id(code: str, suffix: str) -> str | None:
    suffix = core.clean(suffix).strip(" ;,:|\t")
    if not suffix or len(suffix) > 80:
        return None
    # A suffix containing a whole second field/heading is not a safe local id.
    lowered = suffix.lower()
    if any(x in lowered for x in ("identificador de la plaça", "especialitat", "presentació de sol·licituds")):
        return None
    suffix = re.sub(r"\s*/\s*", "/", suffix)
    suffix = re.sub(r"\s*[-–—]\s*", "-", suffix)
    suffix = re.sub(r"\s*\(\s*(\d+)\s*\)", r" (\1)", suffix)
    return f"{code.upper()}-{suffix}"


_original_identifier_from_snippet = core.identifier_from_snippet
_original_derive_non_edubcn = core.derive_non_edubcn

# Target-code mentions inside requirements/merits are diagnostic duplicates, not
# separate placement rows.  They may lack the placement id because the monitor
# intentionally keeps a small context radius around each occurrence.  Ignore such
# an orphan mention only when the SAME source already contains an identifiable
# placement for the SAME specialty.  This keeps the audit fail-closed for genuinely
# unidentified new placements while avoiding false failures such as Lleida's
# "Cal tenir l'especialitat 507 reconeguda a la borsa" line.
NON_POSITIONAL_TARGET_RE = re.compile(
    r"(?:\brequisits?\b|\bm[èe]rits?\b|cal\s+tenir\s+l['’]especialitat|"
    r"reconeguda\s+a\s+la\s+borsa|prova\s+de\s+capacitaci[oó])",
    re.I,
)
POSITIONAL_TARGET_RE = re.compile(
    r"(?:identificador\s+(?:de\s+la\s+)?pla[cç]a|dades\s+de\s+la\s+pla[cç]a)",
    re.I,
)

def identifier_from_snippet_v2(snippet: str) -> tuple[str | None, str | None]:
    text = snippet or ""

    # Highest-confidence dated form: the id occurs under the official field label.
    labelled = LOCAL_DATED_LABELED_RE.search(text)
    if labelled:
        return normalize_local_dated_id(labelled.group(1)), "LOCAL_DATED"

    # Short locally numbered slot under an explicit placement label.
    slot = LOCAL_SLOT_LABELED_RE.search(text)
    if slot:
        centre = core.CENTRE_RE.search(text)
        pid = f"plaça {int(slot.group(1))}"
        if centre:
            pid += f" / {centre.group(0)}"
        return pid, "LOCAL_SLOT"

    # Generic code-prefixed local identifiers, guarded by a repeated same specialty
    # code in the adjacent field. All visible candidates must collapse to one id;
    # otherwise the hit stays unidentified and the audit fails closed.
    paired = set()
    for m in CODE_PREFIX_PAIR_RE.finditer(text):
        pid = normalize_code_prefixed_id(m.group("code"), m.group("suffix"))
        if pid:
            paired.add(pid)
    if len(paired) == 1:
        pid = next(iter(paired))
        # Preserve the more specific LOCAL_DATED kind when applicable.
        if LOCAL_DATED_ID_RE.fullmatch(pid):
            return normalize_local_dated_id(pid), "LOCAL_DATED"
        return pid, "LOCAL_TAG"
    if len(paired) > 1:
        return None, None

    # Defensive fallback for extraction variants that drop/reorder the heading:
    # only accept a local dated id when exactly one unique candidate is visible.
    candidates = {
        normalize_local_dated_id(m.group(1))
        for m in LOCAL_DATED_ID_RE.finditer(text)
    }
    if len(candidates) == 1:
        return next(iter(candidates)), "LOCAL_DATED"
    if len(candidates) > 1:
        return None, None

    return _original_identifier_from_snippet(text)


def filtered_target_hits_v2(source: dict) -> list[dict]:
    """Return positional target hits, suppressing only proven requirement duplicates."""
    hits = [
        h for h in (source.get("target_hits") or [])
        if (h.get("code") or "").upper() in core.TARGETS
    ]
    identified_codes: set[str] = set()
    parsed: list[tuple[dict, str, str | None, str | None]] = []
    for hit in hits:
        code = (hit.get("code") or "").upper()
        pid, kind = identifier_from_snippet_v2(hit.get("snippet") or "")
        if pid:
            identified_codes.add(code)
        parsed.append((hit, code, pid, kind))

    kept: list[dict] = []
    for hit, code, pid, _kind in parsed:
        if pid:
            kept.append(hit)
            continue
        snippet = hit.get("snippet") or ""
        is_requirement_duplicate = (
            code in identified_codes
            and bool(NON_POSITIONAL_TARGET_RE.search(snippet))
            and not bool(POSITIONAL_TARGET_RE.search(snippet))
        )
        if not is_requirement_duplicate:
            kept.append(hit)
    return kept


def derive_non_edubcn_v2(rec: dict) -> dict:
    """Run the core presence builder after filtering non-positional duplicate hits."""
    clone = dict(rec)
    for key in ("documents", "landings"):
        items = []
        for source in (rec.get(key) or []):
            copy = dict(source)
            copy["target_hits"] = filtered_target_hits_v2(source)
            items.append(copy)
        clone[key] = items
    return _original_derive_non_edubcn(clone)


def _assert_nonpositional_regression() -> None:
    source = {
        "target_hits": [
            {
                "code": "507",
                "snippet": "Identificador de la plaça 2026/SEC/089 Especialitat 507 Informàtica Límit presentació",
            },
            {
                "code": "507",
                "snippet": "Requisits - Cal tenir l’especialitat 507 reconeguda a la borsa.",
            },
        ]
    }
    kept = filtered_target_hits_v2(source)
    if len(kept) != 1 or "2026/SEC/089" not in (kept[0].get("snippet") or ""):
        raise RuntimeError("non-positional target-hit regression")


def _assert_identifier_regressions() -> None:
    cases = [
        (
            "Dades de la plaça Identificador de la plaça Especialitat Presentació de sol·licituds "
            "627-21/09 627-Sistemes i Aplicacions Informàtiques",
            "627-21/09", "LOCAL_DATED",
        ),
        (
            "Identificador de la plaça Especialitat 507-21/09 507-Informàtica",
            "507-21/09", "LOCAL_DATED",
        ),
        (
            "Identificador de la plaça Especialitat 507-09/09 (4) 507-Informàtica",
            "507-09/09 (4)", "LOCAL_DATED",
        ),
        (
            "Identificador de la plaça Especialitat 627-Mataró 627- Sistemes I Aplicacions Informàtiques "
            "Termini obert Institut Thos i Codina",
            "627-Mataró", "LOCAL_TAG",
        ),
        (
            "Identificacor Plaça: 109 627 Sistemes i Aplicacions Informàtiques "
            "08058404 Institut Cirviànum de Torelló",
            "plaça 109 / 08058404", "LOCAL_SLOT",
        ),
        (
            "627 Sistemes i Aplicacions Informàtiques19692859 Institut El Calamot",
            "19692859", "NUMERIC",
        ),
        (
            "174S/2026-2027 627 Sistemes i Aplicacions Informàtiques Institut de Palamós",
            "174S/2026-2027", "GIRONA",
        ),
        (
            "2026/SEC/091 507 Informàtica",
            "2026/SEC/091", "SEC",
        ),
        (
            "Identificador de la plaça 2026/SEC/089 Especialitat 507 Informàtica",
            "2026/SEC/089", "SEC",
        ),
        (
            "APA-2627-S050 627 Sistemes i Aplicacions Informàtiques",
            "APA-2627-S050", "APA",
        ),
    ]
    for sample, expected, expected_kind in cases:
        got, kind = identifier_from_snippet_v2(sample)
        if got != expected or kind != expected_kind:
            raise RuntimeError(
                f"placement-id regression: expected {expected!r}/{expected_kind}, got {got!r}/{kind!r}"
            )


def _current_offer_sources(rec: dict) -> list[dict]:
    docs = [
        d for d in (rec.get("documents") or [])
        if not d.get("error") and current_document_kind(d) in {"offer", "pfi"}
    ]
    if docs:
        return docs
    return [
        l for l in (rec.get("landings") or [])
        if not l.get("error") and (l.get("target_hits") or [])
    ]


def audit_current_state() -> int:
    """Audit all 11 SSTT after the snapshot is built.

    This is intentionally fail-closed: if a FRESH current offer contains a target hit
    that cannot be mapped to a stable identifier, the workflow fails and the compact
    state is not persisted as a successful run.
    """
    state = json.loads(core.STATE_FILE.read_text(encoding="utf-8"))
    snapshot = state.get("active_snapshot") or {}
    source_territories = state.get("territories") or {}
    snap_territories = snapshot.get("territories") or {}

    errors: list[str] = []
    per_scope: dict[str, dict] = {}

    for name in EXPECTED_SSTT:
        src = source_territories.get(name)
        act = snap_territories.get(name)
        if src is None or act is None:
            errors.append(f"{name}: missing source/snapshot record")
            continue

        sources = _current_offer_sources(src)
        raw_hits = []
        parsed = []
        unidentified = []
        for source in sources:
            for hit in filtered_target_hits_v2(source):
                code = (hit.get("code") or "").upper()
                if code not in core.TARGETS:
                    continue
                raw_hits.append(hit)
                pid, kind = identifier_from_snippet_v2(hit.get("snippet") or "")
                if pid:
                    parsed.append({"code": code, "id": pid, "kind": kind})
                else:
                    unidentified.append({
                        "code": code,
                        "source": source.get("url") or source.get("logical_url"),
                        "page": hit.get("page"),
                        "line": hit.get("line"),
                        "snippet": core.clean(hit.get("snippet"))[:500],
                    })

        active_unidentified = act.get("unidentified_target_hits") or []
        positions = act.get("current_target_placements") or []
        freshness = act.get("source_freshness")
        authoritative = bool(act.get("presence_authoritative"))

        if unidentified:
            errors.append(f"{name}: {len(unidentified)} current target hit(s) remain unidentified")
        if active_unidentified:
            errors.append(f"{name}: active snapshot still contains {len(active_unidentified)} unidentified hit(s)")
        if freshness == "FRESC" and sources and not authoritative:
            errors.append(f"{name}: FRESH current source is not authoritative")
        if raw_hits and not positions:
            errors.append(f"{name}: {len(raw_hits)} target hit(s) but zero active target placements")
        for p in positions:
            if not p.get("placement_id") or not p.get("target_codes"):
                errors.append(f"{name}: malformed active placement {p!r}")
            if p.get("id_kind") == "UNKNOWN":
                errors.append(f"{name}: active placement has UNKNOWN id kind: {p.get('placement_id')}")

        per_scope[name] = {
            "freshness": freshness,
            "presence_authoritative": authoritative,
            "current_offer_sources": len(sources),
            "raw_target_hits": len(raw_hits),
            "parsed_target_hits": len(parsed),
            "unidentified_target_hits": len(unidentified),
            "active_positions": len(positions),
            "id_kinds": sorted({p.get("id_kind") for p in positions if p.get("id_kind")}),
            "parsed_ids": parsed,
        }

    # EDUBCN is not one of the 11 SSTT, but keep the overall 12-scope integrity check.
    ed = snap_territories.get("EDUBCN")
    if ed is None:
        errors.append("EDUBCN: missing active snapshot record")
    else:
        per_scope["EDUBCN"] = {
            "freshness": ed.get("source_freshness"),
            "presence_authoritative": bool(ed.get("presence_authoritative")),
            "active_positions": len(ed.get("current_target_placements") or []),
            "unidentified_target_hits": len(ed.get("unidentified_target_hits") or []),
            "mode": ed.get("source_mode"),
        }
        if ed.get("source_freshness") == "FRESC" and not ed.get("presence_authoritative"):
            errors.append("EDUBCN: FRESH document-only snapshot is not authoritative")

    audit = {
        "audit_version": 2,
        "generated_at": datetime.now(core.TZ).isoformat(timespec="seconds"),
        "source_generated_at": state.get("generated_at"),
        "status": "PASS" if not errors else "FAIL",
        "sstt_checked": len(EXPECTED_SSTT),
        "scopes_checked": len(EXPECTED_SSTT) + 1,
        "errors": errors,
        "territories": per_scope,
    }
    AUDIT_FILE.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Surface the audit in health.json and latest.md so the reporting layer can
    # verify it without reverse-engineering the raw state.
    if core.HEALTH_FILE.exists():
        try:
            health = json.loads(core.HEALTH_FILE.read_text(encoding="utf-8"))
        except Exception:
            health = {}
        health["audit_at"] = audit["generated_at"]
        health["audit_status"] = audit["status"]
        health["audit_sstt_checked"] = audit["sstt_checked"]
        health["audit_errors"] = len(errors)
        core.HEALTH_FILE.write_text(json.dumps(health, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if core.REPORT_FILE.exists():
        base = core.REPORT_FILE.read_text(encoding="utf-8")
        base = re.sub(r"\n## Auditoria SSTT v2[\s\S]*$", "", base).rstrip()
        lines = [
            "",
            "## Auditoria SSTT v2",
            f"- Estat: **{audit['status']}**",
            f"- SSTT auditats: **{audit['sstt_checked']}/11**",
            f"- Àmbits totals auditats (inclòs EDUBCN): **{audit['scopes_checked']}/12**",
            f"- Errors d'identificació: **{len(errors)}**",
            "",
            "| Àmbit | FRESC | Autoritativa | Hits actuals | Hits identificats | Sense ID | Places actives |",
            "|---|---|---|---:|---:|---:|---:|",
        ]
        for name in EXPECTED_SSTT:
            r = per_scope.get(name, {})
            lines.append(
                f"| {name} | {'sí' if r.get('freshness') == 'FRESC' else 'no'} | "
                f"{'sí' if r.get('presence_authoritative') else 'no'} | "
                f"{r.get('raw_target_hits', 0)} | {r.get('parsed_target_hits', 0)} | "
                f"{r.get('unidentified_target_hits', 0)} | {r.get('active_positions', 0)} |"
            )
        if errors:
            lines += ["", "### Errors", *[f"- {e}" for e in errors]]
        core.REPORT_FILE.write_text(base + "\n" + "\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({
        "audit_status": audit["status"],
        "sstt_checked": audit["sstt_checked"],
        "scopes_checked": audit["scopes_checked"],
        "errors": errors,
    }, ensure_ascii=False))
    return 0 if not errors else 2


core.document_kind = current_document_kind
# PDF text extraction sometimes produces `Informàtica19669277`; word boundaries
# then fail because the preceding letter and first digit are both word chars.
core.NUMERIC_PLACE_RE = re.compile(r"(?<!\d)(?:19|20)\d{6}(?!\d)")
core.identifier_from_snippet = identifier_from_snippet_v2
core.derive_non_edubcn = derive_non_edubcn_v2

if __name__ == "__main__":
    _assert_identifier_regressions()
    _assert_nonpositional_regression()
    rc = core.main()
    if rc == 0:
        rc = audit_current_state()
    raise SystemExit(rc)

