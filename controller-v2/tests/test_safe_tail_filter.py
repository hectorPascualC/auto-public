"""Offline regression tests: safe Wrangler tail filtering without raw data leaks."""
import importlib.util
import io
import json
import subprocess
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location(
    "safe_tail_filter", Path(__file__).resolve().parents[1] / "safe_tail_filter.py"
)
FILTER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FILTER)


class TailEvidenceTests(unittest.TestCase):
    def run_filter(self, lines):
        out = io.StringIO()
        FILTER.process(io.StringIO(lines), out)
        return [json.loads(x) for x in out.getvalue().splitlines()]

    def test_empty_stream_is_explicitly_inconclusive(self):
        result = self.run_filter("")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["verdict"], "NO_TAIL_FRAMES_OBSERVED")
        self.assertEqual(result[0]["tail_frames"], 0)

    def test_unknown_event_is_counted_not_silently_dropped(self):
        result = self.run_filter(json.dumps({
            "outcome": "ok", "eventTimestamp": 1790000000000,
            "event": None, "logs": [], "exceptions": []
        }) + "\n")
        self.assertEqual(result[0]["event_type"], "unknown")
        self.assertEqual(result[1]["tail_frames"], 1)
        self.assertEqual(result[1]["verdict"],
                         "TAIL_FRAMES_WITHOUT_RECOGNIZED_CONTROLLER_LOG")

    def test_structured_controller_log_is_counted_and_redacted(self):
        secret = "token-EVERYTHING-MUST-BE-REDACTED"
        inner = {"controller": "v2", "status": "DISPATCHED",
                 "slot": "2026-10-26T09:00", "attempt": "primary",
                 "phase": "run_coordinator",
                 "reason": secret + " !! invalid"}
        input_line = json.dumps({
            "outcome": "ok", "event": {"cron": "35 7 * * 1-5"},
            "headers": {"Authorization": secret},
            "logs": [{"message": [json.dumps(inner), secret]}],
            "exceptions": []
        }) + "\n"
        out = io.StringIO()
        FILTER.process(io.StringIO(input_line), out)
        self.assertNotIn(secret, out.getvalue())
        self.assertNotIn("Authorization", out.getvalue())
        records = [json.loads(x) for x in out.getvalue().splitlines()]
        self.assertEqual(records[0]["status"], "DISPATCHED")
        self.assertEqual(records[0]["reason"], "REDACTED")
        self.assertEqual(records[1]["scheduled_frames"], 1)
        self.assertEqual(records[1]["controller_log_frames"], 1)
        self.assertEqual(records[1]["verdict"], "CONTROLLER_LOGS_OBSERVED")

    def test_saturday_hourly_slot_and_do_phase_survive_redaction(self):
        for hour in range(9, 24):
            slot=f"2026-10-24T{hour:02}:00"
            self.assertEqual(FILTER.safe_value("slot", slot), slot)
        self.assertEqual(FILTER.safe_value("slot", "2026-10-24T08:00"), "REDACTED")
        self.assertEqual(FILTER.safe_value("phase", "github_read"), "github_read")
        for phase in ("build_request", "send_request", "parse_response",
                      "parse_request", "validate_request", "invoke_slot",
                      "encode_response"):
            self.assertEqual(FILTER.safe_value("phase", phase), phase)
        self.assertEqual(FILTER.safe_value("error", "slot_coordinator_http_500"),
                         "slot_coordinator_http_500")
        self.assertEqual(FILTER.safe_value("error_kind", "TypeError"), "TypeError")
        self.assertEqual(FILTER.safe_value("error_kind", "Bearer-secret"), "REDACTED")
        secret="Bearer-never-leak"
        frame={"outcome":"exception", "event":{"cron":"35,47 6-20 * * 1,7"},
               "logs":[{"message":[json.dumps({
                   "controller":"v2", "status":"ERROR",
                   "slot":"2026-10-24T12:00", "phase":"github_read",
                   "error":"github_http_403",
                   "error_kind":"TypeError",
                   "message":secret
               })]}], "exceptions":[{"message":secret}]}
        output=io.StringIO()
        FILTER.process(io.StringIO(json.dumps(frame)+"\n"),output)
        self.assertNotIn(secret,output.getvalue())
        record=json.loads(output.getvalue().splitlines()[0])
        self.assertEqual(record["slot"],"2026-10-24T12:00")
        self.assertEqual(record["phase"],"github_read")
        self.assertEqual(record["error"],"github_http_403")
        self.assertEqual(record["error_kind"],"TypeError")

    def test_rpc_probe_verdict_is_safe_and_not_leaked(self):
        for verdict in ("do_fetch_204", "do_fetch_404", "do_fetch_other",
                        "do_fetch_exception", "do_fetch_unavailable"):
            self.assertEqual(FILTER.safe_value("rpc_probe", verdict), verdict)
        self.assertEqual(FILTER.safe_value("rpc_probe", "secret-token"),
                         "REDACTED")
        secret = "github_pat_NEVER_ECHO"
        frame = {"outcome": "exception", "event": {"cron": "35,47 6-20 * * 1,7"},
                 "logs": [{"message": [json.dumps({
                     "controller": "v2", "status": "ERROR",
                     "slot": "2026-10-24T15:00", "rpc_probe": "do_fetch_204",
                     "error_kind": "TypeError", "private": secret
                 })]}], "exceptions": [{"message": secret}]}
        out = io.StringIO()
        FILTER.process(io.StringIO(json.dumps(frame)+"\n"), out)
        record = json.loads(out.getvalue().splitlines()[0])
        self.assertEqual(record["rpc_probe"], "do_fetch_204")
        self.assertNotIn(secret, out.getvalue())

    def test_pretty_printed_scheduled_invocations_are_not_lost(self):
        secret = "Bearer-super-secret-never-printed"
        def pretty(status, minute):
            frame = {
                "outcome": "ok",
                "eventTimestamp": 1792794900000 + minute * 60000,
                "event": {"cron": "35,47 20,21 * * 6"},
                "headers": {"Authorization": secret},
                "logs": [{"message": [json.dumps({
                    "controller": "v2", "status": status,
                    "reason": "not_a_nominal_slot"
                })]}],
                "exceptions": []
            }
            return json.dumps(frame, indent=2) + "\n"
        input_text = "Connected to Worker, waiting for logs...\n" + pretty("IGNORED", 35) + pretty("IGNORED", 47)
        out = io.StringIO()
        FILTER.process(io.StringIO(input_text), out)
        records = [json.loads(x) for x in out.getvalue().splitlines()]
        self.assertEqual([r.get("status") for r in records[:2]], ["IGNORED", "IGNORED"])
        self.assertEqual([r.get("event_type") for r in records[:2]], ["scheduled", "scheduled"])
        self.assertEqual(records[-1]["tail_frames"], 2)
        self.assertEqual(records[-1]["multiline_frames"], 2)
        self.assertEqual(records[-1]["controller_log_frames"], 2)
        self.assertEqual(records[-1]["verdict"], "CONTROLLER_LOGS_OBSERVED")
        self.assertNotIn(secret, out.getvalue())
        self.assertNotIn("Authorization", out.getvalue())

    def test_incomplete_pretty_frame_is_explicitly_inconclusive(self):
        result = self.run_filter('{"outcome": "ok",\n')
        self.assertEqual(result[-1]["unparsed_fragments"], 1)
        self.assertEqual(result[-1]["tail_frames"], 0)
        self.assertEqual(result[-1]["verdict"], "NO_TAIL_FRAMES_OBSERVED")

    def test_jsonl_and_pretty_mixed_with_banner(self):
        frame = {"outcome": "ok", "event": {"cron": "test"}, "logs": []}
        mixed = "Wrangler started\n" + json.dumps(frame) + "\n" + json.dumps(frame, indent=2) + "\n"
        result = self.run_filter(mixed)
        self.assertEqual(result[-1]["tail_frames"], 2)
        self.assertEqual(result[-1]["multiline_frames"], 1)
        self.assertEqual(result[-1]["non_json_lines"], 1)

    def test_tail_workflow_fails_closed_on_each_pipeline_failure(self):
        # Exercise the ACTUAL shell exit-code gate from the workflow, not a
        # reimplementation. Old code checked only Wrangler (codes[0]), and
        # silently marked success when the sanitizer or tee failed.
        import yaml
        workflow = Path(__file__).resolve().parents[2] / ".github/workflows/v2-cloudflare-safe-tail.yml"
        steps = yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]["tail"]["steps"]
        capture = next(step["run"] for step in steps
                       if step.get("name") == "Read Cloudflare events with strict log redaction")
        begin = capture.index('if [[ "${codes[0]}"')
        end = capture.index('echo "Tail session finished.', begin)
        gate = capture[begin:end]
        for statuses, accepted in (
            ((0, 0, 0), True),
            ((124, 0, 0), True),  # bounded tail naturally times out
            ((1, 0, 0), False),
            ((0, 1, 0), False),  # sanitizer failure
            ((0, 0, 1), False),  # tee / evidence failure
            ((124, 1, 0), False),
            ((124, 0, 1), False),
        ):
            with self.subTest(statuses=statuses):
                shell = "codes=(" + " ".join(map(str, statuses)) + ")\n" + gate + "\necho GATE_PASS\n"
                result = subprocess.run(["bash", "-c", shell],
                                        capture_output=True, text=True, check=False)
                self.assertEqual(result.returncode == 0, accepted)
                self.assertEqual("GATE_PASS" in result.stdout, accepted)

    def test_daily_tail_and_date_guarded_weekend_captures(self):
        # Sunday uses its own 54m capture after CET fallback, not the older
        # 125m long tail; this prevents overlapping 09..23 E2E evidence.
        import yaml
        workflow = Path(__file__).resolve().parents[2] / ".github/workflows/v2-cloudflare-safe-tail.yml"
        content = workflow.read_text(encoding="utf-8")
        parsed = yaml.safe_load(content)
        # Historical gate remains tested, but retired workflows no longer schedule.
        triggers = parsed[True]  # PyYAML 1.1 treats "on" as True
        self.assertEqual(set(triggers), {"workflow_dispatch"})
        self.assertIn("dt.time(8,0)", content)
        self.assertIn("dt.date(2026,10,26)", content)
        self.assertIn("diagnostic_bridge=", content)
        self.assertIn("diagnostic_probe=", content)
        self.assertIn('dt.time(12,40) <= now.time() < dt.time(12,55)', content)
        self.assertIn('"hourly" if (hourly_saturday or hourly_sunday or diagnostic_probe or diagnostic_postdeploy)', content)
        self.assertIn('dt.time(11,30) <= now.time() < dt.time(11,45)', content)
        self.assertIn('os.getenv("GITHUB_EVENT_NAME")=="push"', content)
        self.assertIn("manual_short or diagnostic_bridge", content)

    def test_saturday_tail_accepts_delayed_github_cron_and_postdeploy_push(self):
        # Execute the actual embedded Python gate at representative UTC times.
        import os
        import tempfile
        import yaml
        workflow = Path(__file__).resolve().parents[2] / ".github/workflows/v2-cloudflare-safe-tail.yml"
        steps = yaml.safe_load(workflow.read_text(encoding="utf-8"))["jobs"]["tail"]["steps"]
        gate = next(step["run"] for step in steps if step.get("name") == "Gate one-date diagnostic window")
        script = gate.split("python3 - <<'PY'\n", 1)[1].split("\nPY", 1)[0]
        for when, event, cron, enabled in (
            ((2026, 10, 24, 14, 2), "schedule", "26 10-20 * * 6", True),
            ((2026, 10, 24, 15, 42), "push", "", True),
            ((2026, 10, 25, 14, 2), "schedule", "26 10-20 * * 6", False),
        ):
            with self.subTest(when=when, event=event):
                injected = script.replace(
                    "now=dt.datetime.now(dt.timezone.utc)",
                    "now=dt.datetime(%s,tzinfo=dt.timezone.utc)" %
                    ",".join(str(x) for x in when))
                with tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8") as output:
                    env = dict(os.environ, GITHUB_OUTPUT=output.name,
                               GITHUB_EVENT_NAME=event, EVENT_CRON=cron)
                    result = subprocess.run(["python3", "-c", injected],
                                            env=env, capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    output.seek(0)
                    values = output.read()
                    self.assertIn("enabled=" + str(enabled).lower(), values)
                    if enabled:
                        self.assertIn("capture_mode=hourly", values)

    def test_token_shaped_metadata_never_leaks(self):
        self.assertEqual(FILTER.safe_value("reason", "github_pat_abcd"), "REDACTED")
        self.assertEqual(FILTER.safe_value("error", "ghp_abcd"), "REDACTED")
        self.assertEqual(FILTER.safe_value("status", "DISPATCHED"), "DISPATCHED")

    def test_non_json_is_counted_separately(self):
        result = self.run_filter("wrangler connected\n")
        self.assertEqual(result[0]["non_json_lines"], 1)
        self.assertEqual(result[0]["tail_frames"], 0)


if __name__ == "__main__":
    unittest.main()
