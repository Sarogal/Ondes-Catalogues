"""Offline regression tests for two pinned festival press articles."""
from copy import deepcopy
import unittest

from targeted_press_edition_watch import (
    SOURCES, HISTORY_PAGES, HISTORY_GIT, approved_roster,
    inspect_article, load_sources, scan, validated_observations,
)

TODAY = "2026-11-11"
TOMORROW = "2026-11-12"

GUEULES_HTML = (
    "<main><h1>Jura : La billetterie du festival des Gueules de Bois "
    "de l'été 2027 est ouverte</h1>"
    "<p>Le festival Les Gueules de Bois voit déjà loin. "
    "Entre une édition hivernale et le rendez-vous estival, "
    "les organisateurs annoncent une année 2027 riche en musique. "
    "Premier rendez-vous, le samedi 13 février 2027, "
    "avec la soirée hivernale à Légna.</p>"
    "<p>Les bénévoles préparent également la septième édition "
    "du festival, programmée les 19, 20 et 21 août 2027.</p>"
    "</main>"
)
MAUGES_HTML = (
    "<main><h1>Le Mauges Pit Fest dresse un bilan positif pour "
    "sa cinquième édition</h1>"
    "<p>La cinquième édition du Mauges Pit Fest, organisée "
    "en octobre 2026, a eu lieu à Saint-Macaire-en-Mauges.</p>"
    "<p>D'après Ouest-France, l'équipe poursuit ses projets "
    "pour l'année suivante.</p>"
    "<p>La prochaine édition du festival est d'ores et déjà "
    "programmée pour les 8 et 9 octobre 2027.</p></main>"
)


def history():
    return {"schema": 2, "knownFestivals": [
        {"slug": config["slug"], "name": config["name"],
         "region": config["region"],
         "officialSite": config["official_home"],
         "lastKnownYear": 2026, "startDate": "2026-08-20",
         "endDate": "2026-08-22"}
        for config in SOURCES.values()
    ]}


def state():
    return {"schema": "grossesondes.source-watch.v1"}


def fetch(url):
    return {
        SOURCES["gueules-progres"]["url"]: GUEULES_HTML,
        SOURCES["mauges-angers"]["url"]: MAUGES_HTML,
    }[url]


