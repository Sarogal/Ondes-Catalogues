"""Grandfather only exact authenticated historical rows, never new admission."""
import copy
import json
import unittest
from cryptography.exceptions import InvalidSignature
from radio_catalog_guard import validate_catalog
from radio_daily_lab_signing import EphemeralLabSigner, validate_candidate
from radio_daily_baseline_verify import verify_baseline
from radio_daily_v9_generator import digest, encode
from test_radio_daily_baseline_selection import signed
from test_radio_daily_repair_plan import fixture, DAY, SID


class LegacyPreservationTests(unittest.TestCase):
    def setUp(self):
        raw,*_=fixture()
        self.old=json.loads(raw)
        first=self.old["stations"][0]
        first["logo"]=None
        other=copy.deepcopy(first)
        other.update(go_station_id="go-station-000002",display_name="Historic quarantine",
            legacy_aliases=[],radio_browser_uuids=[],streams=[])
        other["status"]["state"]="quarantined"
        self.old["stations"].append(other)
        self.signer=EphemeralLabSigner()
        self.pointer,self.raw=signed(self.old,self.signer._key,self.signer.key_id)
        self.new=copy.deepcopy(self.old)
        self.new.update(release_sequence=9,generated_at=DAY+"T00:00:00Z")
        added=copy.deepcopy(first)
        added.update(go_station_id="go-station-000003",display_name="Qualified addition",
                     legacy_aliases=[],radio_browser_uuids=[])
        added["streams"][0].update(url="https://new.example.org/live",previous_urls=[])
        added["editorial"].update(admission_state="approved",reviewed_at=DAY+"T00:00:00Z")
        self.new["stations"].append(added)

    def verify(self,new=None,**kw):
        body=encode(self.new if new is None else new)
        args=dict(expected_sha=digest(self.raw),expected_sequence=8,
            expected_candidate_sha=digest(body),day=DAY,
            public_key=self.signer.public_key,key_id=self.signer.key_id)
        args.update(kw)
        return validate_candidate(self.pointer,self.raw,body,**args)

    def test_exact_legacy_active_and_quarantined_preserved(self):
        self.assertEqual(self.verify()["stations"][:2],self.old["stations"])
        self.assertTrue(validate_catalog(self.new,mode="publish",previous=self.old))

    def test_signed_successor_preserves_exact_records(self):
        body=encode(self.new)
        p=self.signer.sign_candidate(self.pointer,self.raw,body,
            expected_sha=digest(self.raw),expected_sequence=8,
            expected_candidate_sha=digest(body),day=DAY)
        actual=verify_baseline(p,body,expected_sha=digest(body),expected_sequence=9,
            public_key=self.signer.public_key,key_id=self.signer.key_id)
        self.assertEqual(actual["stations"][:2],self.old["stations"])

    def test_changed_legacy_name_or_stream_refused(self):
        for field in ("name","stream","logo","editorial","status"):
            with self.subTest(field=field):
                d=copy.deepcopy(self.new)
                row=d["stations"][0]
                if field=="name":
                    row["display_name"]="Injected name"
                elif field=="stream":
                    row["streams"][0]["url"]="https://other.example.org/live"
                elif field=="logo":
                    row["logo"]=json.loads(fixture()[0])["stations"][0]["logo"]
                elif field=="editorial":
                    row["editorial"]["evidence_refs"].append("injected")
                else:
                    row["status"]["state"]="quarantined"
                with self.assertRaisesRegex(ValueError,"publication guard"):
                    self.verify(d)

    def test_new_legacy_refused(self):
        self.new["stations"][-1]["editorial"]=copy.deepcopy(self.old["stations"][0]["editorial"])
        with self.assertRaisesRegex(ValueError,"publication guard"):
            self.verify()

    def test_legacy_reactivation_refused(self):
        self.new["stations"][1]["status"]["state"]="active"
        self.new["stations"][1]["streams"]=copy.deepcopy(self.old["stations"][0]["streams"])
        with self.assertRaisesRegex(ValueError,"publication guard"):
            self.verify()

    def test_unchanged_legacy_unverified_stream_still_refused(self):
        self.old["stations"][0]["streams"][0]["state"]="candidate_verified"
        self.pointer,self.raw=signed(self.old,self.signer._key,self.signer.key_id)
        self.new["stations"][0]=copy.deepcopy(self.old["stations"][0])
        with self.assertRaisesRegex(ValueError,"no verified stream"):
            self.verify()

    def test_forged_predecessor_refused(self):
        other=EphemeralLabSigner()
        with self.assertRaises((ValueError,InvalidSignature)):
            self.verify(public_key=other.public_key)

    def test_without_predecessor_no_legacy_exception(self):
        self.assertTrue(validate_catalog(self.new,mode="publish",authenticated_legacy=True))

    def test_second_release_keeps_legacy_without_new_approval(self):
        body=encode(self.new)
        p=self.signer.sign_candidate(self.pointer,self.raw,body,
            expected_sha=digest(self.raw),expected_sequence=8,
            expected_candidate_sha=digest(body),day=DAY)
        v10=copy.deepcopy(self.new)
        v10.update(release_sequence=10,generated_at="2026-11-27T00:00:00Z")
        v10["stations"][-1]["display_name"]="Qualified addition 2"
        candidate=encode(v10)
        actual=validate_candidate(p,body,candidate,expected_sha=digest(body),
            expected_sequence=9,expected_candidate_sha=digest(candidate),
            day="2026-11-27",public_key=self.signer.public_key,key_id=self.signer.key_id)
        self.assertEqual(actual["stations"][:2],self.old["stations"])

    def test_approved_station_cannot_be_downgraded(self):
        old=copy.deepcopy(self.new)
        old["release_sequence"]=8
        self.pointer,self.raw=signed(old,self.signer._key,self.signer.key_id)
        self.new["stations"][-1]["editorial"]=copy.deepcopy(self.old["stations"][0]["editorial"])
        with self.assertRaisesRegex(ValueError,"publication guard"):
            self.verify()


if __name__=="__main__":
    unittest.main()
