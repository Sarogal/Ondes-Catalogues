"""Le 106 Rouen: one exact already-known two-artist bill, no inferred start."""
import copy
import datetime as dt
import json
from pathlib import Path
import unittest
from scripts import concerts_cloud_sync as sync

ROOT=Path(__file__).resolve().parents[1]
ID="go-c-20261121-rouen-death-valley-girls-bella-bizarre"
TODAY=dt.date(2026,11,3)


def fixture():
    x=sync.ROUEN_DEATH_VALLEY_SIGNED[ID]
    return {
      "reviewDecision":"approved",
      "reviewedBy":"independent-official-verifier",
      "reviewedAt":"2026-11-03",
      "officialEvidence":[
       {"url":x["officialUrl"],"proofType":"official-organizer-or-venue",
        "checkedAt":"2026-11-03",
        "checkedFields":["artists","date","venue","genre"],
        "notes":"Noms, rock/proto-punk et garage punk, Le 106, 21/11/2026. 20h affiché, non attesté comme début musical."},
       {"url":x["calendarUrl"],"proofType":"first-party-venue-calendar",
        "checkedAt":"2026-11-03",
        "checkedFields":["artists","date","venue"],
        "notes":"Agenda officiel Le 106: samedi 21 novembre 2026, Death Valley Girls + Bella & the Bizarre."}
      ],
      "event":{
       "id":ID,"title":x["title"],"date":x["date"],"time":None,
       "artistIds":list(x["artistIds"]),"venueId":"le-106-rouen",
       "genres":list(x["genres"]),"status":"confirmed",
       "officialUrl":x["officialUrl"],"sourceType":"salle",
       "organizer":"Le 106"
      },
      "newArtists":[]
    }


class RouenDeathValleyTests(unittest.TestCase):
    @staticmethod
    def lookup():
        cat=json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
        return ({v["id"]:v for v in cat["venues"]},
                {a["id"]:a for a in cat["artists"]})

    def test_single_full_official_date_both_existing_artists_no_hour(self):
        venues,artists=self.lookup()
        self.assertIn("death-valley-girls",artists)
        self.assertIn("bella-and-the-bizarre",artists)
        event,added=sync.validate_approval(fixture(),venues,artists,TODAY)
        self.assertEqual(event["date"],"2026-11-21")
        self.assertEqual(event["artistIds"],["death-valley-girls","bella-and-the-bizarre"])
        self.assertEqual(event["venueId"],"le-106-rouen")
        self.assertIsNone(event["time"])
        self.assertEqual(added,{})

    def test_bad_official_details_ineligible(self):
        venues,artists=self.lookup()
        invalid=[]
        for key,value in (
            ("id","go-c-20261121-rouen-faux"),
            ("title","Death Valley Girls"),
            ("date","2026-11-20"),
            ("time","20:00"),
            ("artistIds",["death-valley-girls"]),
            ("venueId","le-cargo-caen"),
            ("genres",["Jazz"]),
            ("officialUrl","https://le106.com/agenda"),
            ("status","cancelled")):
            row=fixture()
            row["event"][key]=value
            invalid.append(row)
        for source in (0,1):
            for key,value in (
                ("url","https://wrong.example/agenda"),
                ("checkedFields",["date"]),
                ("checkedAt","2026-11-02")):
                row=fixture()
                row["officialEvidence"][source][key]=value
                invalid.append(row)
        for row in invalid:
            with self.subTest(row=row),self.assertRaises((ValueError,KeyError)):
                sync.validate_approval(row,venues,artists,TODAY)

    def test_no_duplicate_on_same_day_venue_artist(self):
        c=json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
        matching=[e for e in c["events"] if e["date"]=="2026-11-21"
                  and e["venueId"]=="le-106-rouen"
                  and "death-valley-girls" in e["artistIds"]]
        self.assertLessEqual(len(matching),1)
        if matching:
            x=sync.ROUEN_DEATH_VALLEY_SIGNED[ID]
            self.assertEqual(matching[0]["id"],ID)
            self.assertEqual(matching[0]["officialUrl"],x["officialUrl"])

if __name__=="__main__":
    unittest.main()
