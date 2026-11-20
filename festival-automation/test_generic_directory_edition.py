"""Synthetic fail-closed proofs for unknown festival directory attribution."""
from copy import deepcopy
from pathlib import Path
import sys
from unittest import TestCase, main
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from grossesondes_cloud_sync import collect_registered_directory_sources
from grossesondes_stage import stage
from test_grosses_stage import fixtures
from grossesondes_generic_directory_edition import (
    directory_url, trusted_linked_site, verify_primary, private_proposal,
    validate_private_proposal, independently_verify, validate_verified_row,
    PROOF_MODE,
)

DAY = "2026-11-21"
TITLE = "Festibarock'in 2027"
SITE = "https://www.festibarockin.fr/"
DIRECTORY = "https://www.festivalenfrance.com/festival/festibarockin"
DATES = ("2027-06-25", "2027-06-26")
ENTRY = ("<main><h1>Festibarock'in</h1><p>Festival de rock français."
         "</p><ul><li>Site web : "
         '<a href="https://www.festibarockin.fr">www.festibarockin.fr</a>'
         "</li></ul></main>")
OFFICIAL = ("<main><h1>Festibarock'in</h1>"
            "<p>25 et 26 juin 2027 : notre festival de rock "
            "avec l'association organisatrice.</p></main>")


