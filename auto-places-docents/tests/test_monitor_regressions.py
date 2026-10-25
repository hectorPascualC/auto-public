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
import sanitize_public_state
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
    def test_primary_and_conditional_backup(self):
        slot = "2026-10-20T08:00"
        primary = "37 7,10,12,16 * * 1-5"
        backup = "49 7,10,12,16 * * 1-5"
        p = schedule_gate.decide("schedule", primary,
            at("2026-10-20T07:37:00+02:00"), {}, {})
        self.assertEqual(p, (True, "RUN_SCAN", slot, "primary"))
        b = schedule_gate.decide("schedule", backup,
            at("2026-10-20T07:49:00+02:00"), {}, {})
        self.assertEqual(b, (True, "RUN_SCAN", slot, "backup"))
        good = health("2026-10-20T07:37:10+02:00",
                      "2026-10-20T07:45:10+02:00")
        self.assertEqual(schedule_gate.decide("schedule", backup,
            at("2026-10-20T07:49:00+02:00"), good, {})[1],
            "SKIPPED_ALREADY_VALID_SNAPSHOT")
        ledger = {"slots": {slot: {
            "status": "PASS", "snapshot_run_id": "RUN7",
            "generated_at": good["generated_at"],
            "audit_at": good["audit_at"]}}}
        self.assertEqual(schedule_gate.decide("schedule", backup,
            at("2026-10-20T07:49:00+02:00"), good, ledger)[1],
            "SKIPPED_ALREADY_VALID_LEDGER")
        bad = good.copy()
        bad["audit_errors"] = 1
        self.assertTrue(schedule_gate.decide("schedule", backup,
            at("2026-10-20T07:49:00+02:00"), bad, ledger)[0])

    def test_all_slots_across_dst(self):
        # GitHub's official timezone property removes the old doubled UTC
        # cron list; the gate operates on actual CET/CEST Madrid timestamps.
        for date_str, offset in (("2026-10-20", "+02:00"),
                                 ("2026-10-26", "+01:00")):
            for nominal, pre in ((8,7),(11,10),(13,12),(17,16)):
                key = f"{date_str}T{nominal:02}:00"
                for minute, attempt in ((37,"primary"),(49,"backup")):
                    cron = f"{minute} 7,10,12,16 * * 1-5"
                    when = at(f"{date_str}T{pre:02}:{minute:02}:00{offset}")
                    self.assertEqual(schedule_gate.decide("schedule",cron,when,{},{}),
                        (True,"RUN_SCAN",key,attempt),(date_str,nominal,minute))
                for minute, attempt in ((13,"recovery"),(27,"recovery_late")):
                    cron = f"{minute} 8,11,13,17 * * 1-5"
                    when = at(f"{date_str}T{nominal:02}:{minute:02}:00{offset}")
                    self.assertEqual(schedule_gate.decide("schedule",cron,when,{},{}),
                        (True,"RUN_SCAN",key,attempt),(date_str,nominal,minute))

    def test_delayed_schedule_rescue_and_no_extra_slots(self):
        day = "2026-10-26"
        first = "37 7,10,12,16 * * 1-5"
        second = "13 8,11,13,17 * * 1-5"
        for at_time,expected in (("07:37","RUN_SCAN"),("08:12","RUN_SCAN"),
                                 ("08:44","RUN_SCAN"),("08:45","stale_or_offseason_schedule"),
                                 ("10:34","stale_or_offseason_schedule")):
            result = schedule_gate.decide("schedule",first,
                at(f"{day}T{at_time}:00+01:00"),{},{})
            self.assertEqual(result[1],expected,at_time)
        self.assertEqual(schedule_gate.decide("schedule", second,
            at(f"{day}T08:13:00+01:00"), {}, {})[3],"recovery")
        self.assertEqual(schedule_gate.decide("schedule", second,
            at(f"{day}T07:55:00+01:00"), {}, {})[1],
            "stale_or_offseason_schedule")
        self.assertFalse(schedule_gate.decide("schedule",first,
            at("2026-11-01T07:37:00+01:00"),{}, {})[0])
        # Previous 16 UTC crons must NEVER unexpectedly start extra scans.
        self.assertEqual(schedule_gate.decide("schedule","35 7 * * 1-5",
            at(f"{day}T07:35:00+01:00"),{}, {})[1],"unknown_schedule")

    def test_offseason_stale_and_bad_cron(self):
        cases=[
            ("35 7 * * 1-5","2026-10-20T09:35:00+02:00"),
            ("35 6 * * 1-5","2026-10-26T07:35:00+01:00"),
            ("35 6 * * 1-5","2026-10-20T08:34:00+02:00"),
            ("35 6 * * 1-5","2026-10-20T09:36:00+02:00"),
            ("5 7 * * 1-5","2026-10-20T09:05:00+02:00"),
            ("35 6 * * 1-5","2026-10-24T08:35:00+02:00"),
        ]
        for cron,when in cases:
            self.assertFalse(schedule_gate.decide("schedule",cron,at(when),{}, {})[0],(cron,when))

    def test_saturday_real_hourly_slots_and_retired_duplicate_cron(self):
        # Every Saturday slot 09..23 is a real workflow_dispatch from Cloudflare.
        for hour in range(9, 24):
            for minute, attempt in ((35,"primary"),(47,"backup")):
                slot=f"2026-10-24T{hour:02}:00"
                when=at(f"2026-10-24T{hour-1:02}:{minute}:00+02:00")
                result=schedule_gate.decide("workflow_dispatch","",when,{}, {},
                    slot_input=slot,attempt_input=attempt)
                self.assertEqual(result, (True,"RUN_SCAN",slot,"v2_"+attempt),slot)
        # Old GitHub Saturday schedule cannot compete with the Cloudflare path.
        self.assertEqual(schedule_gate.decide("schedule","27 8-21 * * 6",
            at("2026-10-24T10:27:00+02:00"),{}, {})[1],
            "saturday_probe_superseded_by_cloudflare")
        # GitHub code pushes must not start a separate Saturday scan.
        self.assertEqual(schedule_gate.decide("push","",
            at("2026-10-24T11:05:00+02:00"),{}, {})[1],
            "weekend_cloudflare_exclusive")
        # Later weekends cannot dispatch even with a valid hour.
        for date_str, offset in (("2026-10-31","+01:00"),("2026-11-01","+01:00")):
            for hour in (9,11,14,16,22):
                slot=f"{date_str}T{hour:02}:00"
                when=at(f"{date_str}T{hour-1:02}:35:00{offset}")
                result=schedule_gate.decide("workflow_dispatch","",when,{}, {},
                    slot_input=slot,attempt_input="primary")
                self.assertFalse(result[0],slot)

    def test_sunday_real_hourly_v2_and_no_duplicate_code_pushes(self):
        # Sunday 25 October is CET (UTC+1), unlike Saturday CEST.
        # Every nominal slot has exactly two allowed attempts.
        for hour in range(9, 24):
            for minute, attempt in ((35, "primary"), (47, "backup")):
                slot = f"2026-10-25T{hour:02}:00"
                when = at(f"2026-10-25T{hour-1:02}:{minute}:00+01:00")
                self.assertEqual(
                    schedule_gate.decide("workflow_dispatch", "", when, {}, {},
                        slot_input=slot, attempt_input=attempt),
                    (True, "RUN_SCAN", slot, "v2_" + attempt))
        # Code pushes on Sunday must not create competing unslotted scans.
        self.assertEqual(schedule_gate.decide("push", "",
            at("2026-10-25T09:20:00+01:00"), {}, {})[1],
            "weekend_cloudflare_exclusive")
        # Explicit rescue triggers remain available to perform a one-off scan.
        marker = "AUTO-PUBLIC manual public scan\npublic_data_only=true\n"
        self.assertEqual(schedule_gate.decide("push", "",
            at("2026-10-25T09:20:00+01:00"), {}, {},
            marker_changed=True, marker_text=marker)[1], "RUN_SCAN")
        for slot, when in (
            ("2026-10-25T09:00", "2026-10-25T09:46:00+01:00"),
            ("2026-10-25T10:00", "2026-10-25T08:34:00+01:00"),
            ("2026-11-01T09:00", "2026-11-01T08:35:00+01:00")):
            self.assertFalse(schedule_gate.decide("workflow_dispatch", "",
                at(when), {}, {}, slot_input=slot, attempt_input="primary")[0])

    def test_v2_dispatch_slot_and_backup(self):
        slot = "2026-10-20T08:00"
        a = schedule_gate.decide("workflow_dispatch","",
            at("2026-10-20T07:38:00+02:00"),{},{},
            slot_input=slot,attempt_input="primary")
        self.assertEqual(a,(True,"RUN_SCAN",slot,"v2_primary"))
        a = schedule_gate.decide("workflow_dispatch","",
            at("2026-10-20T07:49:00+02:00"),{},{},
            slot_input=slot,attempt_input="backup")
        self.assertEqual(a,(True,"RUN_SCAN",slot,"v2_backup"))
        h = health("2026-10-20T07:37:00+02:00","2026-10-20T07:45:00+02:00")
        a = schedule_gate.decide("workflow_dispatch","",
            at("2026-10-20T07:49:00+02:00"),h,{},
            slot_input=slot,attempt_input="backup")
        self.assertEqual(a,(True,"RUN_SCAN",slot,"v2_backup"))
        ledger = {"slots":{slot:{
            "status":"PASS","generated_at":h["generated_at"],
            "audit_at":h["audit_at"],"snapshot_run_id":"safe-run"}}}
        a = schedule_gate.decide("workflow_dispatch","",
            at("2026-10-20T07:49:00+02:00"),h,ledger,
            slot_input=slot,attempt_input="backup")
        self.assertEqual(a[1],"SKIPPED_ALREADY_VALID_LEDGER")
        for s,when,attempt in (
            (slot,"2026-10-20T08:46:00+02:00","backup"),
            (slot,"2026-10-20T07:34:00+02:00","primary"),
            ("2026-10-31T08:00","2026-10-31T07:35:00+01:00","primary")):
            self.assertFalse(schedule_gate.decide("workflow_dispatch","",
                at(when),{},{},slot_input=s,attempt_input=attempt)[0])
        for bad, attempt in (
            ("2026-10-20T08:30","primary"),
            (slot,"other"),
            ("2026-10-20T08:00+02:00","primary")):
            self.assertFalse(schedule_gate.decide("workflow_dispatch","",
                at("2026-10-20T07:38:00+02:00"),{},{},
                slot_input=bad,attempt_input=attempt)[0])

    def test_single_day_2015_controller_probe(self):
        slot = "2026-10-22T20:00"
        for when, attempt in (
            ("2026-10-22T20:15:00+02:00", "primary"),
            ("2026-10-22T20:27:00+02:00", "backup")):
            result = schedule_gate.decide("workflow_dispatch", "", at(when),
                {}, {}, slot_input=slot, attempt_input=attempt)
            self.assertEqual(result, (True, "RUN_SCAN", slot, "v2_" + attempt))
        for when, expected in (
            ("2026-10-22T20:46:00+02:00", "stale_v2_slot"),
            ("2026-10-23T20:15:00+02:00", "stale_v2_slot")):
            result = schedule_gate.decide("workflow_dispatch", "", at(when),
                {}, {}, slot_input=slot, attempt_input="primary")
            self.assertFalse(result[0])
            self.assertEqual(result[1], expected)
        self.assertFalse(schedule_gate.decide("workflow_dispatch", "",
            at("2026-10-23T20:15:00+02:00"), {}, {},
            slot_input="2026-10-23T20:00", attempt_input="primary")[0])

    def test_retired_extra_1830_candidates_are_rejected(self):
        for cron, when in (
            ("30 16 * * 1-5", "2026-10-20T18:30:00+02:00"),
            ("30 17 * * 1-5", "2026-10-26T18:30:00+01:00")):
            result = schedule_gate.decide("schedule", cron, at(when), {}, {})
            self.assertFalse(result[0])
            self.assertEqual(result[1], "unknown_schedule")

    def test_health_nominal_pre_hour_and_no_old_data(self):
        good=health("2026-10-20T08:35:10+02:00","2026-10-20T08:43:10+02:00")
        self.assertTrue(schedule_gate.valid_health(good,"2026-10-20T09:00"))
        self.assertFalse(schedule_gate.valid_health(good,"2026-10-20T11:00"))
        old=health("2026-10-20T08:31:00+02:00","2026-10-20T08:33:00+02:00")
        self.assertFalse(schedule_gate.valid_health(old,"2026-10-20T09:00"))
        bad=health("2026-10-20T08:35:00+02:00","2026-10-20T09:15:00+02:00")
        self.assertFalse(schedule_gate.valid_health(bad,"2026-10-20T09:00"))

    def test_rescue_and_expiry(self):
        marker = ("AUTO-PUBLIC scheduled-slot rescue\n"
                  "slot_local=2026-10-20T08:00:00+02:00\n"
                  "public_data_only=true\n")
        args = dict(marker_changed=True,marker_text=marker,
                    trigger_sha="abc",processed_sha="")
        a = schedule_gate.decide("push","",
            at("2026-10-20T08:05:00+02:00"),{},{},**args)
        self.assertEqual(a[2:4],("2026-10-20T08:00","rescue"))
        self.assertEqual(schedule_gate.decide("push","",
            at("2026-10-20T08:05:00+02:00"),{},{},
            **{**args,"processed_sha":"abc"})[1],"duplicate_push")
        self.assertEqual(schedule_gate.decide("push","",
            at("2026-10-20T15:00:00+02:00"),{},{},**args)[1],
            "rescue_slot_expired")
        self.assertIsNone(schedule_gate.parse_rescue(marker.replace("+02:00","+01:00")))

