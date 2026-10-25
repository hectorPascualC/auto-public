"""Offline GitHub-only rescue regressions: proven private push path, strict slot safety."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import schedule_gate


def moment(text):
    return datetime.fromisoformat(text)


def rescue(slot="2026-10-26T08:00:00+01:00", include_public_flag=True):
    flag = "public_data_only=true\n" if include_public_flag else ""
    return "AUTO-PUBLIC scheduled-slot rescue\n" + f"slot_local={slot}\n" + flag


def health_ok():
    return {
        "generated_at": "2026-10-26T07:42:00+01:00",
        "audit_at": "2026-10-26T07:57:00+01:00",
        "fresh": 12,
        "total": 12,
        "presence_authoritative": 12,
        "partial": 0,
        "cache_obsoleta": 0,
        "audit_status": "PASS",
        "audit_errors": 0,
    }


class TestGitHubRescueParity(unittest.TestCase):
    """Never launch duplicate/stale scans when a scheduled GitHub run goes missing."""

    def at(self, when="2026-10-26T08:30:00+01:00", marker_text=None,
           health=None, ledger=None, trigger_sha="rescue-sha", processed_sha=""):
        return schedule_gate.decide(
            "push", "", moment(when), health or {}, ledger or {},
            marker_changed=True,
            marker_text=rescue() if marker_text is None else marker_text,
            trigger_sha=trigger_sha,
            processed_sha=processed_sha,
        )

    def test_valid_missed_slot_rescue_is_one_slot_tied_scan(self):
        self.assertEqual(
            self.at(),
            (True, "RUN_SCAN", "2026-10-26T08:00", "rescue"),
        )

    def test_malformed_rescue_is_fail_closed_not_unslotted_scan(self):
        cases = (
            "AUTO-PUBLIC scheduled-slot rescue\n",
            rescue("2026-10-26T08:00:00+02:00"),  # Wrong CET offset
            rescue("2026-10-26T08:00:00"),        # No timezone
            rescue("2026-10-26T09:00:00+01:00"),  # Unconfigured slot
            rescue(include_public_flag=False),  # Not a public-data-only rescue
        )
        for value in cases:
            with self.subTest(marker=value):
                result = self.at(marker_text=value)
                self.assertEqual(result, (False, "invalid_rescue_marker", "", "invalid"))

    def test_valid_ledger_prevents_duplicate_scan(self):
        h = health_ok()
        ledger = {"slots": {"2026-10-26T08:00": {
            "status": "PASS",
            "generated_at": h["generated_at"],
            "audit_at": h["audit_at"],
            "snapshot_run_id": "known-run",
        }}}
        result = self.at(health=h, ledger=ledger)
        self.assertEqual(result[0], False)
        self.assertEqual(result[1], "SKIPPED_ALREADY_VALID_LEDGER")

    def test_valid_unslotted_snapshot_prevents_duplicate_scan(self):
        result = self.at(health=health_ok())
        self.assertEqual(result[0], False)
        self.assertEqual(result[1], "SKIPPED_ALREADY_VALID_SNAPSHOT")

    def test_processed_rescue_commit_deduplicated(self):
        result = self.at(trigger_sha="already-processed", processed_sha="already-processed")
        self.assertEqual(result[0], False)
        self.assertEqual(result[1], "duplicate_push")

    def test_old_rescue_rejected(self):
        result = self.at("2026-10-26T12:30:00+01:00")
        self.assertEqual(result[0], False)
        self.assertEqual(result[1], "rescue_slot_expired")

    def test_ordinary_private_style_manual_push_path_is_preserved(self):
        ordinary = "AUTO-PUBLIC manual public scan\npublic_data_only=true\n"
        result = self.at("2026-10-26T10:01:00+01:00", marker_text=ordinary)
        self.assertEqual(result, (True, "RUN_SCAN", "", "push"))

    def test_production_cron_contract_remains_unchanged(self):
        workflow = (ROOT.parent / ".github/workflows/auto-places-docents.yml").read_text()
        expected = (
            "37 7,10,12,16 * * 1-5",
            "49 7,10,12,16 * * 1-5",
            "13 8,11,13,17 * * 1-5",
            "27 8,11,13,17 * * 1-5",
        )
        for entry in expected:
            self.assertIn("cron: '" + entry + "'", workflow)
        self.assertEqual(workflow.count("      timezone: 'Europe/Madrid'"), 4)


if __name__ == "__main__":
    unittest.main()
