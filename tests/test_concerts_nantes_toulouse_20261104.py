"""Le synchroniseur accepte seulement le lot officiel Nantes/Toulouse signé."""
import copy
import datetime as dt
import json
from pathlib import Path
import unittest
from scripts import concerts_cloud_sync as sync

ROOT = Path(__file__).resolve().parents[1]
CURRENT = json.loads((ROOT / "docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
DATE = dt.date(2026, 11, 4)

def signed(spec):
    return {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": DATE.isoformat(),
        "officialEvidence": [{
            "url": spec["officialUrl"],
            "proofType": "official-organizer-or-venue",
            "checkedAt": DATE.isoformat(),
            "checkedFields": ["artists", "date", "venue", "genre"] +
                             (["concertStartTime"] if spec["time"] else [])
        }],
        "event": {
            **{key: spec[key] for key in
               ("title", "date", "time", "venueId", "artistIds",
                "genres", "officialUrl")},
            "id": next(key for key, value
                       in sync.NANTES_TOULOUSE_NOV2026_VERIFIED.items()
                       if value is spec),
            "status": "confirmed",
            "sourceType": "salle"
        },
        "newArtists": copy.deepcopy(spec["newArtists"])
    }

def validate(row):
    venues = {v["id"]: v for v in CURRENT["venues"]}
    # The fixture must remain valid after GitHub Pages has published the new artists.
    # They are added by validate_approval, not pre-registered for this test.
    incoming_artist_ids = {artist["id"]
                           for spec in sync.NANTES_TOULOUSE_NOV2026_VERIFIED.values()
                           for artist in spec["newArtists"]}
    artists = {a["id"]: a for a in CURRENT["artists"]
               if a["id"] not in incoming_artist_ids}
    return sync.validate_approval(row, venues, artists, DATE)

class NantesToulouseOfficialSignedTests(unittest.TestCase):
    def test_four_exact_official_affiches(self):
        self.assertEqual(len(sync.NANTES_TOULOUSE_NOV2026_VERIFIED), 4)
        for ident, spec in sync.NANTES_TOULOUSE_NOV2026_VERIFIED.items():
            with self.subTest(ident=ident):
                row = signed(spec)
                event, added = validate(row)
                self.assertEqual(event["id"], ident)
                self.assertEqual(set(added), {a["id"] for a in spec["newArtists"]})
                self.assertEqual(event["time"], spec["time"])
                self.assertTrue(event["officialUrl"].startswith("https://"))

    def test_wrong_date_venue_url_lineup_genres_or_hour_is_held(self):
        specs = sync.NANTES_TOULOUSE_NOV2026_VERIFIED
        for ident, spec in specs.items():
            row = signed(spec)
            for name, value in (
                ("date", "2028-01-01"),
                ("venueId", "le-bikini-toulouse"),
                ("officialUrl", "https://example.org/attacker"),
                ("genres", ["Pop"]),
                ("time", "19:30" if spec["time"] is None else None),
                ("artistIds", ["faux-groupe"])):
                with self.subTest(id=ident, field=name):
                    bad = copy.deepcopy(row)
                    bad["event"][name] = value
                    with self.assertRaises(ValueError):
                        validate(bad)

    def test_no_invented_support_and_no_door_time_as_start(self):
        for ident, spec in sync.NANTES_TOULOUSE_NOV2026_VERIFIED.items():
            row = signed(spec)
            bad = copy.deepcopy(row)
            bad["newArtists"] = [{"id": "guest", "name": "Guest"}]
            with self.subTest(id=ident, change="guest"):
                with self.assertRaises(ValueError):
                    validate(bad)
            bad = copy.deepcopy(row)
            bad["officialEvidence"][0]["checkedFields"].append("doorTime")
            with self.subTest(id=ident, change="door"):
                with self.assertRaises(ValueError):
                    validate(bad)
            bad = copy.deepcopy(row)
            bad["event"]["id"] = "go-c-20270101-faux-doublon"
            with self.subTest(id=ident, change="reused-url"):
                with self.assertRaises(ValueError):
                    validate(bad)

    def test_catalogue_baseline_remains_private_preview(self):
        self.assertEqual(CURRENT["mode"], "preview-public-unlisted")
        self.assertGreaterEqual(len(CURRENT["events"]), 265)
        self.assertEqual(len({e["id"] for e in CURRENT["events"]}), len(CURRENT["events"]))
        # This test must also pass once the protected workflow publishes the lot.
        existing_by_url = {e["officialUrl"]: e for e in CURRENT["events"]}
        for ident, spec in sync.NANTES_TOULOUSE_NOV2026_VERIFIED.items():
            published = existing_by_url.get(spec["officialUrl"])
            if published is not None:
                self.assertEqual(published["id"], ident)
                self.assertEqual(published["date"], spec["date"])
                self.assertEqual(published["venueId"], spec["venueId"])

if __name__ == "__main__":
    unittest.main()
