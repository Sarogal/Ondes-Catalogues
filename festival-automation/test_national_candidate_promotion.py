"""Regression tests: national candidate promotion never inherits authority."""
from copy import deepcopy
import unittest

from national_candidate_promotion import build_review, APPROVED, SCHEMA

SPEC = APPROVED["mozhell-open-air-2027"]
DAY = "2026-11-15"


def inputs():
    dossier = {
        "id": "national-test-mozhell", "name_hint": "MozHell Open Air",
        "edition_year_hint": 2027, "region_hint": "Grand Est",
        "city_hint": "Insming", "status": "PRIMARY_DATE_CLAIM_REVIEW",
        "review_only": True, "safe_to_publish": False,
        "publication_authorized": False,
        "primary_observation": {
            "source_url": SPEC["dates_url"], "dates_visible_in_primary": True,
            "start_date_hint": SPEC["start"], "end_date_hint": SPEC["end"],
            "publication_authorized": False},
        "published_exact_edition_matches": [],
        "published_city_conflicts": [],
        "published_title_city_variants_review_only": [],
        "missing_checks": ["organizer_identity", "coordinates_review"],
    }
    editorial = {
        "schema": "grossesondes.national-editorial-reconciliation-private.v1",
        "review_only": True, "safe_to_publish": False,
        "publication_authorized": False, "as_of": DAY,
        "dossiers": [dossier],
    }
    published = {"schema": 1, "festivals": []}
    history = {"schema": 2, "knownFestivals": [
        {"name": "MozHell Open Air", "lastKnownYear": 2026,
         "city": "Insming", "lineup": ["old 2026 act"]}]}
    return editorial, published, history


def web_sources():
    return {
        SPEC["dates_url"]: "Le MozHell Open Air revient les 23, 24 et 25 juillet 2027 à Insming",
        SPEC["lineup_url"]: "MozHell 2027 Ultra Vomit THE ARRS LocoMuerte",
        SPEC["organizer_url"]: "L'Association MOZHELL PROD présente le festival",
    }


class CandidatePromotionTests(unittest.TestCase):
    def run_review(self, edits=None, sources=None, fetcher=None):
        data = list(inputs())
        if edits:
            edits(data)
        pages = web_sources() if sources is None else sources
        return build_review(*data, DAY, fetcher=fetcher or pages.__getitem__)

    def test_live_first_party_fields_rechecked_but_no_publication(self):
        report = self.run_review()
        row = report["dossiers"][0]
        self.assertEqual(report["schema"], SCHEMA)
        self.assertEqual(row["status"], "FIRST_PARTY_FIELDS_RECHECKED_PRIVATE")
        self.assertEqual(row["verified_fields_private"]["lineup"],
                         ["Ultra Vomit", "THE ARRS", "LocoMuerte"])
        self.assertEqual(row["verified_fields_private"]["organizer"], "MOZHELL PROD")
        self.assertEqual(row["verified_fields_private"]["startDate"], "2027-07-23")
        self.assertFalse(row["safe_to_publish"])
        self.assertFalse(report["publication_authorized"])
        self.assertEqual(report["publications"], 0)
        self.assertIn("edition_2027_venue_confirmation", row["missing_checks"])
        self.assertIn("independent_date_confirmation", row["missing_checks"])
        self.assertNotIn("venue", row["verified_fields_private"])
        self.assertNotIn("lat", row["verified_fields_private"])

    def test_old_year_is_not_a_future_confirmation(self):
        source = web_sources()
        source[SPEC["dates_url"]] = "MozHell Open Air 24 25 et 26 juillet 2026 à Insming"
        row = self.run_review(sources=source)["dossiers"][0]
        self.assertEqual(row["status"], "OFFICIAL_CLAIMS_NOT_RECONFIRMED")
        self.assertFalse(row["verified_fields_private"])

    def test_incomplete_lineup_fails_closed(self):
        source = web_sources()
        source[SPEC["lineup_url"]] = "MozHell 2027 Ultra Vomit THE ARRS"
        self.assertEqual(self.run_review(sources=source)["dossiers"][0]["status"],
                         "OFFICIAL_CLAIMS_NOT_RECONFIRMED")

    def test_collision_with_public_slug_refuses(self):
        def edits(args):
            args[1]["festivals"].append(
                {"slug": "mozhell-open-air-2027", "name": "MozHell Open Air 2027"})
        self.assertEqual(self.run_review(edits=edits)["dossiers"][0]["status"],
                         "DUPLICATE_OR_CONFLICT")

    def test_archive_same_year_is_not_auto_promoted(self):
        def edits(args):
            args[2]["knownFestivals"][0]["lastKnownYear"] = 2027
        self.assertEqual(self.run_review(edits=edits)["dossiers"][0]["status"],
                         "DUPLICATE_OR_CONFLICT")

    def test_other_dossiers_not_implicitly_approved(self):
        def edits(args):
            args[0]["dossiers"][0]["name_hint"] = "Esqui Riot"
            args[0]["dossiers"][0]["publication_authorized"] = False
        result = self.run_review(edits=edits, fetcher=lambda _: self.fail("No network"))
        self.assertEqual(result["dossiers"][0]["status"], "RESEARCH_REQUIRED")
        self.assertEqual(result["first_party_rechecked_count"], 0)

    def test_spoofed_private_approval_does_not_override_gate(self):
        def edits(args):
            args[0]["dossiers"][0]["safe_to_publish"] = True
        row = self.run_review(edits=edits)["dossiers"][0]
        self.assertEqual(row["status"], "PRIMARY_EVIDENCE_MISMATCH")
        self.assertFalse(row["publication_authorized"])

    def test_malformed_or_unsafe_review_rejected(self):
        def edits(args):
            args[0]["safe_to_publish"] = True
        with self.assertRaises(ValueError):
            self.run_review(edits=edits)

    def test_network_failure_private_and_non_publishing(self):
        def fetch(_):
            raise RuntimeError("an upstream URL included an unsafe secret")
        row = self.run_review(fetcher=fetch)["dossiers"][0]
        self.assertEqual(row["status"], "OFFICIAL_RECHECK_FAILED")
        self.assertFalse(row["verified_fields_private"])
        self.assertNotIn("unsafe secret", str(row))


if __name__ == "__main__":
    unittest.main()
