"""Regression tests for exact, independent-source *claims* about a future festival."""
from copy import deepcopy
import unittest

from targeted_institutional_future_watch import (
    SOURCES, STATUS, _approved_history, _exact_dates_near_name,
    _organizer_visible_on_home,
    load_sources, scan, validated_observations,
)
from national_discovery_queue import build_queue
from national_editorial_reconciliation import build_review

TODAY = "2026-11-09"
TOMORROW = "2026-11-10"
SOURCE = SOURCES["mauges-pit-fest"]
INSTITUTIONAL_HTML = (
    "<main><p>Vendredi 8, samedi 9 octobre 2027</p>"
    "<h1>Mauges Pit Fest</h1>"
    "<p>Programmation en cours du MAUGES PIT FEST VI. "
    "Salle Thomas Dupouet, Saint-Macaire-en-Mauges, Sèvremoine.</p>"
    "<p>Proposé par DataTourisme. Annoncé par Pôle Tourisme ôsezMauges.</p>"
    "</main>"
)
OFFICIAL_2026 = (
    "<main><h1>Mauges Pit Fest</h1>"
    "<p>Le 02 octobre 2026 et le 03 octobre 2026 à "
    "Saint-Macaire-en-Mauges. Programme de 2026, 13 artistes.</p>"
    "<p>L’association Mac’N’Roll Metallicus présente le Mauges Pit Fest.</p></main>"
)
OFFICIAL_2027 = (
    "<main><h1>Mauges Pit Fest VI</h1>"
    "<p>Vendredi 8 et samedi 9 octobre 2027 à Saint-Macaire-en-Mauges.</p>"
    "</main>"
)


def history():
    return {"schema": 2, "knownFestivals": [
        {"slug": "mauges-pit-fest", "name": SOURCE["name"],
         "region": SOURCE["region"], "officialSite": SOURCE["official_home"],
         "lastKnownYear": SOURCE["archive_year"],
         "startDate": "2026-10-02", "endDate": "2026-10-03",
         "city": SOURCE["city"], "department": "49",
         "organizer": SOURCE["organizer"], "aliases": ["Mauges Pit Fest V"]},
    ]}


def state():
    return {
        "schema": "grossesondes.source-watch.v1",
        "curated_future_lead_observations": {},
        "regional_festival_candidates_review_only": {},
        "institutional_agenda_candidate_pages": {},
        "secondary_source_candidates_private": {},
    }


def report(day=TODAY, integrity="CONSISTENT"):
    return {"schema": "grossesondes.source-watch-report.v1",
            "date": day, "source_reference_leads_review_only": [],
            "institutional_future_archive_status_private": integrity}


def fake_fetch(url):
    if url == SOURCE["official_home"]:
        return OFFICIAL_2026
    if url == SOURCE["institutional_url"]:
        return INSTITUTIONAL_HTML
    raise AssertionError("unreviewed network URL: " + str(url))


def full_review(s, today=TODAY, integrity="CONSISTENT", public=None):
    queue = build_queue(s, report(today, integrity), [], today)
    detail = {
        "schema": "grossesondes.national-detail-qualification-private.v1",
        "as_of": today, "review_only": True, "publication_authorized": False,
        "safe_to_publish": False, "observations": [],
    }
    catalog = {"schema": 1, "festivals": public or []}
    editorial = build_review(queue, detail, s, [], catalog, history(), today)
    return queue, editorial


