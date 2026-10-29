import unittest
from datetime import date
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from grossesondes_stage import can_add_muscadeath,eligible_autfest,eligible_vouziers,stage
from grossesondes_preview import CAL_URL,HIS_URL

def fixtures():
    cal={"schema":1,"generatedAt":"2026-10-25","festivals":[
        {"slug":f"festival-{i}-2027","name":"Test","status":"Confirmé",
         "startDate":"2027-02-01","endDate":"2027-02-02","notes":"ancien",
         "lastVerified":"2026-10-01"} for i in range(100)]}
    cal["festivals"][1].update({"slug":"autfest-2027","lineup":["Ultra Vomit","Septicflesh","Tagada Jones"],
                                "verificationStatus":"3 noms"})
    cal["festivals"][2].update({"slug":"festival-metal-vouziers-2026",
                                "sourceConfidence":"à recontrôler","verificationStatus":"en cours",
                                "auditSources":[]})
    hist={"schema":2,"updatedAt":"2026-10-22","knownFestivals":[
        {"slug":f"historique-{i}","name":"Archives"} for i in range(170)]}
    patch={"schema":"grossesondes.patch.v1","generated_at":"2026-10-29","safe_to_publish":False,
           "source":{"festivals":{"url":CAL_URL,"generatedAt":"2026-10-25","count":100},
                     "history":{"url":HIS_URL,"updatedAt":"2026-10-22","count":170}},
           "additions":[{"slug":"muscadeath-2027","name":"Muscadeath 2027",
                         "startDate":None,"endDate":None,"city":None,"department":None,
                         "region":None,"venue":None,"lat":None,"lon":None,"price":None,
                         "source":"https://muscadeath.fr/","status":"Dates à venir","showOnMap":False}],
           "updates":[{"slug":"autfest-2027","evidence":["https://www.billetweb.fr/autfest-anniversaire"],
                       "changes":[
                       {"field":"lineup","before":["Ultra Vomit","Septicflesh","Tagada Jones"],
                        "after":["Ultra Vomit","Septicflesh","Tagada Jones","Vanaheim","Hope as a weapon"]},
                       {"field":"notes","before":"ancien","after":"nouveau"},
                       {"field":"verificationStatus","before":"3 noms","after":"5 noms"},
                       {"field":"lastVerified","before":"2026-10-01","after":"2026-10-29"}]}],
           "history_additions":[],"history_updates":[],"deferred":[]}
    return cal,hist,patch

class StageTests(unittest.TestCase):
    def test_muscadeath_2027_confirmed_without_dates(self):
        e=fixtures()[2]["additions"][0]
        self.assertTrue(can_add_muscadeath(e,"Muscadeath rendez vous en 2027"))
        self.assertFalse(can_add_muscadeath(dict(e,startDate="2027-09-18"),"Muscadeath rendez vous en 2027"))
        self.assertFalse(can_add_muscadeath(e,"Muscadeath 2026"))
    def test_muscadeath_cannot_show_unconfirmed_pin(self):
        e=fixtures()[2]["additions"][0]
        self.assertFalse(can_add_muscadeath(dict(e,showOnMap=True),"muscadeath rendez vous en 2027"))
    def test_autfest_requires_five_official_groups(self):
        changes=fixtures()[2]["updates"][0]["changes"]
        body="AUTFEST 2027 LIEVIN Ultra Vomit Septicflesh Tagada Jones Vanaheim Hope as a weapon"
        self.assertTrue(eligible_autfest(changes,body.lower()))
        self.assertFalse(eligible_autfest(changes,body.lower().replace("vanaheim","absent")))
    def test_vouziers_requires_both_tariffs_and_date(self):
        changes=[{"field":x} for x in ("notes","sourceConfidence","verificationStatus","auditSources","lastVerified")]
        text="Festival Metal Vouziers 31 octobre 2026 Prévente 50 Sur place 55"
        self.assertTrue(eligible_vouziers(changes,text.lower()))
        self.assertFalse(eligible_vouziers(changes,text.lower().replace("31 octobre 2026","31 octobre 2025")))
    def test_stage_retains_every_existing_record(self):
        c,h,p=fixtures()
        sources={"muscadeath":"muscadeath rendez vous en 2027",
                 "autfest":"autfest 2027 lievin ultra vomit septicflesh tagada jones vanaheim hope as a weapon"}
        out,report=stage(c,h,p,sources,"2026-10-29")
        self.assertEqual(report["candidate_total"],101)
        self.assertEqual(len(report["accepted_updates"]),1)
        self.assertEqual(report["unmodified_festivals"],99)
        self.assertEqual(out["festivals"][-1]["slug"],"muscadeath-2027")
        self.assertEqual(c["festivals"][1]["lineup"],["Ultra Vomit","Septicflesh","Tagada Jones"])
        self.assertFalse(report["automatic_publication"])
    def test_stage_missing_source_does_not_accept(self):
        c,h,p=fixtures()
        out,report=stage(c,h,p,{},"2026-10-29")
        self.assertEqual(report["candidate_total"],100)
        self.assertEqual(len(report["held"]),2)
        self.assertEqual(out["festivals"],c["festivals"])
    def test_stage_rejects_wrong_base(self):
        c,h,p=fixtures()
        p["source"]["festivals"]["count"]=90
        with self.assertRaises(ValueError):stage(c,h,p,{},"2026-10-29")

if __name__=="__main__":
    unittest.main()
