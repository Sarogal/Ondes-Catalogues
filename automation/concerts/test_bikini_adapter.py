"""Le Bikini: first-party venue proof, exact date, no doors-as-start and no auto publish."""
from __future__ import annotations

import datetime as dt
import unittest
from unittest.mock import patch

import bikini_adapter
import discover


SOURCE = {
    "name": "Le Bikini", "city": "Toulouse", "department": "31",
    "priority": "P1", "url": "https://lebikini.com/programmation/-/concert",
    "adapter": "bikini_official_details_review",
    "maxDetailPagesPerRun": 24,
    "publish_automatically": False,
}
DETAIL_11 = "https://lebikini.com/2026/11/11/chameleons"
DETAIL_14 = "https://lebikini.com/2026/11/14/beast-in-black-sonata-arctica-frozen-crown"
LISTING = f"""<html><body>
  <a href="/2026/11/11/chameleons">CHAMELEONS</a>
  <a href="/2026/11/14/beast-in-black-sonata-arctica-frozen-crown">BEAST IN BLACK</a>
  <a href="/2026/11/09/rap"><span>Rap</span></a>
  <a href="https://external.example/2026/11/11/forged">Fake</a>
  <a href="/2026/10/01/old-show">Old</a>
  <a href="/2026/11/17/slift?utm_source=x">With query</a>
  <a href="/programmation/-/concert">Agenda</a>
</body></html>"""
DETAIL_TEMPLATE = """<html><head><title>Official Le Bikini</title></head><body>
  <nav>Le Bikini</nav>
  <p>{french_date}</p>
  <p>Le Bikini</p>
  <h1>{title}</h1>
  <p>{genre}</p>
  <p>Ouverture des portes : 19h30</p>
  <p>{description}</p>
  <p>Où</p>
  <p>Le Bikini Parc Technologique du Canal Rue Théodore Monod 31520 Ramonville Saint-Agne</p>
  <p>Ces événements devraient vous plaire</p>
</body></html>"""


def detail11(**overrides):
    values = {
        "french_date": "Mercredi 11 novembre 2026 à 19h30",
        "title": "CHAMELEONS",
        "genre": "Post-Punk/Rock alternatif",
        "description": "Chameleons en concert",
    }
    values.update(overrides)
    return DETAIL_TEMPLATE.format(**values)


def detail14(**overrides):
    values = {
        "french_date": "Samedi 14 novembre 2026 à 18h",
        "title": "BEAST IN BLACK + SONATA ARCTICA + FROZEN CROWN",
        "genre": "Heavy Metal",
        "description": "Concert officiel",
    }
    values.update(overrides)
    return DETAIL_TEMPLATE.format(**values)


class BikiniAdapterTests(unittest.TestCase):
    def test_safe_individual_links_only(self):
        self.assertEqual(
            bikini_adapter.detail_urls(LISTING, SOURCE["url"], "2026-11-03"),
            ["https://lebikini.com/2026/11/09/rap", DETAIL_11, DETAIL_14])
        self.assertEqual(bikini_adapter.detail_urls(
            LISTING, SOURCE["url"], "2026-11-12"), [DETAIL_14])

    def test_first_party_detail_is_dated_genre_bound_and_not_published(self):
        candidate = bikini_adapter.detail_candidate(
            detail11(), DETAIL_11, SOURCE, "2026-11-03")
        self.assertEqual(candidate["date"], "2026-11-11")
        self.assertEqual(candidate["name"], "CHAMELEONS")
        self.assertEqual(candidate["classification"], ["Post-Punk/Rock alternatif"])
        self.assertEqual(candidate["venue"], "Le Bikini")
        self.assertIsNone(candidate["localTime"])
        self.assertFalse(candidate["publicationAllowed"])
        self.assertTrue(candidate["reviewRequired"])
        self.assertTrue(candidate["geoReviewRequired"])
        self.assertEqual(candidate["sourceUrl"], DETAIL_11)

    def test_untrusted_details_and_missing_venue_proof_are_held(self):
        cases = [
            ("fake domain", detail11(), DETAIL_11.replace("lebikini.com", "evil.example"), SOURCE),
            ("wrong day", detail11(french_date="Jeudi 12 novembre 2026 à 19h"), DETAIL_11, SOURCE),
            ("no year", detail11(french_date="Mercredi 11 novembre à 19h"), DETAIL_11, SOURCE),
            ("wrong room", detail11().replace("Le Bikini Parc Technologique du Canal", "La Cabane"), DETAIL_11, SOURCE),
            ("wrong genre", detail11(genre="Hip-Hop"), DETAIL_11, SOURCE),
            ("cancelled", detail11(description="CONCERT ANNULÉ"), DETAIL_11, SOURCE),
            ("no title", detail11(title=""), DETAIL_11, SOURCE),
            ("wrong source", detail11(), DETAIL_11, {**SOURCE, "name": "La Cabane"}),
        ]
        for name, html, url, source in cases:
            with self.subTest(case=name), self.assertRaises((ValueError, KeyError)):
                bikini_adapter.detail_candidate(html, url, source, "2026-11-03")

    def test_full_lineup_is_preserved_from_headline(self):
        x = bikini_adapter.detail_candidate(detail14(), DETAIL_14, SOURCE, "2026-11-03")
        self.assertEqual(x["name"], "BEAST IN BLACK + SONATA ARCTICA + FROZEN CROWN")
        self.assertEqual(x["leadArtist"], "BEAST IN BLACK")
        self.assertEqual(x["classification"], ["Heavy Metal"])
        self.assertIsNone(x["localTime"])

    def test_discovery_collects_safe_leads_but_not_approvals(self):
        html = {SOURCE["url"]: LISTING, DETAIL_11: detail11(), DETAIL_14: detail14(),
                "https://lebikini.com/2026/11/09/rap": detail11(
                    french_date="Lundi 9 novembre 2026 à 19h30", genre="Hip-Hop")}
        def get_page(url, **_kwargs):
            if url not in html:
                raise ValueError("Unexpected URL")
            return html[url], url
        report = []
        with patch.object(discover, "robots_allow", return_value=True), \
             patch.object(discover, "download", side_effect=get_page), \
             patch.object(discover.feeds, "feed_links", return_value={"ics":[], "rss":[]}):
            items = discover.scan_venues({"venues":[SOURCE]}, {("officialUrl",DETAIL_14)},
                                         dt.date(2026,11,3), report)
        self.assertEqual(len(items),2)
        self.assertEqual({x["date"] for x in items},{"2026-11-11","2026-11-14"})
        self.assertTrue(all(x["publicationAllowed"] is False for x in items))
        self.assertTrue(all(x["localTime"] is None for x in items))
        self.assertEqual(sum(bool(x["possibleExistingConcert"]) for x in items),1)
        self.assertEqual(report[0]["adapterDiagnostic"]["datedReviewLeads"],2)


if __name__ == "__main__":
    unittest.main()
