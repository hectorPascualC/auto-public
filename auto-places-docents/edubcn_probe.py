#!/usr/bin/env python3
"""EDUBCN robust second-pass probe (v3).

The probe validates EDUBCN freshness and resolves each GENSEC call independently.
A call is classified as 507/F57/627/F87 only when that specialty appears in the
same official call/result document (or, as a fallback, the same DOM container).
This avoids cross-row false positives from global page text.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

import requests
from pypdf import PdfReader
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from coverage import classify as classify_coverage

TZ = ZoneInfo("Europe/Madrid")
ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "state" / "latest.json"
REPORT_FILE = ROOT / "state" / "latest.md"
HEALTH_FILE = ROOT / "state" / "health.json"
EDUBCN = "https://www.edubcn.cat/ca/professorat_i_pas/seleccio_rrhh/dificil_cobertura"
TARGET_CODES = ("507", "F57", "627", "F87")
KNOWN_KEEP = {34, 64, 70, 138, 139}
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36 AUTO-places-docents/1.2"
HEADERS = {"User-Agent": UA, "Cache-Control": "no-cache, no-store, max-age=0", "Pragma": "no-cache"}
GENSEC_RE = re.compile(r"\bGENSEC[_-](\d{4})[_-](\d+)\b", re.I)
TARGET_RE = re.compile(r"(?<![A-Z0-9])(507|627|F57|F87)(?![A-Z0-9])", re.I)


def clean(s: str) -> str:
    s = (s or "").replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def add_param(url: str, k: str, v: str) -> str:
    p = urlparse(url)
    q = parse_qsl(p.query, keep_blank_values=True)
    q.append((k, v))
    return urlunparse(p._replace(query=urlencode(q)))


def gensec_codes(text: str) -> list[str]:
    vals = []
    for m in GENSEC_RE.finditer(text or ""):
        vals.append(f"GENSEC_{m.group(1)}_{int(m.group(2)):03d}")
    return sorted(set(vals), key=lambda x: int(x.rsplit("_", 1)[1]))


def anchors(text: str) -> dict:
    vals = []
    for m in GENSEC_RE.finditer(text or ""):
        vals.append(((int(m.group(1)), int(m.group(2))), m.group(0)))
    if not vals:
        return {}
    vals.sort()
    rank, raw = vals[-1]
    return {"gensec": {"raw": raw, "rank": list(rank), "count": len(vals)}}


def exact_targets(text: str) -> list[str]:
    return sorted({m.group(1).upper() for m in TARGET_RE.finditer(text or "")}, key=lambda x: TARGET_CODES.index(x))


def field(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        m = re.search(pattern, text or "", re.I | re.M)
        if m:
            return clean(m.group(1))
    return None


def parse_place(text: str, url: str, role: str) -> dict:
    txt = clean(text)
    codes = gensec_codes(txt + "\n" + url)
    code = codes[0] if codes else None
    centre_code = field(txt, [r"CODI\s+DE\s+CENTRE\s*:?\s*([0-9]{8})", r"CODI\s+CENTRE\s*:?\s*([0-9]{8})"])
    centre = field(txt, [r"NOM\s+DE\s+CENTRE\s*:?\s*([^\n]+)", r"NOM\s+DEL\s+CENTRE\s*:?\s*([^\n]+)"])
    profile = field(txt, [r"(?:^|\n)\s*NOM\s*:?\s*([^\n]+)", r"CATEGORIA\s*:?\s*([^\n]+)"])
    start = field(txt, [r"DATA\s+D['’]INICI\s*:?\s*([^\n]{1,80}?)(?=\s+DATA\s+(?:DE\s+)?FI|\n|$)"])
    end = field(txt, [r"DATA\s+(?:DE\s+)?FI\s*:?\s*([^\n]{1,100}?)(?=\s+JORNADA|\n|$)"])
    jornada = field(txt, [r"JORNADA\s*:?\s*([^\n]+)"])
    kind = None
    if re.search(r"[☒Xx]\s*VACANT|\b1\s+VACANT\b", txt, re.I):
        kind = "VACANT"
    if re.search(r"[☒Xx]\s*SUBSTITUCI[ÓO]|\bSUBSTITUCI[ÓO]\b", txt, re.I):
        kind = "SUBSTITUCIÓ" if not kind else kind + "+SUBSTITUCIÓ"
    result_document_present = role == "result"
    result_classification = classify_coverage(txt) if result_document_present else "UNKNOWN"
    target_codes = exact_targets(txt)
    return {
        "gensec": code,
        "centre_code": centre_code,
        "centre": centre,
        "profile": profile,
        "target_codes": target_codes,
        "kind": kind,
        "start": start,
        "end": end,
        "jornada": jornada,
        "result_present": result_document_present,
        "result_document_present": result_document_present,
        "result_classification": result_classification,
        "coverage_confirmed": result_classification == "COVERED",
    }


def direct_document(url: str, role: str) -> dict:
    stamp = str(int(time.time() * 1000))
    variants = [add_param(url, "nocache", stamp), add_param(url, "cb", stamp + "1")]
    last: dict = {"url": url, "role": role, "error": "not fetched"}
    for u in variants:
        try:
            r = requests.get(u, headers=HEADERS, timeout=(15, 45), allow_redirects=True)
            last = {
                "url": url, "role": role, "requested_url": u, "final_url": r.url,
                "status_code": r.status_code, "etag": r.headers.get("ETag"),
                "last_modified": r.headers.get("Last-Modified"), "content_type": r.headers.get("Content-Type"),
                "content_length": len(r.content), "sha256": hashlib.sha256(r.content).hexdigest(),
            }
            if not r.ok or not r.content:
                last["error"] = f"HTTP {r.status_code}"
                continue
            ctype = (r.headers.get("Content-Type") or "").lower()
            is_pdf = "pdf" in ctype or url.lower().split("?")[0].endswith(".pdf")
            if not is_pdf:
                text = clean(r.text)
                last.update({"text_sha256": hashlib.sha256(text.encode()).hexdigest(), "text_excerpt": text[:7000]})
                last["place"] = parse_place(text, url, role)
                return last
            tmp = ROOT / "runs" / "edubcn-probe"
            tmp.mkdir(parents=True, exist_ok=True)
            stem = hashlib.sha256(url.encode()).hexdigest()[:14]
            pdf_path = tmp / f"{stem}.pdf"
            txt_path = tmp / f"{stem}.txt"
            pdf_path.write_bytes(r.content)
            reader = PdfReader(str(pdf_path))
            text = clean("\n\n".join((page.extract_text() or "") for page in reader.pages))
            txt_path.write_text(text, encoding="utf-8")
            last.update({
                "pages": len(reader.pages), "anchors": anchors(text),
                "text_sha256": hashlib.sha256(text.encode()).hexdigest(), "text_excerpt": text[:7000],
                "place": parse_place(text, url, role),
            })
            return last
        except Exception as e:
            last = {"url": url, "role": role, "requested_url": u, "error": f"{type(e).__name__}: {e}"}
    return last


def frame_snapshot(frame) -> dict:
    try:
        body = clean(frame.locator("body").inner_text(timeout=5000))
    except Exception:
        body = ""
    containers = []
    try:
        containers = frame.locator("body").evaluate("""body => {
          const rx = /GENSEC[_-]\\d{4}[_-]\\d+/i;
          const out = [];
          const seen = new Set();
          const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
          let n;
          while ((n = walker.nextNode())) {
            if (!rx.test(n.nodeValue || '')) continue;
            let el = n.parentElement;
            let chosen = el;
            for (let i=0; el && i<6; i++, el=el.parentElement) {
              const txt = (el.innerText || '').trim();
              const links = [...el.querySelectorAll('a[href]')];
              if (txt.length <= 5000 && links.length > 0) chosen = el;
              if (txt.length > 5000) break;
            }
            if (!chosen) continue;
            const txt = (chosen.innerText || '').trim();
            const key = txt.slice(0,500) + '|' + chosen.tagName;
            if (seen.has(key)) continue;
            seen.add(key);
            out.push({
              tag: chosen.tagName,
              text: txt,
              links: [...chosen.querySelectorAll('a[href]')].map(a => ({text:(a.innerText||'').trim(), url:a.href||''}))
            });
          }
          return out.slice(0,250);
        }""")
    except Exception:
        containers = []
    return {"url": frame.url, "body": body, "containers": containers}


def role_for(text: str, url: str) -> str:
    s = (text + " " + url).lower()
    return "result" if "result" in s else "offer"


def merge_places(documents: list[dict], dom_groups: dict[str, dict]) -> list[dict]:
    groups: dict[str, dict] = {}
    for code, dom in dom_groups.items():
        groups.setdefault(code, {"gensec": code, "dom_text": dom.get("text", ""), "documents": []})
    for d in documents:
        p = d.get("place") or {}
        code = p.get("gensec")
        if not code:
            codes = gensec_codes(d.get("url", ""))
            code = codes[0] if codes else None
        if not code:
            continue
        groups.setdefault(code, {"gensec": code, "dom_text": "", "documents": []})["documents"].append(d)

    merged = []
    for code, g in groups.items():
        docs = g["documents"]
        offer_docs = [d for d in docs if d.get("role") == "offer"]
        result_docs = [d for d in docs if d.get("role") == "result"]
        ordered = offer_docs + result_docs
        meta = {"gensec": code}
        targets = set()
        for d in ordered:
            p = d.get("place") or {}
            targets.update(p.get("target_codes") or [])
            for k in ("centre_code", "centre", "profile", "kind", "start", "end", "jornada"):
                if not meta.get(k) and p.get(k):
                    meta[k] = p[k]
        dom_text = g.get("dom_text") or ""
        if not targets and code in dom_text:
            targets.update(exact_targets(dom_text))
        meta["target_codes"] = sorted(targets, key=lambda x: TARGET_CODES.index(x))
        meta["result_present"] = any((d.get("place") or {}).get("result_present") for d in docs)
        meta["offer_urls"] = [d.get("url") for d in offer_docs]
        meta["result_urls"] = [d.get("url") for d in result_docs]
        meta["document_count"] = len(docs)
        merged.append(meta)
    merged.sort(key=lambda x: int(x["gensec"].rsplit("_", 1)[1]))
    return merged


def main() -> int:
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    previous = state.get("territories", {}).get("EDUBCN", {})
    prev_anchor = ((previous.get("fingerprint") or {}).get("anchors") or {}).get("gensec")
    record = {
        "name": "EDUBCN", "provider": "playwright-direct-v3",
        "checked_at": datetime.now(TZ).isoformat(timespec="seconds"), "url": EDUBCN,
        "documents": [], "placements": [],
        "probe_strategy": "domcontentloaded+gensec-link-grouping+same-document-specialty-validation",
    }
    captured_responses = []
    dom_groups: dict[str, dict] = {}
    links: list[dict] = []
    combined = ""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=UA, locale="ca-ES", extra_http_headers=HEADERS)
            page = ctx.new_page()

            def on_response(resp):
                u = resp.url.lower()
                if "edubcn" in u and any(k in u for k in ("dificil", "seleccio", "gensec", "ajax", "json")):
                    captured_responses.append({"url": resp.url, "status": resp.status, "content_type": resp.headers.get("content-type")})
            page.on("response", on_response)

            live = add_param(EDUBCN, "nocache", str(int(time.time() * 1000)))
            nav_note = "ok"
            try:
                page.goto(live, wait_until="domcontentloaded", timeout=45000)
            except PlaywrightTimeoutError:
                nav_note = "domcontentloaded timeout; continued with current DOM"

            deadline = time.time() + 35
            snapshots = []
            while time.time() < deadline:
                snapshots = [frame_snapshot(f) for f in page.frames]
                combined = clean("\n".join(s["body"] for s in snapshots))
                if GENSEC_RE.search(combined):
                    break
                page.wait_for_timeout(1000)

            snapshots = [frame_snapshot(f) for f in page.frames]
            combined = clean("\n".join(s["body"] for s in snapshots))
            for s in snapshots:
                for c in s.get("containers") or []:
                    codes = gensec_codes(c.get("text", ""))
                    for code in codes:
                        bucket = dom_groups.setdefault(code, {"text": "", "links": []})
                        if len(c.get("text", "")) > len(bucket["text"]):
                            bucket["text"] = c.get("text", "")
                        bucket["links"].extend(c.get("links") or [])
                try:
                    frame = next((f for f in page.frames if f.url == s["url"]), None)
                    if frame:
                        links.extend(frame.locator("a").evaluate_all("els => els.map(a => ({text:(a.innerText||'').trim(), url:a.href||''})).filter(x => x.url)"))
                except Exception:
                    pass
            record["global"] = {
                "url": page.url, "navigation_note": nav_note, "frame_count": len(snapshots),
                "anchors": anchors(combined), "gensec_count": len(gensec_codes(combined)),
                "gensec_codes": gensec_codes(combined), "body_sha256": hashlib.sha256(combined.encode()).hexdigest(),
                "captured_responses": captured_responses[-120:],
            }
            browser.close()

        grouped_links: dict[str, dict[str, dict]] = {}
        for x in links:
            u, t = x.get("url", ""), x.get("text", "")
            if not u.startswith("http") or "edubcn.cat" not in urlparse(u).netloc.lower():
                continue
            for code in gensec_codes(u + "\n" + t):
                grouped_links.setdefault(code, {})[u] = {"url": u, "text": t, "role": role_for(t, u)}
        for code, dom in dom_groups.items():
            for x in dom.get("links") or []:
                u, t = x.get("url", ""), x.get("text", "")
                if u.startswith("http") and "edubcn.cat" in urlparse(u).netloc.lower():
                    grouped_links.setdefault(code, {})[u] = {"url": u, "text": t, "role": role_for(t, u)}

        candidates = []
        for code, by_url in grouped_links.items():
            for item in by_url.values():
                s = (item["url"] + " " + item["text"]).lower()
                if any(k in s for k in ("rcs_gene/seleccio", ".pdf", "convocat", "resultat")):
                    candidates.append((int(code.rsplit("_", 1)[1]), code, item))
        candidates.sort(key=lambda x: (x[0], x[2]["role"] == "result"), reverse=True)

        seen_urls = set()
        for _, code, item in candidates:
            if item["url"] in seen_urls:
                continue
            seen_urls.add(item["url"])
            doc = direct_document(item["url"], item["role"])
            doc["label"] = item["text"]
            doc["dom_gensec"] = code
            record["documents"].append(doc)

        placements = merge_places(record["documents"], dom_groups)
        record["placements"] = placements
        record["target_placements"] = [p for p in placements if p.get("target_codes")]
        record["target_by_code"] = {c: [p for p in placements if c in (p.get("target_codes") or [])] for c in TARGET_CODES}

        cur_anchor = record.get("global", {}).get("anchors", {}).get("gensec")
        if not cur_anchor:
            cur_anchor = anchors("\n".join(p["gensec"] for p in placements)).get("gensec")
        record["fingerprint"] = {
            "anchors": {"gensec": cur_anchor} if cur_anchor else {},
            "frame_count": record.get("global", {}).get("frame_count", 0),
            "gensec_count": record.get("global", {}).get("gensec_count", 0),
            "document_hashes": [d.get("sha256") for d in record["documents"] if d.get("sha256")],
        }

        notes = []
        if cur_anchor and prev_anchor and tuple(cur_anchor.get("rank", [])) < tuple(prev_anchor.get("rank", [])):
            record["freshness"] = "CACHE OBSOLETA"
            notes.append(f"GENSEC regressa: {cur_anchor.get('raw')} < {prev_anchor.get('raw')}")
        elif cur_anchor and tuple(cur_anchor.get("rank", [])) >= (2627, 138):
            record["freshness"] = "FRESC"
        elif cur_anchor:
            record["freshness"] = "PARCIAL"
            notes.append(f"àncora {cur_anchor.get('raw')} inferior al mínim GENSEC_2627_138")
        else:
            record["freshness"] = "PARCIAL"
            notes.append("no s'ha pogut demostrar cap àncora GENSEC")
        verified_docs = [d for d in record["documents"] if not d.get("error") and d.get("sha256")]
        record["discovery_diagnostics"] = {
            "dom_gensec_observed": record.get("global", {}).get("gensec_count", 0),
            "documents_fetched": len(record["documents"]),
            "documents_verified": len(verified_docs),
            "complete_catalog_verified": False,
        }
        if not verified_docs or record.get("global", {}).get("gensec_count", 0) == 0:
            record["freshness"] = "PARCIAL"
            notes.append("EDUBCN: cannot prove current DOM and official documents")
        record["freshness_notes"] = notes

    except Exception as e:
        record["freshness"] = "PARCIAL"
        record["error"] = f"{type(e).__name__}: {e}"

    state.setdefault("territories", {})["EDUBCN"] = record
    state["edubcn_probe_at"] = datetime.now(TZ).isoformat(timespec="seconds")
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    vals = list(state.get("territories", {}).values())
    health = {
        "generated_at": state.get("generated_at"), "edubcn_probe_at": state.get("edubcn_probe_at"),
        "fresh": sum(1 for x in vals if x.get("freshness") == "FRESC"),
        "partial": sum(1 for x in vals if x.get("freshness") == "PARCIAL"),
        "cache_obsoleta": sum(1 for x in vals if x.get("freshness") == "CACHE OBSOLETA"), "total": len(vals),
    }
    HEALTH_FILE.write_text(json.dumps(health, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    base = REPORT_FILE.read_text(encoding="utf-8") if REPORT_FILE.exists() else ""
    base = re.sub(r"\n## EDUBCN probe v[23] override[\s\S]*$", "", base).rstrip()
    a = ((record.get("fingerprint", {}).get("anchors") or {}).get("gensec") or {}).get("raw", "—")
    targets = record.get("target_placements") or []
    extra = (
        f"\n\n## EDUBCN probe v3 override\n"
        f"- Frescor: **{record.get('freshness', 'PARCIAL')}**\n"
        f"- Àncora global: `{a}`\n"
        f"- GENSEC visibles: {record.get('global', {}).get('gensec_count', 0)}\n"
        f"- Documents GENSEC recuperats: {len(record.get('documents') or [])}\n"
        f"- Places target validades en el mateix document: {len(targets)}\n"
        f"- Estratègia: agrupació per GENSEC + validació d'especialitat dins del mateix PDF/fitxa\n"
    )
    for p in targets:
        extra += f"- `{p['gensec']}`: {','.join(p.get('target_codes') or [])} | {p.get('centre') or '?'} | {p.get('jornada') or '?'} | fi {p.get('end') or '?'} | resultat={p.get('result_present')}\n"
    if record.get("freshness_notes"):
        extra += "- Notes: " + "; ".join(record["freshness_notes"]) + "\n"
    REPORT_FILE.write_text(base + extra, encoding="utf-8")

    focus = next((p for p in record.get("placements", []) if p.get("gensec") == "GENSEC_2627_139"), None)
    print(json.dumps({"EDUBCN": record.get("freshness"), "anchor": a, "targets": len(targets), "GENSEC_2627_139": focus, "health": health}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

