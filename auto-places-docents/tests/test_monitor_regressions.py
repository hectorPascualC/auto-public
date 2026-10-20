"""Offline regression suite: schedule, DST, outcomes, final history and slot ledger."""
from __future__ import annotations
import gzip
import importlib
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))
import schedule_gate
import slot_ledger
import finalize_history
from coverage import classify
TZ = ZoneInfo("Europe/Madrid")

def at(s):
    return datetime.fromisoformat(s)

def health(ts="2026-10-20T09:07:00+02:00", audit="2026-10-20T09:12:00+02:00"):
    return {"generated_at": ts, "audit_at": audit, "fresh": 12, "total": 12,
            "partial": 0, "cache_obsoleta": 0, "presence_authoritative": 12,
            "audit_status": "PASS", "audit_errors": 0}

class TestSchedule(unittest.TestCase):
    def test_primary_backup_and_dedup(self):
        now=at("2026-10-20T09:22:00+02:00")
        a=schedule_gate.decide("schedule","5 9 * * 1-5",now,{}, {})
        self.assertEqual(a, (True,"RUN_SCAN","2026-10-20T09:00","primary"))
        b=schedule_gate.decide("schedule","22 9 * * 1-5",now,health(),{})
        self.assertEqual(b[1],"SKIPPED_ALREADY_VALID_SNAPSHOT")
        c=schedule_gate.decide("schedule","22 9 * * 1-5",now,{},{"slots":{"2026-10-20T09:00":{"status":"PASS"}}})
        self.assertEqual(c[1],"SKIPPED_ALREADY_VALID_LEDGER")
        d=schedule_gate.decide("schedule","22 9 * * 1-5",now,{}, {})
        self.assertEqual(d[:2],(True,"RUN_SCAN"))

    def test_other_slots(self):
        for hour in (9,11,14,16):
            for minute in (5,22):
                now=at(f"2026-10-20T{hour:02}:{minute:02}:00+02:00")
                self.assertTrue(schedule_gate.decide("schedule",f"{minute} {hour} * * 1-5",now,{}, {})[0])

    def test_late_next_day_and_old_cron(self):
        for d in ("2026-10-20T10:36:00+02:00","2026-10-21T11:05:00+02:00"):
            a=schedule_gate.decide("schedule","5 9 * * 1-5",at(d),{}, {})
            self.assertFalse(a[0])
        self.assertFalse(schedule_gate.decide("schedule","0 6 * * 1-5",at("2026-10-20T09:05:00+02:00"),{}, {})[0])

    def test_dst_october(self):
        a=schedule_gate.decide("schedule","5 9 * * 1-5",at("2026-10-26T09:05:00+01:00"),{}, {})
        self.assertEqual(a[2],"2026-10-26T09:00")
        a=schedule_gate.decide("schedule","5 9 * * 1-5",at("2026-07-06T09:05:00+02:00"),{}, {})
        self.assertTrue(a[0])

    def test_rescue_once_and_expiry(self):
        marker="AUTO-PUBLIC scheduled-slot rescue\nslot_local=2026-10-20T09:00:00+02:00\npublic_data_only=true\n"
        args=dict(marker_changed=True,marker_text=marker,trigger_sha="abc",processed_sha="")
        a=schedule_gate.decide("push","",at("2026-10-20T09:42:00+02:00"),{}, {},**args)
        self.assertEqual(a[2:4],("2026-10-20T09:00","rescue"))
        self.assertEqual(schedule_gate.decide("push","",at("2026-10-20T09:42:00+02:00"),{}, {},**{**args,"processed_sha":"abc"})[1],"duplicate_push")
        self.assertEqual(schedule_gate.decide("push","",at("2026-10-20T16:00:00+02:00"),{}, {},**args)[1],"rescue_slot_expired")
        self.assertIsNone(schedule_gate.parse_rescue(marker.replace("+02:00","+01:00")))

    def test_bad_health_rejected(self):
        h=health();h["audit_errors"]=1
        self.assertFalse(schedule_gate.valid_health(h,"2026-10-20T09:00"))

