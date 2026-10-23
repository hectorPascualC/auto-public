#!/usr/bin/env python3
"""Read-only SRE audit for AUTO-PUBLIC V2. No dispatch, mutation or secret output."""
import datetime as dt
import json
import os
import pathlib
import urllib.error
import urllib.request

ROOT = pathlib.Path("auto-places-docents/state")
REPO = os.getenv("GITHUB_REPOSITORY", "hectorPascualC/auto-public")
API = "https://api.github.com/repos/" + REPO
NOW = dt.datetime.now(dt.timezone.utc)
checks = []

def check(name, status, detail):
    checks.append({"name": name, "status": status, "detail": detail})

def read_json(name):
    p = ROOT / name
    if not p.exists():
        check(name, "BLOCKED", "File not present")
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        check(name, "FAIL", "Unreadable JSON")
        return None

def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except ValueError:
        return None

health = read_json("health.json")
consumer = read_json("consumer.json")
ledger = read_json("slot-ledger.json")
if isinstance(health, dict):
    good = (health.get("audit_status") == "PASS" and health.get("fresh") == 12
            and health.get("total") == 12 and health.get("presence_authoritative") == 12
            and health.get("partial") == 0 and health.get("cache_obsoleta") == 0
            and health.get("audit_errors") == 0)
    check("12 official sources", "PASS" if good else "FAIL",
          "12/12 with zero errors" if good else "Health thresholds not met")
    generated = timestamp(health.get("generated_at"))
    age = round((NOW - generated).total_seconds() / 60) if generated else None
    check("Health freshness", "PASS" if age is not None and -5 <= age <= 1440 else "FAIL",
          f"age_minutes={age}" if age is not None else "Missing timestamp")
if isinstance(consumer, dict) and isinstance(health, dict):
    coherent = (consumer.get("generated_at") == health.get("generated_at")
                and bool(consumer.get("run_id")))
    check("Consumer snapshot", "PASS" if coherent else "FAIL",
          "Matches health" if coherent else "Timestamp/run mismatch")
if isinstance(ledger, dict):
    slots = ledger.get("slots")
    if isinstance(slots, dict) and slots:
        latest = max(slots)
        receipt = slots[latest]
        valid = (isinstance(receipt, dict) and receipt.get("status") == "PASS"
                 and receipt.get("snapshot_run_id") == (consumer or {}).get("run_id")
                 and receipt.get("generated_at") == (health or {}).get("generated_at"))
        check("Latest slot receipt", "PASS" if valid else "FAIL", f"slot={latest}")
    else:
        check("Latest slot receipt", "BLOCKED", "No slot receipts")

token = os.getenv("GITHUB_TOKEN", "")
if token:
    try:
        req = urllib.request.Request(
            API + "/actions/workflows/deploy-controller-v2.yml/runs?per_page=10",
            headers={"Authorization": "Bearer " + token,
                     "Accept": "application/vnd.github+json",
                     "User-Agent": "auto-public-sre-audit"})
        with urllib.request.urlopen(req, timeout=15) as response:
            runs = json.load(response).get("workflow_runs", [])
        completed = next((r for r in runs if r.get("status") == "completed"), None)
        if completed:
            check("Latest controller deployment workflow",
                  "PASS" if completed.get("conclusion") == "success" else "FAIL",
                  f"run_id={completed.get('id')} conclusion={completed.get('conclusion')}")
        else:
            check("Latest controller deployment workflow", "BLOCKED", "No completed runs")
    except (urllib.error.URLError, ValueError, TimeoutError):
        check("Latest controller deployment workflow", "BLOCKED", "GitHub API unavailable")
else:
    check("Latest controller deployment workflow", "BLOCKED", "No read token")

check("Cloudflare cron -> Worker -> DO", "BLOCKED",
      "Requires authenticated Cloudflare event evidence; not inferred from deploy success")
check("DO -> workflow_dispatch", "BLOCKED",
      "Requires event-correlated Cloudflare/GitHub run evidence")
overall = ("FAIL" if any(x["status"] == "FAIL" for x in checks)
           else "PASS" if all(x["status"] == "PASS" for x in checks) else "BLOCKED")
result = {"audit_version": 1, "generated_at": NOW.isoformat(),
          "overall": overall, "checks": checks}
pathlib.Path("sre-audit-report.json").write_text(
    json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
with open(os.environ.get("GITHUB_STEP_SUMMARY", os.devnull), "a", encoding="utf-8") as out:
    out.write(f"## AUTO-PUBLIC V2 SRE audit: {overall}\n\n")
    for c in checks:
        out.write(f"- **{c['status']}** {c['name']}: {c['detail']}\n")
print(f"SRE audit {overall}: " + ", ".join(f"{c['name']}={c['status']}" for c in checks))
if overall == "FAIL":
    raise SystemExit(1)
