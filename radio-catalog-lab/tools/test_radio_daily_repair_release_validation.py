import json
import unittest
from radio_daily_repair_release_validation import qualify_repair, validate_repair_release, publish_repair_release
from radio_daily_lab_signing import EphemeralLabSigner
from radio_daily_publication_simulator import MemoryStore, publish, verify_visible
from radio_daily_v9_generator import digest, encode
from test_radio_daily_baseline_selection import signed
from test_radio_daily_repair_plan import fixture, DAY, SID, UID, NEW, PAGE


class StrictRepairGateTests(unittest.TestCase):
    def setUp(self):
        self.prepare()

    def prepare(self, approved=True, quarantine=False):
        raw, _, self.m, self.r, self.c = fixture(approved=approved, quarantine=quarantine, no_logo=True)
        self.signer = EphemeralLabSigner()
        self.pointer, self.raw = signed(json.loads(raw), self.signer._key, self.signer.key_id)
        self.anchor = dict(expected_sha=digest(self.raw), expected_sequence=8,
                           public_key=self.signer.public_key, key_id=self.signer.key_id)
        self.args = dict(anchor=self.anchor, day=DAY, maintenance=self.m, repair=self.r,
                         confirmation=self.c, search=self.search, fetch=self.fetch,
                         probe=self.probe, continuity=self.continuity, hls=self.hls)

    def search(self, name):
        return [dict(stationuuid=UID, name="Iron Radio", countrycode="FR",
                     homepage=PAGE, url_resolved=NEW, lastcheckok=1)]

    def fetch(self, url):
        body = '<script type="application/ld+json">'+json.dumps(
            dict({"@type":"RadioStation"}, name="Iron Radio", streamUrl=NEW))+'</script>'
        return PAGE, body.encode()

    def probe(self, url):
        return dict(streamSha256=digest(url.encode()), verdict="audio_sample_ok", frameChain="mp3")

    def continuity(self, url):
        return dict(verdict="continuous_icy_frame_indication", frameCodec="mp3")

    def hls(self, url):
        return dict(verdict="advancing_hls_audio_frame_indication", frameCodec="aac")

    def qualify(self, **kw):
        args = dict(self.args, **kw)
        return qualify_repair(self.pointer,self.raw,**args)

    def test_exact_fallback_promoted_and_old_fields_preserved(self):
        body=self.qualify()
        doc=json.loads(body)
        new=doc["stations"][0]["streams"].pop()
        self.assertEqual(new["state"],"verified")
        self.assertEqual(new["codec"],"mp3")
        self.assertEqual(new["url"],NEW)
        self.assertEqual(doc["stations"],json.loads(self.raw)["stations"])
        self.assertEqual(validate_repair_release(self.pointer,self.raw,body,**self.args),digest(body))

    def test_fresh_identity_required(self):
        with self.assertRaisesRegex(ValueError,"fresh broadcaster material"):
            self.qualify(fetch=lambda u:(PAGE,b"<html>Unrelated</html>"))

    def test_fresh_continuity_required(self):
        with self.assertRaisesRegex(ValueError,"fresh direct continuity"):
            self.qualify(continuity=lambda u:dict(verdict="finite_response_review",frameCodec="mp3"))

    def test_probe_fingerprint_required(self):
        with self.assertRaisesRegex(ValueError,"fingerprint mismatch"):
            self.qualify(probe=lambda u:dict(streamSha256="0"*64,verdict="audio_sample_ok",frameChain="mp3"))

    def test_hls_requires_advancing_audio(self):
        def sample(u):
            return dict(streamSha256=digest(u.encode()),verdict="playlist_pending")
        doc=json.loads(self.qualify(probe=sample))
        self.assertEqual(doc["stations"][0]["streams"][-1]["codec"],"aac")
        with self.assertRaisesRegex(ValueError,"fresh advancing HLS"):
            self.qualify(probe=sample,hls=lambda u:dict(verdict="advancing_hls_manifest_only"))

    def test_unrelated_delta_refused(self):
        doc=json.loads(self.qualify())
        doc["stations"][0]["display_name"]="Injected"
        with self.assertRaisesRegex(ValueError,"unauthorized repair delta"):
            validate_repair_release(self.pointer,self.raw,encode(doc),**self.args)

    def test_qualified_candidate_passes_strict_signer(self):
        body=self.qualify()
        sha=validate_repair_release(self.pointer,self.raw,body,**self.args)
        store=MemoryStore(self.pointer,self.raw)
        result=publish(store,self.signer,self.pointer,self.raw,body,
                       expected_sha=self.anchor["expected_sha"],expected_sequence=8,
                       expected_candidate_sha=sha,day=DAY)
        self.assertEqual(result["sequence"],9)
        verify_visible(store,store.current(),sha=sha,sequence=9,signer=self.signer)

    def publish_current(self, body):
        store=MemoryStore(self.pointer,self.raw)
        args={k:v for k,v in self.args.items() if k not in ("anchor","day")}
        result=publish_repair_release(store,self.signer,self.pointer,self.raw,body,
            expected_sha=self.anchor["expected_sha"],expected_sequence=8,
            expected_candidate_sha=digest(body),day=DAY,**args)
        self.assertEqual(result["sequence"],9)
        return verify_visible(store,store.current(),sha=digest(body),sequence=9,signer=self.signer)

    def test_legacy_repair_preserves_editorial_and_original_streams(self):
        self.prepare(approved=False)
        row=self.publish_current(self.qualify())["stations"][0]
        old=json.loads(self.raw)["stations"][0]
        self.assertEqual(row["editorial"],old["editorial"])
        self.assertEqual(row["status"],old["status"])
        self.assertEqual(row["streams"][:-1],old["streams"])
        self.assertEqual(row["streams"][-1]["state"],"verified")

    def test_legacy_quarantine_not_implicitly_restored(self):
        self.prepare(approved=False,quarantine=True)
        row=self.publish_current(self.qualify())["stations"][0]
        self.assertEqual(row["status"]["state"],"quarantined")
        self.assertEqual(row["editorial"]["admission_state"],"legacy_preserved")

    def test_legacy_repair_without_evidence_refused(self):
        self.prepare(approved=False)
        body=self.qualify()
        with self.assertRaisesRegex(ValueError,"publication guard"):
            self.signer.sign_candidate(self.pointer,self.raw,body,
                expected_sha=self.anchor["expected_sha"],expected_sequence=8,
                expected_candidate_sha=digest(body),day=DAY)

    def test_legacy_repair_cannot_remove_old_stream(self):
        self.prepare(approved=False)
        doc=json.loads(self.qualify())
        doc["stations"][0]["streams"].pop(0)
        with self.assertRaisesRegex(ValueError,"unauthorized repair delta"):
            validate_repair_release(self.pointer,self.raw,encode(doc),**self.args)

    def test_legacy_repair_cannot_upgrade_editorial(self):
        self.prepare(approved=False)
        doc=json.loads(self.qualify())
        doc["stations"][0]["editorial"].update(admission_state="approved",reviewed_at=DAY+"T00:00:00Z")
        with self.assertRaisesRegex(ValueError,"unauthorized repair delta"):
            validate_repair_release(self.pointer,self.raw,encode(doc),**self.args)

    def test_legacy_repair_evidence_rechecked_at_signing(self):
        self.prepare(approved=False)
        body=self.qualify()
        self.args["continuity"]=lambda u:dict(verdict="finite_response_review",frameCodec="mp3")
        with self.assertRaisesRegex(ValueError,"fresh direct continuity"):
            self.publish_current(body)


if __name__=="__main__":
    unittest.main()
