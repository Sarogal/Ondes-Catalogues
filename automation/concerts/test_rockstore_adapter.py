"""Non-regression: Rockstore first-party date+genre proof, no time inference."""
from __future__ import annotations

import datetime as dt
import unittest
from unittest.mock import patch

import discover
import rockstore_adapter


SOURCE = {
    "name": "Rockstore", "city": "Montpellier", "department": "34",
    "priority": "P1", "url": "https://rockstore.fr/concerts/",
    "adapter": "rockstore_official_detail_review",
    "maxDetailPagesPerRun": 12, "publish_automatically": False
}
MASS = "https://rockstore.fr/mass-hysteria-19-novembre-2026/"
SHAARGHOT = "https://rockstore.fr/shaarghot-solitaris-ghost-dance-01-decembre-2026/"
POP = "https://rockstore.fr/meryl-07-novembre-2026/"
CANCELLED = "https://rockstore.fr/other-02-decembre-2026/"
LISTING = """<html><body>
  <a href="/mass-hysteria-19-novembre-2026/">Mass Hysteria</a>
  <a href="/shaarghot-solitaris-ghost-dance-01-decembre-2026/">Shaârghot</a>
  <a href="/meryl-07-novembre-2026/">Meryl</a>
  <a href="/other-02-decembre-2026/">Other</a>
  <a href="https://evil.example/metal-01-janvier-2027/">Fake</a>
  <a href="/old-01-janvier-2025/">Old</a>
  <a href="/fake-31-fevrier-2027/">Impossible</a>
  <a href="/mass-hysteria-19-novembre-2026/?utm=x">Query</a>
</body></html>"""
DETAIL = """<html><head><title>Rockstore</title></head><body>
  <nav>Concerts</nav><main>
  <h1>{title}</h1>
  <p>{date}</p><p>{genre}</p>
  <p>{bio}</p>
  </main><footer>Rockstore Montpellier</footer></body></html>"""


def mass(**changes):
    v = {
        "title": "MASS HYSTERIA",
        "date": "Jeudi 19 Novembre 2026 à 19h",
        "genre": "Néo-Metal/ Indus/ Fusion/",
        "bio": "Une soirée exceptionnelle avec le groupe."
    }
    v.update(changes)
    return DETAIL.format(**v)


def shaarghot(**changes):
    v = {
        "title": "SHAÂRGHOT + SOLITARIS + GHOST DANCE",
        "date": "Mardi 1er Décembre 2026 à 19h30",
        "genre": "Metal/",
        "bio": "Concert de metal industriel et moderne"
    }
    v.update(changes)
    return DETAIL.format(**v)


