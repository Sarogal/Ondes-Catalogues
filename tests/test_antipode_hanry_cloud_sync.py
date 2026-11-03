"""Hanry apéro-concert: exact official Rock, Le Club and 19:30 show start."""
import copy
import datetime as dt
import json
from pathlib import Path
import unittest
from scripts import concerts_cloud_sync as sync

ROOT=Path(__file__).resolve().parents[1]
IDENT="go-c-20261216-rennes-hanry"
URL="https://antipode-rennes.fr/agenda/hanry-2026"
DAY=dt.date(2026,11,3)

def row():
    return {
        "reviewDecision":"approved",
        "reviewedBy":"independent-official-verifier",
        "reviewedAt":"2026-11-03",
        "officialEvidence":[
            {"url":URL,"proofType":"official-organizer-or-venue",
             "checkedAt":"2026-11-03",
             "checkedFields":["artists","date","venue","genre",
                              "concertStartTime","doorTime"],
             "concertStartTimeConfirmed":"19:30",
             "doorTimeConfirmed":"19:00",
             "soldOutOnDetailAtReview":False},
            {"url":"https://antipode-rennes.fr/agenda",
             "proofType":"first-party-venue-calendar",
             "checkedAt":"2026-11-03",
             "checkedFields":["artists","date","venue"]},
        ],
        "event":{"id":IDENT,"title":"Apéro-concert avec Hanry",
                 "date":"2026-12-16","time":"19:30",
                 "artistIds":["hanry"],"venueId":"antipode-rennes",
                 "genres":["Rock"],"status":"confirmed",
                 "officialUrl":URL,"sourceType":"salle",
                 "organizer":"Antipode"},
        "newArtists":[{"id":"hanry","name":"Hanry"}],
    }

class HanryCloudSignedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cat=json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
        cls.venues={v["id"]:v for v in cat["venues"]}
        cls.artists={a["id"]:a for a in cat["artists"] if a["id"]!="hanry"}
        cls.ids={e["id"] for e in cat["events"]}
        cls.count=len(cat["events"])

    def test_exact_individually_allowed_event_with_distinct_door_and_start(self):
        spec=sync.ANTIPODE_RENNES_VERIFIED[IDENT]
        self.assertEqual(spec["time"],"19:30")
        self.assertEqual(spec["doorTime"],"19:00")
        self.assertEqual(spec["artistNames"],["Hanry"])
        ev,artists=sync.validate_approval(row(),self.venues,self.artists,DAY)
        self.assertEqual(ev["time"],"19:30")
        self.assertEqual(ev["artistIds"],["hanry"])
        self.assertEqual(ev["venueId"],"antipode-rennes")
        self.assertEqual(set(artists),{"hanry"})
        self.assertEqual(artists["hanry"]["name"],"Hanry")
        # Both before and after secure synchronization are valid states.
        # Publication must not create duplicate event identifiers.
        self.assertEqual(len(self.ids),self.count)
        self.assertGreaterEqual(self.count,261)

    def test_reject_forged_year_artist_venue_and_wrong_clock_provenance(self):
        for key,value in (
            ("title","Fictitious band"),("date","2027-12-16"),
            ("time","19:00"),("genres",["Rap"]),
            ("artistIds",["hanry","unknown-open"]),("venueId","l-etage-rennes"),
            ("status","cancelled"),
            ("organizer","Invented promoter"),
            ("officialUrl","https://antipode-rennes.fr/agenda/unknown"),
        ):
            with self.subTest(key=key):
                bad=row()
                bad["event"][key]=value
                with self.assertRaises((ValueError,KeyError)):
                    sync.validate_approval(bad,self.venues,self.artists,DAY)
        for kind,key,value in (
            (0,"doorTimeConfirmed","20:00"),
            (0,"concertStartTimeConfirmed","19:00"),
            (0,"soldOutOnDetailAtReview",True),
            (1,"url","https://example.org/agenda"),
        ):
            with self.subTest(kind=kind,key=key):
                bad=row()
                bad["officialEvidence"][kind][key]=value
                with self.assertRaises((ValueError,KeyError)):
                    sync.validate_approval(bad,self.venues,self.artists,DAY)

if __name__=="__main__":
    unittest.main()
