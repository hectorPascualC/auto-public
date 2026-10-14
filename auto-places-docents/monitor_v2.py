#!/usr/bin/env python3
"""Source monitor v2.

Runs the existing direct HTTP/Playwright monitor with parsing/freshness fixes applied
before ``main()``:
- ``cobertura`` must not be interpreted as ``cobert``/RESULTAT;
- numeric placement ids remain detectable when PDF extraction glues them to text;
- standalone numeric target-code lookalikes inside telephone numbers are ignored;
- an anchor decrease is not automatically stale cache when the SAME official current
  offer document has a strictly newer Last-Modified value and a changed SHA-256.

That last rule is important for rolling PDFs/lists: when the administration removes a
placement from the current list, the highest identifier can legitimately go backwards.
In that case the new document is authoritative and disappearance may prune the place.
"""
from __future__ import annotations

import re
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urlunsplit

import monitor as core

RESULT_RE = re.compile(
    r"(?:\bresultats?\b|\badjudic\w*\b|\bresoluci[oó]\w*\b|"
    r"\bcobert(?:a|es|s)?\b|vacants?[-_ ]cobert(?:a|es|s)?)",
    re.I,
)


def classify_link_v2(link: dict) -> str | None:
    s = (link["text"] + " " + link["url"]).lower()
    if RESULT_RE.search(s):
        return "result"
    if any(w in s for w in core.PFI_WORDS):
        return "pfi"
    if any(w in s for w in core.OFFER_WORDS):
        return "offer"
    if ".pdf" in s:
        return "pdf"
    return None


def canonical_url(url: str | None) -> str:
    if not url:
        return ""
    p = urlsplit(url)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path, "", ""))


def http_date(value: str | None):
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except Exception:
        return None


def newer_current_offer_evidence(current: dict, previous: dict | None) -> tuple[bool, str | None]:
    """Return proof that a regressed anchor comes from a genuinely newer offer PDF/list.

    We only accept regression when the same official offer/PFI document exists in both
    snapshots, its HTTP Last-Modified timestamp moved forward, and its bytes changed.
    This avoids using a merely re-fetched cached object as evidence of disappearance.
    """
    if not previous:
        return False, None

    prev_by_url = {
        canonical_url(d.get("url")): d
        for d in (previous.get("documents") or [])
        if d.get("url")
    }

    for doc in current.get("documents") or []:
        url = canonical_url(doc.get("url"))
        if not url:
            continue
        kind = classify_link_v2({"text": doc.get("label", ""), "url": doc.get("url", "")})
        if kind not in {"offer", "pfi"}:
            continue
        prev = prev_by_url.get(url)
        if not prev:
            continue

        cur_fetch = doc.get("fetch") or {}
        prev_fetch = prev.get("fetch") or {}
        cur_lm = http_date(cur_fetch.get("last_modified"))
        prev_lm = http_date(prev_fetch.get("last_modified"))
        cur_sha = cur_fetch.get("sha256")
        prev_sha = prev_fetch.get("sha256")

        if (
            cur_lm is not None
            and prev_lm is not None
            and cur_lm > prev_lm
            and cur_sha
            and prev_sha
            and cur_sha != prev_sha
        ):
            return True, (
                f"regressió d'àncora acceptada: document d'oferta actualitzat "
                f"({prev_fetch.get('last_modified')} → {cur_fetch.get('last_modified')}; SHA canviat)"
            )
    return False, None


def compare_freshness_v2(current: dict, previous: dict | None) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if current.get("error"):
        return "PARCIAL", [current["error"]]

    # PDF variant disagreement must propagate to territory freshness.
    # A successful HTTP response is not evidence of a current document.
    pdf_errors = [
        d.get("error")
        for d in (current.get("documents") or [])
        if (d.get("error") or "").startswith("PDF_CACHE_")
    ]
    if pdf_errors:
        return "PARCIAL", ["PDF cache verification failed: " + "; ".join(pdf_errors)]

    prev_fp = (previous or {}).get("fingerprint") or {}
    cur_fp = current.get("fingerprint") or {}
    prev_anchors = prev_fp.get("anchors") or {}
    cur_anchors = cur_fp.get("anchors") or {}

    regressions: list[str] = []
    for kind, p in prev_anchors.items():
        c = cur_anchors.get(kind)
        if not c:
            reasons.append(f"àncora prèvia {kind} no observable en aquesta estructura")
            continue
        if tuple(c.get("rank", [])) < tuple(p.get("rank", [])):
            regressions.append(f"{kind} regressa: {c.get('raw')} < {p.get('raw')}")

    if regressions:
        proven_newer, note = newer_current_offer_evidence(current, previous)
        if not proven_newer:
            return "CACHE OBSOLETA", reasons + regressions
        reasons.extend(regressions)
        if note:
            reasons.append(note)

    if current.get("offer_docs_ok", 0) == 0 and current.get("target_hits", 0) == 0:
        t = (current.get("landing_text_excerpt") or "").lower()
        if "no hi ha places" in t or "no hi ha cap plaça" in t or "sense places" in t:
            return "FRESC", reasons + ["pàgina viva indica explícitament que no hi ha places"]
        return "PARCIAL", reasons + ["cap document d'oferta parsejat ni coincidència objectiu"]

    return "FRESC", reasons


