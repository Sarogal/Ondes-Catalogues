from copy import deepcopy
import unittest
from unittest.mock import Mock

from test_ptitesondes_catalogue_geo_correction_preview import DAY, fixture, page
from ptitesondes_catalogue_geo_correction_preview import digest
from ptitesondes_historical_gps_apply_guard import (
    prepare_corrections, validate_transition,
)


class HistoricalGPSApplicationTests(unittest.TestCase):
    def test_recheck_and_idempotence(self):
        doc, state, proof = fixture()
        original = deepcopy(doc)
        researcher = Mock(return_value=proof)
        reader = Mock(return_value=page())
        corrected, audit, count = prepare_corrections(
            doc, doc, DAY, state, researcher=researcher, source_reader=reader)
        self.assertEqual(count, 1)
        self.assertEqual(doc, original)
        self.assertEqual(corrected["events"][1:], original["events"][1:])
        self.assertEqual(corrected["events"][0]["geo_verified_at"], DAY.isoformat())
        researcher.assert_called_once()
        reader.assert_called_once()
        result, _, count = prepare_corrections(
            corrected, corrected, DAY, state, researcher=Mock(side_effect=AssertionError()))
        self.assertEqual(result, corrected)
        self.assertEqual(count, 0)

    def test_failed_fresh_proof_is_no_change(self):
        doc, state, proof = fixture()
        result, _, count = prepare_corrections(doc, doc, DAY, state,
            researcher=lambda *_: None, source_reader=Mock(side_effect=AssertionError()))
        self.assertEqual(result, doc)
        self.assertEqual(count, 0)

    def test_reference_disagreement_refused(self):
        doc, state, proof = fixture()
        ref = deepcopy(doc)
        ref["events"][0]["title"] = "Other"
        with self.assertRaisesRegex(ValueError, "reference_disagreement"):
            prepare_corrections(ref, doc, DAY, state,
                researcher=lambda *_: proof, source_reader=lambda _: page())

    def test_partial_coordinates_are_not_overwritten(self):
        doc, state, proof = fixture()
        doc["events"][0]["lat"] = 44.5
        with self.assertRaisesRegex(ValueError, "existing_or_partial_point"):
            prepare_corrections(doc, doc, DAY, state,
                researcher=lambda *_: proof, source_reader=lambda _: page())

    def test_even_consistent_forged_audit_cannot_change_other_fields(self):
        doc, state, proof = fixture()
        corrected, audit, _ = prepare_corrections(doc, doc, DAY, state,
            researcher=lambda *_: proof, source_reader=lambda _: page())
        corrected["events"][0]["title"] = "Other"
        audit["after_sha256"] = digest(corrected)
        audit["proposals"][0]["after_sha256"] = digest(corrected["events"][0])
        with self.assertRaisesRegex(ValueError, "non_geo_change"):
            validate_transition(doc, doc, corrected, audit, DAY)

    def test_unreported_mutation_and_wrong_digest_rejected(self):
        doc, state, proof = fixture()
        corrected, audit, _ = prepare_corrections(doc, doc, DAY, state,
            researcher=lambda *_: proof, source_reader=lambda _: page())
        bad = dict(audit, after_sha256="0" * 64)
        with self.assertRaisesRegex(ValueError, "invalid_audit"):
            validate_transition(doc, doc, corrected, bad, DAY)
        corrected["events"][1]["lat"] += 1
        audit["after_sha256"] = digest(corrected)
        with self.assertRaisesRegex(ValueError, "proposal_diff_mismatch"):
            validate_transition(doc, doc, corrected, audit, DAY)

    def test_duplicate_proposal_and_reordered_events_rejected(self):
        doc, state, proof = fixture()
        corrected, audit, _ = prepare_corrections(doc, doc, DAY, state,
            researcher=lambda *_: proof, source_reader=lambda _: page())
        bad = dict(audit, proposals=audit["proposals"] * 2, proposed_count=2)
        with self.assertRaisesRegex(ValueError, "proposal_diff_mismatch"):
            validate_transition(doc, doc, corrected, bad, DAY)
        corrected["events"].reverse()
        with self.assertRaisesRegex(ValueError, "ids_or_order_changed"):
            validate_transition(doc, doc, corrected, audit, DAY)
