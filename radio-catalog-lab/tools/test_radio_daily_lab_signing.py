import copy
import unittest
from cryptography.exceptions import InvalidSignature
from radio_daily_lab_signing import EphemeralLabSigner, validate_candidate
from radio_daily_baseline_verify import verify_baseline
from radio_daily_v9_generator import digest, encode
from test_radio_daily_baseline_selection import signed
from test_radio_daily_repair_plan import fixture, DAY


class LabSigningTests(unittest.TestCase):
    def setUp(self):
        import json
        self.signer = EphemeralLabSigner()
        raw, *_ = fixture()
        self.old = json.loads(raw)
        self.pointer, self.raw = signed(self.old, self.signer._key, self.signer.key_id)
        self.new = copy.deepcopy(self.old)
        self.new.update(release_sequence=9, generated_at=DAY+"T00:00:00Z")
        self.new["stations"][0]["editorial"].update(admission_state="approved",
                                                    reviewed_at=DAY+"T00:00:00Z")

    def sign(self, new=None, **overrides):
        body = encode(self.new if new is None else new)
        args = dict(expected_sha=digest(self.raw), expected_sequence=8,
                    expected_candidate_sha=digest(body), day=DAY)
        args.update(overrides)
        return self.signer.sign_candidate(self.pointer, self.raw, body, **args)

    def test_sign_and_verify_existing_pointer_contract(self):
        result = self.sign()
        body = encode(self.new)
        self.assertEqual(verify_baseline(result, body, expected_sha=digest(body),
            expected_sequence=9, public_key=self.signer.public_key, key_id=self.signer.key_id), self.new)

    def test_wrong_digest_refused(self):
        with self.assertRaisesRegex(ValueError, "candidate digest"):
            self.sign(expected_candidate_sha="0"*64)

    def test_wrong_reference_refused(self):
        with self.assertRaises(ValueError):
            self.sign(expected_sha="0"*64)

    def test_wrong_key_refused(self):
        other = EphemeralLabSigner()
        with self.assertRaises((ValueError, InvalidSignature)):
            other.sign_candidate(self.pointer,self.raw,encode(self.new),expected_sha=digest(self.raw),
                expected_sequence=8,expected_candidate_sha=digest(encode(self.new)),day=DAY)

    def test_version_gap_refused(self):
        self.new["release_sequence"]=10
        with self.assertRaisesRegex(ValueError, "immediate successor"):
            self.sign()

    def test_stale_day_refused(self):
        with self.assertRaisesRegex(ValueError, "generation day"):
            self.sign(day="2026-11-27")

    def test_unchanged_catalogue_refused(self):
        self.new["stations"]=copy.deepcopy(self.old["stations"])
        with self.assertRaisesRegex(ValueError, "no catalogue change"):
            self.sign()

    def test_legacy_editorial_refused(self):
        self.new["stations"][0]["editorial"]=copy.deepcopy(self.old["stations"][0]["editorial"])
        self.new["stations"][0]["display_name"]="Changed"
        with self.assertRaisesRegex(ValueError, "publication guard"):
            self.sign()

    def test_active_without_verified_stream_refused(self):
        self.new["stations"][0]["streams"][0]["state"]="candidate_verified"
        with self.assertRaisesRegex(ValueError, "no verified stream"):
            self.sign()

    def test_unresolved_fallback_refused_even_with_verified_primary(self):
        fallback=copy.deepcopy(self.new["stations"][0]["streams"][0])
        fallback.update(stream_id="two",priority=1,url="https://radio.example.org/two",
                        previous_urls=[],state="candidate_verified")
        self.new["stations"][0]["streams"].append(fallback)
        with self.assertRaisesRegex(ValueError, "unresolved candidate_verified"):
            self.sign()

    def test_historical_alias_refused(self):
        self.new["stations"][0]["legacy_aliases"]=[]
        self.new["stations"][0]["radio_browser_uuids"]=[]
        with self.assertRaisesRegex(ValueError, "historical alias lost"):
            self.sign()

    def test_second_successive_release_and_independent_validation(self):
        p9=self.sign()
        b9=encode(self.new)
        v10=copy.deepcopy(self.new)
        v10.update(release_sequence=10,generated_at="2026-11-27T00:00:00Z")
        v10["stations"][0]["display_name"]="Iron Radio 2"
        b10=encode(v10)
        args=dict(expected_sha=digest(b9),expected_sequence=9,expected_candidate_sha=digest(b10),day="2026-11-27")
        self.assertEqual(validate_candidate(p9,b9,b10,public_key=self.signer.public_key,
            key_id=self.signer.key_id,**args),v10)
        p10=self.signer.sign_candidate(p9,b9,b10,**args)
        self.assertEqual(verify_baseline(p10,b10,expected_sha=digest(b10),expected_sequence=10,
            public_key=self.signer.public_key,key_id=self.signer.key_id),v10)


if __name__ == "__main__":
    unittest.main()
