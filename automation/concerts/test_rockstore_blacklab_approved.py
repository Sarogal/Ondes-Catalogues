"""Four individually reviewed first-party Rockstore and Black Lab concert bills.

Only these four exact dates/artists/venues/official details are approved.
The event clock has not been independently proven to be a music start time.
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest
from urllib.parse import urlsplit

APPROVED = Path(__file__).with_name("approved.json")
CASES = {
    "go-c-20261119-montpellier-mass-hysteria": {
        "date": "2026-11-19", "venue": "rockstore-montpellier",
        "artists": ["mass-hysteria"], "new": [],
        "genre": ["Néo-Metal"],
        "url": "https://rockstore.fr/mass-hysteria-19-novembre-2026/",
        "calendar": "https://rockstore.fr/concerts/",
    },
    "go-c-20261201-montpellier-shaarghot": {
        "date": "2026-12-01", "venue": "rockstore-montpellier",
        "artists": ["shaarghot", "solitaris", "ghost-dance"], "new": [],
        "genre": ["Metal industriel"],
        "url": "https://rockstore.fr/shaarghot-solitaris-ghost-dance-01-decembre-2026/",
        "calendar": "https://rockstore.fr/concerts/",
    },
    "go-c-20270220-wasquehal-colour-haze": {
        "date": "2027-02-20", "venue": "the-black-lab-wasquehal",
        "artists": ["colour-haze", "smokemaster"],
        "new": ["colour-haze", "smokemaster"],
        "genre": ["Stoner Rock"],
        "url": "https://theblacklab.fr/agenda/colour-haze-smokemaster/",
        "calendar": "https://theblacklab.fr/agenda/liste/page/2/",
    },
    "go-c-20270305-wasquehal-houle": {
        "date": "2027-03-05", "venue": "the-black-lab-wasquehal",
        "artists": ["houle", "can-bardd", "galibot"], "new": [],
        "genre": ["Black Metal"],
        "url": "https://theblacklab.fr/agenda/houle-can-bardd-galibot/",
        "calendar": "https://theblacklab.fr/agenda/liste/page/2/",
    },
}


class FourSignedRockstoreBlackLabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        document = json.loads(APPROVED.read_text(encoding="utf-8"))
        cls.entries = {e["event"]["id"]: e for e in document["approvals"]}

    def test_four_exact_signatures_and_official_evidence(self):
        for event_id, spec in CASES.items():
            with self.subTest(event_id=event_id):
                row = self.entries[event_id]
                e = row["event"]
                self.assertEqual(row["reviewDecision"], "approved")
                self.assertEqual(row["reviewedBy"], "independent-official-verifier")
                self.assertEqual(row["reviewedAt"], "2026-11-03")
                self.assertEqual(e["date"], spec["date"])
                self.assertEqual(e["venueId"], spec["venue"])
                self.assertEqual(e["artistIds"], spec["artists"])
                self.assertEqual(e["genres"], spec["genre"])
                self.assertEqual(e["officialUrl"], spec["url"])
                self.assertEqual(e["sourceType"], "salle")
                self.assertEqual(e["status"], "confirmed")
                self.assertIsNone(e["time"])
                self.assertEqual([a["id"] for a in row["newArtists"]],
                                 spec["new"])
                proof, calendar = row["officialEvidence"]
                self.assertEqual(proof["url"], spec["url"])
                self.assertEqual(proof["proofType"],
                                 "official-organizer-or-venue")
                self.assertTrue({"artists", "date", "venue", "genre"}
                                .issubset(set(proof["checkedFields"])))
                self.assertEqual(calendar["url"], spec["calendar"])
                self.assertEqual(calendar["proofType"],
                                 "first-party-venue-calendar")
                self.assertTrue({"artists", "date", "venue"}
                                .issubset(set(calendar["checkedFields"])))
                host = urlsplit(proof["url"]).hostname
                self.assertEqual(host, urlsplit(calendar["url"]).hostname)
                for p in (proof, calendar):
                    self.assertEqual(p["checkedAt"], "2026-11-03")
                    self.assertNotIn("startTime", p["checkedFields"])
                    self.assertEqual(urlsplit(p["url"]).scheme, "https")

    def test_new_artist_identities_are_not_invented(self):
        row = self.entries["go-c-20270220-wasquehal-colour-haze"]
        self.assertEqual(row["newArtists"],
                         [{"id": "colour-haze", "name": "Colour Haze"},
                          {"id": "smokemaster", "name": "Smokemaster"}])

    def test_others_remain_unapproved(self):
        # A discovery lead is not a signed approval; no retroactive
        # approval for postponed Morgan or yearless November events.
        self.assertFalse(any(
            "/reporte-morgan/" in e["event"]["officialUrl"]
            for e in self.entries.values()))
        self.assertEqual(
            len({e["event"]["id"] for e in self.entries.values()}),
            len(self.entries))


if __name__ == "__main__":
    unittest.main()
