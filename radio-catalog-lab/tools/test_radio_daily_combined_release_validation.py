import copy
import json
import unittest
from radio_daily_combined_release_validation import compose,validate_combined,publish_combined
from radio_daily_lab_signing import EphemeralLabSigner
from radio_daily_publication_simulator import MemoryStore,verify_visible
from radio_daily_logo_plan import plan as logo_plan,stage
from radio_daily_logo_maintenance import build as logo,source_reference
from radio_daily_missing_logo import build as missing
from radio_daily_maintenance_preview import build as maintenance
from radio_daily_repair_preview import build as repair
from radio_daily_repair_confirmation import build as confirm
from radio_daily_repair_plan import plan
from radio_daily_status_preview import build as status
from radio_daily_v9_generator import digest,encode
from test_radio_daily_baseline_selection import signed
from test_radio_daily_logo_plan import reports,material,DATA,DAY,DAY1,URL,SID

OTHER="go-station-000002"


class CombinedGateTests(unittest.TestCase):
    def setUp(self):
        self.prepare()

    def prepare(self, approved=True):
        raw,*_=reports()
        doc=json.loads(raw)
        first=doc["stations"][0]
        if approved:
            first["editorial"].update(admission_state="approved",reviewed_at=DAY+"T00:00:00Z")
        second=copy.deepcopy(first)
        second.update(go_station_id=OTHER,display_name="Other Radio",homepage=None,
            radio_browser_uuids=[],legacy_aliases=[])
        second["streams"][0].update(url="https://other.example.org/live",previous_urls=[])
        doc["stations"].append(second)
        self.signer=EphemeralLabSigner()
        self.pointer,self.raw=signed(doc,self.signer._key,self.signer.key_id)
        sha=digest(self.raw)
        self.anchor=dict(expected_sha=sha,expected_sequence=8,
            public_key=self.signer.public_key,key_id=self.signer.key_id)
        m=lm=nm=None
        for day in ("2026-11-24",DAY1,DAY):
            def probe(u):
                return dict(streamSha256=digest(u.encode()),
                    verdict="needs_review" if "other.example" in u else "audio_sample_ok",
                    reason="http_not_successful" if "other.example" in u else "",
                    frameChain="" if "other.example" in u else "mp3")
            m=maintenance(self.raw,day,expected=sha,prior=m,limit=20,probe=probe)
            lm=logo(self.raw,day,expected=sha,prior=lm)
            nm=missing(self.raw,day,expected=sha,prior=nm,limit=4,
                fetch_page=lambda u:(material()["pageUrl"],material()["pageBytes"]),
                fetch_image=lambda u,h:(DATA,"image/png"))
        d=dict(schemaVersion=1,scanDate=DAY,publicationAllowed=False,candidates=[])
        r=repair(self.raw,m,d,expected=sha)
        c=confirm(self.raw,r,expected=sha)
        rp=plan(self.raw,m,r,c,expected=sha)
        st=status(self.raw,m,rp,expected=sha)
        ps,_=logo_plan(self.raw,DAY,lm,nm,expected=sha)
        desc,path,data=stage(first,ps[0],material())
        self.objects={path:data}
        a=copy.deepcopy(doc)
        b=copy.deepcopy(doc)
        for x in (a,b):
            x.update(release_sequence=9,generated_at=DAY+"T00:00:00Z")
        a["stations"][0]["logo"]=desc
        a["stations"][0]["editorial"]["evidence_refs"].append(source_reference(desc,URL))
        b["stations"][1]["status"].update(state="quarantined",
            reason_code="experimental_unavailability_review",changed_at=DAY+"T00:00:00Z")
        self.operations={
            "logo":dict(candidate=encode(a),evidence=dict(logo_maintenance=lm,
                missing_logo=nm,artwork={SID:material()},objects=self.objects)),
            "status":dict(candidate=encode(b),evidence=dict(maintenance=m,repair=r,confirmation=c,status=st))}
        self.args=dict(anchor=self.anchor,day=DAY,operations=self.operations,objects=self.objects)

    def test_two_operations_one_release(self):
        body=compose(self.pointer,self.raw,**self.args)
        doc=json.loads(body)
        self.assertEqual(doc["release_sequence"],9)
        self.assertEqual(doc["stations"][0]["logo"]["sha256"],digest(DATA))
        self.assertEqual(doc["stations"][1]["status"]["state"],"quarantined")
        self.assertEqual(validate_combined(self.pointer,self.raw,body,**self.args),digest(body))

    def test_mutated_global_delta_refused(self):
        doc=json.loads(compose(self.pointer,self.raw,**self.args))
        doc["stations"][0]["display_name"]="Injected"
        with self.assertRaisesRegex(ValueError,"unauthorized combined"):
            validate_combined(self.pointer,self.raw,encode(doc),**self.args)

    def test_mutated_operation_refused(self):
        doc=json.loads(self.operations["logo"]["candidate"])
        doc["stations"][1]["display_name"]="Injected"
        self.operations["logo"]["candidate"]=encode(doc)
        with self.assertRaisesRegex(ValueError,"unauthorized catalogue delta"):
            compose(self.pointer,self.raw,**self.args)

    def test_unexpected_object_refused(self):
        with self.assertRaisesRegex(ValueError,"combined artwork inventory"):
            compose(self.pointer,self.raw,**dict(self.args,objects={}))

    def test_unknown_operation_refused(self):
        with self.assertRaisesRegex(ValueError,"unknown combined operation"):
            compose(self.pointer,self.raw,**dict(self.args,operations={"arbitrary":{}}))

    def test_no_change_keeps_version(self):
        self.assertIsNone(compose(self.pointer,self.raw,**dict(self.args,operations={},objects={})))

    def test_publish_combined_and_retry(self):
        body=compose(self.pointer,self.raw,**self.args)
        sha=digest(body)
        store=MemoryStore(self.pointer,self.raw)
        args=dict(expected_sha=self.anchor["expected_sha"],expected_sequence=8,
            expected_candidate_sha=sha,day=DAY,operations=self.operations,objects=self.objects)
        def interrupt(phase):
            if phase=="after_pointer_swap":
                raise RuntimeError("interrupted")
        with self.assertRaisesRegex(RuntimeError,"interrupted"):
            publish_combined(store,self.signer,self.pointer,self.raw,body,checkpoint=interrupt,**args)
        result=publish_combined(store,self.signer,self.pointer,self.raw,body,**args)
        self.assertTrue(result["resumed"])
        verify_visible(store,store.current(),sha=sha,sequence=9,signer=self.signer)

    def test_legacy_logo_and_status_one_signed_release(self):
        self.prepare(approved=False)
        body=compose(self.pointer,self.raw,**self.args)
        store=MemoryStore(self.pointer,self.raw)
        result=publish_combined(store,self.signer,self.pointer,self.raw,body,
            expected_sha=self.anchor["expected_sha"],expected_sequence=8,
            expected_candidate_sha=digest(body),day=DAY,operations=self.operations,objects=self.objects)
        self.assertEqual(result["sequence"],9)
        doc=verify_visible(store,store.current(),sha=digest(body),sequence=9,signer=self.signer)
        self.assertEqual([r["editorial"]["admission_state"] for r in doc["stations"]],
                         ["legacy_preserved","legacy_preserved"])
        self.assertEqual(doc["stations"][0]["logo"]["sha256"],digest(DATA))
        self.assertEqual(doc["stations"][1]["status"]["state"],"quarantined")

    def test_legacy_combined_without_evidence_refused(self):
        self.prepare(approved=False)
        body=compose(self.pointer,self.raw,**self.args)
        with self.assertRaisesRegex(ValueError,"publication guard"):
            self.signer.sign_candidate(self.pointer,self.raw,body,
                expected_sha=self.anchor["expected_sha"],expected_sequence=8,
                expected_candidate_sha=digest(body),day=DAY)


if __name__=="__main__":
    unittest.main()
