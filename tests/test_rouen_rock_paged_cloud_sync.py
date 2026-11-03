"""Three independent Le 106 rock announcements, official dated page 1."""
import copy
import datetime as dt
import json
from pathlib import Path
import unittest
from scripts import concerts_cloud_sync as sync

ROOT=Path(__file__).resolve().parents[1]
DATE=dt.date(2026,11,3)
IDS=tuple(sync.ROUEN_ROCK_PAGED_VERIFIED)


def approval(event_id):
    s=sync.ROUEN_ROCK_PAGED_VERIFIED[event_id]
    return {
        "reviewDecision":"approved",
        "reviewedBy":"independent-official-verifier",
        "reviewedAt":"2026-11-03",
        "officialEvidence":[
            {"url":s["officialUrl"],"proofType":"official-organizer-or-venue",
             "checkedAt":"2026-11-03",
             "checkedFields":["artists","venue","genre"]},
            {"url":s["calendarUrl"],"proofType":"first-party-venue-calendar",
             "checkedAt":"2026-11-03",
             "checkedFields":["artists","date","venue"]}
        ],
        "event":{
            "id":event_id,"title":s["title"],"date":s["date"],
            "time":None,"artistIds":list(s["artistIds"]),
            "venueId":"le-106-rouen","genres":list(s["genres"]),
            "status":"confirmed","officialUrl":s["officialUrl"],
            "sourceType":"salle","organizer":"Le 106"
        },
        "newArtists":[{"id":aid,"name":s["artistNames"][i]}
            for i,aid in enumerate(s["artistIds"])
            if aid in s["newArtistIds"]]
    }


class RouenThreeRockOfficialTests(unittest.TestCase):
    @staticmethod
    def catalogue():
        j=json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
        fresh={aid for s in sync.ROUEN_ROCK_PAGED_VERIFIED.values()
               for aid in s["newArtistIds"]}
        venues={v["id"]:v for v in j["venues"]}
        known={a["id"]:a for a in j["artists"] if a["id"] not in fresh}
        return j,venues,known

    def test_exact_official_bills_accept_all_six_new_artists_without_time(self):
        _,venues,artists=self.catalogue()
        for id in IDS:
            with self.subTest(id=id):
                s=sync.ROUEN_ROCK_PAGED_VERIFIED[id]
                event,added=sync.validate_approval(approval(id),venues,artists,DATE)
                self.assertEqual(event["date"],s["date"])
                self.assertEqual(event["artistIds"],s["artistIds"])
                self.assertEqual(event["genres"],["Rock"])
                self.assertIsNone(event["time"])
                self.assertEqual(list(added),s["newArtistIds"])
        self.assertEqual(len({x for s in sync.ROUEN_ROCK_PAGED_VERIFIED.values()
                              for x in s["newArtistIds"]}),6)

    def test_venue_id_lineup_date_time_source_cannot_be_transplanted(self):
        _,venues,artists=self.catalogue()
        for id in IDS:
            for field,value in (
                ("id","go-c-20261210-rouen-faux"),
                ("title","Different band"),
                ("date","2027-01-01"),
                ("time","19:30"),
                ("artistIds",["made-up-band"]),
                ("venueId","le-cargo-caen"),
                ("genres",["Jazz"]),
                ("officialUrl","https://le106.com/agenda/fake-artist"),
                ("status","cancelled"),
            ):
                with self.subTest(id=id,field=field):
                    x=approval(id)
                    x["event"][field]=value
                    with self.assertRaises((ValueError,KeyError)):
                        sync.validate_approval(x,venues,artists,DATE)
            for idx in (0,1):
                for field,value in (
                    ("url","https://le106.com/agenda"),
                    ("checkedAt","2026-11-01"),
                    ("checkedFields",["artists"]),
                    ("proofType","other-proof"),
                ):
                    with self.subTest(id=id,idx=idx,field=field):
                        x=approval(id)
                        x["officialEvidence"][idx][field]=value
                        with self.assertRaises((ValueError,KeyError)):
                            sync.validate_approval(x,venues,artists,DATE)
            x=approval(id)
            x["officialEvidence"][0]["checkedFields"].append("date")
            with self.assertRaises(ValueError):
                sync.validate_approval(x,venues,artists,DATE)
            x=approval(id)
            x["newArtists"][0]["name"]="Impostor"
            with self.assertRaises((ValueError,KeyError)):
                sync.validate_approval(x,venues,artists,DATE)

    def test_public_dedupe_and_firstparty_page_one_required(self):
        cat,_,_=self.catalogue()
        for id in IDS:
            rows=[e for e in cat["events"] if e["id"]==id]
            self.assertLessEqual(len(rows),1)
            if rows:
                s=sync.ROUEN_ROCK_PAGED_VERIFIED[id]
                for key in ("title","date","time","venueId","artistIds",
                            "genres","officialUrl"):
                    self.assertEqual(rows[0][key],s[key])
        self.assertEqual(len(cat["events"]),len({x["id"] for x in cat["events"]}))


if __name__=="__main__":
    unittest.main()