class GenericDirectoryProofTests(TestCase):
    def test_directory_derived_from_identity_not_patch_url(self):
        self.assertEqual(directory_url(TITLE), DIRECTORY)
        for bad in ("Other Name", "Festival 2027/../../../private",
                    "Rock 2027", "", "A 2027"):
            with self.subTest(bad=bad):
                self.assertIsNone(directory_url(bad))

    def test_exact_visible_heading_and_attributed_https_site(self):
        self.assertEqual(trusted_linked_site(ENTRY, TITLE), SITE)
        for html in (
            ENTRY.replace("<h1>Festibarock'in</h1>", "<h1>Other Fest</h1>"),
            ENTRY.replace('href="https://www.festibarockin.fr"',
                          'href="http://www.festibarockin.fr"'),
            ENTRY.replace('www.festibarockin.fr</a>',
                          'festival-info.fr</a>'),
            ENTRY.replace('www.festibarockin.fr</a>',
                          'www.festibarockin.fr</a>'
                          '<a href="https://evil.example/">Site web</a>'),
        ):
            with self.subTest(html=html[:90]):
                self.assertIsNone(trusted_linked_site(html, TITLE))

    def test_hidden_heading_cannot_claim_festival_identity(self):
        html = ENTRY.replace(
            "<h1>Festibarock'in</h1>",
            '<div hidden><h1>Festibarock\'in</h1></div>')
        self.assertIsNone(trusted_linked_site(html, TITLE))
        script = '<script><h1>Festibarock\'in</h1></script>' + ENTRY
        self.assertEqual(trusted_linked_site(script, TITLE), SITE)

    def test_only_map_free_minimal_private_proposal_is_valid(self):
        p = private_proposal(TITLE, SITE, DATES, DAY)
        self.assertEqual(p["proofMode"], PROOF_MODE)
        self.assertEqual(validate_private_proposal(p, DAY), p)
        self.assertFalse(p["showOnMap"])
        self.assertEqual(p["lineup"], [])
        for field, value in [
            ("lat", 48.0), ("region", "Grand Est"),
            ("source", "https://evil.example/"),
            ("officialSite", "https://evil.example/"),
            ("verificationStatus", "Confirmé"),
        ]:
            with self.subTest(field=field):
                q = deepcopy(p)
                q[field] = value
                self.assertIsNone(validate_private_proposal(q, DAY))
        self.assertIsNone(private_proposal(
            TITLE, "https://127.0.0.1/", DATES, DAY))

        # A structurally valid but forged date remains only a private hint:
        # the publisher's independent HTTP proof must refuse it.
        tampered = deepcopy(p)
        tampered["startDate"] = "2027-06-24"
        self.assertIsNotNone(validate_private_proposal(tampered, DAY))
        with patch("grossesondes_generic_directory_edition.verify_primary",
                   return_value=DATES):
            self.assertIsNone(independently_verify(
                tampered, DAY, directory_fetch=lambda _: ENTRY,
                organizer_fetch=lambda _: OFFICIAL))

    def test_publisher_independently_rediscovers_directory_before_site(self):
        p = private_proposal(TITLE, SITE, DATES, DAY)
        visited = []
        def directory_fetch(url):
            visited.append(url)
            self.assertEqual(url, DIRECTORY)
            return ENTRY
        def organizer_fetch(url):
            visited.append(url)
            self.assertEqual(url, SITE)
            return OFFICIAL
        with patch("grossesondes_generic_directory_edition.verify_primary",
                   return_value=DATES):
            row = independently_verify(p, DAY, directory_fetch,
                                       organizer_fetch)
        self.assertEqual(visited, [DIRECTORY, SITE])
        self.assertEqual(validate_verified_row(p, row, DAY), row)
        self.assertFalse(row["showOnMap"])
        self.assertNotIn("proofMode", row)
        self.assertEqual(row["lineup"], [])

    def test_directory_mismatch_cannot_trigger_external_request(self):
        p = private_proposal(TITLE, SITE, DATES, DAY)
        for directory in (
            ENTRY.replace('www.festibarockin.fr', 'www.faux-festival.fr'),
            '<h1>Festibarock\'in</h1><p>Site web : '
            '<a href="https://127.0.0.1/private">Site officiel</a></p>',
        ):
            with self.subTest(directory=directory[:60]):
                self.assertIsNone(independently_verify(
                    p, DAY, directory_fetch=lambda _: directory,
                    organizer_fetch=lambda _: self.fail(
                        "private site cannot authorize outbound request")))

    def test_independent_primary_genre_and_dates_are_mandatory(self):
        with patch("grossesondes_generic_directory_edition.prove_dates",
                   return_value=DATES):
            self.assertEqual(verify_primary(OFFICIAL, TITLE, 2027, DAY), DATES)
            self.assertIsNone(verify_primary(
                "<main>Festival jazz 2027</main>", TITLE, 2027, DAY))


    def test_publisher_collector_and_stage_accept_only_independently_verified(self):
        candidate = private_proposal(TITLE, SITE, DATES, DAY)
        cal, hist, patch_data = fixtures()
        patch_data["additions"] = [candidate]
        patch_data["updates"] = []
        with patch("grossesondes_generic_directory_edition.verify_primary",
                   return_value=DATES):
            proven = collect_registered_directory_sources(
                patch_data, set(), DAY,
                directory_fetch=lambda url: ENTRY,
                organizer_fetch=lambda url: OFFICIAL)
        self.assertTrue(proven.get(
            "registered-directory-verified:" + candidate["slug"]))
        staged, report = stage(
            cal, hist, patch_data, proven, DAY,
            published_calendar=cal, published_history=hist)
        self.assertEqual(report["accepted_additions"], [candidate["slug"]])
        self.assertEqual(len(staged["festivals"]), len(cal["festivals"]) + 1)
        self.assertIs(staged["festivals"][-1]["showOnMap"], False)

    def test_absent_independent_recheck_and_existing_duplicate_are_held(self):
        candidate = private_proposal(TITLE, SITE, DATES, DAY)
        cal, hist, patch_data = fixtures()
        patch_data["additions"] = [candidate]
        patch_data["updates"] = []
        attempts = []
        absent = collect_registered_directory_sources(
            patch_data, set(), DAY,
            directory_fetch=lambda url: attempts.append(url) or
                                     "<h1>Different Event</h1>",
            organizer_fetch=lambda url: self.fail(
                "No website request without independent link"))
        self.assertEqual(attempts, [DIRECTORY])
        self.assertFalse(absent)
        staged, held = stage(
            cal, hist, patch_data, absent, DAY,
            published_calendar=cal, published_history=hist)
        self.assertNotIn(candidate["slug"], [
            row["slug"] for row in staged["festivals"]])
        self.assertEqual(len(held["held"]), 1)
        duplicate_cal = deepcopy(cal)
        duplicate_cal["festivals"][3].update(
            officialSite=SITE, startDate=DATES[0], endDate=DATES[1])
        with patch("grossesondes_generic_directory_edition.verify_primary",
                   return_value=DATES):
            trusted = collect_registered_directory_sources(
                patch_data, set(), DAY,
                directory_fetch=lambda _: ENTRY,
                organizer_fetch=lambda _: OFFICIAL)
        _, rejected = stage(
            cal, hist, patch_data, trusted, DAY,
            published_calendar=duplicate_cal, published_history=hist)
        self.assertEqual(rejected["accepted_additions"], [])
        self.assertTrue(rejected["held"])

    def test_forged_site_cannot_be_dereferenced_by_publisher_collector(self):
        candidate = private_proposal(TITLE, SITE, DATES, DAY)
        candidate["officialSite"] = "https://127.0.0.1/"
        patch_data = {"additions": [candidate]}
        sources = collect_registered_directory_sources(
            patch_data, set(), DAY,
            directory_fetch=lambda _: self.fail("Untrusted proposal"),
            organizer_fetch=lambda _: self.fail("Untrusted organizer"))
        self.assertEqual(sources, {})


if __name__ == "__main__":
    main()