class TestResults(unittest.TestCase):
    def test_deserta(self):
        self.assertEqual(classify("RESULTAT: la plaça es declara DESERTA"),"UNFILLED")
        self.assertEqual(classify("Sense cap persona seleccionada"),"UNFILLED")
        self.assertEqual(classify("RESULTAT: plaça adjudicada"),"COVERED")
        self.assertEqual(classify("La plaça es troba coberta"),"COVERED")
        self.assertEqual(classify("Anul·lada la convocatòria"),"UNFILLED")
        self.assertEqual(classify("Resultat de la convocatòria: pendent"),"UNKNOWN")
        self.assertEqual(classify("Plaça adjudicada però declarada deserta"),"UNKNOWN")

    def test_edubcn_finalizer(self):
        ed = importlib.import_module("edubcn_finalize")
        with tempfile.TemporaryDirectory() as tmp:
            t=Path(tmp); st=t/"latest.json"; rpt=t/"latest.md"
            docs=[
              {"role":"offer","url":"https://www.edubcn.cat/rcs_gene/seleccio/GENSEC_2627_111_507.pdf",
               "text_excerpt":"CODI GENSEC_2627_111 ESPECIALITAT 507"},
              {"role":"result","url":"https://www.edubcn.cat/rcs_gene/seleccio/GENSEC_2627_111_result.pdf",
               "text_excerpt":"CODI GENSEC_2627_111 RESULTAT DESERTA ESPECIALITAT 507"}]
            st.write_text(json.dumps({"territories":{"EDUBCN":{"documents":docs,"placements":[]}}}))
            rpt.write_text("Original\n")
            with patch.object(ed,"STATE_FILE",st), patch.object(ed,"REPORT_FILE",rpt):
                self.assertEqual(ed.main(),0)
            r=json.loads(st.read_text())["territories"]["EDUBCN"]
            p=r["target_placements_document_verified"][0]
            self.assertTrue(p["result_document_present"])
            self.assertFalse(p["coverage_confirmed"])
            self.assertEqual(p["result_classification"],"UNFILLED")

class TestFinalization(unittest.TestCase):
    def test_final_history_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            t=Path(tmp)
            stamp="2026-10-20T09:07:00+02:00"
            state={"generated_at":stamp,"run_id":"20261020T090700+0200",
                   "territories":{str(i):{} for i in range(12)},
                   "active_snapshot":{"territories":{}},"edubcn_finalize_at":"2026-10-20T09:11:00+02:00"}
            h=health(stamp,"2026-10-20T09:12:00+02:00")
            au={"status":"PASS","source_generated_at":stamp,"scopes_checked":12,"errors":[]}
            c={"generated_at":stamp,"run_id":state["run_id"]}
            for name,val in [("latest.json",state),("health.json",h),("audit.json",au),("consumer.json",c)]:
                (t/name).write_text(json.dumps(val))
            (t/"_previous_final.json").write_text("{}")
            with patch.object(finalize_history,"ROOT",t):
                self.assertEqual(finalize_history.main(),0)
                self.assertFalse((t/"_previous_final.json").exists())
                with gzip.open(t/"history"/(state["run_id"]+".json.gz"),"rt") as f:
                    actual=json.load(f)
                self.assertEqual(actual["final_audit"],au)
                h["audit_errors"]=1
                (t/"health.json").write_text(json.dumps(h))
                with self.assertRaises(SystemExit):
                    finalize_history.main()

    def test_slot_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            t=Path(tmp)
            (t/"health.json").write_text(json.dumps(health()))
            (t/"consumer.json").write_text(json.dumps({"generated_at":health()["generated_at"],"run_id":"RUN7"}))
            e={"STATE_DIR":str(t),"SLOT_KEY":"2026-10-20T09:00","SLOT_KIND":"primary",
               "GITHUB_RUN_ID":"123","TRIGGER_SHA":"sha"}
            with patch.dict(os.environ,e):
                self.assertEqual(slot_ledger.main(),0)
                self.assertEqual(slot_ledger.main(),0)
            j=json.loads((t/"slot-ledger.json").read_text())
            self.assertEqual(j["slots"]["2026-10-20T09:00"]["status"],"PASS")
            self.assertEqual(len(j["slots"]),1)

class TestWorkflow(unittest.TestCase):
    def test_yaml(self):
        import yaml
        data=yaml.safe_load((REPO/".github/workflows/auto-places-docents.yml").read_text())
        on = data.get("on",data.get(True))
        times = on["schedule"]
        self.assertEqual(len(times),8)
        self.assertEqual({x["cron"] for x in times},
            {f"{minute} {hour} * * 1-5" for minute in (5,22) for hour in (9,11,14,16)})
        self.assertTrue(all(x["timezone"]=="Europe/Madrid" for x in times))
        self.assertEqual(data["concurrency"]["queue"],"max")
        self.assertFalse(data["concurrency"]["cancel-in-progress"])

if __name__ == "__main__":
    unittest.main()
