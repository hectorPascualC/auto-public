"""Offline regressions for archived 2026 cron transport experiment."""
from __future__ import annotations

import importlib.util
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
spec = importlib.util.spec_from_file_location("cron_smoke", ROOT / "cron_smoke.py")
cron_smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cron_smoke)


class TestCronSmoke(unittest.TestCase):
    def test_schedule_is_distinct_from_push_and_manual(self):
        t = datetime(2026, 10, 25, 10, 7, tzinfo=timezone.utc)
        r = cron_smoke.inspect_run("schedule", cron_smoke.CRON, t, "42", "abcdef")
        self.assertEqual(r["status"], "SCHEDULE_DELIVERED")
        self.assertEqual(r["source_event"], "schedule")
        self.assertEqual(r["observed_at_madrid"], "2026-10-25T11:07:00+01:00")
        self.assertEqual(r["official_source_requests"], 0)
        self.assertEqual(r["github_dispatch_requests"], 0)
        self.assertEqual(r["persistent_writes"], 0)
        for event in ("push", "workflow_dispatch"):
            x = cron_smoke.inspect_run(event, "", t)
            self.assertEqual(x["status"], "SMOKE_ONLY_NOT_SCHEDULE_EVIDENCE")

    def test_expired_probe_reports_without_claiming_nominal_on_time(self):
        future = datetime(2026, 10, 27, 0, 7, tzinfo=timezone.utc)
        r = cron_smoke.inspect_run("schedule", cron_smoke.CRON, future)
        self.assertEqual(r["status"], "DELAYED_OUTSIDE_TEST_DATES")
        self.assertIn("not proof", r["note"])
        with self.assertRaisesRegex(ValueError, "unrecognized_scheduled_cron"):
            cron_smoke.inspect_run("schedule", "* * * * *", future)
        with self.assertRaisesRegex(ValueError, "non_schedule_must_not_have_cron"):
            cron_smoke.inspect_run("push", cron_smoke.CRON, future)

    def test_temporary_workflow_has_been_retired(self):
        # The read-only experiment completed on 2026-10-25.
        # Keeping the test/archived script is safe; keeping the GitHub cron
        # would silently reactivate every October 25-26 in future years.
        self.assertFalse((REPO / ".github/workflows/cron-smoke-30m.yml").exists())


if __name__ == "__main__":
    unittest.main()
