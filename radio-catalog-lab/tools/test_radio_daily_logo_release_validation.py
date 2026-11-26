import copy
import json
import unittest
from radio_daily_logo_release_validation import validate_logo_release, publish_logo_release
from radio_daily_lab_signing import EphemeralLabSigner
from radio_daily_publication_simulator import MemoryStore
from radio_daily_logo_plan import plan, stage
from radio_daily_logo_maintenance import source_reference
from radio_daily_v9_generator import digest, encode
from test_radio_daily_baseline_selection import signed
from test_radio_daily_logo_plan import reports, material, DATA, OLD, DAY, SID, URL
from radio_daily_logo_maintenance import build as maintain
from radio_daily_missing_logo import build as missing


class IndependentLogoGateTests(unittest.TestCase):
    def setUp(self):
        raw, *_ = reports()
        doc = json.loads(raw)
        doc["stations"][0]["editorial"].update(
            admission_state="approved", reviewed_at=DAY+"T00:00:00Z")
        self.signer = EphemeralLabSigner()
        self.pointer, self.raw = signed(doc, self.signer._key, self.signer.key_id)
        sha = digest(self.raw)
        self.anchor = dict(expected_sha=sha, expected_sequence=8,
                           public_key=self.signer.public_key, key_id=self.signer.key_id)
        self.lm = self.nm = None
        for day in ("2026-11-25", DAY):
            self.lm = maintain(self.raw, day, expected=sha, prior=self.lm)
            self.nm = missing(self.raw, day, expected=sha, prior=self.nm, limit=4,
                fetch_page=lambda u: (material()["pageUrl"], material()["pageBytes"]),
                fetch_image=lambda u,h: (DATA,"image/png"))
        proposals, _ = plan(self.raw, DAY, self.lm, self.nm, expected=sha)
        desc, path, data = stage(doc["stations"][0], proposals[0], material())
        self.artwork = {SID:material()}
        self.objects = {path:data}
        self.new = copy.deepcopy(doc)
        self.new.update(release_sequence=9, generated_at=DAY+"T00:00:00Z")
        row = self.new["stations"][0]
        row["logo"] = desc
        row["editorial"]["evidence_refs"].append(source_reference(desc,URL))

    def verify(self, **kw):
        args = dict(anchor=self.anchor, day=DAY, logo_maintenance=self.lm,
                    missing_logo=self.nm, artwork=self.artwork, objects=self.objects)
        args.update(kw)
        return validate_logo_release(self.pointer, self.raw, encode(self.new), **args)

    def test_exact_delta_accepted(self):
        self.assertEqual(self.verify(), digest(encode(self.new)))

    def test_unrelated_name_change_refused(self):
        self.new["stations"][0]["display_name"]="Injected name"
        with self.assertRaisesRegex(ValueError,"unauthorized catalogue delta"):
            self.verify()

    def test_unrelated_stream_change_refused(self):
        self.new["stations"][0]["streams"][0]["url"]="https://radio.example.org/other"
        with self.assertRaisesRegex(ValueError,"unauthorized catalogue delta"):
            self.verify()

    def test_missing_provenance_refused(self):
        self.new["stations"][0]["editorial"]["evidence_refs"]=[]
        with self.assertRaisesRegex(ValueError,"unauthorized catalogue delta"):
            self.verify()

    def test_extra_object_refused(self):
        with self.assertRaisesRegex(ValueError,"artwork inventory mismatch"):
            self.verify(objects=dict(self.objects, extra=OLD))

    def test_changed_source_bytes_refused(self):
        with self.assertRaises(ValueError):
            self.verify(artwork={SID:dict(material(), imageBytes=OLD)})

    def test_no_evidence_refused(self):
        with self.assertRaisesRegex(ValueError,"unqualified artwork"):
            self.verify(artwork={})

    def test_unauthorized_delta_never_reaches_store(self):
        self.new["stations"][0]["display_name"]="Injected"
        body=encode(self.new)
        store=MemoryStore(self.pointer,self.raw)
        with self.assertRaisesRegex(ValueError,"unauthorized catalogue delta"):
            publish_logo_release(store,self.signer,self.pointer,self.raw,body,
                expected_sha=self.anchor["expected_sha"],expected_sequence=8,
                expected_candidate_sha=digest(body),day=DAY,logo_maintenance=self.lm,
                missing_logo=self.nm,artwork=self.artwork,objects=self.objects)
        self.assertEqual(store.current(),self.pointer)
        with self.assertRaises(KeyError):
            store.get("releases/"+digest(body)+".json")


if __name__=="__main__":
    unittest.main()
