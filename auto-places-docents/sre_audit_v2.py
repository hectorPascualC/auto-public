#!/usr/bin/env python3
"""Read-only GitHub-only SRE audit: green workflow != successful scan."""
import datetime as dt
import json
import os
import pathlib
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

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


def expected_nominal_slot(now):
    """Most recent weekday slot whose 45-minute completion window is over."""
    local = now.astimezone(ZoneInfo("Europe/Madrid"))
    for offset in range(8):
        day = (local - dt.timedelta(days=offset)).date()
        if day.weekday() >= 5:
            continue
        for hour in (17, 13, 11, 8):
            nominal = dt.datetime.combine(day, dt.time(hour), tzinfo=ZoneInfo("Europe/Madrid"))
            if local >= nominal + dt.timedelta(minutes=45):
                return nominal.strftime("%Y-%m-%dT%H:00")
    raise RuntimeError("No nominal slot found")


def github_get(relative_path, token):
    request = urllib.request.Request(
        API + relative_path,
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "auto-public-github-sre"})
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.load(response)


def confirm_scan(receipt, token):
    """Require actual scan steps; an omitted/skipped workflow is never PASS."""
    if not token:
        return "BLOCKED", "GitHub read token missing"
    run_id = str(receipt.get("scan_run_id", ""))
    if not run_id.isdigit():
        return "FAIL", "Invalid or absent GitHub run ID"
    try:
        run = github_get("/actions/runs/" + run_id, token)
        jobs = github_get("/actions/runs/" + run_id + "/jobs?per_page=100", token)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return "BLOCKED", "Cannot read GitHub run/jobs"
    if run.get("conclusion") != "success":
        return "FAIL", "Recorded monitor run did not succeed"
    if run.get("path", "").split("@")[0] != ".github/workflows/auto-places-docents.yml":
        return "FAIL", "Run belongs to another workflow"
    if receipt.get("trigger_sha") and receipt["trigger_sha"] != run.get("head_sha"):
        return "FAIL", "Run commit SHA differs from slot receipt"
    required = ("Fetch official sources", "Revalidate EDUBCN dynamically",
                "Validate final state and finalize history", "Persist compact state safely")
    for job in jobs.get("jobs", []):
        if job.get("name") != "monitor" or job.get("conclusion") != "success":
            continue
        steps = {s.get("name"): s.get("conclusion") for s in job.get("steps", [])}
        if all(steps.get(name) == "success" for name in required):
            return "PASS", "Required fetch, final validation and persistence completed"
    return "FAIL", "No successful job with all required scan steps"


health = read_json("health.json")
consumer = read_json("consumer.json")
ledger = read_json("slot-ledger.json")
source_audit = read_json("audit.json")
if not all(isinstance(item, dict) for item in (health, consumer, ledger, source_audit)):
    check("Canonical files", "BLOCKED", "Missing or invalid JSON")
health, consumer, ledger, source_audit = (item or {} for item in (health, consumer, ledger, source_audit))
good = (health.get("audit_status") == "PASS"
        and all(health.get(x) == 12 for x in ("fresh", "total", "presence_authoritative"))
        and all(health.get(x) == 0 for x in ("partial", "cache_obsoleta", "audit_errors")))
check("12 official sources", "PASS" if good else "FAIL", "12/12 authoritative; zero errors")
audit_good = (source_audit.get("status") == "PASS"
              and source_audit.get("generated_at") == health.get("audit_at"))
check("Source audit", "PASS" if audit_good else "FAIL", "PASS + matching audit timestamp")
coherent = (bool(consumer.get("run_id"))
            and consumer.get("generated_at") == health.get("generated_at"))
check("Consumer snapshot", "PASS" if coherent else "FAIL", "Matching run/timestamp required")

slot = expected_nominal_slot(NOW)
receipt = (ledger.get("slots") or {}).get(slot, {})
generated, audited = timestamp(health.get("generated_at")), timestamp(health.get("audit_at"))
nominal = dt.datetime.strptime(slot, "%Y-%m-%dT%H:00").replace(tzinfo=ZoneInfo("Europe/Madrid")).astimezone(dt.timezone.utc)
valid = (
    isinstance(receipt, dict) and generated is not None and audited is not None
    and nominal - dt.timedelta(minutes=25) <= generated < nominal + dt.timedelta(minutes=45)
    and generated <= audited <= generated + dt.timedelta(minutes=35)
    and receipt.get("status") == "PASS"
    and receipt.get("snapshot_run_id") == consumer.get("run_id")
    and receipt.get("generated_at") == health.get("generated_at")
    and receipt.get("audit_at") == health.get("audit_at")
    and coherent and good and audit_good
)
check("Latest due slot receipt", "PASS" if valid else "FAIL",
      "expected=" + slot + "; requires exact audited receipt")
check("Health freshness", "PASS" if valid else "FAIL",
      "Freshness is tied to the due slot, not an arbitrary 24-hour threshold")

if valid:
    step_status, step_detail = confirm_scan(receipt, os.getenv("GITHUB_TOKEN", ""))
    check("Actual GitHub scan steps", step_status, step_detail)
else:
    check("Actual GitHub scan steps", "BLOCKED", "No matching due-slot receipt")

overall = ("FAIL" if any(x["status"] == "FAIL" for x in checks)
           else "BLOCKED" if any(x["status"] == "BLOCKED" for x in checks)
           else "PASS")

result = {"audit_version": 2, "generated_at": NOW.isoformat(), "expected_slot": slot,
          "overall": overall, "checks": checks}
pathlib.Path("sre-audit-report.json").write_text(
    json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
with open(os.environ.get("GITHUB_STEP_SUMMARY", os.devnull), "a", encoding="utf-8") as out:
    out.write(f"## AUTO-PUBLIC V2 SRE audit: {overall}\n\n")
    for c in checks:
        out.write(f"- **{c['status']}** {c['name']}: {c['detail']}\n")
print(f"SRE audit {overall}: " + ", ".join(f"{c['name']}={c['status']}" for c in checks))
if overall != "PASS":
    raise SystemExit(1 if overall == "FAIL" else 2)
