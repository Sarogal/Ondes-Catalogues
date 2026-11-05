"""Publication strictement signée Saint-Quentin / Vitry-le-François."""
import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from concerts_cloud_sync import (
    PILOT_VENUES,
    TOURNEE_DU_COEUR_SAINT_QUENTIN_VITRY_SIGNED_20261105 as SPECS,
    TOURNEE_DU_COEUR_SAINT_QUENTIN_VITRY_VENUES_20261105 as GEO,
    validate_approval,
    validate_venue_approval,
)
TODAY=dt.date(2026,11,5)
CURRENT=json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
IDS=[
 "go-c-20270204-saint-quentin-cachemire-la-phaze-bobs-not-dead",
 "go-c-20270205-vitry-le-francois-cachemire-la-phaze-bobs-not-dead",
]
VENUE_IDS=["la-manufacture-saint-quentin","l-orange-bleue-vitry-le-francois"]
TRUSTED={
 VENUE_IDS[0]:{
   "url":"https://www.saint-quentin.fr/1674-la-manufacture.htm",
   "geo":"https://tofromfrance.com/lieu/le-concert-des-deux-pianos-a-la-manufacture",
   "coords":(49.85444,3.27029),"address":"8 rue Paul Codos"
 },
 VENUE_IDS[1]:{
   "url":"https://bords2scenes.fr/infos-pratiques/accueil-billetterie",
   "geo":"https://musitree.fr/concerts/salles/bords-2-scenes-lorange-bleue-vitry-le-francois/",
   "coords":(48.72668,4.57955),"address":"4 rue Auguste Choisy"
 },
}
def make_venue(key):
    spec=GEO[key]
    return {"reviewDecision":"approved","reviewedBy":"independent-official-verifier",
            "reviewedAt":"2026-11-05","venue":copy.deepcopy(spec["venue"]),
            "officialEvidence":[
               {"url":spec["officialUrl"],"proofType":"official-venue-address",
                "checkedAt":"2026-11-05","checkedFields":["name","address","postalCode","city"]},
               {"url":spec["locationUrl"],"proofType":"independent-named-venue-geolocation",
                "checkedAt":"2026-11-05","checkedFields":["venueName","coordinates"]},
            ]}
def make_event(key):
    spec=SPECS[key]
    return {"reviewDecision":"approved","reviewedBy":"independent-official-verifier",
            "reviewedAt":"2026-11-05","event":copy.deepcopy(spec["event"]),
            "newArtists":[],
            "officialEvidence":[{**copy.deepcopy(proof),"checkedAt":"2026-11-05"}
                                for proof in spec["proofs"]]}
class TourneeCoeurSaintQuentinVitryStrict(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.venues={v["id"]:v for v in CURRENT["venues"]}
        for key in VENUE_IDS:
            cls.venues[key]=validate_venue_approval(make_venue(key),TODAY)
        cls.artists={a["id"]:a for a in CURRENT["artists"]}

    def test_exact_events_and_new_venues(self):
        self.assertEqual(set(SPECS),set(IDS))
        self.assertEqual(set(GEO),set(VENUE_IDS))
        self.assertEqual(SPECS[IDS[0]]["event"]["time"],None)
        self.assertEqual(SPECS[IDS[1]]["event"]["time"],"21:00")
        for key in VENUE_IDS:
            self.assertEqual(PILOT_VENUES[key],GEO[key])
            v=self.venues[key]
            self.assertEqual(v["address"],TRUSTED[key]["address"])
            self.assertEqual((v["latitude"],v["longitude"]),TRUSTED[key]["coords"])
            self.assertEqual(v["geoSource"],TRUSTED[key]["geo"])
            self.assertEqual(GEO[key]["officialUrl"],TRUSTED[key]["url"])
        for key in IDS:
            with self.subTest(key=key):
                approval=make_event(key)
                entry,added=validate_approval(approval,self.venues,self.artists,TODAY)
                self.assertEqual(entry,SPECS[key]["event"])
                self.assertEqual(added,{})
                self.assertEqual(entry["artistIds"],
                    ["cachemire","la-phaze","bobs-not-dead"])
                existing=[e for e in CURRENT["events"] if e["id"]==key]
                self.assertLessEqual(len(existing),1)
                if existing:
                    for field in ("id","date","time","artistIds","venueId",
                                  "title","genres","officialUrl","status"):
                        self.assertEqual(existing[0][field],entry[field])

    def test_all_forged_events_rejected(self):
        for key in IDS:
            for what,mutate in [
                ("date",lambda x:x["event"].update(date="2027-03-01")),
                ("time",lambda x:x["event"].update(time="22:00")),
                ("venue",lambda x:x["event"].update(venueId="fake-venue")),
                ("artists",lambda x:x["event"]["artistIds"].append("fake-artist")),
                ("genres",lambda x:x["event"].update(genres=["Pop"])),
                ("url",lambda x:x["officialEvidence"][0].update(url="https://fake.org")),
                ("bill",lambda x:x["officialEvidence"][0].update(confirmedArtists=["Fake"])),
                ("promoter",lambda x:x["officialEvidence"][1].update(url="https://fake.org")),
                ("start",lambda x:x["officialEvidence"][0]["checkedFields"].append("startTime")),
                ("reviewer",lambda x:x.update(reviewedBy="automated-official-recheck")),
                ("oldReview",lambda x:x.update(reviewedAt="2026-08-01")),
                ("missingEvidence",lambda x:x["officialEvidence"].pop()),
            ]:
                row=make_event(key);mutate(row)
                with self.subTest(key=key,mutate=what),self.assertRaises(ValueError):
                    validate_approval(row,self.venues,self.artists,TODAY)

    def test_unapproved_bill_in_protected_venue_rejected(self):
        for venue in VENUE_IDS:
            row=make_event(IDS[0])
            row["event"]["id"]="go-c-20270204-fake-concert"
            row["event"]["venueId"]=venue
            with self.subTest(venue=venue),self.assertRaises(ValueError):
                validate_approval(row,self.venues,self.artists,TODAY)

    def test_geo_mutations_rejected(self):
        for key in VENUE_IDS:
            for name,mutate in [
                ("latitude",lambda x:x["venue"].update(latitude=0.0)),
                ("address",lambda x:x["venue"].update(address="Adresse inventée")),
                ("coordSource",lambda x:x["officialEvidence"][1].update(url="https://fake.org")),
                ("officialSource",lambda x:x["officialEvidence"][0].update(url="https://fake.org")),
                ("reviewer",lambda x:x.update(reviewedBy="automated-official-recheck")),
            ]:
                row=make_venue(key);mutate(row)
                with self.subTest(key=key,mutate=name),self.assertRaises(ValueError):
                    validate_venue_approval(row,TODAY)

if __name__=="__main__":
    unittest.main()
