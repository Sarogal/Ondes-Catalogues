"""Offline fixtures for two pinned 2027 festival official-homepage checks."""
from copy import deepcopy
import unittest

from targeted_first_party_edition_watch import (
    SOURCES, roster, inspect_homepage, validated_observations, scan,
)

TODAY = "2026-11-12"
TOMORROW = "2026-11-13"

# Representative CURRENT visible body of the first-party 2027 homepage.
# After navigation/footers are filtered, both editions remain separately
# visible before the retrospective section.
GUEULES = (
    "<main><section><h2>Été 2027</h2><p>On remet ça.</p>"
    "<p>19 · 20 · 21 août · Légna (39)</p><h2>Hiver 2027</h2>"
    "<p>13 février · Légna</p><h2>Et cet été, on remet ça.</h2>"
    "<p>19, 20 & 21 août 2027 · Légna (39)</p>"
    "<p>L'esprit Gueules de Bois : du son, des potes, du BMX.</p>"
    "<p>Hiver 2027 13 février à Légna. "
    "Les Ramoneurs de Menhirs, Le Réparateur, PKRK, Blondi Beat Rousse.</p>"
    "<h2>Retour sur l'édition 2026</h2>"
    "<p>Les Gueules de Bois ont soufflé leurs bougies en 2025.</p>"
    "</section></main>"
)
GROS = (
    "<main><p>.07.08 Mai 2027</p>"
    "<h2>Replonge dans le millésime 2026 du GROS TONNEAU !</h2>"
    "<p>Aftermovie 2026. Une jolie 6ème cuvée se prépare.</p>"
    "<p>Le Gros Tonneau est un festival Punk Hardcore Métal.</p>"
    "<h2>Ils nous soutiennent</h2><p>Archives et partenaires 2026</p>"
    "</main>"
)


def state():
    return {"schema": "grossesondes.source-watch.v1"}


def fetch(url):
    return {
        SOURCES["les-gueules-de-bois"]["url"]: GUEULES,
        SOURCES["le-gros-tonneau"]["url"]: GROS,
    }[url]