class TargetedPressArticleTests(unittest.TestCase):
    def test_pinned_articles_need_identical_historical_snapshots(self):
        approved = approved_roster(history(), TODAY)
        self.assertEqual(set(approved), set(SOURCES))
        seen = []
        sources, status = load_sources(
            TODAY, fetch_json=lambda url: (
                seen.append(url), deepcopy(history()))[1])
        self.assertEqual(status, "CONSISTENT")
        self.assertEqual(seen, [HISTORY_PAGES, HISTORY_GIT])
        self.assertEqual(sources, SOURCES)

        def divergent(url):
            snapshot = history()
            if url == HISTORY_GIT:
                snapshot["knownFestivals"][0]["officialSite"] = "https://evil.example/"
            return snapshot
        self.assertEqual(load_sources(TODAY, fetch_json=divergent),
                         ({}, "DIVERGENT"))

    def test_historical_identity_or_date_change_blocks_all_approval(self):
        for patch in (
                {"name": "Other Festival"},
                {"region": "Bretagne"},
                {"lastKnownYear": 2027},
                {"officialSite": "https://evil.example/"},
                {"startDate": "2027-02-13"}):
            modified = history()
            modified["knownFestivals"][0].update(patch)
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                approved_roster(modified, TODAY)

    def test_exact_article_claims_are_unverified_review_signals(self):
        winter, digest = inspect_article(GUEULES_HTML, SOURCES["gueules-progres"])
        self.assertEqual(winter, ["summer", "winter"])
        self.assertEqual(len(digest), 64)
        dates, digest = inspect_article(MAUGES_HTML, SOURCES["mauges-angers"])
        self.assertEqual(dates, ["next-edition"])
        self.assertEqual(len(digest), 64)

    def test_no_inference_from_old_dates_or_unrelated_event(self):
        cases = (
            "<main><h1>Les Gueules de Bois 2026</h1>"
            "<p>Premier rendez-vous, le samedi 13 février 2026.</p>"
            "<p>Septième édition du festival 19, 20 et 21 août 2026.</p></main>",
            "<main><h1>Un autre festival punk 2027</h1>"
            "<p>Premier rendez-vous, le samedi 13 février 2027.</p>"
            "<p>Septième édition du festival programmée les "
            "19, 20 et 21 août 2027.</p></main>",
            "<main><p>Les Gueules de Bois auront une "
            "nouvelle édition en 2027 sans date exacte.</p></main>",
            "<main><p>Les Gueules de Bois 2027 : "
            "confirmation des prochains événements.</p>"
            "<script>Premier rendez-vous le samedi 13 février 2027</script>"
            "<div hidden>Septième édition du festival "
            "programmée les 19, 20 et 21 août 2027</div></main>",
        )
        for html in cases:
            with self.subTest(html=html):
                try:
                    ids, _ = inspect_article(html, SOURCES["gueules-progres"])
                    self.assertEqual(ids, [])
                except ValueError:  # very short visible pages are inconclusive
                    pass

    def test_mauges_2026_or_unrelated_event_never_confirms_2027(self):
        cases = (
            "<main><h1>Mauges Pit Fest</h1>"
            "<p>La prochaine édition du festival est déjà prévue "
            "pour les 8 et 9 octobre 2026.</p></main>",
            "<main><h1>Other Festival</h1>"
            "<p>La prochaine édition du festival est d'ores et déjà "
            "programmée pour les 8 et 9 octobre 2027.</p></main>",
        )
        for html in cases:
            with self.subTest(html=html):
                try:
                    ids, _ = inspect_article(html, SOURCES["mauges-angers"])
                    self.assertEqual(ids, [])
                except ValueError:
                    pass

    def test_two_exact_article_urls_are_only_network_destinations(self):
        st = state()
        urls = []
        results = scan(st, SOURCES, TODAY,
                       fetch=lambda url: (urls.append(url), fetch(url))[1])
        self.assertEqual(urls, [SOURCES[k]["url"] for k in sorted(SOURCES)])
        self.assertEqual(len(results), 2)
        self.assertEqual(len(validated_observations(st, TODAY)), 2)
        self.assertEqual(scan(st, SOURCES, TODAY,
                              fetch=lambda _: self.fail("same-day retry")), [])
        reviews = validated_observations(st, TODAY)
        for row in reviews:
            self.assertFalse(row["publication_authorized"])
            self.assertFalse(row["independence_verified"])
            self.assertFalse(row["publisher_origin_assessed"])
            self.assertTrue(row["review_only"])
            self.assertTrue(all(not c["edition_dates_verified"]
                                for c in row["claims"]))

    def test_source_injection_never_causes_an_unreviewed_fetch(self):
        st = state()
        fake = dict(SOURCES["mauges-angers"],
                    url="https://evil.example/internal")
        with self.assertRaises(ValueError):
            scan(st, {"mauges-angers": fake}, TODAY,
                 fetch=lambda _: self.fail("unreviewed fetch"))
        with self.assertRaises(ValueError):
            scan(st, SOURCES, TODAY, limit=3,
                 fetch=lambda _: self.fail("unbounded fetch"))

    def test_unavailable_article_removes_old_positive_observation(self):
        st = state()
        scan(st, SOURCES, TODAY, fetch=fetch)
        results = scan(st, SOURCES, TOMORROW,
                       fetch=lambda _: (_ for _ in ()).throw(OSError("403")))
        self.assertEqual(len(results), 2)
        self.assertEqual(validated_observations(st, TOMORROW), [])
        self.assertEqual(st["press_edition_observations_private"], {})

    def test_forged_private_source_cannot_approve_independence(self):
        st = state()
        scan(st, SOURCES, TODAY, fetch=fetch)
        original = deepcopy(st["press_edition_observations_private"])
        cases = (
            {"article_url": "https://evil.example/payload"},
            {"observed_claim_ids": ["summer", "winter", "extra"]},
            {"independence_verified": True},
            {"publication_authorized": True},
            {"safe_to_publish": True},
            {"edition_dates_verified": True},
            {"review_only": False},
            {"publisher": "Organisateur officiel"},
            {"observed_at": "2027-01-01"},
        )
        for patch in cases:
            with self.subTest(patch=patch):
                st["press_edition_observations_private"] = deepcopy(original)
                st["press_edition_observations_private"]["gueules-progres"].update(patch)
                self.assertEqual(
                    [x["slug"] for x in validated_observations(st, TODAY)],
                    ["mauges-pit-fest"])

    def test_absent_and_stale_reviews_are_not_current_proof(self):
        self.assertEqual(validated_observations(state(), TODAY), [])
        st = state()
        scan(st, SOURCES, TODAY, fetch=fetch)
        self.assertEqual(validated_observations(st, "2026-11-20"), [])


if __name__ == "__main__":
    unittest.main()
