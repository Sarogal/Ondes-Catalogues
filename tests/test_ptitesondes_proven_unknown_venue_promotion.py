"""Unknown venue can advance only after an in-memory independent place proof.

Entirely synthetic, no network, no catalogue write. This suite verifies that
a newly discovered square (without street number and without VENUES registry
entry) does NOT bypass the unchanged event and publisher preflights.
"""
import sys
from datetime import date, timedelta
from pathlib import Path
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ptitesondes_candidate_promotion import (
    evaluate, permitted, registry_location, public_run_summary,
    unique_review_candidates,
)
from ptitesondes_shared_venue_location_evidence import location_from_proof
from test_ptitesondes_candidate_promotion import (
    base, lead as original_lead, record as original_record,
)
from test_ptitesondes_unnumbered_official_geo_proof import (
    CITY, VENUE, POINT, mint as mint_unnumbered,
)

TODAY = date(2026, 11, 20)
DATE = "2027-02-10"
KEY = ("ville les bois", "place du village")


def lead(title=None):
    candidate = original_lead(day=DATE, venue=VENUE)
    candidate["city"] = CITY
    if title is not None:
        candidate["title"] = title
    return candidate


def record():
    doc = original_record()
    doc.update(
        location_city=CITY, location_name=VENUE,
        location_department="Aveyron", location_region="Occitanie",
        location_coordinates={"lat": POINT[0], "lon": POINT[1]},
    )
    return doc


def execute(candidate=None, proof=None, *, document=None, verify=None,
            pub=None):
    ref = base()
    published = ref if pub is None else pub
    proofs = None if proof is None else {KEY: proof}
    verifier = verify or (lambda ev, originals: (True, "verified"))
    return evaluate(
        [lead() if candidate is None else candidate],
        ref, published, TODAY,
        fetch=lambda uid: record() if document is None else document,
        verifier=verifier, venue_proofs=proofs,
    )


class ProvenUnknownVenuePromotionTests(unittest.TestCase):
    def test_unknown_place_is_not_promoted_without_independent_proof(self):
        candidate = lead()
        self.assertIsNone(registry_location(candidate))
        self.assertFalse(permitted(candidate, TODAY))
        fetch = Mock(side_effect=AssertionError(
            "Unknown venue may not reach ODS without trusted location"))
        ref = base()
        patch, report = evaluate([candidate], ref, ref, TODAY, fetch=fetch)
        self.assertEqual(report["eligible_raw"], 0)
        self.assertEqual(report["accepted_preflight"], 0)
        self.assertEqual(patch["additions"], [])
        fetch.assert_not_called()

    def test_numberless_square_can_pass_location_gate_in_explicit_dry_run(self):
        witness = mint_unnumbered()
        self.assertEqual(witness.method, "dila_official_geo_plus_named_osm")
        self.assertTrue(permitted(lead(), TODAY, evidence=witness))
        verifier = Mock(return_value=(True, "independent show proof"))
        patch, report = execute(proof=witness, verify=verifier)
        self.assertEqual(report["eligible_raw"], 1)
        self.assertEqual(report["accepted_preflight"], 1)
        self.assertTrue(report["opt_in_shared_geo_proofs_in_memory"])
        self.assertFalse(patch["safe_to_publish"])
        self.assertEqual(len(patch["additions"]), 1)
        event = patch["additions"][0]
        self.assertEqual(event["venue"], VENUE)
        self.assertEqual((event["lat"], event["lng"]), POINT)
        self.assertEqual(event["geo_precision"], "venue")
        self.assertEqual(event["category"], "conte-musical")
        self.assertEqual(event["date_start"], DATE)
        verifier.assert_called_once()

    def test_forged_dict_wrong_place_expired_proof_cannot_admit(self):
        witness = mint_unnumbered()
        unknown = lead()
        bad = (
            {KEY: {"city": CITY, "venue": VENUE,
                   "lat": POINT[0], "lng": POINT[1], "verified": True}},
            {("nantes", "place du village"): witness},
            {("ville les bois", "other place"): witness},
            {KEY: mint_unnumbered(group={"city": CITY, "venue": "Other place",
                                         "key": ["ville les bois", "other place"]},
                                  official_html="<html><h1>Wrong</h1></html>")},
        )
        for mapping in bad:
            with self.subTest(mapping=str(mapping)[:90]):
                self.assertFalse(permitted(
                    unknown, TODAY,
                    evidence=mapping.get(KEY)))
                ref = base()
                patch, report = evaluate(
                    [unknown], ref, ref, TODAY,
                    venue_proofs=mapping,
                    fetch=lambda uid: self.fail("Must not fetch unproven venue"))
                self.assertEqual(report["accepted_preflight"], 0)
                self.assertEqual(patch["additions"], [])
        with self.assertRaisesRegex(ValueError, "invalid_private_venue_proof_map"):
            unique_review_candidates([lead()], TODAY, venue_proofs="forged")
        stale = mint_unnumbered(checked_on=TODAY-timedelta(days=31))
        self.assertFalse(permitted(lead(), TODAY, evidence=stale))

    def test_even_with_geo_proof_source_coordinates_must_agree(self):
        witness = mint_unnumbered()
        altered = record()
        altered["location_coordinates"] = {"lat": POINT[0] + .015,
                                           "lon": POINT[1]}
        verifier = Mock(side_effect=AssertionError(
            "Source coordinate conflict must precede verifier"))
        patch, report = execute(proof=witness, document=altered, verify=verifier)
        self.assertEqual(patch["additions"], [])
        self.assertEqual(report["accepted_preflight"], 0)
        self.assertEqual(report["details"][0]["status"], "deferred")
        verifier.assert_not_called()

    def test_unverified_event_or_ordinary_gouter_is_still_not_published(self):
        witness = mint_unnumbered()
        verifier = Mock(return_value=(False, "organizer not verified"))
        patch, report = execute(proof=witness, verify=verifier)
        self.assertEqual(patch["additions"], [])
        self.assertEqual(report["details"][0]["status"], "unverified")
        doc = record()
        doc["title_fr"] = "Goûter au parc pour les enfants"
        candidate = lead(title=doc["title_fr"])
        patch, report = execute(
            candidate=candidate, proof=witness, document=doc,
            verify=lambda ev, originals: self.fail("Out-of-scope event"))
        self.assertEqual(patch["additions"], [])
        self.assertEqual(report["accepted_preflight"], 0)
        self.assertEqual(report["details"][0]["status"], "deferred")

    def test_public_logs_remain_counts_even_with_private_proven_location(self):
        witness = mint_unnumbered()
        patch, report = execute(proof=witness)
        public = public_run_summary(report)
        self.assertFalse(patch["safe_to_publish"])
        self.assertNotIn("admission_diagnostics", public)
        self.assertNotIn("details", public)
        self.assertNotIn("proof", public)
        self.assertNotIn("venue", public)
        self.assertEqual(public["accepted_preflight"], 1)
        self.assertNotIn(CITY, str(public))
        self.assertNotIn(VENUE, str(public))


if __name__ == "__main__":
    unittest.main()
