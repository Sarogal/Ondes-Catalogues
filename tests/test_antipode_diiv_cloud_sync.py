"""DIIV June 2027 named first-party Antipode ticket, exact solo artist."""
import copy
import datetime as dt
import json
from pathlib import Path
import unittest
from scripts import concerts_cloud_sync as sync

ROOT=Path(__file__).resolve().parents[1]
ID="go-c-20270602-rennes-diiv"
URL="https://antipode-rennes.fr/agenda/diiv-2027"

def approved():
    return {"reviewDecision":"approved",
        "reviewedBy":"independent-official-verifier",
        "reviewedAt":"2026-11-03",
        "officialEvidence":[
            {"url":URL,"proofType":"official-organizer-or-venue",
             "checkedAt":"2026-11-03",
             "checkedFields":["artists","date","venue","genre","concertStartTime","doorTime"],
             "concertStartTimeConfirmed":"20:30","doorTimeConfirmed":"20:00",
             "soldOutOnDetailAtReview":False},
            {"url":"https://antipode-rennes.fr/agenda",
             "proofType":"first-party-venue-calendar","checkedAt":"2026-11-03",
             "checkedFields":["artists","date","venue"]}],
        "event":{"id":ID,"title":"DIIV","date":"2027-06-02","time":"20:30",
                 "artistIds":["diiv"],"venueId":"antipode-rennes",
                 "genres":["Rock"],"status":"confirmed",
                 "officialUrl":URL,"sourceType":"salle"},
        "newArtists":[{"id":"diiv","name":"DIIV"}]}

class DiivOfficialSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalogue=json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
        cls.venues={v["id"]:v for v in cls.catalogue["venues"]}
        cls.artists={v["id"]:v for v in cls.catalogue["artists"] if v["id"]!="diiv"}

    def test_exact_only_one_new_artist_full_date_and_start(self):
        self.assertEqual(sync.ANTIPODE_RENNES_VERIFIED[ID]["newArtistIds"],["diiv"])
        self.assertIsNone(sync.ANTIPODE_RENNES_VERIFIED[ID]["organizer"])
        event,added=sync.validate_approval(approved(),self.venues,self.artists,
                                          dt.date(2026,11,3))
        self.assertEqual(event["date"],"2027-06-02")
        self.assertEqual(event["time"],"20:30")
        self.assertEqual(event["artistIds"],["diiv"])
        self.assertEqual(list(added),["diiv"])
        self.assertEqual(added["diiv"]["name"],"DIIV")

    def test_no_secondary_band_no_guessing_organizer_or_festival(self):
        bad_fields={"date":"2026-06-02","time":"20:00",
                    "artistIds":["diiv","unknown-opening-act"],
                    "title":"DIIV + unknown-opening-act",
                    "venueId":"l-etage-rennes","genres":["Rap"],
                    "status":"cancelled","sourceType":"festival",
                    "organizer":"Unverified Producer",
                    "officialUrl":"https://antipode-rennes.fr/agenda/fake"}
        for key,value in bad_fields.items():
            with self.subTest(key=key):
                row=approved()
                row["event"][key]=value
                with self.assertRaises((ValueError,KeyError)):
                    sync.validate_approval(row,self.venues,self.artists,dt.date(2026,11,3))
        for typ,key,value in (("detail","concertStartTimeConfirmed","20:00"),
                              ("detail","doorTimeConfirmed","20:30"),
                              ("detail","soldOutOnDetailAtReview",True),
                              ("calendar","url","https://example.org/agenda")):
            with self.subTest(typ=typ,key=key):
                row=approved()
                row["officialEvidence"][0 if typ=="detail" else 1][key]=value
                with self.assertRaises((ValueError,KeyError)):
                    sync.validate_approval(row,self.venues,self.artists,dt.date(2026,11,3))

    def test_previous_260_concerts_are_not_overwritten_by_new_diiv_spec(self):
        ids=[e["id"] for e in self.catalogue["events"]]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertLessEqual(ids.count(ID),1)
        self.assertEqual(len([e for e in self.catalogue["events"] if
                              e["venueId"]=="antipode-rennes" and
                              e["date"]=="2027-06-02"]),ids.count(ID))

if __name__=="__main__":
    unittest.main()
