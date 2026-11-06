"""Non-regression: extension nationale de veille, sans droits de publication."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from urllib.parse import urlsplit


SOURCES = Path(__file__).with_name("sources.json")
TARGETS = {
    ("La Laiterie", "Strasbourg"): "www.artefact.org",
    ("Le Bikini", "Toulouse"): "lebikini.com",
    ("The Black Lab", "Wasquehal"): "theblacklab.fr",
    ("Rockstore", "Montpellier"): "rockstore.fr",
    ("L'Autre Canal", "Nancy"): "lautrecanalnancy.fr",
    ("La Cartonnerie", "Reims"): "www.cartonnerie.fr",
    ("Le Confort Moderne", "Poitiers"): "www.confort-moderne.fr",
    ("Le Grillen", "Colmar"): "grillen.colmar.fr",
    ("Espace John Lennon", "Limoges"): "centresculturels.limoges.fr",
}


class NationalSourceExpansionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(SOURCES.read_text(encoding="utf-8"))

    def test_new_sources_are_unique_and_first_party(self):
        rows = self.data["venues"]
        self.assertEqual(len(rows), len({(x["name"], x["city"]) for x in rows}))
        for identity, hostname in TARGETS.items():
            matches = [x for x in rows if (x["name"], x["city"]) == identity]
            self.assertEqual(len(matches), 1, identity)
            row = matches[0]
            self.assertFalse(row["publish_automatically"])
            self.assertEqual(row["kind"], "official_venue_agenda_candidate")
            self.assertIn(row["priority"], ("P1", "P2"))
            for field in ("url", "officialAgendaUrl"):
                parsed = urlsplit(row[field])
                self.assertEqual(parsed.scheme, "https")
                self.assertEqual(parsed.hostname, hostname)
                self.assertFalse(parsed.username or parsed.password)

    def test_underserved_official_sources_are_p1_and_bounded(self):
        for name, city in (("L'Autre Canal", "Nancy"),
                           ("La Cartonnerie", "Reims"),
                           ("Le Confort Moderne", "Poitiers")):
            row = next(x for x in self.data["venues"]
                       if x["name"] == name and x["city"] == city)
            self.assertEqual(row["priority"], "P1")
            self.assertFalse(row["publish_automatically"])
            self.assertEqual(row["status"], "official_calendar_discovery_review_only")
            self.assertEqual(row["verifiedOn"], "2026-11-04")

    def test_two_new_venues_reject_unreviewed_publication_and_inferred_dates(self):
        for name, city in (("Le Grillen", "Colmar"),
                           ("Espace John Lennon", "Limoges")):
            item = next(x for x in self.data["venues"]
                        if x["name"] == name and x["city"] == city)
            self.assertEqual(item["priority"], "P1")
            self.assertEqual(item["status"], "official_calendar_discovery_review_only")
            self.assertFalse(item["publish_automatically"])
            self.assertEqual(item["verifiedOn"], "2026-11-04")
            self.assertLessEqual(item["maxDetailPagesPerRun"], 9)
            self.assertLessEqual(item["maxAgendaPagesPerRun"], 3)
            self.assertTrue(item["adapterStatus"])
            self.assertIn(item["adapter"], (
                "grillen_official_detail_review",
                "limoges_municipal_card_detail_review"))

    def test_all_sources_remain_discovery_only(self):
        self.assertTrue(all(x["publish_automatically"] is False for x in self.data["venues"]))
        self.assertEqual(self.data["schema"], "grossesondes.concert.sourcelist.v1")


if __name__ == "__main__":
    unittest.main()
