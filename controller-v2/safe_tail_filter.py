#!/usr/bin/env python3
"""Redact Wrangler tail JSON, retaining counters even when no log matches.

Never prints raw messages, URLs, headers, exception text or token-like values.
Accepts JSONL AND Wrangler's pretty-printed multiline JSON envelopes.
Each accepted tail frame produces a safe observation, and EOF always produces
a summary. NO_TAIL_FRAMES is not evidence that Cloudflare cron did not run:
the tail connection or capture window may also be responsible.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone

FIELDS = ("status", "slot", "attempt", "phase", "error", "error_kind", "reason", "rpc_probe")
VALUES = {
    "status": {"IGNORED", "STALE", "DISABLED", "SKIPPED", "DISPATCHED", "ERROR"},
    "rpc_probe": {"do_fetch_204", "do_fetch_404", "do_fetch_other",
                  "do_fetch_exception", "do_fetch_unavailable"},
    "attempt": {"primary", "backup"},
    "error_kind": {"Error", "TypeError", "RangeError", "ReferenceError",
                   "SyntaxError", "DurableObjectError", "other"},
    "phase": {"classify_slot", "resolve_coordinator", "run_coordinator",
              "block_concurrency", "storage_read", "github_read",
              "github_dispatch", "storage_write", "parse_request",
              "validate_request", "invoke_slot", "encode_response",
              "build_request", "send_request", "parse_response"},
    "reason": {"not_a_nominal_slot", "already_sent", "valid_receipt",
               "backup_already_dispatched", "slot_already_dispatched"},
    "error": {"controller_configuration_invalid", "slot_coordinator_binding_invalid",
              "slot_coordinator_stub_invalid", "github_contents_unexpected_schema",
              "github_runs_unexpected_schema", "unexpected_exception"}
}
OUTCOMES = {"ok", "exception", "canceled", "unknown", "exceededCpu", "exceededMemory"}
SLOT = re.compile(r"^20[0-9]{2}-[01][0-9]-[0-3][0-9]T((?:09|1[0-9]|2[0-3])|11|14|16):00$")
GH_ERROR = re.compile(r"^(?:github_http_|slot_coordinator_http_)[0-9]{3}$")


def safe_value(field, value):
    if not isinstance(value, str):
        return "REDACTED"
    if field == "slot":
        return value if SLOT.fullmatch(value) else "REDACTED"
    if field == "error" and GH_ERROR.fullmatch(value):
        return value
    return value if value in VALUES.get(field, set()) else "REDACTED"


def event_type(info):
    event = info.get("event")
    if not isinstance(event, dict):
        return "unknown"
    if "cron" in event or "scheduledTime" in event:
        return "scheduled"
    if "request" in event:
        return "http"
    return "unknown"


# Wrangler --format=json emits pretty-printed MULTILINE JSON envelopes, not
# necessarily JSONL. The original per-line json.loads() silently discarded every
# line of a valid invocation, producing a false NO_TAIL_FRAMES_OBSERVED verdict.
# Never echo source bytes: tail envelopes can include headers and secrets.
MAX_FRAME_BYTES = 256 * 1024
MAX_FRAME_LINES = 1500


def parse_frames(source, counts):
    """Yield sanitized candidate envelopes from JSONL or bounded pretty JSON."""
    pending = []
    pending_bytes = 0

    for line in source:
        if not line.strip():
            if pending:
                pending.append(line)
                pending_bytes += len(line)
            continue
        counts["input_lines"] += 1
        if not pending and not line.lstrip().startswith("{"):
            counts["non_json_lines"] += 1
            continue
        pending.append(line)
        pending_bytes += len(line)
        if pending_bytes > MAX_FRAME_BYTES or len(pending) > MAX_FRAME_LINES:
            counts["unparsed_fragments"] += 1
            pending = []
            pending_bytes = 0
            continue
        try:
            obj = json.loads("".join(pending))
        except (TypeError, ValueError):
            continue
        if len(pending) > 1:
            counts["multiline_frames"] += 1
        pending = []
        pending_bytes = 0
        if not isinstance(obj, dict) or not isinstance(obj.get("logs", []), list):
            counts["non_json_lines"] += 1
            continue
        yield obj
    if pending:
        counts["unparsed_fragments"] += 1


def process(source, target):
    started_at = datetime.now(timezone.utc).isoformat()
    counts = {"input_lines": 0, "tail_frames": 0, "non_json_lines": 0,
              "controller_log_frames": 0, "scheduled_frames": 0,
              "other_outcomes": 0, "multiline_frames": 0,
              "unparsed_fragments": 0}
    for info in parse_frames(source, counts):
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
                        record[field] = safe_value(field, data[field])
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
                             "started_at_utc": started_at,
                             "ended_at_utc": datetime.now(timezone.utc).isoformat(),
                             **counts}, sort_keys=True) + "\n")
    target.flush()
    return counts


if __name__ == "__main__":
    process(sys.stdin, sys.stdout)
