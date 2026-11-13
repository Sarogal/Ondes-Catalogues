"""Publisher parity: a named headliner with an unannounced GUEST must not be held.

Uses only the public reference/current schema and a deterministic official-page
fixture. No private approvals, no network, and absolutely no publication.
"""
import datetime as dt
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "automation" / "concerts"))
sys.path.insert(0, str(ROOT / "scripts"))

import backstage_recheck
from concerts_cloud_sync import validate_approval

DATE = dt.date(2026, 11, 13)
URL = "https://www.backstage-btm.com/agenda/greenleaf-2/"
OFFICIAL_PAGE = (
    "<main><h1>GREENLEAF + GUEST</h1>"
    "<p>Stoner Rock</p><p>14/12/2026</p>"
    "<p>O’Sullivans By The Mill, 92 bis bd de Clichy - Paris</p>"
    "<p>GARMONBOZIA présente GREENLEAF + GUEST</p></main>"
)


class PublisherGreenleafGuestTests(unittest.TestCase):
    def test_official_headliner_passes_exact_same_publisher_validation(self):
        catalogue = json.loads(
            (ROOT / "docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
        original_count = len(catalogue["events"])
        existing_venues = {v["id"]: v for v in catalogue["venues"]}
        existing_artists = {a["id"]: a for a in catalogue["artists"]}
        candidate = {
            "candidateId": "backstage:2026-12-14:greenleaf-2",
            "source": "agenda_officiel_backstage_detail",
            "sourceUrl": URL,
            "name": "GREENLEAF + GUEST",
            "date": "2026-12-14",
            "venue": "Backstage By The Mill", "city": "Paris",
            "classification": ["stoner rock"],
            "reviewBucket": "genre_tag_review",
            "possibleExistingConcert": False,
            "reviewRequired": True,
            "publicationAllowed": False,
        }
        approval = backstage_recheck.verify(candidate, OFFICIAL_PAGE,
                                             catalogue, DATE)
        evt, added = validate_approval(approval, existing_venues,
                                        existing_artists, DATE)
        self.assertEqual(evt["title"], "GREENLEAF")
        self.assertEqual(evt["date"], "2026-12-14")
        self.assertEqual(evt["venueId"], "backstage-by-the-mill-paris")
        self.assertEqual(evt["artistIds"], ["greenleaf"])
        self.assertEqual(approval["newArtists"],
                         [{"id": "greenleaf", "name": "GREENLEAF"}])
        self.assertIn("greenleaf", added)
        self.assertNotIn("guest", added)
        self.assertIsNone(evt["time"])
        self.assertEqual(len(catalogue["events"]), original_count)

    def test_publisher_rejects_forged_guest_artist_from_same_page(self):
        catalogue = json.loads(
            (ROOT / "docs/grossesondes/concerts.json").read_text(encoding="utf-8"))
        candidate = {
            "source": "agenda_officiel_backstage_detail",
            "sourceUrl": URL, "name": "GREENLEAF + GUEST",
            "date": "2026-12-14", "venue": "Backstage By The Mill",
            "city": "Paris", "classification": ["stoner rock"],
            "reviewBucket": "genre_tag_review",
            "possibleExistingConcert": False,
            "reviewRequired": True, "publicationAllowed": False,
        }
        a = backstage_recheck.verify(candidate, OFFICIAL_PAGE, catalogue, DATE)
        a["event"]["title"] = "GREENLEAF + GUEST"
        a["event"]["artistIds"] = ["greenleaf", "guest"]
        a["newArtists"].append({"id": "guest", "name": "GUEST"})
        with self.assertRaises(ValueError):
            validate_approval(a,
                              {v["id"]: v for v in catalogue["venues"]},
                              {x["id"]: x for x in catalogue["artists"]},
                              DATE)


if __name__ == "__main__":
    unittest.main()
