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
        a=schedule_gate.decide("schedule","5 7 * * 1-5",now,{}, {})
        self.assertEqual(a, (True,"RUN_SCAN","2026-10-20T09:00","primary"))
        b=schedule_gate.decide("schedule","22 7 * * 1-5",now,health(),{})
        self.assertEqual(b[1],"SKIPPED_ALREADY_VALID_SNAPSHOT")
        c=schedule_gate.decide("schedule","22 7 * * 1-5",now,{},{"slots":{"2026-10-20T09:00":{"status":"PASS"}}})
        self.assertEqual(c[:2],(True,"RUN_SCAN"))  # Unverified ledger must never suppress a scan
        matching = {"slots":{"2026-10-20T09:00":{
            "status":"PASS","generated_at":health()["generated_at"],
            "audit_at":health()["audit_at"],"snapshot_run_id":"RUN7"}}}
        verified=schedule_gate.decide("schedule","22 7 * * 1-5",now,health(),matching)
        self.assertEqual(verified[1],"SKIPPED_ALREADY_VALID_LEDGER")
        d=schedule_gate.decide("schedule","22 7 * * 1-5",now,{}, {})
        self.assertEqual(d[:2],(True,"RUN_SCAN"))

    def test_other_slots(self):
        for hour in (9,11,14,16):
            for minute in (5,22):
                now=at(f"2026-10-20T{hour:02}:{minute:02}:00+02:00")
                self.assertTrue(schedule_gate.decide("schedule",f"{minute} {hour-2} * * 1-5",now,{}, {})[0])

    def test_extra_1830_both_dst_offsets_and_fresh_snapshot(self):
        for cron, now in (
            ("30 16 * * 1-5", "2026-10-20T18:30:00+02:00"),
            ("30 17 * * 1-5", "2026-10-26T18:30:00+01:00"),
        ):
            out = schedule_gate.decide("schedule", cron, at(now),
                health("2026-10-20T18:13:00+02:00",
                       "2026-10-20T18:20:00+02:00"), {})
            self.assertEqual(out[0], True)
            self.assertEqual(out[3], "extra_1830")
            self.assertTrue(out[2].endswith("T18:00"))
        self.assertFalse(schedule_gate.decide(
            "schedule", "30 17 * * 1-5",
            at("2026-10-20T19:30:00+02:00"), {}, {})[0])
        self.assertFalse(schedule_gate.decide(
            "schedule", "30 16 * * 1-5",
            at("2026-10-26T17:30:00+01:00"), {}, {})[0])

    def test_late_next_day_and_old_cron(self):
        for d in ("2026-10-20T10:36:00+02:00","2026-10-21T11:05:00+02:00"):
            a=schedule_gate.decide("schedule","5 7 * * 1-5",at(d),{}, {})
            self.assertFalse(a[0])
        self.assertFalse(schedule_gate.decide("schedule","0 6 * * 1-5",at("2026-10-20T09:05:00+02:00"),{}, {})[0])

    def test_dst_october(self):
        a=schedule_gate.decide("schedule","5 8 * * 1-5",at("2026-10-26T09:05:00+01:00"),{}, {})
        self.assertEqual(a[2],"2026-10-26T09:00")
        a=schedule_gate.decide("schedule","5 7 * * 1-5",at("2026-07-06T09:05:00+02:00"),{}, {})
        self.assertTrue(a[0])

    def test_utc_candidates_offseason_and_delays(self):
        # Scheduled strings are UTC, including across the DST boundary.
        for cron, when, slot in (
            ("5 7 * * 1-5", "2026-10-20T09:05:00+02:00", "2026-10-20T09:00"),
            ("22 9 * * 1-5", "2026-10-20T11:30:00+02:00", "2026-10-20T11:00"),
            ("5 12 * * 1-5", "2026-10-20T14:09:00+02:00", "2026-10-20T14:00"),
            ("5 14 * * 1-5", "2026-10-20T16:05:00+02:00", "2026-10-20T16:00"),
            ("5 8 * * 1-5", "2026-10-26T09:05:00+01:00", "2026-10-26T09:00"),
            ("22 10 * * 1-5", "2026-10-26T11:22:00+01:00", "2026-10-26T11:00"),
            ("5 13 * * 1-5", "2026-10-26T14:05:00+01:00", "2026-10-26T14:00"),
            ("22 15 * * 1-5", "2026-10-26T16:25:00+01:00", "2026-10-26T16:00"),
        ):
            decision = schedule_gate.decide("schedule", cron, at(when), {}, {})
            self.assertEqual(decision[:3], (True, "RUN_SCAN", slot), (cron, when))
        for cron, when in (
            ("5 8 * * 1-5", "2026-10-20T10:05:00+02:00"),
            ("5 7 * * 1-5", "2026-10-26T08:05:00+01:00"),
            ("5 7 * * 1-5", "2026-10-20T09:04:00+02:00"),
            ("5 7 * * 1-5", "2026-10-20T10:05:00+02:00"),
        ):
            self.assertFalse(schedule_gate.decide(
                "schedule", cron, at(when), {}, {})[0], (cron, when))

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

    def test_territorial_result_matches_exact_id(self):
        snap = importlib.import_module("active_snapshot_v2")
        doc_offer = {"url":"https://educacio.gencat.cat/DC_oferta.pdf", "label":"Oferta",
                     "role":"offer", "target_hits":[
                       {"code":"507","snippet":"Identificador plaça 19659466 Especialitat 507"}]}
        def check(result_text):
            doc_result = {"url":"https://educacio.gencat.cat/DC_resultat.pdf",
                          "label":"Resultat", "role":"result", "target_hits":[
                            {"code":"507","snippet":"19659466 Especialitat 507 "+result_text}]}
            return snap.derive_non_edubcn_v2({"freshness":"FRESC",
                        "documents":[doc_offer,doc_result], "landings":[]})
        empty=check("RESULTAT DESERTA")
        self.assertEqual(len(empty["current_target_placements"]),1)
        self.assertEqual(len(empty["covered_by_results"]),0)
        filled=check("RESULTAT: plaça adjudicada")
        self.assertEqual(len(filled["current_target_placements"]),0)
        self.assertEqual(filled["covered_by_results"][0]["placement_id"],"19659466")

    def test_result_borsa_selected(self):
        self.assertEqual(classify(
            "RESULTAT:\n Persona Exemple Cognom núm borsa:215.288 Consorci."), "COVERED")
        self.assertEqual(classify(
            "RESULTAT:\n Plaça declarada DESERTA. Sense cap persona seleccionada."), "UNFILLED")
        self.assertEqual(classify("RESULTAT: pendent de resolució"), "UNKNOWN")

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
        # UTC candidates cover both CET and CEST; schedule_gate checks Madrid local time.
        self.assertEqual(len(times), 18)
        self.assertEqual({x["cron"] for x in times},
            {f"{minute} {hour} * * 1-5" for minute in (5, 22)
             for hour in (7, 8, 9, 10, 12, 13, 14, 15)} |
            {"30 16 * * 1-5", "30 17 * * 1-5"})
        self.assertTrue(all("timezone" not in x for x in times))
        self.assertEqual(data["concurrency"]["queue"],"max")
        self.assertFalse(data["concurrency"]["cancel-in-progress"])

if __name__ == "__main__":
    unittest.main()
