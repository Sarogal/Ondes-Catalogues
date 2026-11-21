"""Fail-closed, offline end-to-end contract for officially announced undated editions."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from grossesondes_undated_edition import (
    PROOF_MODE, private_proposal, visible_future_edition_without_dates,
    validate_verified_row, conflicting_undated_edition,
)
from grossesondes_cloud_sync import (
    collect_registered_edition_sources, browser_needed_for_pending_patch,
)

ARCHIVED = {
    "slug": "xtreme-fest", "name": "Xtreme Fest",
    "lastKnownYear": 2026,
    "startDate": "2026-07-30", "endDate": "2026-08-02",
    "officialSite": "https://xtremefest.fr/",
    "city": "Le Garric", "venue": "Cap Découverte",
    "lat": 44.02, "lon": 2.15,
    "lineup": ["Pennywise"], "price": "ancien tarif",
}
TODAY = date(2026, 11, 21)
OFFICIAL = (
    "<html><body><main><h1>RENDEZ-VOUS EN 2027 !</h1>"
    "<p>L'Xtreme Fest est un festival associatif consacré au punk rock, "
    "au hardcore et au metal.</p>"
    "<p>La playlist Xtreme Fest 2026 reste consultable.</p>"
    "</main></body></html>"
)


class UndatedFutureEditionTests(unittest.TestCase):
    def setUp(self):
        self.proposal = private_proposal(ARCHIVED, 2027, TODAY)
        self.assertIsNotNone(self.proposal)

    def test_official_future_edition_can_be_admitted_without_dates(self):
        self.assertTrue(visible_future_edition_without_dates(
            OFFICIAL, ARCHIVED, 2027))
        approved = validate_verified_row(
            self.proposal, ARCHIVED, OFFICIAL, TODAY.isoformat())
        self.assertIsNotNone(approved)
        self.assertEqual(approved["slug"], "xtreme-fest-2027")
        self.assertEqual(approved["name"], "Xtreme Fest 2027")
        self.assertIsNone(approved["startDate"])
        self.assertIsNone(approved["endDate"])
        self.assertEqual(approved["status"], "Dates à venir")
        self.assertFalse(approved["showOnMap"])
        self.assertIsNone(approved["city"])
        self.assertIsNone(approved["lat"])
        self.assertIsNone(approved["lon"])
        self.assertEqual(approved["lineup"], [])
        self.assertEqual(approved["bands"], 0)
        self.assertIsNone(approved["price"])
        self.assertEqual(approved["officialSite"], ARCHIVED["officialSite"])
        self.assertEqual(set(approved), set(self.proposal) - {
            "proofMode", "originSlug", "evidence", "verified_at"
        })

    def test_new_brand_name_allowed_without_list(self):
        novel = deepcopy(ARCHIVED)
        novel["slug"] = "inconnu-fest-des-montagnes"
        novel["name"] = "Inconnu Fest des Montagnes"
        novel["officialSite"] = "https://festival-inedit.fr/"
        html = ("<main><h2>Édition 2 — Été 2027</h2>"
                "<p>Inconnu Fest des Montagnes, festival punk-metal.</p></main>")
        proposal = private_proposal(novel, 2027, TODAY)
        self.assertIsNotNone(validate_verified_row(
            proposal, novel, html, TODAY.isoformat()))

    def test_prepare_or_fundraise_for_2027_is_not_a_confirmed_edition(self):
        html = ("<p>Pour préparer le Xtreme Fest 2027 nous cherchons "
                "des dons après l'édition 2026.</p>")
        self.assertFalse(visible_future_edition_without_dates(
            html, ARCHIVED, 2027))
        self.assertIsNone(validate_verified_row(
            self.proposal, ARCHIVED, html, TODAY.isoformat()))

    def test_no_guess_from_old_year_or_footer_and_unrelated_tour(self):
        for html in (
            "<p>Xtreme Fest 2026</p><p>© 2027</p>",
            "<p>Xtreme Fest : festival 2026</p>"
            "<p>Reconstruction Tour : rendez-vous en 2027</p>",
            "<script>rendez-vous en 2027</script><p>Xtreme Fest</p>",
            "<template><h2>Édition 2027</h2></template><p>Xtreme Fest</p>",
            "<p>Xtreme Fest 2027 peut-être, sous réserve du budget.</p>",
        ):
            with self.subTest(html=html):
                self.assertIsNone(validate_verified_row(
                    self.proposal, ARCHIVED, html, TODAY.isoformat()))

    def test_date_claim_and_cancellation_do_not_become_undated(self):
        cases = [
            "<h2>Xtreme Fest, édition 2027</h2>"
            "<p>Festival les 30 et 31 juillet 2027</p>",
            "<h2>Xtreme Fest édition 2027 annulée</h2>",
            "<h2>Xtreme Fest 2027 : rendez-vous en 2027 ?"
            " Finalement annulé.</h2>",
        ]
        for html in cases:
            with self.subTest(html=html):
                self.assertIsNone(validate_verified_row(
                    self.proposal, ARCHIVED, html, TODAY.isoformat()))

    def test_forged_fields_or_missing_signed_parent_rejected(self):
        for field, bad_value in (
            ("officialSite", "https://attacker.example/"),
            ("source", "https://attacker.example/"),
            ("originSlug", "another-festival"),
            ("name", "Other Festival 2027"),
            ("startDate", "2027-07-30"),
            ("lat", ARCHIVED["lat"]),
            ("city", ARCHIVED["city"]),
            ("showOnMap", True),
            ("lineup", ["Old Act"]),
            ("status", "Confirmé"),
            ("verified_at", "2026-11-22"),
        ):
            with self.subTest(field=field):
                forged = deepcopy(self.proposal)
                forged[field] = bad_value
                self.assertIsNone(validate_verified_row(
                    forged, ARCHIVED, OFFICIAL, TODAY.isoformat()))
        forged = deepcopy(self.proposal)
        forged["newTrustedFlag"] = True
        self.assertIsNone(validate_verified_row(
            forged, ARCHIVED, OFFICIAL, TODAY.isoformat()))
        parent = deepcopy(ARCHIVED)
        parent["officialSite"] = "https://attacker.example/"
        self.assertIsNone(validate_verified_row(
            self.proposal, parent, OFFICIAL, TODAY.isoformat()))

    def test_already_published_or_same_name_dated_collision_is_refused(self):
        self.assertTrue(conflicting_undated_edition(
            self.proposal, [{"slug": "xtreme-fest-2027"}], []))
        self.assertTrue(conflicting_undated_edition(
            self.proposal,
            [{"slug": "different", "name": "Xtreme Fest 2027",
              "startDate": "2027-07-30"}], []))
        self.assertFalse(conflicting_undated_edition(
            self.proposal, [], [ARCHIVED]))

    def test_cloud_publisher_fetches_only_signed_archive_organizer(self):
        patch_data = {"additions": [self.proposal]}
        visits = []
        def fetch(url, *, registered=False, raw=False):
            visits.append((url, registered, raw))
            return OFFICIAL
        result = collect_registered_edition_sources(
            patch_data, {}, fetcher=fetch,
            archived={ARCHIVED["slug"]: ARCHIVED},
            published_slugs=set())
        self.assertEqual(visits, [(ARCHIVED["officialSite"], True, True)])
        self.assertEqual(
            result["registered-edition:xtreme-fest-2027"], OFFICIAL)
        self.assertFalse(browser_needed_for_pending_patch(patch_data, set()))
        self.assertEqual(collect_registered_edition_sources(
            patch_data, {}, fetcher=fetch,
            archived={ARCHIVED["slug"]: ARCHIVED},
            published_slugs={"xtreme-fest-2027"}), {})
        self.assertEqual(len(visits), 1)

    def test_actual_stage_admits_only_independently_rechecked_row(self):
        from grossesondes_preview import CAL_URL, HIS_URL
        from grossesondes_stage import stage
        baseline_rows = [
            {"slug": "unrelated-calendar-" + str(n),
             "name": "Unrelated festival " + str(n)}
            for n in range(90)
        ]
        archive_rows = [
            {"slug": "unrelated-history-" + str(n),
             "name": "Unrelated historical festival " + str(n)}
            for n in range(90)
        ] + [ARCHIVED]
        original = {"schema": 1, "generatedAt": "2026-10-25",
                    "festivals": baseline_rows}
        history = {"schema": 2, "updatedAt": "2026-10-25",
                   "knownFestivals": archive_rows}
        patch_data = {
            "schema": "grossesondes.patch.v1",
            "safe_to_publish": False,
            "source": {
                "festivals": {"url": CAL_URL,
                              "generatedAt": "2026-10-25", "count": 90},
                "history": {"url": HIS_URL,
                            "updatedAt": "2026-10-25", "count": 91},
            },
            "additions": [self.proposal], "updates": [],
            "history_additions": [], "history_updates": [], "deferred": [],
        }
        sources = {"registered-edition:xtreme-fest-2027": OFFICIAL}
        target, report = stage(
            original, history, patch_data, sources, TODAY.isoformat())
        self.assertEqual(report["accepted_additions"], ["xtreme-fest-2027"])
        self.assertEqual(target["festivals"][-1]["status"], "Dates à venir")
        self.assertIsNone(target["festivals"][0]["startDate"])
        self.assertFalse(target["festivals"][0]["showOnMap"])
        rejected, fail = stage(
            original, history, patch_data,
            {"registered-edition:xtreme-fest-2027":
             "<h2>Festival 2027 possible sous réserve</h2>"},
            TODAY.isoformat())
        self.assertEqual(len(rejected["festivals"]), 90)
        self.assertEqual(fail["accepted_additions"], [])
        # Signed duplicate must not generate another edition.
        signed = deepcopy(target)
        duplicated, blocked = stage(
            original, history, patch_data, sources,
            TODAY.isoformat(), published_calendar=signed)
        self.assertEqual(len(duplicated["festivals"]), 90)
        self.assertEqual(blocked["already_published"], ["xtreme-fest-2027"])

    def test_two_days_required_even_if_same_page_is_repeated_today(self):
        import grossesondes_archived_html_intake as intake
        state = {}
        self.assertFalse(intake.stability(
            state, self.proposal, ARCHIVED["officialSite"], TODAY))
        self.assertFalse(intake.stability(
            state, self.proposal, ARCHIVED["officialSite"], TODAY))
        self.assertTrue(intake.stability(
            state, self.proposal, ARCHIVED["officialSite"],
            date(2026, 11, 22)))


if __name__ == "__main__":
    unittest.main()
