#!/usr/bin/env python3
"""Public-safe diagnostics for the official Penedes rolling secondary vacancies PDF.

Never publish full raw PDFs or extracted text. Only HTTP metadata, hashes, page
counts and Boolean matches for public vacancy identifiers are persisted.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
import requests
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "state"
URL = ("https://educacio.gencat.cat/web/.content/home/departament/"
       "serveis-territorials/penedes/personal-docent/nomenaments-telematics/"
       "dificil-cobertura/secundaria/PEN-SEC-dificil-cobertura-oferta-vacants.pdf")
IDS = ("19742262", "19764334")
CODES = ("507", "627", "F57", "F87")


def analyse_pdf(data: bytes) -> dict:
    result = {
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "pdf_signature": data.startswith(b"%PDF-"),
    }
    try:
        reader = PdfReader(io.BytesIO(data))
        result["pages"] = len(reader.pages)
        page_results = []
        text_chars = 0
        for n, page in enumerate(reader.pages, 1):
            txt = page.extract_text() or ""
            text_chars += len(txt)
            codes = [c for c in CODES if re.search(r"Especialitat\\s*" + c + r"(?!\\d)", txt, re.I) or re.search(r"(?<![A-Za-z0-9])" + c + r"(?![A-Za-z0-9])", txt, re.I)]
            ids = [i for i in IDS if i in txt]
            if codes or ids:
                page_results.append({"page": n, "codes": codes, "reference_ids": ids})
        result["text_chars"] = text_chars
        result["target_pages"] = page_results
        result["reference_ids_found"] = {i: any(i in p["reference_ids"] for p in page_results) for i in IDS}
    except Exception as exc:
        result["extract_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return result


def main() -> None:
    output = {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "git_sha": os.environ.get("GITHUB_SHA"),
        "source_url": URL,
        "privacy": "metadata-only: no document bodies or extracted text stored",
    }
    try:
        state = json.loads((STATE / "latest.json").read_text(encoding="utf-8"))
        output["run_id"] = state.get("run_id")
        territory = state.get("territories", {}).get("Penedès", {})
        output["territory_freshness"] = territory.get("freshness")
        output["territory_target_hits"] = territory.get("target_hits")
        matched = [d for d in territory.get("documents", []) if d.get("url", "").split("?")[0] == URL]
        output["official_pdf_in_monitor"] = bool(matched)
        if matched:
            doc = matched[0]
            f = doc.get("fetch") or {}
            output["monitor_document"] = {
                "role": doc.get("role"), "error": doc.get("error"),
                "parse_error": doc.get("parse_error"),
                "status": f.get("status_code"), "final_url": f.get("final_url"),
                "etag": f.get("etag"), "last_modified": f.get("last_modified"),
                "content_type": f.get("content_type"),
                "bytes": f.get("content_length"), "sha256": f.get("sha256"),
                "cache_error": f.get("error"),
                "pages": doc.get("pages"),
                "target_hit_counts": {c: sum(1 for h in doc.get("target_hits", [])
                                             if h.get("code") == c) for c in CODES},
                "reference_ids_in_excerpt": {i: i in (doc.get("text_excerpt") or "") for i in IDS},
            }
            short = hashlib.sha256(URL.encode()).hexdigest()[:12]
            role = doc.get("role", "offer")
            raw = ROOT / "runs" / str(state.get("run_id")) / "penedes" / f"{role}-{short}.pdf"
            output["monitor_raw_present"] = raw.is_file()
            if raw.is_file():
                output["monitor_raw_pdf"] = analyse_pdf(raw.read_bytes())
        else:
            output["error"] = "OFFICIAL_PDF_NOT_PROCESSED"
    except Exception as exc:
        output["state_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"

    # Independent requests to the exact official PDF, without the monitor's
    # cache-buster sequence, for distinguishing stale CDN data from bad parsing.
    nonce = str(int(datetime.now(timezone.utc).timestamp()))
    variants = [
        ("canonical", URL),
        ("no_cache_query", URL + "?" + urlencode({"diagnostic": nonce})),
    ]
    output["independent_http_probes"] = []
    for label, request_url in variants:
        item = {"variant": label}
        try:
            response = requests.get(
                request_url,
                headers={"User-Agent": "Mozilla/5.0 AUTO-places-diagnostic/1.0",
                         "Cache-Control": "no-cache, no-store, max-age=0",
                         "Pragma": "no-cache"},
                timeout=(15, 60),
            )
            item.update({
                "status": response.status_code,
                "content_type": response.headers.get("Content-Type"),
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
                "cache_control": response.headers.get("Cache-Control"),
                "age": response.headers.get("Age"),
                "final_url": response.url,
            })
            if response.ok and response.content:
                item["pdf"] = analyse_pdf(response.content)
        except requests.RequestException as exc:
            item["request_error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        output["independent_http_probes"].append(item)

    path = STATE / "penedes_diagnostic.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("[PENEDES_DIAGNOSTIC] " + json.dumps({
        "run_id": output.get("run_id"),
        "official_pdf_in_monitor": output.get("official_pdf_in_monitor"),
        "monitor_pdf": output.get("monitor_raw_pdf", {}),
        "probes": [{"variant": p["variant"], "status": p.get("status"),
                    "sha256": (p.get("pdf") or {}).get("sha256"),
                    "reference_ids": (p.get("pdf") or {}).get("reference_ids_found")}
                   for p in output["independent_http_probes"]],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