class InstitutionalPilotTests(unittest.TestCase):
    def test_exact_historical_identity_and_two_copies_required(self):
        roster = _approved_history(history(), TODAY)
        self.assertEqual(list(roster), ["mauges-pit-fest"])
        visits = []
        def get_snapshot(url):
            visits.append(url)
            return deepcopy(history())
        approved, quality = load_sources(TODAY, fetch_json=get_snapshot)
        self.assertEqual(approved, SOURCES)
        self.assertEqual(quality, "CONSISTENT")
        self.assertEqual(len(visits), 2)
        def divergent(url):
            snap = history()
            if url != visits[0]:
                snap["knownFestivals"][0]["officialSite"] = "https://evil.example/"
            return snap
        self.assertEqual(load_sources(TODAY, fetch_json=divergent),
                         ({}, "DIVERGENT"))
        for patch in (
            {"officialSite": "https://evil.example/admin"},
            {"name": "Mauges Pit Fest VI"},
            {"region": "Normandie"},
            {"lastKnownYear": 2027},
            {"endDate": "2027-10-09"},
            {"organizer": "Other Association"},
        ):
            altered = history()
            altered["knownFestivals"][0].update(patch)
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                _approved_history(altered, TODAY)

    def test_current_official_home_names_organizer_without_confirming_2027(self):
        # The primary homepage still announces 2026 while attributing the
        # festival to the reviewed association. These are separate facts.
        self.assertTrue(_organizer_visible_on_home(OFFICIAL_2026, SOURCE))
        self.assertIsNone(_exact_dates_near_name(OFFICIAL_2026, SOURCE))
        self.assertFalse(_organizer_visible_on_home(
            "<main><h1>Mauges Pit Fest</h1><p>Festival 2026.</p>"
            "<footer>Association Mac'N'Roll Metallicus présente le Mauges Pit Fest</footer>"
            "</main>", SOURCE))
        self.assertFalse(_organizer_visible_on_home(
            "<main><h1>Un autre événement</h1>"
            "<p>Une autre association présente un autre festival.</p></main>",
            SOURCE))

    def test_visible_named_2027_dates_and_stale_primary_2026(self):
        event = _exact_dates_near_name(INSTITUTIONAL_HTML, SOURCE)
        self.assertEqual(event["start_date_hint"], "2027-10-08")
        self.assertEqual(event["end_date_hint"], "2027-10-09")
        self.assertEqual(event["city_name_hint"], "Saint-Macaire-en-Mauges")
        self.assertEqual(event["venue_name_hint"], "Salle Thomas Dupouet")
        self.assertEqual(len(event["visible_text_sha256"]), 64)
        self.assertIsNone(_exact_dates_near_name(OFFICIAL_2026, SOURCE))
        self.assertIsNotNone(_exact_dates_near_name(OFFICIAL_2027, SOURCE))

    def test_full_realistic_single_institutional_source_never_claims_independence(self):
        s = state()
        visited = []
        def fetch(url):
            visited.append(url)
            return fake_fetch(url)
        results = scan(s, SOURCES, TODAY, fetch=fetch)
        self.assertEqual(visited,
                         [SOURCE["official_home"], SOURCE["institutional_url"]])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["first_party_status"], "FUTURE_DATE_NOT_VISIBLE")
        self.assertEqual(results[0]["institutional_status"],
                         "FUTURE_DATE_VISIBLE_UNVERIFIED")
        self.assertFalse(results[0]["publication_authorized"])
        hints = validated_observations(s, TODAY)
        self.assertEqual(len(hints), 1)
        self.assertFalse(hints[0]["primary_same_dates"])
        self.assertEqual(hints[0]["organizer_name_on_home_review_only"], SOURCE["organizer"])
        queue, editorial = full_review(s)
        self.assertEqual(queue["candidate_dossiers_count"], 1)
        self.assertEqual(queue["institutional_future_date_dossiers_private"], 1)
        self.assertEqual(queue["publications"], 0)
        row = queue["dossiers"][0]
        self.assertEqual(row["name_hint"], "Mauges Pit Fest")
        self.assertEqual(row["edition_year_hint"], 2027)
        self.assertEqual(row["region_hint"], SOURCE["region"])
        self.assertEqual(row["city_hint"], SOURCE["city"])
        self.assertEqual(row["date_hints"], [])
        self.assertEqual(row["institutional_future_date_hints_review_only"][0]
                         ["organizer_name_home_review_only"], SOURCE["organizer"])
        self.assertEqual(row["sources"][0]["kind"],
                         "INSTITUTIONAL_FUTURE_DATE_HINT")
        self.assertFalse(row["publication_authorized"])
        self.assertEqual(editorial["dossiers_count"], 1)
        self.assertEqual(editorial["editorial_drafts_count"], 0)
        self.assertEqual(editorial["publications"], 0)
        dossier = editorial["dossiers"][0]
        self.assertEqual(dossier["status"],
                         "INSTITUTIONAL_ONLY_FUTURE_DATE_REVIEW")
        self.assertEqual(dossier["institutional_future_date_hints_review_only"][0]
                         ["organizer_name_home_review_only"], SOURCE["organizer"])
        self.assertIn("organizer_identity", dossier["missing_checks"])
        self.assertIn("organizer_site_not_yet_confirming_future_dates",
                      dossier["missing_checks"])
        self.assertIn("institutional_syndication_not_independent_confirmation",
                      dossier["missing_checks"])
        self.assertFalse(dossier["independence_verified"])
        self.assertFalse(dossier["future_edition_confirmed"])
        self.assertEqual(editorial["institutional_future_date_dossiers_private"], 1)
        self.assertEqual(editorial["institutional_future_source_agreements_private"], 0)
        self.assertNotIn("lineup", dossier)
        self.assertEqual(scan(s, SOURCES, TODAY, fetch=lambda _: self.fail("repeat")), [])
        self.assertEqual(len(validated_observations(s, TODAY)), 1)

    def test_two_visible_sources_remain_unverified_not_auto_published(self):
        s = state()
        def fetch(url):
            return (OFFICIAL_2027 if url == SOURCE["official_home"]
                    else INSTITUTIONAL_HTML)
        scan(s, SOURCES, TODAY, fetch=fetch)
        queue, editorial = full_review(s)
        self.assertEqual(queue["candidate_dossiers_count"], 1)
        self.assertEqual(editorial["dossiers"][0]["status"],
                         "INSTITUTIONAL_AND_ORGANIZER_DATE_HINT_REVIEW")
        self.assertEqual(editorial["institutional_future_source_agreements_private"], 1)
        self.assertFalse(editorial["dossiers"][0]["future_edition_confirmed"])
        self.assertFalse(editorial["dossiers"][0]["safe_to_publish"])
        self.assertEqual(editorial["publications"], 0)
        self.assertEqual(editorial["editorial_drafts_count"], 0)

    def test_mauges_press_claim_is_not_an_independent_date_certificate(self):
        from targeted_press_edition_watch import SOURCES as PRESS, scan as press_scan
        private = state()
        scan(private, SOURCES, TODAY, fetch=fake_fetch)
        press_scan(private, {"mauges-angers": PRESS["mauges-angers"]},
                   TODAY, fetch=lambda _: (
                       "<main><h1>Le Mauges Pit Fest, bilan de la cinquième édition</h1>"
                       "<p>Le festival a eu lieu en 2026 à Saint-Macaire-en-Mauges. "
                       "D'après Ouest-France, la cinquième édition a mobilisé "
                       "des bénévoles locaux.</p>"
                       "<p>La prochaine édition du festival est d'ores et déjà "
                       "programmée pour les 8 et 9 octobre 2027.</p></main>"))
        queue, editorial = full_review(private)
        row = editorial["dossiers"][0]
        self.assertEqual(queue["candidate_dossiers_count"], 1)
        self.assertEqual(editorial["press_date_claim_dossiers_private"], 1)
        self.assertEqual(editorial["press_date_claims_private"], 1)
        self.assertEqual(row["status"], "INSTITUTIONAL_ONLY_FUTURE_DATE_REVIEW")
        self.assertEqual(row["press_date_observations_review_only"][0]["publisher"],
                         "Angers Info")
        self.assertFalse(row["press_date_observations_review_only"][0]
                         ["publisher_origin_assessed"])
        self.assertIn("press_article_origin_requires_editorial_review",
                      row["missing_checks"])
        self.assertIn("independent_date_confirmation", row["missing_checks"])
        self.assertIn("organizer_site_not_yet_confirming_future_dates",
                      row["missing_checks"])
        self.assertEqual(editorial["publications"], 0)

    def test_failed_institutional_fetch_removes_prior_claim(self):
        s = state()
        scan(s, SOURCES, TODAY, fetch=fake_fetch)
        def gone(url):
            if url == SOURCE["institutional_url"]:
                raise OSError("institutional site unavailable")
            return OFFICIAL_2026
        results = scan(s, SOURCES, TOMORROW, fetch=gone)
        self.assertEqual(results[0]["institutional_status"], "UNAVAILABLE")
        self.assertEqual(validated_observations(s, TOMORROW), [])
        queue, editorial = full_review(s, TOMORROW)
        self.assertEqual(queue["candidate_dossiers_count"], 0)
        self.assertEqual(editorial["dossiers_count"], 0)

    def test_reject_reassigned_source_html_injection_dates_and_private_poison(self):
        s = state()
        def illegal_fetch(url):
            self.fail("must not fetch altered URL: "+url)
        for patched in (
            dict(SOURCE, institutional_url="https://evil.example/admin"),
            dict(SOURCE, official_home="https://localhost/private"),
            dict(SOURCE, name="Fake Fest"),
        ):
            with self.assertRaises(ValueError):
                scan(state(), {"mauges-pit-fest": patched}, TODAY,
                     fetch=illegal_fetch)
        # Never accept an adjacent unrelated event's 2027 dates.
        hostile_html = (
            "<main><h1>Mauges Pit Fest 2026</h1><p>2 et 3 octobre 2026.</p>"
            "<h2>Another Festival</h2><p>8 et 9 octobre 2027.</p></main>"
        )
        self.assertIsNone(_exact_dates_near_name(hostile_html, SOURCE))
        scan(s, SOURCES, TODAY, fetch=fake_fetch)
        pristine = deepcopy(s["institutional_future_date_observations_private"])
        for patch in (
            {"institutional_url": "https://evil.example/admin"},
            {"start_date_hint": "2026-10-08"},
            {"edition_dates_verified": True},
            {"independence_verified": True},
            {"publication_authorized": True},
            {"city_name_hint": "Lyon"},
            {"provider_claim": "Official Organizer"},
            {"visible_text_sha256": {"not": "a digest"}},
            {"organizer_name_visible_on_home_review_only": "FORGED ORGANIZER"},
        ):
            with self.subTest(patch=patch):
                s["institutional_future_date_observations_private"] = deepcopy(pristine)
                s["institutional_future_date_observations_private"]["mauges-pit-fest"].update(patch)
                self.assertEqual(validated_observations(s, TODAY), [])
                q, edited = full_review(s)
                self.assertEqual(q["candidate_dossiers_count"], 0)
                self.assertEqual(edited["publications"], 0)

    def test_institutional_claim_does_not_duplicate_public_2027(self):
        s = state()
        scan(s, SOURCES, TODAY, fetch=fake_fetch)
        already = [{
            "slug": "mauges-pit-fest-vi-2027",
            "name": "Mauges Pit Fest 2027",
            "region": SOURCE["region"], "city": SOURCE["city"],
            "startDate": SOURCE["start"], "endDate": SOURCE["end"],
        }]
        _, review = full_review(s, public=already)
        self.assertEqual(review["dossiers"][0]["status"],
                         "PUBLISHED_EDITION_MATCH_REVIEW")
        self.assertEqual(review["editorial_drafts_count"], 0)
        other_dates = deepcopy(already)
        other_dates[0]["startDate"] = "2027-02-13"
        other_dates[0]["endDate"] = "2027-02-13"
        _, review = full_review(s, public=other_dates)
        self.assertEqual(review["dossiers"][0]["status"],
                         "POTENTIAL_CONFLICT_REVIEW")
        self.assertIn("published_same_year_may_hide_other_edition",
                      review["dossiers"][0]["missing_checks"])
        self.assertEqual(len(review["dossiers"][0]
                             ["institutional_future_uncovered_dates_review_only"]), 1)


if __name__ == "__main__":
    unittest.main()
