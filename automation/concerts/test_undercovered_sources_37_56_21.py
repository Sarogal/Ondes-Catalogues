"""Gap priorities: first-party Bateau Ivre (37), Echonova (56), La Vapeur (21).

Sources produce review-only leads. Adding a first-party URL is not approval.
"""
import json
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlsplit

SOURCES = Path(__file__).with_name("sources.json")
EXPECTED = {
    ("Le Bateau Ivre", "Tours"): ("37", "www.bateauivre.coop", "/2027/"),
    ("L'Echonova", "Saint-Avé"): ("56", "lechonova.com", "/programmation/"),
    ("La Vapeur", "Dijon"): ("21", "lavapeur.com", "/programme"),
}


class UnderservedSourcesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.items = json.loads(SOURCES.read_text(encoding="utf-8"))["venues"]

    def test_official_sources_exist_once_with_geographic_priority(self):
        for identity, (department, hostname, path) in EXPECTED.items():
            with self.subTest(venue=identity):
                matches = [row for row in self.items
                           if (row["name"], row["city"]) == identity]
                self.assertEqual(len(matches), 1)
                s = matches[0]
                self.assertEqual(s["department"], department)
                self.assertEqual(s["priority"], "P1")
                self.assertFalse(s["publish_automatically"])
                self.assertEqual(s["status"], "official_calendar_discovery_review_only")
                self.assertEqual(s["verifiedOn"], "2026-11-04")
                for label in ("url", "officialAgendaUrl"):
                    u = urlsplit(s[label])
                    self.assertEqual(u.scheme, "https")
                    self.assertEqual((u.hostname, u.path), (hostname, path))
                    self.assertFalse(u.fragment or u.username or u.password)
                self.assertLessEqual(s["maxDetailPagesPerRun"], 6)
                self.assertLessEqual(s.get("maxAgendaPagesPerRun", 1), 2)

    def test_bateau_2027_filter_not_yearless_or_2026_paginated_archive(self):
        row = next(x for x in self.items if x["name"] == "Le Bateau Ivre")
        url = urlsplit(row["url"])
        self.assertEqual(parse_qs(url.query), {"post_type":["events"]})
        self.assertIn("2027", row["note"])
        self.assertIn("des portes", row["note"])
        self.assertEqual(row["adapter"], "bateau_ivre_official_detail_review")
        self.assertEqual(row["maxAgendaPagesPerRun"], 1)
        self.assertIn("aucune publication", row["adapterStatus"])

    def test_no_publication_token_or_unverified_event_is_added(self):
        self.assertFalse(any(s.get("publish_automatically") for s in self.items))
        self.assertEqual(len({(s["name"], s["city"]) for s in self.items}),
                         len(self.items))


if __name__ == "__main__":
    unittest.main()
