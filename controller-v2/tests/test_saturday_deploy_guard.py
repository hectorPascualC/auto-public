"""Offline tests for bounded 24-25 October Cloudflare deployment guard."""
import datetime as dt
import importlib.util
import unittest
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "saturday_deploy_guard", ROOT / "saturday_deploy_guard.py"
)
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class SaturdayDeployTests(unittest.TestCase):
    def test_allowed_day_only(self):
        tz = ZoneInfo("Europe/Madrid")
        for date, allow in (
            (dt.datetime(2026, 10, 24, 10, 30, tzinfo=tz), True),
            (dt.datetime(2026, 10, 25, 10, 30, tzinfo=tz), True),
            (dt.datetime(2026, 10, 31, 10, 30, tzinfo=tz), False),
            (dt.datetime(2026, 10, 23, 10, 30, tzinfo=tz), False)
        ):
            self.assertIs(guard.date_guard(date), allow)

    def test_runtime_config_keeps_trigger_schedules_untouched(self):
        original = (ROOT / "wrangler.toml").read_text(encoding="utf-8")
        runtime = guard.make_runtime(original)
        self.assertIn('DISPATCH_ENABLED = "true"', runtime)
        self.assertIn('name = "auto-public-controller-v2"', runtime)
        self.assertIn('class_name = "SlotCoordinator"', runtime)
        self.assertNotIn("[triggers]", runtime)
        self.assertNotIn("crons =", runtime)
        self.assertIn("[observability]", runtime)
        self.assertIn('DISPATCH_ENABLED = "false"', original)
        self.assertIn(guard.PRODUCTION, original)

    def test_manual_deploy_requires_explicit_confirm_and_never_schedules(self):
        import yaml
        name = ROOT.parent / ".github/workflows/v2-saturday-manual-deploy.yml"
        workflow = yaml.safe_load(name.read_text(encoding="utf-8"))
        on = workflow.get("on", workflow.get(True))
        self.assertEqual(set(on), {"workflow_dispatch"})
        self.assertTrue(on["workflow_dispatch"]["inputs"]["confirm_saturday"]["required"])
        self.assertEqual(workflow["permissions"]["contents"], "read")
        self.assertIn("concurrency", workflow)

    def test_unexpected_source_or_live_config_fails_closed(self):
        src = (ROOT / "wrangler.toml").read_text(encoding="utf-8")
        with self.assertRaises(ValueError):
            guard.make_runtime(src.replace('DISPATCH_ENABLED = "false"',
                                           'DISPATCH_ENABLED = "true"'))
        bindings = [
            {"name": "DISPATCH_ENABLED", "text": "true"},
            {"name": "SLOT_COORDINATOR", "type": "durable_object_namespace"},
            {"name": "GITHUB_TOKEN", "type": "secret_text"},
            {"name": "GITHUB_REPO", "text": "hectorPascualC/auto-public"},
        ]
        valid = {"schedules": [{"cron": c} for c in guard.EXPECTED]}
        self.assertTrue(guard.validate_live(valid, {"bindings": bindings}))
        # After the date-guarded Sunday cron migration, redeploying a
        # minimal SRE hotfix must still pass without altering triggers.
        valid_extended = {"schedules": [{"cron": c} for c in guard.EXPECTED_EXTENDED]}
        self.assertTrue(guard.validate_live(valid_extended, {"bindings": bindings}))
        with self.assertRaises(ValueError):
            guard.validate_live({"schedules": [
                {"cron": guard.PRODUCTION}, {"cron": "35,47 6-22 * * 1,7"}
            ]}, {"bindings": bindings})
        with self.assertRaises(ValueError):
            guard.validate_live({"schedules": [{"cron": guard.PRODUCTION}]},
                                {"bindings": bindings})
        with self.assertRaises(ValueError):
            guard.validate_live(valid, {"bindings": bindings[:-1]})


if __name__ == "__main__":
    unittest.main()
