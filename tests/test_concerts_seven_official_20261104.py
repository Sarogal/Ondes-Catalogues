"""Exact official seven-concert approval allowlist — never a generic venue permission."""
import copy
import datetime as dt
import json
from pathlib import Path
import unittest
from scripts import concerts_cloud_sync as sync

ROOT=Path(__file__).resolve().parents[1]
CAT=json.loads((ROOT/"docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
TODAY=dt.date(2026,11,4)
NEW_IDS={a["id"] for spec in sync.SEVEN_OFFICIAL_NOV2026_VERIFIED.values()
         for a in spec["newArtists"]}

def approval(ident):
    spec=sync.SEVEN_OFFICIAL_NOV2026_VERIFIED[ident]
    evidence=[{
        "url":spec["officialUrl"],
        "proofType":"official-organizer-or-venue",
        "checkedAt":"2026-11-04",
        "checkedFields":["artists","date","venue","genre"] +
            (["concertStartTime","doorTime"] if spec["time"] else [])
    }]
    if spec["calendarUrl"]:
        evidence.append({
            "url":spec["calendarUrl"],
            "proofType":"first-party-venue-calendar",
            "checkedAt":"2026-11-04",
            "checkedFields":["artists","date","venue"]
        })
    return {
        "reviewDecision":"approved",
        "reviewedBy":"independent-official-verifier",
        "reviewedAt":"2026-11-04",
        "officialEvidence":evidence,
        "event":{
            "id":ident,
            **{key:spec[key] for key in ("title","date","time","venueId",
                "artistIds","genres","officialUrl")},
            "status":"confirmed",
            "sourceType":"salle"
        },
        "newArtists":copy.deepcopy(spec["newArtists"])
    }

def validate(approval):
    venues={v["id"]:v for v in CAT["venues"]}
    # This fixture stays usable after the approved batch is published.
    artists={a["id"]:a for a in CAT["artists"] if a["id"] not in NEW_IDS}
    return sync.validate_approval(approval,venues,artists,TODAY)

class SevenOfficialSignedTests(unittest.TestCase):
    def test_all_seven_reviewed_exact_bills(self):
        self.assertEqual(len(sync.SEVEN_OFFICIAL_NOV2026_VERIFIED),7)
        for ident,spec in sync.SEVEN_OFFICIAL_NOV2026_VERIFIED.items():
            with self.subTest(ident=ident):
                ev, added=validate(approval(ident))
                self.assertEqual(ev["id"],ident)
                self.assertEqual(ev["title"],spec["title"])
                self.assertEqual(ev["time"],spec["time"])
                self.assertEqual(set(added),
                                 {a["id"] for a in spec["newArtists"]})

    def test_reject_tampered_identity_place_date_artists_start_genres_url(self):
        for ident,spec in sync.SEVEN_OFFICIAL_NOV2026_VERIFIED.items():
            for key,value in (
                    ("id","go-c-20270101-false-bill"),
                    ("date","2028-01-01"),
                    ("venueId","le-rex-toulouse"),
                    ("genres",["Pop"]),
                    ("artistIds",["invented-guest"]),
                    ("time","19:00" if spec["time"] is None else None),
                    ("officialUrl","https://example.org/not-official")):
                with self.subTest(ident=ident,field=key):
                    case=approval(ident)
                    case["event"][key]=value
                    with self.assertRaises(ValueError):
                        validate(case)

    def test_no_door_time_or_fake_guest_and_all_expected_proofs(self):
        for ident in sync.SEVEN_OFFICIAL_NOV2026_VERIFIED:
            with self.subTest(ident=ident):
                bad=approval(ident)
                bad["newArtists"].append({"id":"guest","name":"Guest"})
                with self.assertRaises(ValueError):
                    validate(bad)
                bad=approval(ident)
                bad["officialEvidence"][0]["checkedFields"].append("startTime")
                with self.assertRaises(ValueError):
                    validate(bad)
                bad=approval(ident)
                bad["officialEvidence"][0]["checkedAt"]="2026-10-01"
                with self.assertRaises(ValueError):
                    validate(bad)

    def test_published_preview_preserved_and_official_urls_not_reassigned(self):
        self.assertEqual(CAT["mode"],"preview-public-unlisted")
        self.assertGreaterEqual(len(CAT["events"]),269)
        self.assertEqual(len({e["id"] for e in CAT["events"]}),len(CAT["events"]))
        by_url={e["officialUrl"]:e for e in CAT["events"]}
        for ident,spec in sync.SEVEN_OFFICIAL_NOV2026_VERIFIED.items():
            if spec["officialUrl"] in by_url:
                e=by_url[spec["officialUrl"]]
                self.assertEqual(e["id"],ident)
                self.assertEqual(e["date"],spec["date"])
                self.assertEqual(e["venueId"],spec["venueId"])

if __name__=="__main__":
    unittest.main()
