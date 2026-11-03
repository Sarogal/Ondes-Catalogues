"""Exactly signed Le Cargö FFF + DJ Bluff, door vs musical start provenance."""
import copy
import datetime as dt
import json
from pathlib import Path
import unittest
from scripts import concerts_cloud_sync as sync

ROOT=Path(__file__).resolve().parents[1]
TODAY=dt.date(2026, 11, 3)
ID="go-c-20261128-caen-fff-dj-bluff"

def case():
    spec=sync.CARGO_VERIFIED[ID]
    return {
        "reviewDecision":"approved",
        "reviewedBy":"independent-official-verifier",
        "reviewedAt":"2026-11-03",
        "officialEvidence":[{
            "url":spec["officialUrl"],
            "proofType":"official-organizer-or-venue",
            "checkedAt":"2026-11-03",
            "checkedFields":["artists","date","venue","genre",
                             "doorTime","concertStartTime"],
            "doorTimeConfirmed":"19:30",
            "concertStartTimeConfirmed":"20:30",
            "notes":("Fiche officielle Cargö: samedi 28 novembre 2026, "
                     "FFF + DJ Bluff, Grande salle; ouverture des portes 19h30, "
                     "Début des concerts 20h30, funk/rock sur la description.")
        }],
        "event":{
            "id":ID,
            "title":spec["title"],
            "date":spec["date"],
            "time":spec["time"],
            "artistIds":list(spec["artistIds"]),
            "venueId":spec["venueId"],
            "genres":list(spec["genres"]),
            "status":"confirmed",
            "officialUrl":spec["officialUrl"],
            "sourceType":"salle",
            "organizer":"Le Cargö"
        },
        "newArtists":[{"id":"dj-bluff","name":"DJ Bluff"}]
    }


class CargoWhitelistTests(unittest.TestCase):
    @staticmethod
    def data():
        cat=json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
        venues={v["id"]:v for v in cat["venues"]}
        artists={v["id"]:v for v in cat["artists"] if v["id"]!="dj-bluff"}
        return venues,artists

    def test_exact_fff_performers_date_venue_and_musical_start_accepted(self):
        venues, artists=self.data()
        row=case()
        event,new=sync.validate_approval(row,venues,artists,TODAY)
        self.assertEqual(event["time"],"20:30")
        self.assertEqual(event["date"],"2026-11-28")
        self.assertEqual(event["artistIds"],["fff","dj-bluff"])
        self.assertEqual(list(new),["dj-bluff"])
        self.assertEqual(row["officialEvidence"][0]["doorTimeConfirmed"],"19:30")
        self.assertEqual(row["officialEvidence"][0]["concertStartTimeConfirmed"],"20:30")

    def test_no_silent_substitution_or_door_as_start(self):
        venues, artists=self.data()
        bad=[]
        for field,value in (
            ("time","19:30"),("time",None),("date","2026-11-27"),
            ("genres",["Pop"]),("artistIds",["fff"]),("venueId","le-106-rouen"),
            ("officialUrl","https://lecargo.fr/programmation/concert/"),
            ("id","go-c-20261129-caen-fff-dj-bluff")):
            row=case()
            row["event"][field]=value
            bad.append(row)
        for field,value in (
            ("doorTimeConfirmed","20:30"),
            ("concertStartTimeConfirmed","19:30"),
            ("checkedAt","2026-11-01"),
            ("url","https://lecargo.fr/programmation/concert/"),
            ("checkedFields",["artists","date","venue","genre"])):
            row=case()
            row["officialEvidence"][0][field]=value
            bad.append(row)
        for row in bad:
            with self.subTest(changed=row),self.assertRaises((ValueError,KeyError)):
                sync.validate_approval(row,venues,artists,TODAY)

    def test_no_duplicate_festivals_or_published_concert(self):
        data=json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
        ids=[e for e in data["events"] if e["id"]==ID]
        self.assertLessEqual(len(ids),1)
        if ids:
            spec=sync.CARGO_VERIFIED[ID]
            for field in ("title","date","time","venueId","artistIds","genres","officialUrl"):
                self.assertEqual(ids[0][field],spec[field])
        clashes=[e for e in data["events"] if e["date"]=="2026-11-28"
                 and e["venueId"]=="le-cargo-caen" and "fff" in e["artistIds"]]
        self.assertLessEqual(len(clashes),1)

if __name__=="__main__":
    unittest.main()
