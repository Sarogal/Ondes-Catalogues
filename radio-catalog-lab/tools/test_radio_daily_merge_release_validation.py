import copy
import json
import unittest
from radio_daily_merge_release_validation import validate_merge_release, publish_merge_release
from radio_daily_lab_signing import EphemeralLabSigner
from radio_daily_publication_simulator import MemoryStore, verify_visible
from radio_daily_unified_generator import build
from radio_daily_decision_preview import decide
from radio_daily_repair_preview import build as repair
from radio_daily_repair_confirmation import build as confirm
from radio_daily_repair_plan import plan
from radio_daily_maintenance_preview import build as maintenance, digest as url_digest
from radio_daily_v9_generator import digest, encode
from test_radio_daily_baseline_selection import signed
from test_radio_daily_merge_plan import setup, OTHER
from test_radio_daily_repair_plan import DAY, DAY1, SID


class IndependentMergeGateTests(unittest.TestCase):
    def fixture(self, change=None, single_day=False):
        self.signer = EphemeralLabSigner()
        doc, _ = setup(change)
        for row in doc["stations"]:
            row["logo"] = None
            row["editorial"].update(admission_state="approved", reviewed_at=DAY+"T00:00:00Z")
        self.pointer, self.raw = signed(doc, self.signer._key, self.signer.key_id)
        sha = digest(self.raw)
        self.anchor = dict(expected_sha=sha, expected_sequence=8,
                           public_key=self.signer.public_key, key_id=self.signer.key_id)
        def probe(url):
            return dict(streamSha256=url_digest(url), verdict="audio_sample_ok", frameChain="mp3")
        m = None
        for day in ((DAY,) if single_day else (DAY1, DAY)):
            m = maintenance(self.raw, day, expected=sha, prior=m, limit=20, probe=probe)
        d = dict(schemaVersion=1, scanDate=DAY, publicationAllowed=False, candidates=[])
        e = dict(schemaVersion=1, scanDate=DAY, publicationAllowed=False, approvedCount=0,
                 catalogBaselineSha256=sha, records=[])
        r = repair(self.raw, m, d, expected=sha)
        c = confirm(self.raw, r, expected=sha)
        rp = plan(self.raw, m, r, c, expected=sha)
        self.evidence = dict(maintenance=m, repair=r, confirmation=c)
        self.candidate, _ = build(self.raw, d, e, decide(d,e,sha), m,r,c,rp, expected=sha)

    def verify(self, candidate=None, **kw):
        args = dict(anchor=self.anchor, day=DAY, **self.evidence)
        args.update(kw)
        return validate_merge_release(self.pointer, self.raw,
            self.candidate if candidate is None else candidate, **args)

    def forced_merge(self):
        doc = json.loads(self.raw)
        source = doc["stations"].pop()
        doc["tombstones"].append(dict(go_station_id=source["go_station_id"],
            legacy_aliases=source["legacy_aliases"], retired_at=DAY+"T00:00:00Z",
            reason_code="merged_into_station", redirect_to=SID))
        doc.update(release_sequence=9, generated_at=DAY+"T00:00:00Z")
        return encode(doc)

    def test_exact_generated_merge_preserves_all_favorites(self):
        self.fixture()
        self.assertEqual(self.verify(),digest(self.candidate))
        old,new=json.loads(self.raw),json.loads(self.candidate)
        self.assertEqual(new["stations"],old["stations"][:1])
        self.assertEqual(new["tombstones"][0]["legacy_aliases"],old["stations"][1]["legacy_aliases"])
        self.assertEqual(new["tombstones"][0]["go_station_id"],OTHER)
        self.assertEqual(new["tombstones"][0]["redirect_to"],SID)

    def test_missing_alias_refused(self):
        self.fixture()
        doc=json.loads(self.candidate)
        doc["tombstones"][0]["legacy_aliases"]=[]
        with self.assertRaises(ValueError):
            self.verify(encode(doc))

    def test_unrelated_target_change_refused(self):
        self.fixture()
        doc=json.loads(self.candidate)
        doc["stations"][0]["display_name"]="Injected name"
        with self.assertRaisesRegex(ValueError,"unauthorized catalogue delta"):
            self.verify(encode(doc))

    def test_distinct_variant_refused(self):
        self.fixture(lambda doc: doc["stations"][1]["streams"][0].update(url="https://radio.example.org/different"))
        self.assertIsNone(self.candidate)
        with self.assertRaisesRegex(ValueError,"no qualified duplicate merge"):
            self.verify(self.forced_merge())

    def test_radio_bob_protected(self):
        def change(doc):
            for row in doc["stations"]:
                row["display_name"]="Radio BOB! Metal"
        self.fixture(change)
        self.assertIsNone(self.candidate)
        with self.assertRaisesRegex(ValueError,"no qualified duplicate merge"):
            self.verify(self.forced_merge())

    def test_one_day_evidence_refused(self):
        self.fixture(single_day=True)
        self.assertIsNone(self.candidate)
        with self.assertRaisesRegex(ValueError,"no qualified duplicate merge"):
            self.verify(self.forced_merge())

    def test_forged_maintenance_summary_refused(self):
        self.fixture()
        m=copy.deepcopy(self.evidence["maintenance"])
        m["records"][0]["reviewStatus"]="quarantine_review"
        with self.assertRaisesRegex(ValueError,"maintenance evidence mismatch"):
            self.verify(maintenance=m)

    def test_existing_redirect_preserved(self):
        def change(doc):
            doc["tombstones"].append(dict(go_station_id="go-station-999999",
                legacy_aliases=["cccccccc-cccc-4ccc-8ccc-cccccccccccc"], retired_at=DAY1+"T00:00:00Z",
                reason_code="merged_into_station", redirect_to=OTHER))
        self.fixture(change)
        self.assertEqual(self.verify(),digest(self.candidate))
        new=json.loads(self.candidate)
        self.assertEqual(new["stations"][0]["go_station_id"],OTHER)
        self.assertEqual(new["tombstones"][0],json.loads(self.raw)["tombstones"][0])
        self.assertEqual(new["tombstones"][1]["redirect_to"],OTHER)

    def test_publication_rejects_tampering_then_accepts_exact_delta(self):
        self.fixture()
        store=MemoryStore(self.pointer,self.raw)
        doc=json.loads(self.candidate)
        doc["stations"][0]["display_name"]="Injected"
        body=encode(doc)
        args=dict(expected_sha=self.anchor["expected_sha"],expected_sequence=8,
                  day=DAY,**self.evidence)
        with self.assertRaisesRegex(ValueError,"unauthorized catalogue delta"):
            publish_merge_release(store,self.signer,self.pointer,self.raw,body,
                expected_candidate_sha=digest(body),**args)
        self.assertEqual(store.current(),self.pointer)
        result=publish_merge_release(store,self.signer,self.pointer,self.raw,self.candidate,
                expected_candidate_sha=digest(self.candidate),**args)
        self.assertEqual(result["sequence"],9)
        verify_visible(store,store.current(),sha=digest(self.candidate),sequence=9,signer=self.signer)


if __name__=="__main__":
    unittest.main()
