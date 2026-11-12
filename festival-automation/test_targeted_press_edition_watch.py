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
         "lastKnownYear": 2026,
         "startDate": ("2026-10-02" if config["slug"] == "mauges-pit-fest"
                       else "2026-08-20"),
         "endDate": ("2026-10-03" if config["slug"] == "mauges-pit-fest"
                     else "2026-08-22")}
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

    def test_validated_press_starts_private_dossiers_without_homepage_hint(self):
        from national_discovery_queue import build_queue
        st = state()
        scan(st, SOURCES, TODAY, fetch=fetch)
        report = {
            "schema": "grossesondes.source-watch-report.v1",
            "date": TODAY, "source_reference_leads_review_only": [],
            "press_edition_archive_integrity_private": "CONSISTENT",
            "historical_future_watch_archive_status_private": "CONSISTENT",
        }
        queue = build_queue(st, report, [], TODAY)
        self.assertEqual(queue["candidate_dossiers_count"], 2)
        self.assertEqual(queue["press_article_research_dossiers_private"], 2)
        self.assertEqual(queue["historical_homepage_date_hints_private"], 0)
        for dossier in queue["dossiers"]:
            self.assertEqual(dossier["date_hints"], [])
            self.assertEqual(dossier["historical_homepage_date_hints_review_only"], [])
            self.assertEqual(len(dossier["sources"]), 1)
            self.assertEqual(dossier["sources"][0]["kind"],
                             "PRESS_ARTICLE_DATE_CLAIM_REVIEW")
            self.assertEqual(dossier["sources"][0]["discovered_via"],
                             dossier["sources"][0]["url"])
            self.assertFalse(dossier["sources"][0]["independence_verified"])
            self.assertFalse(dossier["publication_authorized"])
            self.assertFalse(dossier["safe_to_publish"])
            self.assertIn("editorial_signoff", dossier["missing_checks"])

    def test_press_only_editorial_dossiers_remain_unverified(self):
        from national_discovery_queue import build_queue
        from national_editorial_reconciliation import build_review
        st = state()
        scan(st, SOURCES, TODAY, fetch=fetch)
        report = {
            "schema": "grossesondes.source-watch-report.v1",
            "date": TODAY, "source_reference_leads_review_only": [],
            "press_edition_archive_integrity_private": "CONSISTENT",
        }
        q = build_queue(st, report, [], TODAY)
        detail = {
            "schema": "grossesondes.national-detail-qualification-private.v1",
            "as_of": TODAY, "review_only": True,
            "safe_to_publish": False, "publication_authorized": False,
            "observations": [],
        }
        public = {"schema": 1, "festivals": []}
        review = build_review(q, detail, st, [], public, history(), TODAY)
        self.assertEqual(review["dossiers_count"], 2)
        self.assertEqual(review["press_date_claims_private"], 3)
        self.assertEqual(review["press_date_claim_dossiers_private"], 2)
        for d in review["dossiers"]:
            self.assertEqual(d["status"], "PRESS_DATE_CLAIM_REVIEW")
            self.assertEqual(d["historical_homepage_date_hints_review_only"], [])
            self.assertIn("independent_date_confirmation", d["missing_checks"])
            self.assertIn("first_party_date_observation_missing", d["missing_checks"])
            self.assertIn("press_article_origin_requires_editorial_review",
                          d["missing_checks"])
            self.assertIn("editorial_approval", d["missing_checks"])
            self.assertFalse(d["publication_authorized"])
            self.assertFalse(d["safe_to_publish"])
            self.assertFalse(d["future_edition_confirmed"])
        self.assertEqual(review["publications"], 0)
        self.assertEqual(review["editorial_drafts_count"], 0)

    def test_bad_winter_summer_homepage_record_does_not_hide_fresh_press(self):
        from historical_future_lead_watch import validated_hints
        from national_discovery_queue import build_queue
        st = state()
        scan(st, {"gueules-progres": SOURCES["gueules-progres"]},
             TODAY, fetch=fetch)
        name, region, url = (
            "Les Gueules de Bois", "Bourgogne-Franche-Comté",
            "https://festivalgueulesdebois.com/",
        )
        st["historical_future_edition_hints_private"] = {
            "les-gueules-de-bois": {
                "name_hint": name, "region_hint": region, "source_url": url,
                "edition_year_hint": 2027, "firstSeen": TODAY,
                "lastSeen": TODAY, "status":
                    "UNVERIFIED_ARCHIVE_HOMEPAGE_YEAR_MENTION",
                "visible_text_sha256": "b"*64,
                "publication_authorized": False,
                "safe_to_publish": False, "edition_dates_verified": False,
                "organizer_verified": False, "independence_verified": False,
                "date_hints_review_only": [{
                    "start_date_hint": "2027-02-13",
                    "end_date_hint": "2027-02-13",
                    "season_hint": "summer",
                    "status": "UNVERIFIED_VISIBLE_DATE_PHRASE",
                    "edition_dates_verified": False, "organizer_verified": False,
                    "independence_verified": False, "publication_authorized": False,
                    "review_only": True,
                }],
            },
        }
        self.assertEqual(validated_hints(st, TODAY), [])
        report = {
            "schema": "grossesondes.source-watch-report.v1",
            "date": TODAY, "source_reference_leads_review_only": [],
            "historical_future_watch_archive_status_private": "CONSISTENT",
            "press_edition_archive_integrity_private": "CONSISTENT",
        }
        q = build_queue(st, report, [], TODAY)
        self.assertEqual(q["candidate_dossiers_count"], 1)
        self.assertEqual(q["press_article_research_dossiers_private"], 1)
        self.assertEqual(q["historical_homepage_year_hints_private"], 0)
        self.assertEqual(q["historical_homepage_date_hints_private"], 0)
        self.assertFalse(q["dossiers"][0]["publication_authorized"])
        self.assertEqual(q["dossiers"][0]["date_hints"], [])

    def test_press_only_queue_fails_closed_if_archives_diverge(self):
        from national_discovery_queue import build_queue
        st = state()
        scan(st, SOURCES, TODAY, fetch=fetch)
        initial = {
            "schema": "grossesondes.source-watch-report.v1",
            "date": TODAY, "source_reference_leads_review_only": [],
        }
        for integrity in (None, "DIVERGENT", "UNAVAILABLE_OR_INVALID"):
            with self.subTest(integrity=integrity):
                rep = dict(initial)
                if integrity is not None:
                    rep["press_edition_archive_integrity_private"] = integrity
                out = build_queue(st, rep, [], TODAY)
                self.assertEqual(out["candidate_dossiers_count"], 0)
                self.assertEqual(out["press_article_research_dossiers_private"], 0)

    def test_press_queue_does_not_trust_forged_state_or_more_urls(self):
        from national_discovery_queue import build_queue
        st = state()
        scan(st, {"gueules-progres": SOURCES["gueules-progres"]},
             TODAY, fetch=fetch)
        rep = {
            "schema": "grossesondes.source-watch-report.v1",
            "date": TODAY, "source_reference_leads_review_only": [],
            "press_edition_archive_integrity_private": "CONSISTENT",
        }
        original = deepcopy(st["press_edition_observations_private"]["gueules-progres"])
        for patch in (
                {"article_url": "https://evil.example/reassign"},
                {"publication_authorized": True},
                {"independence_verified": True},
                {"observed_claim_ids": ["unknown-2027"]},
                {"observed_at": "2027-01-01"}):
            with self.subTest(patch=patch):
                st["press_edition_observations_private"]["gueules-progres"] = dict(
                    original, **patch)
                self.assertEqual(build_queue(st, rep, [], TODAY)[
                    "press_article_research_dossiers_private"], 0)

    def test_repeated_press_witness_does_not_create_duplicate_dossiers(self):
        from national_discovery_queue import build_queue
        from historical_future_lead_watch import scan as historic_scan
        from historical_future_lead_watch import APPROVED as HIST
        st = state()
        scan(st, {"gueules-progres": SOURCES["gueules-progres"]},
             TODAY, fetch=fetch)
        name, region, url = HIST["les-gueules-de-bois"]
        historic_scan(st, {"les-gueules-de-bois": {
            "slug": "les-gueules-de-bois", "name": name,
            "region": region, "url": url, "last_known_year": 2026}},
            TODAY, fetch=lambda _: (
                "<main><h1>Les Gueules de Bois hiver 2027</h1>"
                "<p>Samedi 13 février 2027 à Légna.</p></main>"))
        rep = {
            "schema": "grossesondes.source-watch-report.v1",
            "date": TODAY, "source_reference_leads_review_only": [],
            "historical_future_watch_archive_status_private": "CONSISTENT",
            "press_edition_archive_integrity_private": "CONSISTENT",
        }
        q = build_queue(st, rep, [], TODAY)
        self.assertEqual(q["candidate_dossiers_count"], 1)
        self.assertEqual(q["press_article_research_dossiers_private"], 1)
        self.assertEqual(q["historical_homepage_dossiers_private"], 1)
        self.assertEqual(len(q["dossiers"][0]["sources"]), 2)
        self.assertEqual(q["publications"], 0)

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