class TestPublicSanitizer(unittest.TestCase):
    def test_identifying_source_text_is_never_in_public_new_state(self):
        raw = {
            "generated_at":"2026-10-20T08:35:00+02:00",
            "run_id":"fixture",
            "territories":{"EDUBCN":{
                "documents":[{"url":"https://example.test/offer.pdf",
                   "text_excerpt":"Private applicant DNI: synthetic-example",
                   "sha256":"sha-test","target_hits":[{"code":"507",
                     "snippet":"synthetic applicant text"}]}],
                "global":{"row_samples":["synthetic applicant"],
                          "body_sha256":"stable-hash"},
                "freshness":"FRESC",
            }},
            "active_snapshot":{"territories":{"EDUBCN":{
                "current_target_placements":[{"placement_id":"GENSEC_2627_999",
                   "target_codes":["507"],"snippet":"synthetic applicant"}]}}}
        }
        cleaned=sanitize_public_state.sanitize(raw)
        sanitize_public_state.audit_absence(cleaned)
        payload=json.dumps(cleaned)
        self.assertNotIn("synthetic applicant",payload)
        self.assertEqual(cleaned["territories"]["EDUBCN"]["documents"][0]["sha256"],"sha-test")
        self.assertEqual(cleaned["active_snapshot"]["territories"]["EDUBCN"]
                         ["current_target_placements"][0]["placement_id"],
                         "GENSEC_2627_999")

    def test_file_sanitizer_preserves_snapshot_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            statefile=Path(tmp)/"latest.json"
            fixture={"generated_at":"2026-10-20T08:35:00+02:00",
                 "run_id":"one","territories":{"EDUBCN":{"text_excerpt":"person"}} ,
                 "active_snapshot":{"territories":{"EDUBCN":{"snippet":"person"}}}}
            statefile.write_text(json.dumps(fixture))
            with patch.object(sanitize_public_state,"SOURCE",statefile):
                self.assertEqual(sanitize_public_state.main(),0)
            new=json.loads(statefile.read_text())
            self.assertEqual(new["run_id"],"one")
            self.assertEqual(new["territories"]["EDUBCN"],{})
            self.assertEqual(new["active_snapshot"]["territories"]["EDUBCN"],{})

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
        for generated,audit in (
            ("2026-10-20T09:07:00+02:00","2026-10-20T09:12:00+02:00"),
            ("2026-10-20T08:35:00+02:00","2026-10-20T08:43:00+02:00"),
        ):
            with self.subTest(generated=generated), tempfile.TemporaryDirectory() as tmp:
                t=Path(tmp)
                h=health(generated,audit)
                (t/"health.json").write_text(json.dumps(h))
                (t/"consumer.json").write_text(json.dumps({
                    "generated_at":generated,"run_id":"RUN7"}))
                env={"STATE_DIR":str(t),"SLOT_KEY":"2026-10-20T09:00",
                     "SLOT_KIND":"primary","GITHUB_RUN_ID":"123","TRIGGER_SHA":"sha"}
                with patch.dict(os.environ,env):
                    self.assertEqual(slot_ledger.main(),0)
                    self.assertEqual(slot_ledger.main(),0)
                j=json.loads((t/"slot-ledger.json").read_text())
                self.assertEqual(j["slots"]["2026-10-20T09:00"]["status"],"PASS")
                self.assertEqual(len(j["slots"]),1)

