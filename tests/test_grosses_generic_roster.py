import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from grossesondes_generic_roster import validate_roster
from grossesondes_stage import stage
from test_grosses_stage import fixtures

ORIGINAL={
    "slug":"festival-du-marais-2027",
    "name":"Festival du Marais 2027",
    "startDate":"2027-07-16","endDate":"2027-07-17",
    "city":"Chartres","lineup":["Anciens Titans","Foudre Blanche"],
    "bands":2,"notes":"ancienne programmation",
    "verificationStatus":"deux groupes",
    "sourceConfidence":"ancienne annonce",
    "auditSources":["https://festival-du-marais.example/programmation"],
    "lastVerified":"2026-10-01",
    "officialSite":"https://festival-du-marais.example/",
    "status":"Confirmé"
}
DOCUMENT=("Bienvenue au FESTIVAL DU MARAIS 2027. "
          "PROGRAMMATION 2027 : Nouveaux Métaux - Tempête Noire "
          "spectacles et concerts.")
def proposal(extra=("Nouveaux Métaux","Tempête Noire")):
    after=list(ORIGINAL["lineup"])+list(extra)
    data={
        "lineup":after,
        "bands":len(after),
        "notes":"nouveaux groupes",
        "verificationStatus":"mise à jour",
        "sourceConfidence":"source officielle",
        "auditSources":["https://festival-du-marais.example/"],
        "lastVerified":"2026-10-29",
    }
    return {"slug":ORIGINAL["slug"],"evidence":["https://festival-du-marais.example/"],
           "changes":[{"field":k,"before":ORIGINAL[k],"after":v} for k,v in data.items()]}

class GenericRosterTests(unittest.TestCase):
    def test_two_official_names_accepted(self):
        got=validate_roster(ORIGINAL,proposal(),DOCUMENT)
        self.assertIsNotNone(got)
        edited,fields,pending=got
        self.assertEqual(edited["lineup"],ORIGINAL["lineup"]+["Nouveaux Métaux","Tempête Noire"])
        self.assertEqual(edited["bands"],4)
        self.assertEqual(pending,[])
        self.assertEqual(ORIGINAL["bands"],2)
    def test_one_missing_is_held(self):
        got=validate_roster(ORIGINAL,proposal(("Nouveaux Métaux","Non annoncé")),DOCUMENT)
        self.assertIsNotNone(got)
        edited,fields,pending=got
        self.assertEqual(edited["bands"],3)
        self.assertEqual(pending,["Non annoncé"])
    def test_no_year_anchor_rejects(self):
        self.assertIsNone(validate_roster(ORIGINAL,proposal(),DOCUMENT.replace("PROGRAMMATION 2027","PROGRAMMATION 2026")))
    def test_no_festival_identity_rejects(self):
        self.assertIsNone(validate_roster(ORIGINAL,proposal(),DOCUMENT.replace("FESTIVAL DU MARAIS","FESTIVAL DU NORD")))
    def test_year_from_existing_date_not_candidate(self):
        original=dict(ORIGINAL,startDate="2026-07-16")
        self.assertIsNone(validate_roster(original,proposal(),DOCUMENT))
    def test_removal_rejected(self):
        item=proposal()
        item["changes"][0]["after"]=["Foudre Blanche","Nouveaux Métaux"]
        self.assertIsNone(validate_roster(ORIGINAL,item,DOCUMENT))
    def test_date_field_rejected(self):
        item=proposal()
        item["changes"].append({"field":"startDate","before":"2027-07-16","after":"2027-07-21"})
        self.assertIsNone(validate_roster(ORIGINAL,item,DOCUMENT))
    def test_unsupported_price_field_rejected(self):
        item=proposal()
        item["changes"].append({"field":"price","before":None,"after":"1 €"})
        self.assertIsNone(validate_roster(ORIGINAL,item,DOCUMENT))
    def test_mismatched_band_count_rejected(self):
        item=proposal()
        item["changes"][1]["after"]=999
        self.assertIsNone(validate_roster(ORIGINAL,item,DOCUMENT))
    def test_no_substantial_new_evidence_rejected(self):
        self.assertIsNone(validate_roster(ORIGINAL,proposal(),DOCUMENT.replace("Nouveaux Métaux","Autre groupe").replace("Tempête Noire","Autre nom")))
    def test_stage_integration_without_network(self):
        c,h,p=fixtures()
        c["festivals"][3]=dict(ORIGINAL)
        p["updates"]=[proposal()]
        p["additions"]=[]
        out,rep=stage(c,h,p,{"registered:festival-du-marais-2027":DOCUMENT},"2026-10-29")
        self.assertEqual(out["festivals"][3]["bands"],4)
        self.assertEqual(len(rep["accepted_updates"]),1)
        self.assertEqual(rep["held"],[])
        self.assertEqual(len(out["festivals"]),100)
        self.assertEqual(len(h["knownFestivals"]),170)

if __name__=="__main__":
    unittest.main()
