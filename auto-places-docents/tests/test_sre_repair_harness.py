"""Offline repair harness tests: safe, bounded, idempotent and fail-closed."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import repair_harness


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")


class TestRepairHarness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.ts = "2026-10-27T17:30:14+01:00"
        self.audit_ts = "2026-10-27T17:38:30+01:00"
        self.state = {
            "run_id": "run-1", "generated_at": self.ts,
            "territories": {"T" + str(i): {"freshness": "FRESC"} for i in range(12)},
            "active_snapshot": {"territories": {"T" + str(i): {"presence_authoritative": True} for i in range(12)}},
        }
        self.health = {
            "generated_at": self.ts, "audit_at": self.audit_ts,
            "fresh": 12, "total": 12, "presence_authoritative": 12,
            "partial": 0, "cache_obsoleta": 0, "audit_errors": 0,
            "audit_status": "PASS",
        }
        self.audit = {"generated_at": self.audit_ts, "status": "PASS"}
        self.report_path = self.root / "sre-audit-report.json"
        self.write_fixture()

    def write_fixture(self):
        save(self.root / "latest.json", self.state)
        save(self.root / "health.json", self.health)
        save(self.root / "audit.json", self.audit)
        save(self.root / "consumer.json", {"run_id": "old-run", "generated_at": "old"})
        save(self.report_path, {"overall": "FAIL", "checks": [
            {"name": "Consumer snapshot", "status": "FAIL"},
            {"name": "Latest due slot receipt", "status": "PASS"},
        ]})

    def test_verified_correction_and_idempotence(self):
        plan = repair_harness.diagnose(self.root, self.report_path)
        self.assertEqual(plan["action"], "rebuild_consumer")
        self.assertFalse(plan["production_write"])
        self.assertEqual(plan["max_attempts"], 1)
        self.assertEqual(repair_harness.apply_safe(self.root, plan), "LOCAL_CANDIDATE_VERIFIED")
        actual = repair_harness.load(self.root / "consumer.json")
        self.assertEqual(actual["run_id"], "run-1")
        self.assertEqual(actual["generated_at"], self.ts)
        self.assertEqual(len(actual["territories"]), 12)
        self.assertEqual(repair_harness.apply_safe(self.root, plan), "ALREADY_CORRECT")

    def test_sources_not_authoritative_no_repair(self):
        for mutation in ("partial", "bad_audit", "wrong_identity"):
            with self.subTest(mutation=mutation):
                self.write_fixture()
                if mutation == "partial":
                    self.health["fresh"] = 11
                    save(self.root / "health.json", self.health)
                elif mutation == "bad_audit":
                    self.audit["status"] = "FAIL"
                    save(self.root / "audit.json", self.audit)
                else:
                    self.state["generated_at"] = "2026-10-01T00:00:00+02:00"
                    save(self.root / "latest.json", self.state)
                plan = repair_harness.diagnose(self.root, self.report_path)
                self.assertEqual(plan["action"], "investigate")
                self.assertEqual(repair_harness.apply_safe(self.root, plan), "NO_SAFE_ACTION")
                self.assertEqual(repair_harness.load(self.root / "consumer.json")["run_id"], "old-run")
                self.state["generated_at"] = self.ts
                self.health["fresh"] = 12
                self.audit["status"] = "PASS"

    def test_unverified_active_snapshot_is_never_repaired(self):
        self.state["active_snapshot"]["territories"].pop("T0")
        self.write_fixture()
        plan = repair_harness.diagnose(self.root, self.report_path)
        self.assertEqual(plan["action"], "investigate")
        self.assertEqual(repair_harness.apply_safe(self.root, plan), "NO_SAFE_ACTION")

    def test_canonical_changes_after_plan_never_write(self):
        plan = repair_harness.diagnose(self.root, self.report_path)
        self.state["territories"]["T0"]["freshness_notes"] = ["changed"]
        save(self.root / "latest.json", self.state)
        with self.assertRaises(ValueError):
            repair_harness.apply_safe(self.root, plan)
        self.assertEqual(repair_harness.load(self.root / "consumer.json")["run_id"], "old-run")

    def test_missing_nominal_slot_never_triggers_unscheduled_scan(self):
        save(self.report_path, {"overall": "FAIL", "checks": [
            {"name": "Latest due slot receipt", "status": "FAIL"},
            {"name": "Consumer snapshot", "status": "FAIL"},
        ]})
        plan = repair_harness.diagnose(self.root, self.report_path)
        self.assertEqual(plan["action"], "existing_rescue_only")
        self.assertFalse(plan["production_write"])
        self.assertEqual(repair_harness.apply_safe(self.root, plan), "NO_SAFE_ACTION")

    def test_unknown_report_is_not_auto_repaired(self):
        self.report_path.unlink()
        plan = repair_harness.diagnose(self.root, self.report_path)
        self.assertEqual(plan["action"], "investigate")
        self.assertEqual(repair_harness.apply_safe(self.root, plan), "NO_SAFE_ACTION")

class TestNoObsoleteScheduledWorkflows(unittest.TestCase):
    def test_legacy_diagnostics_are_manual_only(self):
        for name in ("v2-cloudflare-safe-tail.yml", "weekend-cron-probe-v2.yml"):
            with self.subTest(name=name):
                yml = (ROOT.parent / ".github/workflows" / name).read_text(encoding="utf-8")
                trigger = yml.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
                self.assertEqual(trigger.strip(), "workflow_dispatch:")


if __name__ == "__main__":
    unittest.main()
