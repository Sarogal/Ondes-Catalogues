"""Bonjour Minuit Saint-Brieuc, official Magma, no tentative time published."""
import copy
import datetime as dt
import json
from pathlib import Path
import unittest
from scripts import concerts_cloud_sync as sync

ROOT=Path(__file__).resolve().parents[1]
IDENT="go-c-20261202-saint-brieuc-magma"
VENUE="bonjour-minuit-saint-brieuc"
URL="https://bonjour-minuit.fr/evenement/magma-02dec26/"
GEO="https://acceslibre.beta.gouv.fr/app/22-saint-brieuc/a/salle-de-spectacle/erp/bonjour-minuit/"
DAY=dt.date(2026,11,3)

def signed_venue():
    v=copy.deepcopy(sync.PILOT_VENUES[VENUE]["venue"])
    return {"reviewDecision":"approved","reviewedBy":"independent-official-verifier",
            "reviewedAt":"2026-11-03",
            "officialEvidence":[
                {"url":"https://bonjour-minuit.fr/contact/",
                 "proofType":"official-venue-address",
                 "checkedAt":"2026-11-03",
                 "checkedFields":["name","address","postalCode","city"]},
                {"url":GEO,"proofType":"government-accessibility-location",
                 "checkedAt":"2026-11-03",
                 "checkedFields":["venueName","coordinates"]}],
            "venue":v}

def signed_event():
    return {"reviewDecision":"approved",
            "reviewedBy":"independent-official-verifier",
            "reviewedAt":"2026-11-03",
            "officialEvidence":[
                {"url":URL,"proofType":"official-organizer-or-venue",
                 "checkedAt":"2026-11-03",
                 "checkedFields":["artists","date","venue","genre"]},
                {"url":"https://bonjour-minuit.fr/agenda/",
                 "proofType":"first-party-venue-calendar",
                 "checkedAt":"2026-11-03",
                 "checkedFields":["artists","date","venue"]}],
            "event":{"id":IDENT,"title":"Magma","date":"2026-12-02",
                     "time":None,"artistIds":["magma"],"venueId":VENUE,
                     "genres":["Rock progressif"],"status":"confirmed",
                     "officialUrl":URL,"sourceType":"salle"},
            "newArtists":[]}

class BonjourMinuitCloudSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat=json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
        cls.venues={v["id"]:v for v in cls.cat["venues"]}
        cls.artists={a["id"]:a for a in cls.cat["artists"]}
        cls.venues[VENUE]=sync.PILOT_VENUES[VENUE]["venue"]

    def test_new_venue_signed_by_independent_government_point(self):
        venue=sync.validate_venue_approval(signed_venue(),DAY)
        self.assertEqual(venue["id"],VENUE)
        self.assertEqual((venue["latitude"],venue["longitude"]),(48.5196,-2.7852))
        self.assertEqual(venue["department"],"22")
        self.assertEqual(venue["geoSource"],GEO)
        self.assertIn("non assimilées",venue["geoPrecision"])
        for source,key,value in ((0,"url","https://example.net/infos"),
                                 (1,"url","https://example.net/carte"),
                                 (1,"proofType","non-official"),
                                 (1,"checkedFields",[])):
            bad=signed_venue()
            bad["officialEvidence"][source][key]=value
            with self.subTest(source=source,key=key):
                with self.assertRaises((ValueError,KeyError)):
                    sync.validate_venue_approval(bad,DAY)
        bad=signed_venue()
        bad["venue"]["latitude"]=47.0
        with self.assertRaises(ValueError):
            sync.validate_venue_approval(bad,DAY)

    def test_only_one_magma_exact_date_no_tentative_start(self):
        self.assertIn("magma",self.artists)
        spec=sync.BONJOUR_MINUIT_VERIFIED[IDENT]
        self.assertIsNone(spec["time"])
        ev,added=sync.validate_approval(signed_event(),self.venues,self.artists,DAY)
        self.assertEqual(ev["date"],"2026-12-02")
        self.assertIsNone(ev["time"])
        self.assertEqual(ev["artistIds"],["magma"])
        self.assertEqual(ev["genres"],["Rock progressif"])
        self.assertEqual(ev["venueId"],VENUE)
        self.assertEqual(added,{})
        self.assertEqual(len(self.cat["events"]),
                         len({e["id"] for e in self.cat["events"]}))

    def test_reject_wrong_year_start_artist_genre_venue_and_evidence(self):
        for key,value in (
            ("date","2027-12-02"),("time","20:00"),
            ("artistIds",["magma","invented"]),("genres",["Electro"]),
            ("venueId","antipode-rennes"),("title","Another headline"),
            ("officialUrl","https://bonjour-minuit.fr/agenda/"),
            ("status","cancelled"),
        ):
            with self.subTest(key=key):
                bad=signed_event()
                bad["event"][key]=value
                with self.assertRaises((ValueError,KeyError)):
                    sync.validate_approval(bad,self.venues,self.artists,DAY)
        for kind,key,value in (
            (0,"checkedFields",["artists","date","venue","genre","concertStartTime"]),
            (0,"url","https://bonjour-minuit.fr/evenement/other/"),
            (1,"url","https://example.org/agenda/"),
        ):
            with self.subTest(kind=kind,key=key):
                bad=signed_event()
                bad["officialEvidence"][kind][key]=value
                with self.assertRaises((ValueError,KeyError)):
                    sync.validate_approval(bad,self.venues,self.artists,DAY)

if __name__=="__main__":
    unittest.main()
