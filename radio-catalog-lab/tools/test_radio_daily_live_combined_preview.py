import unittest
from unittest.mock import patch
from cryptography.exceptions import InvalidSignature

from radio_daily_live_combined_preview import combine_and_rehearse
from radio_daily_lab_signing import EphemeralLabSigner
from radio_daily_baseline_verify import verify_baseline
from radio_daily_combined_release_validation import compose
from radio_daily_v9_generator import digest
import test_radio_daily_combined_release_validation as fixture_module
from test_radio_daily_logo_plan import DAY


class LiveCombinedPreviewTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture_module.CombinedGateTests()
        self.f.prepare(approved=False)

    def run_preview(self, operations):
        f = self.f
        return combine_and_rehearse(f.pointer, f.raw, anchor=f.anchor, day=DAY,
                                   operations=operations)

    def test_exact_combined_candidate_signed_with_ephemeral_key(self):
        f = self.f
        result = self.run_preview(f.operations)
        self.assertEqual(result["candidateSha256"], digest(compose(f.pointer, f.raw, **f.args)))
        self.assertEqual(result["candidateSequence"], 9)
        self.assertEqual(set(result["selectedOperations"]), {"logo", "status"})
        self.assertTrue(result["experimentalSignatureVerified"])
        self.assertFalse(result["publicationAllowed"])
        self.assertTrue(result["simulatedPublication"])
        self.assertTrue(result["retryVerified"])
        self.assertEqual(result["visibleSequence"], 9)
        self.assertNotEqual(result["experimentalKeyId"], f.anchor["key_id"])

    @patch("radio_daily_live_combined_preview.EphemeralLabSigner")
    def test_no_change_does_not_create_key_or_version(self, signer):
        result = self.run_preview({})
        self.assertEqual(result["outcome"], "no_change")
        self.assertIsNone(result["candidateSequence"])
        self.assertFalse(result["signed"])
        signer.assert_not_called()

    def test_bad_family_held_without_losing_valid_family(self):
        f = self.f
        broken = dict(f.operations)
        broken["logo"] = dict(f.operations["logo"], candidate=b"{}")
        result = self.run_preview(broken)
        self.assertEqual(result["selectedOperations"], ["status"])
        self.assertEqual(result["deferredOperations"], [{"operation":"logo","reason":"combined_gate_held"}])
        self.assertTrue(result["experimentalSignatureVerified"])

    def test_unknown_family_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown"):
            self.run_preview({"other": {}})

    def test_reanchor_refuses_tampered_body(self):
        f = self.f
        with self.assertRaises(ValueError):
            EphemeralLabSigner().reanchor_verified_baseline(f.pointer, f.raw+b" ", anchor=f.anchor)

    def test_reanchored_pointer_is_not_valid_under_original_key(self):
        f = self.f
        signer = EphemeralLabSigner()
        pointer = signer.reanchor_verified_baseline(f.pointer, f.raw, anchor=f.anchor)
        with self.assertRaises(ValueError):
            verify_baseline(pointer, f.raw, **f.anchor)
        verify_baseline(pointer, f.raw, **dict(f.anchor, public_key=signer.public_key, key_id=signer.key_id))

    @patch("radio_daily_live_combined_preview.recover_inherited", side_effect=__import__("radio_daily_live_inherited_artwork").ArtworkUnavailable("held"))
    def test_missing_inherited_artwork_blocks_publication_not_signature(self, recover):
        result = self.run_preview(self.f.operations)
        self.assertTrue(result["experimentalSignatureVerified"])
        self.assertFalse(result["simulatedPublication"])
        self.assertEqual(result["outcome"], "inherited_artwork_held")

    @patch("radio_daily_live_combined_preview.publish_combined", side_effect=ValueError("collision"))
    def test_atomic_publication_failure_is_held(self, publish):
        result = self.run_preview(self.f.operations)
        self.assertFalse(result["simulatedPublication"])
        self.assertEqual(result["outcome"], "experimental_publication_held")
