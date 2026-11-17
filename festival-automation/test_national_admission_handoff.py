"""Offline-only fail-closed contracts for national festival publisher handoff."""
from copy import deepcopy
import unittest

from national_admission_handoff import build_handoff, SCHEMA
from national_candidate_promotion import build_review as promotion_review
from test_national_candidate_promotion import (
    DAY, SPEC, inputs, web_sources,
    MAPS_FR, MAPS_EN,
)


def fixtures():
    editorial, public, history = inputs()
    editorial["dossiers_count"] = len(editorial["dossiers"])
    editorial["publications"] = 0
    history["knownFestivals"][0].update(
        slug="mozhell-open-air", region="Grand Est",
        startDate="2026-07-24", endDate="2026-07-26",
        officialSite="https://www.mozhell.fr/fr/")
    pages = web_sources()
    raw = {SPEC["access_fr_url"]: MAPS_FR, SPEC["access_en_url"]: MAPS_EN}
    candidate = promotion_review(
        editorial, public, history, DAY,
        fetcher=pages.__getitem__, html_fetcher=raw.__getitem__)
    return editorial, candidate, public, history


class NationalPublisherHandoffTests(unittest.TestCase):
    def test_private_core_suggests_archive_route_but_no_patch(self):
        source = fixtures()
        output = build_handoff(*source, DAY)
        self.assertEqual(output["schema"], SCHEMA)
        self.assertEqual(output["dossiers_total"], 1)
        self.assertEqual(output["edition_cores_rechecked_private"], 1)
        self.assertEqual(output["archive_parents_identified_private"], 1)
        self.assertEqual(output["publisher_ready_count"], 0)
        self.assertEqual(output["publications"], 0)
        self.assertIs(output["publisher_patch_created"], False)
        self.assertIs(output["publisher_gate_connected"], False)
        row = output["dossiers"][0]
        self.assertEqual(row["status"], "ARCHIVED_PUBLISHER_PROOF_REQUIRED")
        self.assertEqual(row["archive_parent_slug_review_only"], "mozhell-open-air")
        self.assertEqual(row["edition_core_review_only"]["startDate"],
                         "2027-07-23")
        self.assertIn("current_edition_jsonld_independent_recheck",
                      row["required_checks"])
        self.assertIn("venue_coordinates_confirmation", row["required_checks"])
        self.assertFalse(row["publisher_patch_ready"])
        self.assertFalse(row["publication_authorized"])
        self.assertNotIn("lat", row["edition_core_review_only"])
        self.assertNotIn("lineup", row["edition_core_review_only"])

    def test_missing_archived_origin_cannot_be_borrowed(self):
        editorial, candidate, published, history = fixtures()
        history["knownFestivals"][0]["officialSite"] = "https://fake.invalid"
        output = build_handoff(editorial, candidate, published, history, DAY)
        self.assertEqual(output["archive_parents_identified_private"], 0)
        self.assertEqual(output["dossiers"][0]["status"],
                         "NO_TRUSTED_ARCHIVE_PARENT")
        self.assertFalse(output["dossiers"][0]["publisher_patch_ready"])

    def test_duplicate_known_edition_invalidates_handoff(self):
        editorial, candidate, published, history = fixtures()
        published["festivals"].append({
            "slug": "mozhell-open-air-2027", "name": "MozHell Open Air 2027",
            "startDate": "2027-07-23",
        })
        row = build_handoff(editorial, candidate, published, history, DAY)[
            "dossiers"][0]
        self.assertEqual(row["status"], "DUPLICATE_OR_CONFLICT_REVIEW")
        self.assertIsNone(row["edition_core_review_only"])
        self.assertFalse(row["publisher_patch_ready"])

    def test_one_unreviewed_national_dossier_stays_unverified(self):
        editorial, candidate, published, history = fixtures()
        editorial["dossiers"].append({
            "id": "another-test", "name_hint": "Another Metal Fest",
            "edition_year_hint": 2027, "region_hint": "Occitanie",
            "status": "RESEARCH_REQUIRED", "review_only": True,
            "safe_to_publish": False, "publication_authorized": False,
        })
        editorial["dossiers_count"] = 2
        candidate["dossiers"].append({
            "id": "another-test", "name_hint": "Another Metal Fest",
            "edition_year_hint": 2027, "status": "RESEARCH_REQUIRED",
            "verified_fields_private": {},
            "review_only": True, "safe_to_publish": False,
            "publication_authorized": False,
        })
        candidate["dossiers_total"] = 2
        output = build_handoff(editorial, candidate, published, history, DAY)
        self.assertEqual(output["dossiers_total"], 2)
        self.assertEqual(output["edition_cores_rechecked_private"], 1)
        self.assertEqual(output["dossiers"][1]["status"],
                         "PRIMARY_EVIDENCE_PENDING")
        self.assertFalse(output["dossiers"][1]["publisher_patch_ready"])

    def test_spoofed_review_approval_and_forged_fields_fail_closed(self):
        mutations = [
            lambda e,c,p,h: c.update(publication_authorized=True),
            lambda e,c,p,h: e.update(safe_to_publish=True),
            lambda e,c,p,h: c["dossiers"][0].update(safe_to_publish=True),
            lambda e,c,p,h: c["dossiers"][0]["verified_fields_private"].update(
                startDate="2027-07-24"),
            lambda e,c,p,h: c["dossiers"][0]["verified_fields_private"].update(
                lat=48.95),
            lambda e,c,p,h: c["dossiers"][0]["verified_fields_private"].update(
                lineup=["Unknown Artist"], bands=1),
            lambda e,c,p,h: c["dossiers"][0]["checked_official_urls"].clear(),
            lambda e,c,p,h: c.update(source_review_as_of="2026-11-14"),
            lambda e,c,p,h: e["dossiers"][0].update(
                name_hint="Different Festival"),
            lambda e,c,p,h: c["dossiers"][0].update(id="other-dossier"),
            lambda e,c,p,h: c.update(dossiers_total=2),
        ]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                data = deepcopy(fixtures())
                mutate(*data)
                with self.assertRaises(ValueError):
                    build_handoff(*data, DAY)

    def test_core_missing_with_injected_published_fields_is_not_an_approval(self):
        editorial, candidate, published, history = fixtures()
        row = candidate["dossiers"][0]
        row["status"] = "RESEARCH_REQUIRED"
        row["verified_fields_private"] = {"startDate": "2027-07-23"}
        with self.assertRaises(ValueError):
            build_handoff(editorial, candidate, published, history, DAY)

    def test_future_date_or_previous_day_review_is_not_accepted(self):
        for day in ("2026-11-14", "2027-08-01"):
            with self.subTest(day=day), self.assertRaises(ValueError):
                build_handoff(*fixtures(), day)


if __name__ == "__main__":
    unittest.main()
