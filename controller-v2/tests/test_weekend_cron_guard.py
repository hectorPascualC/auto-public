"""Safety tests for the bounded weekend Cron addition and cleanup."""
import datetime as dt
import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("weekend_cron_guard", ROOT / "weekend_cron_guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)

def stamp(day, hour=10):
    return dt.datetime.fromisoformat(day + f"T{hour:02d}:00:00+00:00")

SETTINGS = {"result": {"bindings": [
    {"name": "DISPATCH_ENABLED", "text": "true"},
    {"name": "SLOT_COORDINATOR", "type": "durable_object_namespace"},
    {"name": "GITHUB_TOKEN", "type": "secret_text"}
]}}

class FakeCF:
    def __init__(self, schedules, settings=SETTINGS):
        self.schedules = list(schedules)
        self.settings = settings
        self.puts = []
    def call(self, suffix, method="GET", payload=None):
        if suffix == "/settings":
            return self.settings
        if suffix == "/schedules" and method == "PUT":
            self.puts.append(payload)
            self.schedules = [x["cron"] for x in payload]
        if suffix == "/schedules":
            return {"success": True, "result": {
                "schedules": [{"cron": x} for x in self.schedules]}}
        raise AssertionError("Unexpected API endpoint")

class WeekendCronTests(unittest.TestCase):
    def test_bounded_mode(self):
        self.assertEqual(guard.mode_for(stamp("2026-10-23"), "push"), "install")
        self.assertEqual(guard.mode_for(stamp("2026-10-24"), "schedule"), "verify")
        self.assertEqual(guard.mode_for(stamp("2026-10-25"), "schedule"), "verify")
        self.assertEqual(guard.mode_for(stamp("2026-10-26"), "schedule"), "restore")
        self.assertEqual(guard.mode_for(stamp("2026-10-27"), "schedule"), "no_action")
        self.assertEqual(guard.mode_for(stamp("2026-10-24"), "push"), "no_action")

    def test_install_preserves_original_cron(self):
        cf = FakeCF([guard.PRIMARY])
        result = guard.run("install", cf)
        self.assertEqual(set(cf.schedules), {guard.PRIMARY, guard.WEEKEND})
        self.assertEqual(len(cf.puts), 1)
        self.assertEqual(result["status"], "PASS_CONFIG_ONLY")
        self.assertFalse(result["runtime_invocations_verified"])

    def test_verify_is_read_only(self):
        cf = FakeCF([guard.PRIMARY, guard.WEEKEND])
        result = guard.run("verify", cf)
        self.assertFalse(result["updated"])
        self.assertEqual(cf.puts, [])

    def test_monday_restores_only_original(self):
        cf = FakeCF([guard.PRIMARY, guard.WEEKEND])
        guard.run("restore", cf)
        self.assertEqual(cf.schedules, [guard.PRIMARY])
        self.assertEqual(len(cf.puts), 1)
        guard.run("restore", cf)
        self.assertEqual(len(cf.puts), 1)

    def test_unknown_schedule_fails_closed(self):
        cf = FakeCF([guard.PRIMARY, "0 0 * * *"])
        with self.assertRaisesRegex(RuntimeError, "unexpected_schedule_configuration"):
            guard.run("install", cf)
        self.assertEqual(cf.puts, [])

    def test_missing_or_inactive_bindings_prevent_write(self):
        cf = FakeCF([guard.PRIMARY], {"result": {"bindings": []}})
        with self.assertRaisesRegex(RuntimeError, "preconditions_mismatch"):
            guard.run("install", cf)
        self.assertEqual(cf.puts, [])

    def test_response_schema_fail_closed(self):
        for sample in [{}, {"success": True, "result": {}},
                       {"success": True, "result": {"schedules": ["bad"]}}]:
            with self.assertRaises(RuntimeError):
                guard.extract_schedules(sample)

    def test_missing_weekend_schedule_is_not_success(self):
        cf = FakeCF([guard.PRIMARY])
        with self.assertRaisesRegex(RuntimeError, "weekend_schedule_missing"):
            guard.run("verify", cf)
        self.assertFalse(cf.puts)

    def test_duplicate_weekend_schedule_is_rejected(self):
        cf = FakeCF([guard.PRIMARY, guard.WEEKEND, guard.WEEKEND])
        with self.assertRaisesRegex(RuntimeError, "unexpected_schedule_configuration"):
            guard.run("restore", cf)
        self.assertFalse(cf.puts)

if __name__ == "__main__":
    unittest.main()
