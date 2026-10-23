#!/usr/bin/env python3
"""One-weekend, fail-closed Cloudflare cron probe (no Worker source changes).

The EXTRA trigger only runs Saturday/Sunday. The deployed controller intentionally
returns IGNORED for weekend events; hence no GitHub dispatch or source scan.
It tests the Cron -> Worker path. Exact slot -> DO -> GitHub remains BLOCKED until
independent end-to-end evidence exists. Restore job removes only this known trigger.
"""
from __future__ import annotations
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

WORKER = "auto-public-controller-v2"
PRIMARY = "35,47 6,7,8,9,11,12,13,14 * * 1-5"
WEEKEND = "35,47 6-20 * * 6,0"
START = dt.date(2026, 10, 23)
DAYS = {dt.date(2026, 10, 24), dt.date(2026, 10, 25)}
RESTORE = dt.date(2026, 10, 26)

def mode_for(now: dt.datetime, event: str) -> str:
    now = now.astimezone(dt.timezone.utc)
    if event == "push" and now.date() == START:
        return "install"
    if event == "schedule" and now.date() in DAYS:
        return "verify"
    if event == "schedule" and now.date() == RESTORE:
        return "restore"
    return "no_action"

def extract_schedules(obj):
    if not isinstance(obj, dict) or obj.get("success") is not True:
        raise RuntimeError("cloudflare_response_not_success")
    data = obj.get("result")
    if not isinstance(data, dict) or not isinstance(data.get("schedules"), list):
        raise RuntimeError("cloudflare_schedule_unexpected_schema")
    crons = [x.get("cron") for x in data["schedules"] if isinstance(x, dict)]
    if len(crons) != len(data["schedules"]) or any(not isinstance(x, str) for x in crons):
        raise RuntimeError("cloudflare_schedule_unexpected_schema")
    return crons

def safe_expected(crons):
    return len(crons) == len(set(crons)) and set(crons) in (
        {PRIMARY}, {PRIMARY, WEEKEND}
    )

class Cloudflare:
    def __init__(self, account, token):
        if not account or not token:
            raise RuntimeError("cloudflare_credentials_unavailable")
        self.base = f"https://api.cloudflare.com/client/v4/accounts/{account}/workers/scripts/{WORKER}"
        self.token = token

    def call(self, suffix, method="GET", payload=None):
        req = urllib.request.Request(
            self.base + suffix,
            method=method,
            data=json.dumps(payload).encode("utf-8") if payload is not None else None,
            headers={
                "Authorization": "Bearer " + self.token,
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "auto-public-v2-weekend-guard",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as res:
                obj = json.load(res)
            if not isinstance(obj, dict) or obj.get("success") is not True:
                raise RuntimeError("cloudflare_api_error")
            return obj
        except urllib.error.HTTPError as ex:
            raise RuntimeError("cloudflare_http_" + str(ex.code)) from None
        except (urllib.error.URLError, ValueError, TimeoutError):
            raise RuntimeError("cloudflare_network_or_schema_error") from None

def verify_config(settings):
    bindings = settings.get("result", {}).get("bindings", [])
    if not isinstance(bindings, list):
        raise RuntimeError("cloudflare_settings_unexpected_schema")
    enabled = any(x.get("name") == "DISPATCH_ENABLED" and x.get("text") == "true"
                  for x in bindings if isinstance(x, dict))
    durable = any(x.get("name") == "SLOT_COORDINATOR"
                  for x in bindings if isinstance(x, dict))
    secret = any(x.get("name") == "GITHUB_TOKEN" and x.get("type") == "secret_text"
                 for x in bindings if isinstance(x, dict))
    if not (enabled and durable and secret):
        raise RuntimeError("cloudflare_live_preconditions_mismatch")
    return True

def transition(current, mode):
    if not safe_expected(current):
        raise RuntimeError("unexpected_schedule_configuration; no mutation")
    expected = [PRIMARY] if mode == "restore" else [PRIMARY, WEEKEND]
    if mode == "verify":
        if set(current) != {PRIMARY, WEEKEND}:
            raise RuntimeError("weekend_schedule_missing")
        return None
    if set(current) == set(expected):
        return None
    return [{"cron": x} for x in expected]

def run(mode, client):
    settings = client.call("/settings")
    verify_config(settings)
    existing = extract_schedules(client.call("/schedules"))
    payload = transition(existing, mode)
    if payload is not None:
        updated = extract_schedules(client.call("/schedules", "PUT", payload))
        if set(updated) != {x["cron"] for x in payload} or len(updated) != len(payload):
            raise RuntimeError("schedule_put_response_mismatch")
    after = extract_schedules(client.call("/schedules"))
    wanted = {PRIMARY} if mode == "restore" else {PRIMARY, WEEKEND}
    if set(after) != wanted or len(after) != len(wanted):
        raise RuntimeError("schedule_readback_mismatch")
    return {"phase": mode, "status": "PASS_CONFIG_ONLY",
            "updated": payload is not None, "scheduled_crons": sorted(after),
            "runtime_invocations_verified": False}

def main():
    now = dt.datetime.now(dt.timezone.utc)
    mode = mode_for(now, os.getenv("GITHUB_EVENT_NAME", ""))
    if mode == "no_action":
        print("WEEKEND_V2=SKIPPED_date_or_event_guard")
        return 0
    try:
        client = Cloudflare(os.getenv("CLOUDFLARE_ACCOUNT_ID"),
                            os.getenv("CLOUDFLARE_API_TOKEN"))
        result = run(mode, client)
    except RuntimeError as exc:
        print(json.dumps({"phase": mode, "status": "BLOCKED", "reason": str(exc)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("## Weekend V2 Cloudflare cron diagnostics\n\n")
            f.write(f"- Phase: {mode}\n- Configuration: PASS (readback)\n")
            f.write("- Runtime Cron -> Worker -> DO -> GitHub: NOT VERIFIED by this job\n")
            f.write("- Worker source and main production cron unchanged\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())
