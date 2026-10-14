#!/usr/bin/env python3
"""
AUTO places docents 507/627/F57/F87
Directly retrieves official Generalitat/EDUBCN sources without paid crawlers.
Trigger marker: production direct-fetch workflow.

Design goals:
- force a fresh HTTP request with unique cache-busters;
- retain HTTP validators (ETag/Last-Modified), SHA-256 and document structure;
- reject obvious cache regressions using persistent global anchors;
- collect exact-code contexts for 507, 627, F57 and F87;
- use Playwright only for EDUBCN's dynamic list;
- persist a compact state for ChatGPT to consume; raw downloads are workflow artifacts.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse, parse_qsl, urlencode, urlunparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

TZ = ZoneInfo("Europe/Madrid")
NOW = datetime.now(TZ)
RUN_ID = NOW.strftime("%Y%m%dT%H%M%S%z")
ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / "state"
HISTORY_DIR = STATE_DIR / "history"
RUN_DIR = ROOT / "runs" / RUN_ID
STATE_FILE = STATE_DIR / "latest.json"
REPORT_FILE = STATE_DIR / "latest.md"

TARGET_CODES = ("507", "F57", "627", "F87")
OFFICIAL_DOMAINS = {"educacio.gencat.cat", "www.edubcn.cat", "edubcn.cat"}

ST = [
    ("Alt Pirineu i Aran", "alt-pirineu-aran"),
    ("Baix Llobregat", "baix-llobregat"),
    ("Barcelonès", "barcelones"),
    ("Catalunya Central", "catalunya-central"),
    ("Girona", "girona"),
    ("Lleida", "lleida"),
    ("Maresme-Vallès Oriental", "maresme-valles-oriental"),
    ("Penedès", "penedes"),
    ("Tarragona", "tarragona"),
    ("Terres de l'Ebre", "terres-ebre"),
    ("Vallès Occidental", "valles-occidental"),
]

EDUBCN = "https://www.edubcn.cat/ca/professorat_i_pas/seleccio_rrhh/dificil_cobertura"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126 Safari/537.36 "
    "AUTO-places-docents/1.0"
)
REQ_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "*/*",
    "Cache-Control": "no-cache, no-store, max-age=0",
    "Pragma": "no-cache",
}
TIMEOUT = (15, 60)

ANCHOR_PATTERNS = {
    "gensec": re.compile(r"\bGENSEC[_-](\d{4})[_-](\d+)\b", re.I),
    "apa": re.compile(r"\bAPA[-_](\d{4})[-_]S(\d+)\b", re.I),
    "sec": re.compile(r"\b(20\d{2})/SEC(?:/PFI)?/(\d+)\b", re.I),
    "numeric_id": re.compile(r"\b(19\d{6}|20\d{6})\b"),
    "fitxa": re.compile(r"\bfitxa\s+(\d+)\b", re.I),
}
UPDATE_RE = re.compile(
    r"(?:Data\s+d['’]actualitzaci[oó]|Actualitzat(?:/da)?(?:\s+el)?)\s*:?\s*"
    r"([0-3]?\d[./-][01]?\d[./-]20\d{2})",
    re.I,
)

OFFER_WORDS = (
    "oferta", "vacant", "substit", "pendent", "dificil", "difícil", "places",
)
RESULT_WORDS = (
    "resultat", "adjudic", "cobert", "cobertes", "resoluc",
)
PFI_WORDS = ("pfi", "ife", "ptt", "f57", "f87")


def log(msg: str) -> None:
    print(f"[{datetime.now(TZ).isoformat(timespec='seconds')}] {msg}", flush=True)


def safe_slug(s: str) -> str:
    s = s.lower()
    repl = {
        "à": "a", "á": "a", "è": "e", "é": "e", "í": "i", "ï": "i",
        "ò": "o", "ó": "o", "ú": "u", "ü": "u", "ç": "c", "’": "", "'": "",
    }
    for a, b in repl.items():
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def add_param(url: str, key: str, value: str) -> str:
    p = urlparse(url)
    q = parse_qsl(p.query, keep_blank_values=True)
    q.append((key, value))
    return urlunparse(p._replace(query=urlencode(q)))


def cache_variants(url: str) -> list[str]:
    stamp = str(int(time.time() * 1000))
    return [
        add_param(url, "nocache", stamp),
        add_param(url, "cb", stamp + "1"),
        add_param(add_param(url, "versio", "last"), "nocache", stamp + "2"),
    ]


@dataclass
class FetchMeta:
    requested_url: str
    final_url: str | None = None
    status_code: int | None = None
    fetched_at: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    content_type: str | None = None
    content_length: int | None = None
    sha256: str | None = None
    cache_control: str | None = None
    error: str | None = None


class DirectFetcher:
    def __init__(self) -> None:
        self.s = requests.Session()
        self.s.headers.update(REQ_HEADERS)

    def get(self, url: str, *, binary: bool = True) -> tuple[FetchMeta, bytes | None]:
        last_meta = FetchMeta(requested_url=url)
        is_pdf = urlparse(url).path.lower().endswith(".pdf")
        successes = []
        for i, variant in enumerate(cache_variants(url)):
            try:
                r = self.s.get(variant, timeout=TIMEOUT, allow_redirects=True)
                meta = FetchMeta(
                    requested_url=variant,
                    final_url=r.url,
                    status_code=r.status_code,
                    fetched_at=datetime.now(TZ).isoformat(timespec="seconds"),
                    etag=r.headers.get("ETag"),
                    last_modified=r.headers.get("Last-Modified"),
                    content_type=r.headers.get("Content-Type"),
                    content_length=len(r.content),
                    sha256=hashlib.sha256(r.content).hexdigest(),
                    cache_control=r.headers.get("Cache-Control"),
                )
                last_meta = meta
                if r.ok and r.content:
                    successes.append((meta, r.content))
                    if not is_pdf:
                        return meta, r.content
                else:
                    meta.error = f"HTTP {r.status_code}"
            except requests.RequestException as e:
                last_meta = FetchMeta(
                    requested_url=variant,
                    fetched_at=datetime.now(TZ).isoformat(timespec="seconds"),
                    error=f"{type(e).__name__}: {e}",
                )
            if i < 2:
                time.sleep(0.7 * (i + 1))
        if successes:
            hashes = {meta.sha256 for meta, _ in successes}
            meta, content = successes[-1]
            if len(hashes) > 1:
                meta.error = "PDF_CACHE_VARIANTS_DISAGREE: " + ",".join(sorted(hashes))
                log(f"PDF variants disagree: {url}")
            elif len(successes) < 2:
                meta.error = "PDF_CACHE_UNCONFIRMED: only one successful variant"
            return meta, content
        return last_meta, None


def decode_html(content: bytes, content_type: str | None = None) -> str:
    return content.decode("utf-8", errors="replace")


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return clean_text(soup.get_text("\n"))


def extract_links(base_url: str, html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"].strip())
        p = urlparse(href)
        if p.scheme not in {"http", "https"}:
            continue
        if p.netloc.lower() not in OFFICIAL_DOMAINS:
            continue
        txt = clean_text(a.get_text(" ", strip=True))
        key = (href, txt)
        if key in seen:
            continue
        seen.add(key)
        out.append({"url": href, "text": txt})
    return out


def classify_link(link: dict) -> str | None:
    s = (link["text"] + " " + link["url"]).lower()
    if any(w in s for w in RESULT_WORDS):
        return "result"
    if any(w in s for w in PFI_WORDS):
        return "pfi"
    if any(w in s for w in OFFER_WORDS):
        return "offer"
    if ".pdf" in s:
        return "pdf"
    return None


def likely_relevant_links(links: list[dict], max_links: int = 10) -> list[dict]:
    scored = []
    for link in links:
        role = classify_link(link)
        if role is None:
            continue
        s = (link["text"] + " " + link["url"]).lower()
        score = 0
        if link["url"].lower().split("?")[0].endswith(".pdf"):
            score += 8
        if role == "offer":
            score += 7
        elif role == "result":
            score += 6
        elif role == "pfi":
            score += 5
        if any(w in s for w in ("2026", "2027", "26-27", "2627")):
            score += 4
        if any(c.lower() in s for c in TARGET_CODES):
            score += 3
        scored.append((score, role, link))
    scored.sort(key=lambda x: x[0], reverse=True)
    out, seen_urls = [], set()
    for _, role, link in scored:
        u = link["url"].split("#")[0]
        if u in seen_urls:
            continue
        seen_urls.add(u)
        out.append({**link, "role": role})
        if len(out) >= max_links:
            break
    return out


def extract_anchors(text: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for kind, rx in ANCHOR_PATTERNS.items():
        vals = []
        for m in rx.finditer(text):
            raw = m.group(0)
            nums = tuple(int(x) for x in m.groups())
            vals.append((nums, raw))
        if vals:
            vals.sort()
            nums, raw = vals[-1]
            out[kind] = {"raw": raw, "rank": list(nums), "count": len(vals)}
    return out


def extract_update_date(text: str) -> str | None:
    m = UPDATE_RE.search(text)
    return m.group(1) if m else None


def context_hits(text: str, radius: int = 3, max_each: int = 20) -> list[dict]:
    lines = [clean_text(x) for x in text.splitlines()]
    hits = []
    for code in TARGET_CODES:
        rx = re.compile(rf"(?<![A-Z0-9]){re.escape(code)}(?![A-Z0-9])", re.I)
        count = 0
        for i, line in enumerate(lines):
            if not line or not rx.search(line):
                continue
            lo, hi = max(0, i - radius), min(len(lines), i + radius + 1)
            snippet = "\n".join(x for x in lines[lo:hi] if x)
            hits.append({"code": code.upper(), "line": i + 1, "snippet": snippet[:3500]})
            count += 1
            if count >= max_each:
                break
    return hits


def extract_pdf_text(path: Path) -> tuple[str, int, str | None]:
    try:
        reader = PdfReader(str(path))
        pages = []
        for p in reader.pages:
            try:
                pages.append(p.extract_text() or "")
            except Exception as e:
                pages.append(f"[PAGE_EXTRACTION_ERROR {type(e).__name__}]")
        return clean_text("\n\n".join(pages)), len(reader.pages), None
    except Exception as e:
        return "", 0, f"{type(e).__name__}: {e}"


def normalize_penedes_offer_page(text: str) -> str:
    """Restore field boundaries lost in pypdf's concatenated Penedes form text.

    Example: `plaça19764334Especialitat627` must become
    `plaça 19764334 Especialitat 627` before positional matching.
    """
    text = re.sub(
        r"(pla[cç]a)\s*((?:19|20)\d{6})\s*(Especialitat)",
        r"\1 \2 \3", text, flags=re.I,
    )
    text = re.sub(
        r"(Especialitat)\s*(507|627|F57|F87)(?=\s|$)",
        r"\1 \2", text, flags=re.I,
    )
    return text


def penedes_offer_page_hits(path: Path) -> list[dict]:
    """Extract each official Penedes offer sheet independently.

    One PDF page corresponds to one placement. Never allow a target hit to
    inherit the numeric ID of the previous or following page.
    """
    reader = PdfReader(str(path))
    all_hits: list[dict] = []
    for page_no, page in enumerate(reader.pages, 1):
        normalized = normalize_penedes_offer_page(page.extract_text() or "")
        for hit in context_hits(normalized):
            all_hits.append({**hit, "page": page_no})
    return all_hits


def save_raw(territory: str, role: str, url: str, content: bytes, ext: str) -> Path:
    td = RUN_DIR / safe_slug(territory)
    td.mkdir(parents=True, exist_ok=True)
    short = hashlib.sha256(url.encode()).hexdigest()[:12]
    path = td / f"{role}-{short}{ext}"
    path.write_bytes(content)
    return path


def compare_freshness(current: dict, previous: dict | None) -> tuple[str, list[str]]:
    reasons = []
    if current.get("error"):
        return "PARCIAL", [current["error"]]
    prev_fp = (previous or {}).get("fingerprint") or {}
    cur_fp = current.get("fingerprint") or {}
    prev_anchors = prev_fp.get("anchors") or {}
    cur_anchors = cur_fp.get("anchors") or {}
    regressed = False
    for kind, p in prev_anchors.items():
        c = cur_anchors.get(kind)
        if not c:
            reasons.append(f"àncora prèvia {kind} no observable en aquesta estructura")
            continue
        if tuple(c.get("rank", [])) < tuple(p.get("rank", [])):
            regressed = True
            reasons.append(f"{kind} regressa: {c.get('raw')} < {p.get('raw')}")
    if regressed:
        return "CACHE OBSOLETA", reasons
    if current.get("offer_docs_ok", 0) == 0 and current.get("target_hits", 0) == 0:
        t = (current.get("landing_text_excerpt") or "").lower()
        if "no hi ha places" in t or "no hi ha cap plaça" in t or "sense places" in t:
            return "FRESC", ["pàgina viva indica explícitament que no hi ha places"]
        return "PARCIAL", reasons + ["cap document d'oferta parsejat ni coincidència objectiu"]
    return "FRESC", reasons


def candidate_landing_urls(slug: str, kind: str) -> list[str]:
    root = f"https://educacio.gencat.cat/ca/departament/serveis-territorials/{slug}/personal-docent/"
    if slug == "catalunya-central" and kind == "secondary":
        return [
            root + "provisio-vacants-SPD/",
            root + "nomenaments-telematics/dificil-cobertura/secundaria/",
            root + "nomenaments-telematics/dificil-cobertura/",
        ]
    if kind == "secondary":
        return [
            root + "nomenaments-telematics/dificil-cobertura/secundaria/",
            root + "nomenaments-telematics/dificil-cobertura/",
            root + "provisio-vacants-SPD/",
        ]
    return [
        root + "nomenaments-telematics/dificil-cobertura/oferta-moduls-pfi-ife/",
        root + "nomenaments-telematics/dificil-cobertura/oferta-moduls-pfi-ptt/",
        root + "nomenaments-telematics/dificil-cobertura/pfi/",
    ]


def fetch_first_live(fetcher: DirectFetcher, urls: Iterable[str]) -> tuple[FetchMeta, bytes | None, str]:
    urls = list(urls)
    last_meta = None
    for u in urls:
        meta, content = fetcher.get(u)
        last_meta = meta
        if content and meta.status_code and 200 <= meta.status_code < 300:
            return meta, content, u
    assert last_meta is not None
    return last_meta, None, urls[0]


def scrape_document(fetcher: DirectFetcher, territory: str, doc: dict) -> dict:
    meta, content = fetcher.get(doc["url"])
    out = {"url": doc["url"], "label": doc.get("text", ""), "role": doc.get("role", "document"), "fetch": asdict(meta)}
    if not content:
        out["error"] = meta.error or f"HTTP {meta.status_code}"
        return out
    ctype = (meta.content_type or "").lower()
    is_pdf = "pdf" in ctype or doc["url"].lower().split("?")[0].endswith(".pdf")
    if is_pdf:
        if meta.error and meta.error.startswith("PDF_CACHE_"):
            out["error"] = meta.error
        p = save_raw(territory, out["role"], doc["url"], content, ".pdf")
        text, pages, err = extract_pdf_text(p)
        out["pages"] = pages
        if err: out["parse_error"] = err
        out["anchors"] = extract_anchors(text)
        if (territory == "Penedès"
                and "PEN-SEC-dificil-cobertura-oferta-vacants.pdf" in doc["url"]):
            # This rolling PDF is one placement per page; pypdf often glues
            # `plaça19764334Especialitat627` into a single word.
            out["target_hits"] = penedes_offer_page_hits(p)
        else:
            out["target_hits"] = context_hits(text)
        out["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
        out["text_excerpt"] = text[:5000]
        return out
    html = decode_html(content, meta.content_type)
    text = html_to_text(html)
    save_raw(territory, out["role"], doc["url"], content, ".html")
    out["anchors"] = extract_anchors(text)
    out["target_hits"] = context_hits(text)
    out["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    out["text_excerpt"] = text[:5000]
    return out


def merge_anchors(items: Iterable[dict]) -> dict:
    merged: dict[str, dict] = {}
    for item in items:
        for kind, val in (item.get("anchors") or {}).items():
            old = merged.get(kind)
            if old is None or tuple(val.get("rank", [])) > tuple(old.get("rank", [])):
                merged[kind] = val
    return merged


def scrape_territory(fetcher: DirectFetcher, name: str, slug: str, previous: dict | None) -> dict:
    log(f"{name}: landing pages")
    landings, docs, landing_texts = [], [], []
    for kind in ("secondary", "pfi"):
        urls = candidate_landing_urls(slug, kind)
        meta, content, logical = fetch_first_live(fetcher, urls)
        landing = {"kind": kind, "logical_url": logical, "fetch": asdict(meta)}
        if not content:
            landing["error"] = meta.error or f"HTTP {meta.status_code}"
            landings.append(landing)
            continue
        html = decode_html(content, meta.content_type)
        text = html_to_text(html)
        links = extract_links(meta.final_url or logical, html)
        selected = likely_relevant_links(links, max_links=8 if kind == "secondary" else 6)
        landing.update({
            "update_date": extract_update_date(text), "anchors": extract_anchors(text),
            "target_hits": context_hits(text), "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "text_excerpt": text[:7000], "selected_links": selected,
        })
        landing_texts.append(text); landings.append(landing); docs.extend(selected)
    # The Penedes rolling secondary-offer PDF is a known authoritative source.
    # Landing-page ranking/limits must never silently omit it.
    if slug == "penedes":
        docs.append({
            "url": "https://educacio.gencat.cat/web/.content/home/departament/serveis-territorials/penedes/personal-docent/nomenaments-telematics/dificil-cobertura/secundaria/PEN-SEC-dificil-cobertura-oferta-vacants.pdf",
            "text": "Penedès oferta vacants secundària PDF oficial",
            "role": "offer",
        })
    unique, seen = [], set()
    for d in docs:
        u = d["url"].split("#")[0]
        if u in seen: continue
        seen.add(u); unique.append(d)
    def doc_score(d: dict) -> int:
        s = (d.get("text", "") + " " + d.get("url", "")).lower(); n = 0
        if any(re.search(rf"(?<![a-z0-9]){c.lower()}(?![a-z0-9])", s) for c in TARGET_CODES): n += 20
        n += {"offer":12,"result":10,"pfi":9}.get(d.get("role"),0)
        if d["url"].lower().split("?")[0].endswith(".pdf"): n += 5
        return n
    unique.sort(key=doc_score, reverse=True)
    # Keep mandatory official rolling sources even if they rank below the cap.
    mandatory = [d for d in unique if slug == "penedes" and "PEN-SEC-dificil-cobertura-oferta-vacants.pdf" in d["url"]]
    selected_docs = unique[:12]
    selected_urls = {d["url"] for d in selected_docs}
    selected_docs.extend(d for d in mandatory if d["url"] not in selected_urls)
    document_records = []
    for d in selected_docs:
        log(f"{name}: {d.get('role')} {d['url']}")
        document_records.append(scrape_document(fetcher, name, d))
    all_sources = landings + document_records
    anchors = merge_anchors(all_sources)
    total_hits = sum(len(x.get("target_hits") or []) for x in all_sources)
    offers_ok = sum(1 for x in document_records if x.get("role") in {"offer","pfi"} and not x.get("error") and (x.get("pages",1) or 1)>0)
    if slug == "penedes":
        mandatory_records = [x for x in document_records if "PEN-SEC-dificil-cobertura-oferta-vacants.pdf" in x.get("url", "")]
        if not mandatory_records or any(x.get("error") or x.get("parse_error") for x in mandatory_records):
            log("Penedès mandatory official secondary PDF missing or unreadable")
            offers_ok = 0
    combined_landing = "\n".join(landing_texts)
    cur = {
        "name": name, "slug": slug, "provider": "direct-http",
        "checked_at": datetime.now(TZ).isoformat(timespec="seconds"),
        "landings": landings, "documents": document_records, "target_hits": total_hits,
        "offer_docs_ok": offers_ok, "landing_text_excerpt": combined_landing[:5000],
        "fingerprint": {
            "anchors": anchors,
            "landing_update_dates": [x.get("update_date") for x in landings if x.get("update_date")],
            "document_hashes": [x.get("fetch",{}).get("sha256") for x in document_records if x.get("fetch",{}).get("sha256")],
            "pages": [{"url":x.get("url"),"pages":x.get("pages")} for x in document_records if x.get("pages") is not None],
        },
    }
    if not any(not l.get("error") for l in landings): cur["error"] = "No s'ha pogut recuperar cap pàgina oficial candidata"
    status, reasons = compare_freshness(cur, previous); cur["freshness"] = status; cur["freshness_notes"] = reasons
    return cur


def playwright_edubcn(previous: dict | None, fetcher: DirectFetcher) -> dict:
    record = {"name":"EDUBCN","provider":"playwright-direct","checked_at":datetime.now(TZ).isoformat(timespec="seconds"),"url":EDUBCN,"searches":{},"documents":[]}
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        record["error"] = f"Playwright no disponible: {e}"; record["freshness"] = "PARCIAL"; return record
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=USER_AGENT, locale="ca-ES", extra_http_headers={"Cache-Control":"no-cache, no-store, max-age=0","Pragma":"no-cache"})
            live_url = add_param(EDUBCN, "nocache", str(int(time.time()*1000)))
            page.goto(live_url, wait_until="networkidle", timeout=90000); page.wait_for_timeout(1200)
            body_text = clean_text(page.locator("body").inner_text())
            rows_global = [clean_text(x) for x in page.locator("table tbody tr").all_inner_texts()]
            links = page.locator("a").evaluate_all("""els => els.map(a => ({text:(a.innerText||'').trim(), url:a.href||''})).filter(x => x.url)""")
            record["global"] = {"url":page.url,"body_sha256":hashlib.sha256(body_text.encode()).hexdigest(),"anchors":extract_anchors(body_text+"\n"+"\n".join(rows_global)),"row_count":len(rows_global),"row_samples":rows_global[:40],"target_hits":context_hits(body_text)}
            search_inputs = page.locator("input[type=search]"); visible_idx = None
            for i in range(search_inputs.count()):
                if search_inputs.nth(i).is_visible(): visible_idx = i; break
            for term in ("507","F57","627","F87","informàtica","sistemes","PFI"):
                if visible_idx is None:
                    record["searches"][term] = {"available":False,"rows":[]}; continue
                inp=search_inputs.nth(visible_idx); inp.fill(term); page.wait_for_timeout(450)
                rows=[clean_text(x) for x in page.locator("table tbody tr").all_inner_texts()]
                record["searches"][term]={"available":True,"row_count":len(rows),"rows":rows[:100],"anchors":extract_anchors("\n".join(rows))}
            if visible_idx is not None: search_inputs.nth(visible_idx).fill(""); page.wait_for_timeout(300)
            cand=[]
            for x in links:
                u=x.get("url",""); t=x.get("text",""); s=(u+" "+t).lower()
                if not u.startswith("http") or "edubcn.cat" not in urlparse(u).netloc: continue
                if any(k in s for k in ("convocat","resultat","rcs_gene/seleccio",".pdf")):
                    cand.append({"url":u,"text":t,"role":"result" if "result" in s else "offer"})
            seen=set(); uniq=[]
            for d in cand:
                if d["url"] in seen: continue
                seen.add(d["url"]); uniq.append(d)
            browser.close()
        for d in uniq[:24]: record["documents"].append(scrape_document(fetcher,"EDUBCN",d))
        all_sources=[record.get("global",{})]+list(record.get("searches",{}).values())+record["documents"]
        anchors=merge_anchors(all_sources)
        record["fingerprint"]={"anchors":anchors,"row_count":record.get("global",{}).get("row_count"),"document_hashes":[x.get("fetch",{}).get("sha256") for x in record["documents"] if x.get("fetch",{}).get("sha256")]}
        record["target_hits"]=len(record.get("global",{}).get("target_hits") or [])+sum(len(x.get("target_hits") or []) for x in record["documents"])
        record["offer_docs_ok"]=sum(1 for x in record["documents"] if x.get("role")=="offer" and not x.get("error"))
        rows=record.get("global",{}).get("row_count",0)
        if rows<=0: record["error"]="Llistat dinàmic no enumerable (0 files visibles)"
        status,reasons=compare_freshness(record,previous)
        if rows<=0: status="PARCIAL"
        record["freshness"]=status; record["freshness_notes"]=reasons
        return record
    except Exception as e:
        record["error"]=f"{type(e).__name__}: {e}"; record["freshness"]="PARCIAL"; return record


def load_previous() -> dict:
    if not STATE_FILE.exists(): return {}
    try: return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception: return {}


def summarize_hits(rec: dict) -> dict[str,int]:
    counts={c:0 for c in TARGET_CODES}; sources=[]
    sources+=rec.get("landings",[]); sources+=rec.get("documents",[])
    if rec.get("global"): sources.append(rec["global"])
    for s in rec.get("searches",{}).values(): sources.append(s)
    for src in sources:
        for h in src.get("target_hits") or []:
            c=h.get("code","").upper()
            if c in counts: counts[c]+=1
    for term,data in rec.get("searches",{}).items():
        if term.upper() in counts:
            counts[term.upper()]+=sum(1 for r in data.get("rows",[]) if re.search(rf"(?<![A-Z0-9]){re.escape(term)}(?![A-Z0-9])",r,re.I))
    return counts


def report_markdown(state: dict) -> str:
    lines=[f"# Passada directa {state['generated_at']}","","Font: HTTP directe a Generalitat + Playwright directe a EDUBCN. Sense Tavily/Firecrawl.","","| Àmbit | Frescor | 507 hits | F57 hits | 627 hits | F87 hits | Àncora global |","|---|---|---:|---:|---:|---:|---|"]
    for name,rec in state["territories"].items():
        counts=summarize_hits(rec); anchors=rec.get("fingerprint",{}).get("anchors",{}); anchor_text=", ".join(v.get("raw","") for _,v in sorted(anchors.items())) or "—"
        lines.append(f"| {name} | **{rec.get('freshness','PARCIAL')}** | {counts['507']} | {counts['F57']} | {counts['627']} | {counts['F87']} | {anchor_text} |")
    lines += ["","## Notes de frescor"]
    for name,rec in state["territories"].items():
        notes=rec.get("freshness_notes") or []; err=rec.get("error")
        if err or notes: lines.append(f"- **{name}**: "+"; ".join(([err] if err else [])+notes))
    lines += ["","## Ús","Aquest fitxer és una síntesi tècnica. Per redactar la llista general i la shortlist, cal llegir `latest.json`, aplicar RESULTAT/cobertura i la regla de caducitat per `Fins a`."]
    return "\n".join(lines)+"\n"


def main() -> int:
    STATE_DIR.mkdir(parents=True,exist_ok=True); HISTORY_DIR.mkdir(parents=True,exist_ok=True); RUN_DIR.mkdir(parents=True,exist_ok=True)
    previous=load_previous(); previous_territories=previous.get("territories",{}); fetcher=DirectFetcher()
    state={"schema_version":1,"generated_at":NOW.isoformat(timespec="seconds"),"run_id":RUN_ID,"source_strategy":"direct-http+cachebuster+validators+sha256; playwright-direct-edubcn","paid_crawlers_used":False,"territories":{}}
    for name,slug in ST:
        try: state["territories"][name]=scrape_territory(fetcher,name,slug,previous_territories.get(name))
        except Exception as e: state["territories"][name]={"name":name,"provider":"direct-http","checked_at":datetime.now(TZ).isoformat(timespec="seconds"),"freshness":"PARCIAL","error":f"{type(e).__name__}: {e}"}
    log("EDUBCN: llistat dinàmic"); state["territories"]["EDUBCN"]=playwright_edubcn(previous_territories.get("EDUBCN"),fetcher)
    state_json=json.dumps(state,ensure_ascii=False,indent=2,sort_keys=False)+"\n"; STATE_FILE.write_text(state_json,encoding="utf-8"); (HISTORY_DIR/f"{RUN_ID}.json").write_text(state_json,encoding="utf-8"); REPORT_FILE.write_text(report_markdown(state),encoding="utf-8")
    fresh=sum(1 for r in state["territories"].values() if r.get("freshness")=="FRESC"); stale=sum(1 for r in state["territories"].values() if r.get("freshness")=="CACHE OBSOLETA"); partial=len(state["territories"])-fresh-stale
    (STATE_DIR/"health.json").write_text(json.dumps({"generated_at":state["generated_at"],"fresh":fresh,"partial":partial,"cache_obsoleta":stale,"total":len(state["territories"])},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    log(f"Fi: FRESC={fresh} PARCIAL={partial} CACHE_OBSOLETA={stale}"); return 0


if __name__ == "__main__": raise SystemExit(main())

