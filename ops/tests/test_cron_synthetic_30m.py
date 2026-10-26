#!/usr/bin/env python3
"""Safety, cron, CET/CEST and provenance tests for the synthetic-only probe."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ops.cron_synthetic_30m import classify, EXPECTED_CRON

TZ = ZoneInfo("Europe/Madrid")


class TestSyntheticProbe(unittest.TestCase):
    def test_real_schedule_only_for_exact_october_2026_dates(self):
        for hour in (0, 7, 11, 17, 23):
            for minute in (27, 57):
                for day in (25, 26):
                    now = datetime(2026, 10, day, hour, minute, tzinfo=TZ)
                    self.assertEqual(classify("schedule", EXPECTED_CRON, now),
                                     "SCHEDULE_FIRED")
        for day in (24, 27):
            now = datetime(2026, 10, day, 10, 27, tzinfo=TZ)
            self.assertEqual(classify("schedule", EXPECTED_CRON, now),
                             "EXPIRED_INERT")
        self.assertEqual(classify("schedule", EXPECTED_CRON,
                         datetime(2027, 10, 25, 10, 27, tzinfo=TZ)),
                         "EXPIRED_INERT")

    def test_smoke_is_not_counted_as_real_scheduled_execution(self):
        when = datetime(2026, 10, 25, 11, 0, tzinfo=TZ)
        for name in ("push", "workflow_dispatch"):
            self.assertEqual(classify(name, "", when),
                             "SMOKE_ONLY_NOT_SCHEDULE")

    def test_fail_closed_for_unknown_event_or_cron(self):
        now = datetime(2026, 10, 25, 11, 0, tzinfo=TZ)
        for bad_cron in ("", "* * * * *", "27,57 * * * *"):
            with self.assertRaisesRegex(ValueError, "unexpected_cron_fail_closed"):
                classify("schedule", bad_cron, now)
        with self.assertRaisesRegex(ValueError, "unexpected_event_fail_closed"):
            classify("repository_dispatch", EXPECTED_CRON, now)
        with self.assertRaisesRegex(ValueError, "timezone_required"):
            classify("schedule", EXPECTED_CRON, datetime(2026, 10, 25))

    def test_timezone_change_has_no_implicit_utc_hour(self):
        # Same nominal Madrid local time on either side of 2026 DST rollback.
        for when in (datetime(2026, 10, 24, 11, 27, tzinfo=TZ),
                     datetime(2026, 10, 25, 11, 27, tzinfo=TZ)):
            expected = "EXPIRED_INERT" if when.date().day == 24 else "SCHEDULE_FIRED"
            self.assertEqual(classify("schedule", EXPECTED_CRON,
                             when.astimezone(timezone.utc)), expected)

    def test_yaml_is_read_only_finite_and_separate_from_monitor(self):
        p = ROOT / ".github/workflows/cron-synthetic-30m.yml"
        raw = p.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)
        triggers = data.get("on", data.get(True))
        self.assertEqual(triggers["schedule"], [{
            "cron": EXPECTED_CRON, "timezone": "Europe/Madrid"
        }])
        self.assertEqual(data["permissions"], {"contents": "read"})
        self.assertEqual(data["concurrency"]["cancel-in-progress"], False)
        self.assertEqual(data["jobs"]["synthetic-clock"]["timeout-minutes"], 3)
        self.assertEqual(set(triggers), {"schedule", "push", "workflow_dispatch"})
        self.assertEqual(triggers["push"]["branches"], ["main"])
        self.assertNotIn("secrets.", raw)
        self.assertNotIn("monitor_v2.py", raw)
        self.assertNotIn("workflow_dispatch:", raw.split("jobs:", 1)[-1])
        self.assertNotIn("cloudflare", raw.split("jobs:", 1)[-1].lower())

    def test_main_monitor_production_schedule_unchanged(self):
        p = ROOT / ".github/workflows/auto-places-docents.yml"
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        triggers = data.get("on", data.get(True))
        self.assertEqual([x["cron"] for x in triggers["schedule"]], [
            "37 7,10,12,16 * * 1-5", "49 7,10,12,16 * * 1-5",
            "13 8,11,13,17 * * 1-5", "27 8,11,13,17 * * 1-5",
        ])
        self.assertTrue(all(x["timezone"] == "Europe/Madrid"
                            for x in triggers["schedule"]))


if __name__ == "__main__":
    unittest.main()
