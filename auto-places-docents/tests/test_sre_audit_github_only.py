"""Subprocess tests: audited slot != merely successful GitHub workflow."""
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zoneinfo import ZoneInfo

SCRIPT = Path(__file__).resolve().parents[1] / "sre_audit_v2.py"
TZ = ZoneInfo("Europe/Madrid")


def latest_due(now):
    local = now.astimezone(TZ)
    for days in range(8):
        date = (local - dt.timedelta(days=days)).date()
        if date.weekday() > 4:
            continue
        for h in (17, 13, 11, 8):
            nominal = dt.datetime.combine(date, dt.time(h), tzinfo=TZ)
            if local >= nominal + dt.timedelta(minutes=45):
                return nominal
    raise AssertionError("No due slot")


def write_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


class TestAuditedDueSlot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / "auto-places-docents" / "state"
        self.state.mkdir(parents=True)
        slot = latest_due(dt.datetime.now(dt.timezone.utc))
        generated = (slot - dt.timedelta(minutes=15)).isoformat()
        audited = (slot - dt.timedelta(minutes=10)).isoformat()
        self.health = {"generated_at": generated, "audit_at": audited, "fresh": 12,
                       "total": 12, "presence_authoritative": 12, "partial": 0,
                       "cache_obsoleta": 0, "audit_errors": 0, "audit_status": "PASS"}
        self.consumer = {"run_id": "snapshot1", "generated_at": generated}
        self.source_audit = {"generated_at": audited, "status": "PASS"}
        self.key = slot.strftime("%Y-%m-%dT%H:00")
        self.ledger = {"slots": {self.key: {
            "scan_run_id": "12345", "status": "PASS",
            "snapshot_run_id": "snapshot1", "generated_at": generated,
            "audit_at": audited, "trigger_sha": "sha",
        }}}
        self.persist()

    def persist(self):
        for filename, data in (("health.json", self.health),
                               ("consumer.json", self.consumer),
                               ("audit.json", self.source_audit),
                               ("slot-ledger.json", self.ledger)):
            write_json(self.state / filename, data)

    def run_audit(self):
        env = dict(os.environ)
        env["GITHUB_TOKEN"] = ""  # no network: offline evidence is never an invented PASS
        result = subprocess.run([sys.executable, str(SCRIPT)], cwd=self.root,
                                env=env, text=True, capture_output=True, timeout=15)
        report = json.loads((self.root / "sre-audit-report.json").read_text(encoding="utf-8"))
        checks = {x["name"]: x["status"] for x in report["checks"]}
        return result.returncode, report, checks

    def test_valid_receipt_without_job_api_is_blocked_not_pass(self):
        code, report, checks = self.run_audit()
        self.assertEqual(code, 2)
        self.assertEqual(report["expected_slot"], self.key)
        self.assertEqual(report["overall"], "BLOCKED")
        self.assertEqual(checks["Latest due slot receipt"], "PASS")
        self.assertEqual(checks["Actual GitHub scan steps"], "BLOCKED")

    def test_missing_slot_detected_even_with_recent_healthy_snapshot(self):
        self.ledger = {"slots": {}}
        self.persist()
        code, report, checks = self.run_audit()
        self.assertEqual(code, 1)
        self.assertEqual(report["overall"], "FAIL")
        self.assertEqual(checks["Latest due slot receipt"], "FAIL")
        self.assertEqual(checks["Health freshness"], "FAIL")

    def test_partial_sources_block_false_success(self):
        self.health["fresh"] = 11
        self.persist()
        code, report, checks = self.run_audit()
        self.assertEqual(code, 1)
        self.assertEqual(checks["12 official sources"], "FAIL")
        self.assertEqual(checks["Latest due slot receipt"], "FAIL")


if __name__ == "__main__":
    unittest.main()
