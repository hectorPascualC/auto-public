#!/usr/bin/env python3
"""Read-only Cloudflare cron and GitHub dispatch access diagnosis. Output allowlisted evidence only."""
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

GH = "https://api.github.com/repos/hectorPascualC/auto-public"
CF = "https://api.cloudflare.com/client/v4"
WORKER = "auto-public-controller-v2"

def get(url, token, payload=None):
    if not token:
        return None, "secret_missing"
    hdr = {"Authorization": "Bearer " + token, "Accept": "application/json",
           "User-Agent": "auto-public-v2-safe-diagnostic"}
    if payload is not None:
        hdr["Content-Type"] = "application/json"
    req = urllib.request.Request(url, headers=hdr,
        data=json.dumps(payload).encode() if payload is not None else None,
        method="POST" if payload is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=25) as f:
            return json.load(f), None
    except urllib.error.HTTPError as e:
        return None, "http_" + str(e.code)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None, "network_or_schema_error"

def main():
    token = os.getenv("CLOUDFLARE_API_TOKEN", "")
    account = os.getenv("CLOUDFLARE_ACCOUNT_ID", "")
    dispatch_token = os.getenv("V2_GITHUB_DISPATCH_TOKEN", "")
    github_token = os.getenv("GITHUB_TOKEN", "")
    now = dt.datetime.now(dt.timezone.utc)
    start = dt.datetime(2026,10,23,6,20,tzinfo=dt.timezone.utc)
    report = {"diagnosed_at_utc": now.isoformat(), "from_utc": start.isoformat()}
    if token and account:
        base = CF + "/accounts/" + account
        c, err = get(base + "/workers/scripts/" + WORKER + "/settings", token)
        if c and c.get("success"):
            bindings = c.get("result", {}).get("bindings", [])
            dispatch = next((b.get("text") for b in bindings if b.get("name")=="DISPATCH_ENABLED"), None)
            has_do = any(b.get("name")=="SLOT_COORDINATOR" for b in bindings)
            has_secret = any(b.get("name")=="GITHUB_TOKEN" and b.get("type")=="secret_text" for b in bindings)
            report["live_configuration"] = {"status": "PASS" if dispatch=="true" and has_do and has_secret else "FAIL",
                "dispatch_enabled": dispatch, "has_durable_object": has_do, "has_github_secret": has_secret}
        else:
            report["live_configuration"] = {"status":"BLOCKED","reason":err or "cloudflare_schema"}
        query = {"queryId":"auto-public-v2-cron-audit-20261023", "view":"events",
            "limit":200, "dry":False, "parameters":{
                "datasets":["cloudflare-workers"],"filters":[
                    {"id":"1","key":"$metadata.service","operation":"eq","type":"string","value":WORKER},
                    {"id":"2","key":"$metadata.origin","operation":"eq","type":"string","value":"cron"}],
                "calculations":[],"groupBys":[],"havings":[]},
            "timeframe":{"from":int(start.timestamp()*1000),"to":int(now.timestamp()*1000)}}
        c, err = get(base + "/workers/observability/telemetry/query", token, query)
        if c:
            ev = c.get("events",{})
            if isinstance(ev,dict):
                ev = ev.get("events",[])
            if isinstance(ev,list):
                events = []
                for item in ev:
                    if not isinstance(item,dict):
                        continue
                    meta=item.get("$metadata") or {}
                    source=item.get("source") or {}
                    if isinstance(source,str):
                        try: source=json.loads(source)
                        except ValueError: source={}
                    if not isinstance(source,dict): source={}
                    d={"timestamp":str(meta.get("timestamp",""))[:35]}
                    for k in ("controller","status","slot","attempt","phase","error","reason"):
                        if k in source: d[k]=str(source[k])[:100]
                    events.append(d)
                report["cron_events"]={"status":"PASS" if events else "FAIL","count":len(events),"events":events[:45]}
            else: report["cron_events"]={"status":"BLOCKED","reason":"unexpected_events_schema"}
        else: report["cron_events"]={"status":"BLOCKED","reason":err or "cloudflare_telemetry_schema"}
    else:
        report["live_configuration"]={"status":"BLOCKED","reason":"cloudflare_secrets_missing"}
        report["cron_events"]={"status":"BLOCKED","reason":"cloudflare_secrets_missing"}
    c,err=get(GH+"/actions/runs?event=workflow_dispatch&per_page=5", dispatch_token)
    report["dispatch_token_read"]={"status":"PASS" if isinstance(c,dict) and isinstance(c.get("workflow_runs"),list) else "BLOCKED",
        "reason":err or ("ok" if c else "bad_schema")}
    for k,workflow in [("monitor_runs","auto-places-docents.yml"),("sre_runs","sre-audit-v2.yml")]:
        c,err=get(GH+"/actions/workflows/"+workflow+"/runs?per_page=50",github_token)
        if isinstance(c,dict) and isinstance(c.get("workflow_runs"),list):
            runs=c["workflow_runs"]
            report[k]={"status":"PASS","count":len(runs),"recent":[
                {"id":r.get("id"),"event":r.get("event"),"name":str(r.get("display_title",""))[:100],
                 "created_at":r.get("created_at"),"status":r.get("status"),"conclusion":r.get("conclusion")}
                 for r in runs[:20] if isinstance(r,dict)]}
        else: report[k]={"status":"BLOCKED","reason":err or "bad_schema"}
    print(json.dumps(report,indent=2,ensure_ascii=False))
    with open("controller-v2-runtime-diagnosis.json","w") as f: json.dump(report,f,indent=2)
    with open(os.environ["GITHUB_STEP_SUMMARY"],"a") as f:
        f.write("## Phase 2 - runtime evidence (read only)\n\n\`\`\`json\n"+json.dumps(report,indent=2)+"\n\`\`\`\n")
    return 0 if all(report[k]["status"]=="PASS" for k in ("live_configuration","cron_events",
                  "dispatch_token_read","monitor_runs","sre_runs")) else 2

if __name__ == "__main__":
    sys.exit(main())