class FirstPartyResearchTests(unittest.TestCase):
    def test_approved_roster_matches_exact_historical_public_sources(self):
        candidates = {
            slug: {"name": config["name"], "region": config["region"],
                   "url": config["url"]}
            for slug, config in SOURCES.items()
        }
        approved, quality = roster(
            TODAY, fetch_archive=lambda _: (candidates, "CONSISTENT"))
        self.assertEqual(quality, "CONSISTENT")
        self.assertEqual(approved, SOURCES)
        self.assertEqual(roster(TODAY, fetch_archive=lambda _: (
            candidates, "DIVERGENT")), ({}, "DIVERGENT"))
        forged = deepcopy(candidates)
        forged["les-gueules-de-bois"]["url"] = "https://evil.example/secret"
        self.assertEqual(roster(TODAY, fetch_archive=lambda _: (
            forged, "CONSISTENT")), ({}, "UNAVAILABLE_OR_INVALID"))

    def test_exact_active_hero_dates_are_separated(self):
        ids, digest = inspect_homepage(GUEULES, SOURCES["les-gueules-de-bois"])
        self.assertEqual(ids, ["summer", "winter"])
        self.assertEqual(len(digest), 64)
        ids, digest = inspect_homepage(GROS, SOURCES["le-gros-tonneau"])
        self.assertEqual(ids, ["may"])
        self.assertEqual(len(digest), 64)

    def test_archive_2026_or_other_event_cannot_supply_2027(self):
        cases = [
            "<main><h1>Les Gueules de Bois</h1><h2>Été 2026</h2>"
            "<p>19, 20 et 21 août 2026</p><h2>Hiver 2026</h2>"
            "<p>13 février 2026</p></main>",
            "<main><h1>Autre Festival 2027</h1>"
            "<h2>Été 2027</h2><p>19, 20 et 21 août</p>"
            "<h2>Hiver 2027</h2><p>13 février</p>"
            "<h2>Retour sur l'édition 2026</h2>"
            "<p>Les Gueules de Bois 2025, merci aux bénévoles.</p></main>",
            "<main><h1>Les Gueules de Bois en 2027</h1>"
            "<p>Le bilan de 2026 est disponible.</p>"
            "<script>Été 2027 19, 20 et 21 août</script>"
            "<style>Hiver 2027 13 février</style></main>",
            "<main><h1>Les Gueules de Bois 2027</h1>"
            "<p>Autre festival Été 2027 19, 20 et 21 août.</p>"
            "<p>Hiver 2027 13 février pour un autre événement.</p></main>",
        ]
        for html in cases:
            with self.subTest(html=html):
                try:
                    ids, _ = inspect_homepage(html, SOURCES["les-gueules-de-bois"])
                    self.assertEqual(ids, [])
                except ValueError:
                    pass

    def test_poster_before_old_edition_must_have_exact_brand(self):
        cases = [
            "<main><h1>Festival voisin</h1><p>07.08 mai 2027</p>"
            "<h2>Archives d'un autre festival 2026</h2></main>",
            "<main><h1>Le Gros Tonneau 2026</h1>"
            "<p>07.08 mai 2026</p><h2>Replonge dans le millésime 2026 du"
            " GROS TONNEAU</h2></main>",
            "<main><p>.07.08 mai 2027</p><h2>Un autre festival</h2>"
            "<p>Replonge dans le millésime 2026 du GROS TONNEAU</p></main>",
            "<main><p>07 08 mai 2027</p>"
            "<h2>Retour sur l'édition 2026</h2>"
            "<p>Le Gros Tonneau festival 2026</p></main>",
        ]
        for html in cases:
            with self.subTest(html=html):
                try:
                    ids, _ = inspect_homepage(html, SOURCES["le-gros-tonneau"])
                    self.assertEqual(ids, [])
                except ValueError:
                    pass

    def test_scan_visits_only_two_pinned_homepages(self):
        st = state()
        seen = []
        out = scan(st, SOURCES, TODAY, fetch=lambda url: (
            seen.append(url), fetch(url))[1])
        self.assertEqual(seen, [SOURCES[slug]["url"] for slug in sorted(SOURCES)])
        self.assertEqual(len(out), 2)
        self.assertTrue(all(x["publication_authorized"] is False for x in out))
        reviews = validated_observations(st, TODAY)
        self.assertEqual(len(reviews), 2)
        self.assertEqual(sum(len(x["claims"]) for x in reviews), 3)
        self.assertEqual(scan(st, SOURCES, TODAY, fetch=lambda _:
                              self.fail("same-day fetch")), [])
        for row in reviews:
            self.assertFalse(row["edition_dates_verified"])
            self.assertFalse(row["independence_verified"])
            self.assertFalse(row["organizer_verified"])
            self.assertFalse(row["publication_authorized"])
            self.assertTrue(all(not x["edition_dates_verified"]
                                for x in row["claims"]))

    def test_fail_closed_on_injected_url_and_unbounded_limit(self):
        fake = deepcopy(SOURCES)
        fake["les-gueules-de-bois"]["url"] = "https://evil.example/private"
        with self.assertRaises(ValueError):
            scan(state(), fake, TODAY,
                 fetch=lambda _: self.fail("unapproved URL"))
        with self.assertRaises(ValueError):
            scan(state(), SOURCES, TODAY, limit=3,
                 fetch=lambda _: self.fail("budget exceeded"))

    def test_failed_recheck_erases_previous_positive_evidence(self):
        st = state()
        scan(st, SOURCES, TODAY, fetch=fetch)
        new = scan(st, SOURCES, TOMORROW,
                   fetch=lambda _: (_ for _ in ()).throw(OSError("HTTP 403")))
        self.assertEqual(len(new), 2)
        self.assertEqual(validated_observations(st, TOMORROW), [])
        self.assertEqual(st["first_party_edition_observations_private"], {})

    def test_private_forgery_cannot_turn_hint_into_verified_dates(self):
        st = state()
        scan(st, SOURCES, TODAY, fetch=fetch)
        originals = deepcopy(st["first_party_edition_observations_private"])
        patches = (
            {"url": "https://evil.example/payload"},
            {"claim_ids": ["summer", "winter", "fake"]},
            {"claim_ids": ["winter", "summer"]},  # unsorted IDs
            {"publication_authorized": True},
            {"edition_dates_verified": True},
            {"independence_verified": True},
            {"organizer_verified": True},
            {"safe_to_publish": True},
            {"review_only": False},
            {"observed_at": "2027-02-13"},
        )
        for patch in patches:
            with self.subTest(patch=patch):
                st["first_party_edition_observations_private"] = deepcopy(originals)
                st["first_party_edition_observations_private"][
                    "les-gueules-de-bois"].update(patch)
                self.assertEqual(len(validated_observations(st, TODAY)), 1)

    def test_first_party_dates_reconcile_with_press_but_stay_private(self):
        from targeted_press_edition_watch import (
            SOURCES as PRESS, scan as press_scan,
        )
        from historical_future_lead_watch import (
            APPROVED as HISTORIC, scan as historical_scan,
        )
        from national_discovery_queue import build_queue
        from national_editorial_reconciliation import build_review
        st = state()
        scan(st, SOURCES, TODAY, fetch=fetch)
        press_html = (
            "<main><h1>Les Gueules de Bois en 2027</h1>"
            "<p>Premier rendez-vous le samedi 13 février 2027.</p>"
            "<p>Les bénévoles préparent la septième édition du festival, "
            "programmée les 19, 20 et 21 août 2027.</p></main>"
        )
        press_scan(st, {"gueules-progres": PRESS["gueules-progres"]},
                   TODAY, fetch=lambda _: press_html)
        slug = "le-gros-tonneau"
        historic_name, historic_region, historic_url = HISTORIC[slug]
        historical_scan(st, {slug: {
            "slug": slug, "name": historic_name, "region": historic_region,
            "url": historic_url, "last_known_year": 2026,
        }}, TODAY, fetch=lambda _: (
            "<main><h1>Le Gros Tonneau 2027</h1>"
            "<p>07 et 08 mai 2027 à Artonne.</p></main>"
        ))
        report = {
            "schema": "grossesondes.source-watch-report.v1", "date": TODAY,
            "source_reference_leads_review_only": [],
            "historical_future_watch_archive_status_private": "CONSISTENT",
            "press_edition_archive_integrity_private": "CONSISTENT",
        }
        queue = build_queue(st, report, [], TODAY)
        self.assertEqual(queue["candidate_dossiers_count"], 2)
        detail = {
            "schema": "grossesondes.national-detail-qualification-private.v1",
            "as_of": TODAY, "review_only": True,
            "publication_authorized": False, "safe_to_publish": False,
            "observations": [],
        }
        archives = {
            "schema": 2, "knownFestivals": [
                {
                    "slug": "les-gueules-de-bois",
                    "name": "Les Gueules de Bois",
                    "region": "Bourgogne-Franche-Comté", "city": "Légna",
                    "lastKnownYear": 2026,
                    "startDate": "2026-08-20",
                    "endDate": "2026-08-22",
                    "officialSite": SOURCES["les-gueules-de-bois"]["url"],
                },
                {
                    "slug": "le-gros-tonneau", "name": "Le Gros Tonneau",
                    "region": "Auvergne-Rhône-Alpes", "city": "Artonne",
                    "lastKnownYear": 2026,
                    "startDate": "2026-05-07",
                    "endDate": "2026-05-08",
                    "officialSite": SOURCES["le-gros-tonneau"]["url"],
                },
            ],
        }
        review = build_review(
            queue, detail, st, [], {"schema": 1, "festivals": []},
            archives, TODAY,
        )
        self.assertEqual(review["dossiers_count"], 2)
        self.assertEqual(review["first_party_date_claim_dossiers_private"], 2)
        self.assertEqual(review["first_party_date_claims_private"], 3)
        self.assertEqual(review["first_party_press_agreement_dates_private"], 2)
        self.assertEqual(review["publications"], 0)
        gueules = next(x for x in review["dossiers"] if
                       x["name_hint"] == "Les Gueules de Bois")
        tonneau = next(x for x in review["dossiers"] if
                       x["name_hint"] == "Le Gros Tonneau")
        self.assertEqual(gueules["status"], "FIRST_PARTY_AND_PRESS_DATE_REVIEW")
        self.assertEqual(tonneau["status"], "FIRST_PARTY_VISIBLE_DATE_REVIEW")
        self.assertEqual(len(gueules["first_party_press_same_dates_review_only"]), 2)
        self.assertEqual(len(gueules["first_party_edition_date_claims_review_only"][0]
                             ["claims"]), 2)
        self.assertEqual(len(tonneau["first_party_edition_date_claims_review_only"][0]
                             ["claims"]), 1)
        for dossier in (gueules, tonneau):
            self.assertNotIn("first_party_date_observation_missing",
                             dossier["missing_checks"])
            self.assertIn("independent_date_confirmation",
                          dossier["missing_checks"])
            self.assertIn("organizer_identity", dossier["missing_checks"])
            self.assertIn("editorial_approval", dossier["missing_checks"])
            self.assertIn("first_party_website_claim_requires_editorial_confirmation",
                          dossier["missing_checks"])
            self.assertFalse(dossier["future_edition_confirmed"])
            self.assertFalse(dossier["publication_authorized"])
            self.assertFalse(dossier["safe_to_publish"])
        # Generic same-year coverage of one edition MUST NOT hide another.
        for start, end, other in (
                ("2027-02-13", "2027-02-13", "2027-08-19"),
                ("2027-08-19", "2027-08-21", "2027-02-13")):
            with self.subTest(published_start=start):
                same_year = build_review(
                    queue, detail, st, [],
                    {"schema": 1, "festivals": [{
                        "slug": "les-gueules-de-bois-one-2027",
                        "name": "Les Gueules de Bois", "region":
                            "Bourgogne-Franche-Comté", "city": "Légna",
                        "startDate": start, "endDate": end,
                    }]}, archives, TODAY)
                existing = next(x for x in same_year["dossiers"]
                                if x["name_hint"] == "Les Gueules de Bois")
                self.assertEqual(existing["status"], "POTENTIAL_CONFLICT_REVIEW")
                self.assertEqual(len(
                    existing["first_party_uncovered_date_claims_review_only"]), 1)
                self.assertEqual(
                    existing["first_party_uncovered_date_claims_review_only"][0]
                    ["start_date_hint"], other)
                self.assertIn("published_same_year_may_hide_other_edition",
                              existing["missing_checks"])
                self.assertEqual(same_year["publications"], 0)

        # Poisoned private evidence cannot survive reconciliation.
        st["first_party_edition_observations_private"]["les-gueules-de-bois"][
            "edition_dates_verified"] = True
        poisoned = build_review(queue, detail, st, [],
                                {"schema": 1, "festivals": []}, archives, TODAY)
        restored = next(x for x in poisoned["dossiers"]
                        if x["name_hint"] == "Les Gueules de Bois")
        self.assertEqual(restored["status"], "PRESS_DATE_CLAIM_REVIEW")
        self.assertIn("first_party_date_observation_missing",
                      restored["missing_checks"])
        self.assertEqual(poisoned["publications"], 0)

    def test_primary_and_catchup_each_check_once_per_day(self):
        st = state()
        seen = []

        def recording_fetch(url):
            seen.append(url)
            return fetch(url)

        self.assertEqual(len(scan(st, SOURCES, TODAY,
                                  fetch=recording_fetch, phase="primary")), 2)
        self.assertEqual(len(scan(st, SOURCES, TODAY,
                                  fetch=recording_fetch, phase="primary")), 0)
        self.assertEqual(len(seen), 2)
        # Existing evening cron checks the same two approved sites again.
        self.assertEqual(len(scan(st, SOURCES, TODAY,
                                  fetch=recording_fetch, phase="catchup")), 2)
        self.assertEqual(len(scan(st, SOURCES, TODAY,
                                  fetch=recording_fetch, phase="catchup")), 0)
        self.assertEqual(len(seen), 4)
        self.assertEqual(sum(len(x["claims"]) for x in
                             validated_observations(st, TODAY)), 3)
        self.assertEqual(len(scan(st, SOURCES, TOMORROW,
                                  fetch=recording_fetch, phase="primary")), 2)
        self.assertEqual(len(seen), 6)

    def test_evening_failure_invalidates_morning_evidence(self):
        st = state()
        scan(st, SOURCES, TODAY, fetch=fetch, phase="primary")
        self.assertEqual(len(validated_observations(st, TODAY)), 2)

        def unavailable(_):
            raise OSError("temporary network failure")

        self.assertEqual(len(scan(st, SOURCES, TODAY,
                                  fetch=unavailable, phase="catchup")), 2)
        self.assertEqual(validated_observations(st, TODAY), [])
        self.assertEqual(len(scan(st, SOURCES, TODAY,
                                  fetch=unavailable, phase="catchup")), 0)

    def test_legacy_daily_check_and_poisoned_phases_fail_closed(self):
        # The private register is allowed to lack phase stamps on upgrade.
        st = state()
        st["first_party_edition_checks_private"] = {
            slug: TODAY for slug in SOURCES
        }
        self.assertEqual(scan(st, SOURCES, TODAY,
                              fetch=fetch, phase="primary"), [])
        self.assertEqual(len(scan(st, SOURCES, TODAY,
                                  fetch=fetch, phase="catchup")), 2)
        with self.assertRaises(ValueError):
            scan(st, SOURCES, TODAY, fetch=fetch, phase="third")
        st["first_party_edition_phase_checks_private"][
            "les-gueules-de-bois"]["phases"] = ["catchup", "catchup"]
        with self.assertRaises(ValueError):
            scan(st, SOURCES, TODAY, fetch=fetch, phase="primary")

    def test_stale_observations_expire(self):
        st = state()
        scan(st, SOURCES, TODAY, fetch=fetch)
        self.assertEqual(validated_observations(st, "2026-11-22"), [])


if __name__ == "__main__":
    unittest.main()
