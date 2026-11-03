"""Four Le 106 official rock/punk events: exact source, full date and bill."""
import copy
import datetime as dt
import json
from pathlib import Path
import unittest
from scripts import concerts_cloud_sync as sync

ROOT=Path(__file__).resolve().parents[1]
TODAY=dt.date(2026,11,3)
CASES={
    "go-c-20270311-rouen-steve-n-seagulls":(2,["steve-n-seagulls"]),
    "go-c-20270413-rouen-peter-hook-and-the-light":(2,["peter-hook-and-the-light"]),
    "go-c-20270515-rouen-tagada-jones":(2,[]),
    "go-c-20261212-rouen-maustetytot-francis":(1,["maustetytot","francis"]),
}

def approval(ident):
    spec=sync.ROUEN_ROCK_PAGED_VERIFIED[ident]
    return {
        "reviewDecision":"approved","reviewedBy":"independent-official-verifier",
        "reviewedAt":"2026-11-03",
        "officialEvidence":[
            {"url":spec["officialUrl"],"proofType":"official-organizer-or-venue",
             "checkedAt":"2026-11-03","checkedFields":["artists","venue","genre"]},
            {"url":spec["calendarUrl"],"proofType":"first-party-venue-calendar",
             "checkedAt":"2026-11-03","checkedFields":["artists","date","venue"]},
        ],
        "event":{"id":ident,"title":spec["title"],"date":spec["date"],
                 "time":None,"artistIds":list(spec["artistIds"]),
                 "venueId":"le-106-rouen","genres":list(spec["genres"]),
                 "status":"confirmed","officialUrl":spec["officialUrl"],
                 "sourceType":"salle","organizer":"Le 106"},
        "newArtists":[{"id":aid,"name":spec["artistNames"][i]}
                      for i,aid in enumerate(spec["artistIds"])
                      if aid in spec["newArtistIds"]]
    }

class RouenSecondWaveVerifiedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cat=json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
        cls.venues={v["id"]:v for v in cls.cat["venues"]}
        fresh={aid for ident in CASES for aid in sync.ROUEN_ROCK_PAGED_VERIFIED[ident]["newArtistIds"]}
        cls.artists={a["id"]:a for a in cls.cat["artists"] if a["id"] not in fresh}

    def test_all_four_exact_events_validate_without_start_times(self):
        for ident,(page,new_ids) in CASES.items():
            with self.subTest(ident=ident):
                spec=sync.ROUEN_ROCK_PAGED_VERIFIED[ident]
                self.assertEqual(spec["calendarUrl"],f"https://le106.com/agenda?page={page}")
                event,added=sync.validate_approval(approval(ident),self.venues,self.artists,TODAY)
                self.assertEqual(event["date"],spec["date"])
                self.assertEqual(list(added),new_ids)
                self.assertIsNone(event["time"])

    def test_transplants_calendar_pagination_dates_and_genres_are_rejected(self):
        for ident in CASES:
            for field,value in (("date","2027-08-08"),("title","unknown artist"),
                                ("time","20:00"),("venueId","le-cargo-caen"),
                                ("genres",["Jazz"]),("artistIds",["made-up"])):
                with self.subTest(ident=ident,field=field):
                    row=approval(ident)
                    row["event"][field]=value
                    with self.assertRaises((ValueError,KeyError)):
                        sync.validate_approval(row,self.venues,self.artists,TODAY)
            for wrong in ("https://le106.com/agenda?page=1","https://le106.com/agenda?page=2",
                          "https://le106.com/agenda"):
                if wrong==approval(ident)["officialEvidence"][1]["url"]:
                    continue
                with self.subTest(ident=ident,wrong_calendar=wrong):
                    row=approval(ident)
                    row["officialEvidence"][1]["url"]=wrong
                    with self.assertRaises((ValueError,KeyError)):
                        sync.validate_approval(row,self.venues,self.artists,TODAY)

    def test_no_duplicate_ids_or_same_venue_date_artist(self):
        ids=[e["id"] for e in self.cat["events"]]
        self.assertEqual(len(ids),len(set(ids)))
        for ident in CASES:
            spec=sync.ROUEN_ROCK_PAGED_VERIFIED[ident]
            existing=[e for e in self.cat["events"]
                      if e["date"]==spec["date"] and e["venueId"]=="le-106-rouen"
                      and bool(set(e["artistIds"]) & set(spec["artistIds"]))]
            self.assertLessEqual(len(existing),1)
            if existing:
                self.assertEqual(existing[0]["id"],ident)

if __name__=="__main__":
    unittest.main()
