"""Offline regression tests: safe Wrangler tail filtering without raw data leaks."""
import importlib.util
import io
import json
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
            return json.dumps(frame, indent=2) + "\\n"
        input_text = "Connected to Worker, waiting for logs...\\n" + pretty("IGNORED", 35) + pretty("IGNORED", 47)
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
        result = self.run_filter('{"outcome": "ok",\\n')
        self.assertEqual(result[-1]["unparsed_fragments"], 1)
        self.assertEqual(result[-1]["tail_frames"], 0)
        self.assertEqual(result[-1]["verdict"], "NO_TAIL_FRAMES_OBSERVED")

    def test_jsonl_and_pretty_mixed_with_banner(self):
        frame = {"outcome": "ok", "event": {"cron": "test"}, "logs": []}
        mixed = "Wrangler started\\n" + json.dumps(frame) + "\\n" + json.dumps(frame, indent=2) + "\\n"
        result = self.run_filter(mixed)
        self.assertEqual(result[-1]["tail_frames"], 2)
        self.assertEqual(result[-1]["multiline_frames"], 1)
        self.assertEqual(result[-1]["non_json_lines"], 1)

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
