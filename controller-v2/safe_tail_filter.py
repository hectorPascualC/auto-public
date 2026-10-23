#!/usr/bin/env python3
"""Redact Wrangler tail JSON, retaining counters even when no log matches.

Never prints raw messages, URLs, headers, exception text or token-like values.
Each accepted tail frame produces a safe observation, and EOF always produces
a summary. NO_TAIL_FRAMES is not evidence that Cloudflare cron did not run:
the tail connection or capture window may also be responsible.
"""
from __future__ import annotations

import json
import re
import sys

FIELDS = ("status", "slot", "attempt", "phase", "error", "reason")
OUTCOMES = {"ok", "exception", "canceled", "unknown", "exceededCpu", "exceededMemory"}
VALUE = re.compile(r"^[A-Za-z0-9_:.\/-]{1,80}$")


def safe_value(value):
    return value if isinstance(value, str) and VALUE.fullmatch(value) else "REDACTED"


def event_type(info):
    event = info.get("event")
    if not isinstance(event, dict):
        return "unknown"
    if "cron" in event or "scheduledTime" in event:
        return "scheduled"
    if "request" in event:
        return "http"
    return "unknown"


def process(source, target):
    counts = {"input_lines": 0, "tail_frames": 0, "non_json_lines": 0,
              "controller_log_frames": 0, "scheduled_frames": 0,
              "other_outcomes": 0}
    for line in source:
        if not line.strip():
            continue
        counts["input_lines"] += 1
        try:
            info = json.loads(line)
        except (TypeError, ValueError):
            counts["non_json_lines"] += 1
            continue
        if not isinstance(info, dict) or not isinstance(info.get("logs", []), list):
            counts["non_json_lines"] += 1
            continue
        # This is a structured tail frame. Never include arbitrary original fields.
        counts["tail_frames"] += 1
        outcome = info.get("outcome")
        if outcome not in OUTCOMES:
            counts["other_outcomes"] += 1
            outcome = "other"
        kind = event_type(info)
        if kind == "scheduled":
            counts["scheduled_frames"] += 1
        record = {"kind": "tail_observation", "outcome": outcome,
                  "event_type": kind,
                  "exception_count": len(info.get("exceptions") or [])
                      if isinstance(info.get("exceptions") or [], list) else 0}
        stamp = info.get("eventTimestamp")
        if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
            record["event_timestamp_ms"] = int(stamp)
        controller_seen = False
        for entry in info.get("logs", []):
            if not isinstance(entry, dict):
                continue
            messages = entry.get("message", [])
            if isinstance(messages, str):
                messages = [messages]
            if not isinstance(messages, list):
                continue
            for message in messages:
                if not isinstance(message, str):
                    continue
                try:
                    data = json.loads(message)
                except (ValueError, TypeError):
                    continue
                if not isinstance(data, dict) or data.get("controller") != "v2":
                    continue
                controller_seen = True
                record["controller"] = "v2"
                for field in FIELDS:
                    if field in data:
                        record[field] = safe_value(data[field])
        if controller_seen:
            counts["controller_log_frames"] += 1
        target.write(json.dumps(record, sort_keys=True) + "\n")
        target.flush()
    # A 0-frame report distinguishes no tail observations from filter rejection.
    if counts["tail_frames"] == 0:
        verdict = "NO_TAIL_FRAMES_OBSERVED"
    elif counts["controller_log_frames"] == 0:
        verdict = "TAIL_FRAMES_WITHOUT_RECOGNIZED_CONTROLLER_LOG"
    else:
        verdict = "CONTROLLER_LOGS_OBSERVED"
    target.write(json.dumps({"kind": "tail_summary", "verdict": verdict,
                             **counts}, sort_keys=True) + "\n")
    target.flush()
    return counts


if __name__ == "__main__":
    process(sys.stdin, sys.stdout)
