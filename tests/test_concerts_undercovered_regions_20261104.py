"""Historic regional reviews plus newer signed national additions."""
import copy
import datetime as dt
import json
import unittest
from pathlib import Path
from scripts import concerts_cloud_sync as sync

ROOT=Path(__file__).resolve().parents[1]
CAT=json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
TODAY=dt.date(2026,11,4)
NEW_IDS={a["id"] for spec in sync.UNDERCOVERED_REGIONS_NOV2026_VERIFIED.values()
         for a in spec["newArtists"]}

def reviewed(ident):
    spec=sync.UNDERCOVERED_REGIONS_NOV2026_VERIFIED[ident]
    return {
        "reviewDecision":"approved","reviewedBy":"independent-official-verifier",
        "reviewedAt":"2026-11-04",
        "officialEvidence":[
            {"url":spec["officialUrl"],"proofType":"official-organizer-or-venue",
             "checkedAt":"2026-11-04","checkedFields":
             ["artists","date","venue","genre"]+
             (["concertStartTime","doorTime"] if spec["time"] else [])},
            {"url":spec["calendarUrl"],"proofType":"first-party-venue-calendar",
             "checkedAt":"2026-11-04","checkedFields":["artists","date","venue"]}
        ],
        "event":{"id":ident,**{k:spec[k] for k in ("title","date","time","venueId",
                 "artistIds","genres","officialUrl")},"status":"confirmed","sourceType":"salle"},
        "newArtists":copy.deepcopy(spec["newArtists"]),
    }

def validate(row):
    venues={v["id"]:v for v in CAT["venues"]}
    # Keep the same test once the seven new artists are published.
    known={a["id"]:a for a in CAT["artists"] if a["id"] not in NEW_IDS}
    return sync.validate_approval(row,venues,known,TODAY)

class UndercoveredOfficialTests(unittest.TestCase):
    def test_regional_historic_and_new_signed_events(self):
        # Les dix fiches historiques sont le minimum, pas un plafond définitif.
        self.assertGreaterEqual(len(sync.UNDERCOVERED_REGIONS_NOV2026_VERIFIED),10)
        for ident,spec in sync.UNDERCOVERED_REGIONS_NOV2026_VERIFIED.items():
            with self.subTest(id=ident):
                ev,new=validate(reviewed(ident))
                self.assertEqual(ev["id"],ident)
                self.assertEqual(ev["date"],spec["date"])
                self.assertEqual(ev["venueId"],spec["venueId"])
                self.assertEqual(ev["time"],spec["time"])
                self.assertEqual(set(new),{a["id"] for a in spec["newArtists"]})
                self.assertEqual(len(ev["artistIds"]),len(spec["artistNames"]))

    def test_tampering_is_never_silently_published(self):
        for ident,spec in sync.UNDERCOVERED_REGIONS_NOV2026_VERIFIED.items():
            for key,value in (
                ("id","go-c-20281212-forged"),
                ("title","Unverified guest"),
                ("date","2028-01-01"),
                ("time","19:30" if spec["time"] is None else None),
                ("venueId","le-ferrailleur-nantes"),
                ("artistIds",["guest"]),
                ("genres",["Pop"]),
                ("officialUrl","https://example.com/forged-event"),
            ):
                with self.subTest(id=ident,field=key):
                    r=reviewed(ident)
                    r["event"][key]=value
                    with self.assertRaises(ValueError):
                        validate(r)

    def test_no_fake_first_part_and_fresh_official_sources(self):
        for ident,spec in sync.UNDERCOVERED_REGIONS_NOV2026_VERIFIED.items():
            with self.subTest(id=ident):
                row=reviewed(ident)
                row["newArtists"].append({"id":"guest","name":"Guest"})
                with self.assertRaises(ValueError):
                    validate(row)
                row=reviewed(ident)
                row["officialEvidence"][0]["checkedFields"].append("startTime")
                with self.assertRaises(ValueError):
                    validate(row)
                row=reviewed(ident)
                row["officialEvidence"][0]["checkedAt"]="2026-10-01"
                with self.assertRaises(ValueError):
                    validate(row)
                row=reviewed(ident)
                row["officialEvidence"].pop()
                with self.assertRaises(ValueError):
                    validate(row)

    def test_catalogue_retains_unlisted_preview_and_unique_events(self):
        self.assertEqual(CAT["mode"],"preview-public-unlisted")
        self.assertGreaterEqual(len(CAT["events"]),276)
        self.assertEqual(len({e["id"] for e in CAT["events"]}),len(CAT["events"]))
        published={e["id"]:e for e in CAT["events"]}
        for ident,spec in sync.UNDERCOVERED_REGIONS_NOV2026_VERIFIED.items():
            if ident in published:
                self.assertEqual(published[ident]["date"],spec["date"])
                self.assertEqual(published[ident]["venueId"],spec["venueId"])
                self.assertEqual(published[ident]["artistIds"],spec["artistIds"])

if __name__=="__main__":
    unittest.main()
