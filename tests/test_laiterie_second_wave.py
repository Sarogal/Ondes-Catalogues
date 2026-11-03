"""Verrou de publication de quatre concerts Artefact dûment contrôlés."""
import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from concerts_cloud_sync import LAITERIE_SECOND_WAVE_VERIFIED, validate_approval

CAT=json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
VENUES={x["id"]:x for x in CAT["venues"]}
ARTISTS={x["id"]:x for x in CAT["artists"]}
TODAY=dt.date(2026,11,3)

def row(event_id,spec):
    return {
        "reviewDecision":"approved",
        "reviewedBy":"independent-official-verifier",
        "reviewedAt":"2026-11-03",
        "officialEvidence":[
           {"url":spec["officialUrl"],"proofType":"official-organizer-or-venue",
            "checkedAt":"2026-11-03","checkedFields":["artists","date","venue","genre"]},
           {"url":spec["calendarUrl"],"proofType":"first-party-venue-calendar",
            "checkedAt":"2026-11-03","checkedFields":["artists","date","venue","genre"]}
        ],
        "event":{"id":event_id,"title":spec["title"],"date":spec["date"],
                 "time":None,"artistIds":copy.deepcopy(spec["artistIds"]),
                 "venueId":"la-laiterie-strasbourg","genres":copy.deepcopy(spec["genres"]),
                 "status":"confirmed","officialUrl":spec["officialUrl"],
                 "sourceType":"salle"},
        "newArtists":copy.deepcopy(spec["newArtists"])
    }

class SecondWaveLaiterieSecurityTests(unittest.TestCase):
    def test_four_official_bills_and_rejected_mutations(self):
        self.assertEqual(len(LAITERIE_SECOND_WAVE_VERIFIED),4)
        existing_ids={e["id"] for e in CAT["events"]}
        for event_id,spec in LAITERIE_SECOND_WAVE_VERIFIED.items():
            with self.subTest(event_id=event_id):
                # Recreate the prepublication artist index so the test
                # remains valid after these entries are published.
                fresh={a["id"] for a in spec["newArtists"]}
                known={k:v for k,v in ARTISTS.items() if k not in fresh}
                review=row(event_id,spec)
                event,artists=validate_approval(review,VENUES,known,TODAY)
                self.assertEqual(event["id"],event_id)
                self.assertIsNone(event["time"])
                self.assertEqual(set(artists),fresh)
                if event_id in existing_ids:
                    published=next(x for x in CAT["events"] if x["id"]==event_id)
                    self.assertEqual(published["officialUrl"],spec["officialUrl"])
                    self.assertEqual(published["artistIds"],spec["artistIds"])
                for case in ("start-from-doors","wrong-day","unknown-artist","wrong-venue",
                             "missing-calendar","third-party-url","bad-genre"):
                    bad=copy.deepcopy(review)
                    if case=="start-from-doors":
                        bad["event"]["time"]="19:30"
                    elif case=="wrong-day":
                        bad["event"]["date"]="2027-01-01"
                    elif case=="unknown-artist":
                        bad["event"]["artistIds"]=["unconfirmed"]
                    elif case=="wrong-venue":
                        bad["event"]["venueId"]="le-rex-toulouse"
                    elif case=="missing-calendar":
                        bad["officialEvidence"].pop()
                    elif case=="third-party-url":
                        bad["event"]["officialUrl"]="https://example.org/event"
                    else:
                        bad["event"]["genres"]=["Unknown"]
                    with self.assertRaises((ValueError,KeyError)):
                        validate_approval(bad,VENUES,known,TODAY)

if __name__=="__main__":
    unittest.main()
