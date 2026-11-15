"""Regression tests: national candidate promotion never inherits authority."""
from copy import deepcopy
import unittest

from national_candidate_promotion import build_review, APPROVED, SCHEMA
from test_map_reference import FR as MAPS_FR, EN as MAPS_EN

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
        SPEC["locality_url"]: "Le festival se déroulera au cœur du village d'Insming les 23 24 et 25 juillet 2027.",
        SPEC["press_url"]: "MozHell Open Air 2027 trois premiers groupes Ultra Vomit THE ARRS LocoMuerte du 23 au 25 juillet à Insming",
    }


class CandidatePromotionTests(unittest.TestCase):
    def run_review(self, edits=None, sources=None, fetcher=None, map_html=None):
        data = list(inputs())
        if edits:
            edits(data)
        pages = web_sources() if sources is None else sources
        html = {SPEC["access_fr_url"]: MAPS_FR, SPEC["access_en_url"]: MAPS_EN}
        if map_html is not None:
            html = map_html
        return build_review(*data, DAY, fetcher=fetcher or pages.__getitem__,
                            html_fetcher=html.__getitem__)

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

    def test_village_location_and_press_agreement_not_independent(self):
        row = self.run_review()["dossiers"][0]
        self.assertEqual(row["crosschecks_private"]["organizer_2027_locality"],
                         "INSMING_VILLAGE_ONLY")
        self.assertEqual(row["crosschecks_private"]["press_agreement"],
                         "SAME_CLAIMS_PROVENANCE_UNVERIFIED")
        self.assertFalse(row["crosschecks_private"]["exact_2027_venue_verified"])
        self.assertFalse(row["crosschecks_private"]["press_independence_verified"])
        self.assertIn("independent_date_confirmation", row["missing_checks"])
        self.assertIn("edition_2027_venue_confirmation", row["missing_checks"])
        self.assertNotIn("lat", row["verified_fields_private"])
        self.assertFalse(row["publication_authorized"])

    def test_old_year_locality_does_not_certify_venue(self):
        pages = web_sources()
        pages[SPEC["locality_url"]] = "au cœur du village d'Insming 24 25 et 26 juillet 2026"
        row = self.run_review(sources=pages)["dossiers"][0]
        self.assertEqual(row["crosschecks_private"]["organizer_2027_locality"],
                         "CLAIM_NOT_RECONFIRMED")
        self.assertFalse(row["crosschecks_private"]["exact_2027_venue_verified"])

    def test_press_unavailable_does_not_erase_confirmed_first_party(self):
        pages = web_sources()
        del pages[SPEC["press_url"]]
        row = self.run_review(sources=pages)["dossiers"][0]
        self.assertEqual(row["status"], "FIRST_PARTY_FIELDS_RECHECKED_PRIVATE")
        self.assertEqual(row["crosschecks_private"]["press_agreement"], "SOURCE_UNAVAILABLE")
        self.assertFalse(row["safe_to_publish"])
        self.assertEqual(row["verified_fields_private"]["bands"], 3)

    def test_press_looks_independent_but_is_never_treated_as_such(self):
        pages = web_sources()
        pages[SPEC["press_url"]] = ("Enquête exclusive: " + pages[SPEC["press_url"]])
        row = self.run_review(sources=pages)["dossiers"][0]
        self.assertFalse(row["crosschecks_private"]["press_independence_verified"])
        self.assertFalse(row["publication_authorized"])

    def test_private_preview_contains_poi_but_is_never_published(self):
        report = self.run_review()
        row = report["dossiers"][0]
        maps = row["map_reference_private"]
        self.assertEqual(maps["geo_precision"], "organizer_linked_poi")
        self.assertEqual(maps["coordinates"]["lat"], 48.9580091)
        self.assertTrue(maps["official_addresses_disagree"])
        draft = row["candidate_preview_private"]
        self.assertEqual(draft["schema"],
                         "grossesondes.national-festival-preview-private.v1")
        self.assertEqual(draft["candidate"]["slug"], "mozhell-open-air-2027")
        self.assertEqual(draft["candidate"]["lineup"],
                         ["Ultra Vomit", "THE ARRS", "LocoMuerte"])
        self.assertEqual(draft["candidate"]["geoPrecision"], "commune")
        self.assertFalse(draft["candidate"]["futureVenueConfirmed"])
        self.assertFalse(draft["candidate"]["showOnMap"])
        self.assertFalse(draft["publication_authorized"])
        self.assertFalse(draft["publication_ready"])
        self.assertFalse(report["publication_authorized"])
        self.assertEqual(report["publications"], 0)

    def test_2026_access_page_is_not_sufficient_for_map_reference(self):
        html = {SPEC["access_fr_url"]:
                MAPS_FR.replace("Vendredi 23 juillet", "Vendredi 24 juillet"),
                SPEC["access_en_url"]: MAPS_EN}
        row = self.run_review(map_html=html)["dossiers"][0]
        self.assertEqual(row["map_reference_private"]["status"],
                         "MAPS_REFERENCE_UNCONFIRMED")
        self.assertNotIn("candidate_preview_private", row)
        self.assertEqual(row["status"], "FIRST_PARTY_FIELDS_RECHECKED_PRIVATE")

    def test_maps_down_does_not_block_primary_date_review(self):
        html = {SPEC["access_fr_url"]: MAPS_FR}
        row = self.run_review(map_html=html)["dossiers"][0]
        self.assertEqual(row["status"], "FIRST_PARTY_FIELDS_RECHECKED_PRIVATE")
        self.assertEqual(row["map_reference_private"]["status"],
                         "MAPS_REFERENCE_UNCONFIRMED")
        self.assertFalse(row["publication_authorized"])

    def test_maps_lookalike_domain_does_not_produce_candidate(self):
        html = {
            SPEC["access_fr_url"]: MAPS_FR.replace(
                "www.google.com", "www.google.com.attacker.invalid"),
            SPEC["access_en_url"]: MAPS_EN,
        }
        row = self.run_review(map_html=html)["dossiers"][0]
        self.assertNotIn("candidate_preview_private", row)
        self.assertIn("venue_coordinates_confirmation", row["missing_checks"])

    def test_consistent_postal_address_still_not_future_venue_proof(self):
        html = {
            SPEC["access_fr_url"]: MAPS_FR,
            SPEC["access_en_url"]: MAPS_EN.replace(
                "13 rue de l'Albe", "5 rue de l'Albe"),
        }
        row = self.run_review(map_html=html)["dossiers"][0]
        self.assertFalse(
            row["map_reference_private"]["official_addresses_disagree"])
        self.assertFalse(
            row["map_reference_private"]["future_edition_exact_venue_confirmed"])
        self.assertFalse(row["candidate_preview_private"]["candidate"]["showOnMap"])

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