class RockstoreAdapterTests(unittest.TestCase):
    def test_only_dated_official_future_links(self):
        self.assertEqual(
            rockstore_adapter.detail_urls(
                LISTING, SOURCE["url"], "2026-11-03"),
            [POP, MASS, SHAARGHOT, CANCELLED])
        self.assertEqual(
            rockstore_adapter.detail_urls(
                LISTING, SOURCE["url"], "2026-11-20"),
            [SHAARGHOT, CANCELLED])

    def test_official_detail_never_infers_start_or_publishes(self):
        row = rockstore_adapter.detail_candidate(
            mass(), MASS, SOURCE, "2026-11-03")
        self.assertEqual(row["date"], "2026-11-19")
        self.assertEqual(row["leadArtist"], "MASS HYSTERIA")
        self.assertEqual(row["classification"], ["Néo-Metal/ Indus/ Fusion/"])
        self.assertIsNone(row["localTime"])
        self.assertFalse(row["publicationAllowed"])
        self.assertTrue(row["reviewRequired"])
        self.assertTrue(row["geoReviewRequired"])
        self.assertEqual(row["sourceUrl"], MASS)

    def test_first_party_bill_and_first_of_month(self):
        row = rockstore_adapter.detail_candidate(
            shaarghot(), SHAARGHOT, SOURCE, "2026-11-03")
        self.assertEqual(
            row["name"], "SHAÂRGHOT + SOLITARIS + GHOST DANCE")
        self.assertEqual(row["date"], "2026-12-01")

    def test_fail_closed_for_inaccurate_or_irrelevant_pages(self):
        variants = [
            ("wrong date", mass(date="Vendredi 20 Novembre 2026"), MASS, SOURCE),
            ("missing year", mass(date="Jeudi 19 Novembre"), MASS, SOURCE),
            ("pop", mass(genre="Pop/"), MASS, SOURCE),
            ("generic rock", mass(genre="Rock/"), MASS, SOURCE),
            ("wrong venue", mass(), MASS, {**SOURCE, "name": "Other"}),
            ("third party", mass(), MASS.replace("rockstore.fr","evil.example"), SOURCE),
            ("cancelled", mass(bio="CONCERT ANNULÉ"), MASS, SOURCE),
            ("postponed", mass(bio="REPORTÉ à une date future"), MASS, SOURCE),
            ("old", mass(), MASS, SOURCE),
            ("date forgery", mass(), MASS + "?utm=ad", SOURCE),
            ("club", mass(title="MASS HYSTERIA DJ SET"), MASS, SOURCE),
        ]
        for name, html, url, source in variants:
            today = "2026-11-20" if name == "old" else "2026-11-03"
            with self.subTest(case=name), self.assertRaises((ValueError, KeyError)):
                rockstore_adapter.detail_candidate(html, url, source, today)

    def test_balanced_rotation_covers_imminent_and_future_events(self):
        """Each day brings new dates rather than the same 5 pop listings."""
        near = [
            f"https://rockstore.fr/show-n{i}-{i+10}-novembre-2026/"
            for i in range(20)
        ]
        far = [
            f"https://rockstore.fr/show-f{i}-{i+1}-mars-2027/"
            for i in range(20)
        ]
        selected = [
            rockstore_adapter.selected_details(
                near + far, set(),
                (dt.date(2026, 11, 3) + dt.timedelta(days=offset)).isoformat(),
                limit=12)
            for offset in range(5)
        ]
        self.assertTrue(all(len(day) == 12 for day in selected))
        self.assertEqual(len(set().union(*map(set, selected))), 40)
        self.assertTrue(all(len(set(day) & set(near)) == 8 for day in selected))
        self.assertTrue(all(len(set(day) & set(far)) == 4 for day in selected))
        self.assertNotEqual(selected[0], selected[1])

    def test_discover_integrates_and_ignores_pop_and_cancelled(self):
        pages = {
            SOURCE["url"]: LISTING,
            MASS: mass(),
            SHAARGHOT: shaarghot(),
            POP: DETAIL.format(title="MERYL", date="Samedi 7 Novembre 2026 à 20h",
                               genre="Rap/", bio="Concert de rap"),
            CANCELLED: DETAIL.format(
                title="OTHER", date="Mercredi 2 Décembre 2026 à 20h",
                genre="Punk/", bio="ANNULÉ")
        }
        def get(url, **_):
            return pages[url], url
        report = []
        with patch.object(discover, "robots_allow", return_value=True), \
             patch.object(discover, "download", side_effect=get), \
             patch.object(discover.feeds, "feed_links", return_value={"ics": [], "rss": []}):
            candidates = discover.scan_venues(
                {"venues": [SOURCE]}, {("officialUrl", MASS)},
                dt.date(2026, 11, 3), report)
        self.assertEqual(len(candidates), 2)
        self.assertEqual(
            {x["name"] for x in candidates},
            {"MASS HYSTERIA", "SHAÂRGHOT + SOLITARIS + GHOST DANCE"})
        self.assertEqual(sum(x["possibleExistingConcert"] for x in candidates), 1)
        self.assertTrue(all(x["localTime"] is None for x in candidates))
        self.assertTrue(all(x["publicationAllowed"] is False for x in candidates))
        self.assertEqual(report[0]["adapterDiagnostic"]["datedGenreLeads"],2)


if __name__ == "__main__":
    unittest.main()