class TestWorkflow(unittest.TestCase):
    def test_yaml(self):
        import yaml
        data=yaml.safe_load((REPO/".github/workflows/auto-places-docents.yml").read_text())
        on=data.get("on",data.get(True))
        expected={
            "37 7,10,12,16 * * 1-5",
            "49 7,10,12,16 * * 1-5",
            "13 8,11,13,17 * * 1-5",
            "27 8,11,13,17 * * 1-5",
        }
        self.assertEqual({x["cron"] for x in on["schedule"]},expected)
        self.assertEqual(len(on["schedule"]),4)
        self.assertTrue(all(x.get("timezone")=="Europe/Madrid"
                            for x in on["schedule"]))
        self.assertEqual(data["concurrency"]["queue"],"max")
        self.assertFalse(data["concurrency"]["cancel-in-progress"])
        self.assertIn("slot_local",on["workflow_dispatch"]["inputs"])
        self.assertIn("trigger_attempt",on["workflow_dispatch"]["inputs"])
        self.assertIn("AUTO V2",data["run-name"])
        self.assertEqual(data["jobs"]["monitor"]["runs-on"],"ubuntu-24.04")

    def test_deploy_is_manual_and_fails_closed(self):
        import yaml
        d=yaml.safe_load((REPO/".github/workflows/deploy-controller-v2.yml").read_text())
        on=d.get("on",d.get(True))
        self.assertEqual(set(on), {"workflow_dispatch"})
        self.assertEqual(d["permissions"]["contents"], "read")
        inputs=on["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["mode"]["default"], "dry-run")
        self.assertEqual(inputs["mode"]["options"],
                         ["dry-run", "deploy-disabled", "deploy-enabled"])
        self.assertIn("confirm_activation", inputs)
        job=d["jobs"]["deploy-controller"]
        self.assertEqual(job["runs-on"],"ubuntu-24.04")
        self.assertTrue(all("schedule" not in k for k in on))

if __name__ == "__main__":
    unittest.main()
