"""Offline tests for date-bounded Saturday/Sunday hourly capture."""
from __future__ import annotations

import contextlib
import io
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / ".github/workflows/v2-cloudflare-safe-tail.yml"


class WeekendHourlyTailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.safe_load(PATH.read_text(encoding="utf-8"))
        cls.config = cls.workflow.get("on", cls.workflow.get(True))
        steps = cls.workflow["jobs"]["tail"]["steps"]
        gate = next(step for step in steps if step.get("id") == "window")
        match = re.search(r"python3 - <<'PY'\n(.*?)\nPY", gate["run"], re.DOTALL)
        assert match, "Missing inline date gate"
        cls.source = match.group(1)

    def evaluate(self, utc, event="schedule", cron="26 10-20 * * 6"):
        code = self.source.replace(
            "now=dt.datetime.now(dt.timezone.utc)",
            "now=dt.datetime.fromisoformat(" + repr(utc) + ")",
        )
        with tempfile.TemporaryDirectory() as directory:
            output = str(Path(directory) / "output")
            with patch.dict(os.environ, {
                "GITHUB_EVENT_NAME": event,
                "EVENT_CRON": cron,
                "GITHUB_OUTPUT": output,
            }):
                with contextlib.redirect_stdout(io.StringIO()):
                    exec(code, {"__name__": "__main__"})
            return dict(line.split("=", 1) for line in
                        Path(output).read_text().splitlines())

    def test_date_scoped_hourly_windows(self):
        for utc in ("2026-10-24T10:26:00+00:00",
                    "2026-10-24T14:31:00+00:00",
                    "2026-10-24T20:47:00+00:00"):
            self.assertEqual(self.evaluate(utc),
                             {"enabled": "true", "capture_mode": "hourly"})
        # GitHub delivered the 13:26 UTC run at 14:02 UTC.
        # A delayed but still date-scoped schedule must capture, not SKIP.
        for utc in ("2026-10-24T10:15:00+00:00",
                    "2026-10-24T10:53:00+00:00",
                    "2026-10-24T14:02:00+00:00"):
            self.assertEqual(self.evaluate(utc),
                             {"enabled": "true", "capture_mode": "hourly"})
        for utc in ("2026-10-24T09:59:00+00:00",
                    "2026-10-24T21:00:00+00:00",
                    "2026-10-31T10:26:00+00:00"):
            self.assertEqual(self.evaluate(utc)["enabled"], "false")

    def test_sunday_hourly_after_cet_fallback(self):
        cron = "26 6-21 * * 0"
        for utc in ("2026-10-25T06:26:00+00:00",
                    "2026-10-25T10:26:00+00:00",
                    "2026-10-25T21:26:00+00:00",
                    "2026-10-25T22:02:00+00:00"):
            self.assertEqual(self.evaluate(utc, cron=cron),
                             {"enabled": "true", "capture_mode": "hourly"})
        for utc in ("2026-10-25T05:59:00+00:00",
                    "2026-10-25T23:00:00+00:00",
                    "2026-11-01T10:26:00+00:00"):
            self.assertEqual(self.evaluate(utc, cron=cron)["enabled"], "false")
        self.assertEqual(self.evaluate("2026-10-25T10:26:00+00:00")
                         ["enabled"], "false")

    def test_no_push_duplicate_and_wrong_schedule(self):
        self.assertEqual(self.evaluate(
            "2026-10-24T09:30:00+00:00", "push")["enabled"], "false")
        self.assertEqual(self.evaluate(
            "2026-10-24T12:26:00+00:00", "schedule",
            "13 6 * * 6,0")["enabled"], "false")
        self.assertEqual(self.evaluate(
            "2026-10-24T09:30:00+00:00", "workflow_dispatch"),
            {"enabled": "true", "capture_mode": "long"})
        self.assertEqual(self.evaluate(
            "2026-10-24T10:36:00+00:00", "workflow_dispatch"),
            {"enabled": "true", "capture_mode": "short"})
        self.assertEqual(self.evaluate(
            "2026-10-24T10:36:00+00:00", "push"),
            {"enabled": "true", "capture_mode": "short"})
        self.assertEqual(self.evaluate(
            "2026-10-24T10:45:00+00:00", "workflow_dispatch")["enabled"], "false")
        self.assertEqual(self.evaluate(
            "2026-10-25T10:36:00+00:00", "workflow_dispatch")["enabled"], "false")

    def test_postdeploy_push_is_single_day_and_bounded(self):
        self.assertEqual(self.evaluate(
            "2026-10-24T15:42:00+00:00", "push"),
            {"enabled": "true", "capture_mode": "hourly"})
        self.assertEqual(self.evaluate(
            "2026-10-24T16:15:00+00:00", "push")["enabled"], "false")
        self.assertEqual(self.evaluate(
            "2026-10-25T15:42:00+00:00", "push")["enabled"], "false")

    def test_preserve_normal_schedule_redaction_and_nonoverlap(self):
        # Archived workflow remains testable, but must not auto-run after its date window.
        self.assertEqual(set(self.config), {"workflow_dispatch"})
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        self.assertFalse(self.workflow["concurrency"]["cancel-in-progress"])
        tail = next(step for step in
                    self.workflow["jobs"]["tail"]["steps"]
                    if step.get("name") == "Read Cloudflare events with strict log redaction")
        self.assertIn("capture_seconds=1080", tail["run"])
        self.assertIn("capture_seconds=3240", tail["run"])
        self.assertIn("capture_seconds=7500", tail["run"])
        self.assertIn("controller-v2/safe_tail_filter.py", tail["run"])
        self.assertIn('codes=( "${PIPESTATUS[@]}" )', tail["run"])
        self.assertIn('v2-safe-traces.jsonl', tail["run"])


if __name__ == "__main__":
    unittest.main()
