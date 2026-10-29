import unittest
from datetime import date
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from merge_policy import merge,validate_patch,valid,safe_published_event
from proof import norm,names,meters,LD,proof

TODAY=date(2026,10,29)
URL="https://ptitesondes.fr/config/sorties.json"
def event(i):
    return {"id":f"existant-{i}","title":f"Titre {i}","category":"concert","category_label":"Concert",
            "date_start":"2027-02-02","date_end":"2027-02-02","city":"Bordeaux","department":"Gironde (33)",
            "region":"Nouvelle-Aquitaine","venue":"Auditorium de Bordeaux","source_url":"https://www.opera-bordeaux.com/agenda",
            "source_label":"Opéra de Bordeaux","verified_at":"2026-10-29","geo_verified_at":"2026-10-29",
            "geo_precision":"venue","lat":44.842222,"lng":-0.579722}
def fixture():
    b={"version":3,"updated_at":"2026-10-22T21:00:00+02:00","events":[event(i) for i in range(100)]}
    x=dict(event(100),id="nouvelle-concert-2027-02-02",title="Nouveau concert")
    p={"schema":"ptitesondes.patch.v1","generated_at":"2026-10-29",
       "source":{"url":URL,"version":3,"updated_at":b["updated_at"],"events_count":100},
       "safe_to_publish":False,"additions":[x],"updates":[],"deferred":[],
       "checks":{"ids_unique":True,"official_sources_verified":True}}
    return b,p

class TestsCloud(unittest.TestCase):
    def test_add_with_proof(self):
        b,p=fixture()
        out,r=merge(b,b,p,TODAY,checker=lambda e,ref:(True,"preuve"))
        self.assertEqual(len(out["events"]),101)
        self.assertEqual(r["ajoutes"],1)
        self.assertEqual(out["events"][:100],b["events"])
        self.assertEqual(r["suppression"],0)

    def test_no_proof_no_publication(self):
        b,p=fixture()
        out,r=merge(b,b,p,TODAY,checker=lambda e,ref:(False,"non vérifié"))
        self.assertEqual(out,b)
        self.assertEqual(r["ajoutes"],0)
        self.assertEqual(len(r["attente"]),1)

    def test_already_published_is_idempotent(self):
        b,p=fixture()
        o=dict(b,events=b["events"]+[p["additions"][0]])
        out,r=merge(b,o,p,TODAY,checker=lambda e,ref:(False,"non vérifié"))
        self.assertEqual(len(out["events"]),101)
        self.assertEqual(r["ajoutes"],0)

    def test_unchecked_description_is_replaced(self):
        b,p=fixture()
        b["events"][0]["description"]="Description historique"
        p["additions"][0]["description"]="Promesse non vérifiée."
        out,r=merge(b,b,p,TODAY,checker=lambda e,ref:(True,"preuve"))
        self.assertEqual(r["ajoutes"],1)
        self.assertNotIn("Promesse non vérifiée.",out["events"][-1]["description"])
        self.assertIn("source officielle",out["events"][-1]["description"])

    def test_sanitized_catalogue_is_idempotent(self):
        b,p=fixture()
        p["additions"][0]["description"]="Description non auditée"
        accepted=safe_published_event(p["additions"][0])
        published=dict(b,events=b["events"]+[accepted])
        out,r=merge(b,published,p,TODAY,checker=lambda e,ref:(False,"sans appel"))
        self.assertEqual(len(out["events"]),101)
        self.assertEqual(r["ajoutes"],0)

    def test_historical_deletion_blocked(self):
        b,p=fixture()
        o=dict(b,events=b["events"][1:])
        with self.assertRaises(ValueError):merge(b,o,p,TODAY)

    def test_historical_tampering_blocked(self):
        b,p=fixture()
        o=dict(b,events=[dict(b["events"][0],title="Faux")]+b["events"][1:])
        with self.assertRaises(ValueError):merge(b,o,p,TODAY)

    def test_collision_blocked(self):
        b,p=fixture()
        o=dict(b,events=b["events"]+[dict(p["additions"][0],title="Autre")])
        with self.assertRaises(ValueError):merge(b,o,p,TODAY)

    def test_duplicate_patch_blocked(self):
        b,p=fixture()
        p["additions"]*=2
        with self.assertRaises(ValueError):merge(b,b,p,TODAY)

    def test_unknown_category_pending(self):
        b,p=fixture()
        p["additions"][0]["category"]="fantaisie"
        out,r=merge(b,b,p,TODAY,checker=lambda e,ref:(True,"preuve"))
        self.assertEqual(r["ajoutes"],0)

    def test_invalid_geo_pending(self):
        b,p=fixture()
        p["additions"][0]["lat"]=999
        out,r=merge(b,b,p,TODAY,checker=lambda e,ref:(True,"preuve"))
        self.assertEqual(r["ajoutes"],0)

    def test_patch_update_rejected(self):
        b,p=fixture()
        p["updates"]=[{"id":"existant-1"}]
        with self.assertRaises(ValueError):merge(b,b,p,TODAY)

    def test_wrong_baseline_rejected(self):
        b,p=fixture()
        p["source"]["events_count"]=42
        with self.assertRaises(ValueError):merge(b,b,p,TODAY)

    def test_future_patch_rejected(self):
        b,p=fixture()
        p["generated_at"]="2026-10-30"
        with self.assertRaises(ValueError):merge(b,b,p,TODAY)

    def test_normalized_names(self):
        self.assertTrue(names("Auditorium de Bordeaux","Auditorium de Bordeaux"))
        self.assertFalse(names("Théâtre du Châtelet","Auditorium de Bordeaux"))

    def test_distance(self):
        self.assertLess(meters((44.842222,-0.579722),(44.842222,-0.579722)),1)
        self.assertGreater(meters((44.842222,-0.579722),(48.85777,2.34613)),100000)

    def test_ld_parser(self):
        p=LD()
        p.feed('<script type="application/ld+json">{"@type":"Event","name":"Concert"}</script>')
        self.assertEqual(len(p.blocks),1)

if __name__=="__main__":
    unittest.main()
