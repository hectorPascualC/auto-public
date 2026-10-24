"""Offline tests for Saturday hourly Cloudflare tail capture schedule."""
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


class SaturdayHourlyTailTests(unittest.TestCase):
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
        for utc in ("2026-10-24T10:15:00+00:00",
                    "2026-10-24T10:53:00+00:00",
                    "2026-10-25T10:26:00+00:00",
                    "2026-10-31T10:26:00+00:00"):
            self.assertEqual(self.evaluate(utc)["enabled"], "false")

    def test_no_push_duplicate_and_wrong_schedule(self):
        self.assertEqual(self.evaluate(
            "2026-10-24T09:30:00+00:00", "push")["enabled"], "false")
        self.assertEqual(self.evaluate(
            "2026-10-24T12:26:00+00:00", "schedule",
            "13 6 * * 6,0")["enabled"], "false")
        self.assertEqual(self.evaluate(
            "2026-10-24T09:30:00+00:00", "workflow_dispatch"),
            {"enabled": "true", "capture_mode": "long"})

    def test_preserve_normal_schedule_redaction_and_nonoverlap(self):
        crons = [item["cron"] for item in self.config["schedule"]]
        self.assertEqual(set(crons),
            {"13 6 * * 1", "13 6 * * 6,0", "26 10-20 * * 6"})
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        self.assertFalse(self.workflow["concurrency"]["cancel-in-progress"])
        tail = next(step for step in
                    self.workflow["jobs"]["tail"]["steps"]
                    if step.get("name") == "Read Cloudflare events with strict log redaction")
        self.assertIn("capture_seconds=3240", tail["run"])
        self.assertIn("capture_seconds=7500", tail["run"])
        self.assertIn("controller-v2/safe_tail_filter.py", tail["run"])
        self.assertIn('codes=( "${PIPESTATUS[@]}" )', tail["run"])
        self.assertIn('v2-safe-traces.jsonl', tail["run"])


if __name__ == "__main__":
    unittest.main()
