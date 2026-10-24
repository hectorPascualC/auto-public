#!/usr/bin/env python3
"""Read-only Cloudflare pre/postflight and fail-closed runtime config generation.

One-day deployment 2026-10-24 ONLY. Never writes schedules or secrets.
The temp Wrangler config OMITs [triggers], preserving live registered crons.
"""
from __future__ import annotations
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

PRODUCTION = "35,47 6,7,8,9,11,12,13,14 * * 2-6"
WEEKEND = "35,47 6-20 * * 1,7"
EXPECTED = {PRODUCTION, WEEKEND}
WORKER = "auto-public-controller-v2"
DATE = dt.date(2026, 10, 24)
TIMEZONE = ZoneInfo("Europe/Madrid")
SOURCE = Path("controller-v2/wrangler.toml")
RUNTIME = Path("controller-v2/wrangler.saturday-runtime.toml")


def date_guard(now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    return now.astimezone(TIMEZONE).date() == DATE


def make_runtime(source):
    if source.count('DISPATCH_ENABLED = "false"') != 1:
        raise ValueError("source_dispatch_flag_unexpected")
    block = re.search(
        r"(?ms)^\[triggers\]\s*\n.*?(?=^\[\[durable_objects\.bindings\]\])",
        source,
    )
    if block is None or PRODUCTION not in block.group(0) or "[triggers]" in source[:block.start()]:
        raise ValueError("source_cron_contract_unexpected")
    result = source[:block.start()] + source[block.end():]
    result = result.replace('DISPATCH_ENABLED = "false"', 'DISPATCH_ENABLED = "true"')
    if "[triggers]" in result or "crons =" in result:
        raise ValueError("runtime_must_not_set_triggers")
    if 'DISPATCH_ENABLED = "true"' not in result:
        raise ValueError("runtime_must_activate_dispatch")
    return result


def fetch_cloudflare(suffix):
    account, token = os.getenv("CLOUDFLARE_ACCOUNT_ID"), os.getenv("CLOUDFLARE_API_TOKEN")
    if not account or not token:
        raise ValueError("cloudflare_credentials_missing")
    endpoint = ("https://api.cloudflare.com/client/v4/accounts/" + account
                + "/workers/scripts/" + WORKER + suffix)
    request = urllib.request.Request(endpoint, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
        "User-Agent": "auto-public-saturday-one-day-preflight",
    })
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            obj = json.load(response)
    except urllib.error.HTTPError as exc:
        raise ValueError("cloudflare_http_" + str(exc.code)) from None
    except (urllib.error.URLError, ValueError, TimeoutError):
        raise ValueError("cloudflare_read_failure") from None
    if not isinstance(obj, dict) or obj.get("success") is not True:
        raise ValueError("cloudflare_bad_response")
    return obj.get("result")


def validate_live(schedules, settings):
    if not isinstance(schedules, dict) or not isinstance(schedules.get("schedules"), list):
        raise ValueError("cron_response_schema")
    rows = schedules["schedules"]
    crons = [x.get("cron") if isinstance(x, dict) else None for x in rows]
    if len(crons) != len(EXPECTED) or set(crons) != EXPECTED:
        raise ValueError("unexpected_live_cron_configuration")
    bindings = settings.get("bindings") if isinstance(settings, dict) else None
    if not isinstance(bindings, list):
        raise ValueError("settings_response_schema")
    def present(name, predicate):
        return any(isinstance(x, dict) and x.get("name") == name and predicate(x)
                   for x in bindings)
    if not present("DISPATCH_ENABLED", lambda x: x.get("text") == "true"):
        raise ValueError("dispatch_not_enabled")
    if not present("SLOT_COORDINATOR", lambda x: True):
        raise ValueError("durable_object_missing")
    if not present("GITHUB_TOKEN", lambda x: x.get("type") == "secret_text"):
        raise ValueError("github_secret_missing")
    if not present("GITHUB_REPO", lambda x: x.get("text") == "hectorPascualC/auto-public"):
        raise ValueError("repository_binding_mismatch")
    return True


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("preflight", "postflight"):
        raise ValueError("usage_preflight_or_postflight")
    if not date_guard():
        raise ValueError("not_authorized_calendar_day")
    schedules = fetch_cloudflare("/schedules")
    settings = fetch_cloudflare("/settings")
    validate_live(schedules, settings)
    if sys.argv[1] == "preflight":
        RUNTIME.write_text(make_runtime(SOURCE.read_text(encoding="utf-8")),
                           encoding="utf-8")
    print("SATURDAY_V2_" + sys.argv[1].upper() + "=PASS")
    print("LIVE_CRONS_PRESERVED=weekday_plus_weekend")
    print("LIVE_DISPATCH_ENABLED=true")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as error:
        print("SATURDAY_V2=BLOCKED_" + str(error))
        raise SystemExit(2)
