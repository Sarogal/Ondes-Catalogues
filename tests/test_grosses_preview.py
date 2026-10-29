import unittest
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from grossesondes_preview import audit,CAL_URL,HIS_URL

def samples():
    c={"schema":1,"generatedAt":"2026-10-25","festivals":[
      {"slug":f"festival-{i}-2027","name":"Festival test","status":"Confirmé","price":"20 €",
       "startDate":"2027-02-01","endDate":"2027-02-02"} for i in range(100)]}
    h={"schema":2,"updatedAt":"2026-10-22","knownFestivals":[
      {"slug":f"festival-historique-{i}","name":"Hist"} for i in range(170)]}
    p={"schema":"grossesondes.patch.v1","safe_to_publish":False,"generated_at":"2026-10-29",
       "source":{"festivals":{"url":CAL_URL,"generatedAt":c["generatedAt"],"count":100},
                 "history":{"url":HIS_URL,"updatedAt":h["updatedAt"],"count":170}},
       "additions":[{"slug":"nouveau-2027","status":"Dates à venir","showOnMap":False}],
       "updates":[{"slug":"festival-1-2027","changes":[{"field":"price","before":"20 €","after":"25 €"}],
                   "evidence":["https://example.org/billet"]}],
       "history_additions":[],"history_updates":[],"deferred":[]}
    return c,h,p

class TestGrossesPreview(unittest.TestCase):
    def test_strict_preview(self):
        c,h,p=samples()
        z=audit(c,h,p,c,h)
        self.assertEqual(z["additions_to_review"],1)
        self.assertEqual(z["fields_to_review"],1)
        self.assertEqual(z["deleted"],0)
        self.assertIn("INTERDITE",z["publication"])
    def test_delete_historical_blocks(self):
        c,h,p=samples()
        old=dict(h,knownFestivals=h["knownFestivals"][:-1])
        with self.assertRaises(ValueError):audit(c,h,p,c,old)
    def test_changed_baseline_blocks(self):
        c,h,p=samples()
        old=dict(c,generatedAt="2026-10-29")
        with self.assertRaises(ValueError):audit(c,h,p,old,h)
    def test_unsafe_patch_blocks(self):
        c,h,p=samples();p["safe_to_publish"]=True
        with self.assertRaises(ValueError):audit(c,h,p,c,h)
    def test_wrong_before_blocks(self):
        c,h,p=samples();p["updates"][0]["changes"][0]["before"]="15 €"
        with self.assertRaises(ValueError):audit(c,h,p,c,h)
    def test_unknown_existing_field_blocks(self):
        c,h,p=samples();p["updates"][0]["changes"][0]["field"]="age"
        with self.assertRaises(ValueError):audit(c,h,p,c,h)
    def test_duplicate_field_blocks(self):
        c,h,p=samples()
        p["updates"][0]["changes"]*=2
        with self.assertRaises(ValueError):audit(c,h,p,c,h)
    def test_invented_marker_blocks(self):
        c,h,p=samples()
        p["additions"][0]["showOnMap"]=True
        with self.assertRaises(ValueError):audit(c,h,p,c,h)
    def test_history_updates_block(self):
        c,h,p=samples()
        p["history_updates"]=[{"slug":"festival-historique-1"}]
        with self.assertRaises(ValueError):audit(c,h,p,c,h)
    def test_unknown_status_blocks(self):
        c,h,p=samples()
        p["additions"][0]["status"]="Affirmé"
        with self.assertRaises(ValueError):audit(c,h,p,c,h)
if __name__=="__main__":
    unittest.main()