# Catalunya Central's rolling PDF places the specialty near the top of each
# page but its stable "fitxa N" identifier near the bottom. The core default
# context radius (3 lines) therefore preserved the 627 hit but dropped the
# identity, so active_snapshot could not count the placement. Keep a wider
# evidence window only for that layout. Using it globally can make a target code
# inherit an identifier from a neighbouring non-target placement.
#
# Tarragona exposed a second edge case: a telephone such as `977 627 203`
# contains a standalone `627` token. The old exact-token matcher treated that as
# an specialty hit and the fail-closed audit correctly stopped persistence. We
# reject only 507/627 occurrences that are structurally part of a phone number;
# F57/F87 cannot occur inside a numeric telephone and are untouched.
_PHONE_TRIPLET_RE = re.compile(
    r"(?<!\d)(?:\+34[\s.()-]*)?\d{3}[\s.()-]+(?P<code>507|627)[\s.()-]+\d{3}(?!\d)",
    re.I,
)
_PHONE_HEADER_RE = re.compile(r"\btel[eè]fon\b|\btelefon\b", re.I)


def _phone_false_positive(lines: list[str], index: int, line: str, code: str, match: re.Match[str]) -> bool:
    if code not in {"507", "627"}:
        return False
    for m in _PHONE_TRIPLET_RE.finditer(line):
        if m.group("code").upper() == code and m.start() <= match.start() < m.end():
            return True

    # Defensive fallback for extraction that groups a Spanish 9-digit phone in a
    # non-3/3/3 layout. Only apply it immediately below a `Telèfon` heading and
    # only when the line contains exactly nine digits in total.
    previous = " ".join(lines[max(0, index - 2):index])
    if _PHONE_HEADER_RE.search(previous) and len(re.sub(r"\D", "", line)) == 9:
        return True
    return False


def context_hits_v2(text: str, radius: int = 3, max_each: int = 20) -> list[dict]:
    lowered = text.lower()
    effective_radius = 24 if ("catalunya central" in lowered or "identificacor plaça" in lowered) else radius
    lines = [core.clean_text(x) for x in text.splitlines()]
    hits: list[dict] = []
    for code in core.TARGET_CODES:
        rx = re.compile(rf"(?<![A-Z0-9]){re.escape(code)}(?![A-Z0-9])", re.I)
        count = 0
        for i, line in enumerate(lines):
            if not line:
                continue
            matches = list(rx.finditer(line))
            if not matches:
                continue
            if all(_phone_false_positive(lines, i, line, code.upper(), match) for match in matches):
                continue
            lo, hi = max(0, i - effective_radius), min(len(lines), i + effective_radius + 1)
            snippet = "\n".join(x for x in lines[lo:hi] if x)
            hits.append({"code": code.upper(), "line": i + 1, "snippet": snippet[:3500]})
            count += 1
            if count >= max_each:
                break
    return hits


def _assert_target_hit_regressions() -> None:
    phone_sample = """Municipi Telèfon
Els Pallaresos 977 627 203
Jornada Data d’inici Data de finalització prevista"""
    if any(h["code"] == "627" for h in context_hits_v2(phone_sample)):
        raise RuntimeError("target-hit regression: telephone 977 627 203 matched specialty 627")

    real_sample = """Dades de la plaça
Identificador de la plaça Especialitat Presentació de sol·licituds
19681272 627 - Sistemes i aplicacions informàtiques
Institut El Calamot"""
    if not any(h["code"] == "627" for h in context_hits_v2(real_sample)):
        raise RuntimeError("target-hit regression: real 627 specialty was filtered")

    neighbour_sample = """Dades de la plaça
503 - Assessoria i Processos d'Imatge Personal19662328
Institut Enric Borràs
Observacions
Oferta de vacants o substitucions de difícil cobertura
Dades de la plaça
Identificador de la plaça Especialitat Presentació de sol·licituds
507 - Informàtica19663355
Institut Manuel Vázquez Montalbán"""
    hit = next(h for h in context_hits_v2(neighbour_sample) if h["code"] == "507")
    if "19662328" in hit["snippet"]:
        raise RuntimeError("target-hit regression: non-target neighbouring placement leaked into 507 evidence")


_assert_target_hit_regressions()
core.context_hits = context_hits_v2
core.classify_link = classify_link_v2
core.compare_freshness = compare_freshness_v2
core.ANCHOR_PATTERNS["numeric_id"] = re.compile(r"(?<!\d)(19\d{6}|20\d{6})(?!\d)")

if __name__ == "__main__":
    raise SystemExit(core.main())

