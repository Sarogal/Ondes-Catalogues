import copy
import json
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from radio_daily_publication_simulator import MemoryStore, publish, verify_visible
from radio_daily_lab_signing import EphemeralLabSigner
from radio_daily_logo_plan import PREVIEW_BASE
from radio_daily_v9_generator import encode,digest
from test_radio_daily_baseline_selection import signed
from test_radio_daily_logo_plan import DATA, OLD, URL, reports, DAY


class PublicationSimulatorTests(unittest.TestCase):
    def setUp(self):
        self.signer=EphemeralLabSigner()
        raw,*_=reports(True)
        self.old=json.loads(raw)
        self.prior,self.raw=signed(self.old,self.signer._key,self.signer.key_id)
        self.store=MemoryStore(self.prior,self.raw,legacy_logos={URL:OLD})
        self.new=copy.deepcopy(self.old)
        self.new.update(release_sequence=9,generated_at=DAY+"T00:00:00Z")
        s=self.new["stations"][0]
        s["editorial"].update(admission_state="approved",reviewed_at=DAY+"T00:00:00Z")
        sha=digest(DATA)
        self.path=sha+".png"
        s["logo"].update(asset_id="sha256:"+sha,sha256=sha,revision=2,
                         url=PREVIEW_BASE+self.path,byte_size=len(DATA))
        self.body=encode(self.new)

    def run_publish(self, **kw):
        args=dict(expected_sha=digest(self.raw),expected_sequence=8,
                  expected_candidate_sha=digest(self.body),day=DAY,
                  objects={self.path:DATA})
        args.update(kw)
        return publish(self.store,self.signer,self.prior,self.raw,self.body,**args)

    def verify_old(self):
        self.assertEqual(self.store.current(),self.prior)
        verify_visible(self.store,self.prior,sha=digest(self.raw),sequence=8,signer=self.signer)

    def verify_new(self):
        self.assertEqual(verify_visible(self.store,self.store.current(),sha=digest(self.body),
                         sequence=9,signer=self.signer),self.new)

    def test_order_and_visible_release(self):
        phases=[]
        result=self.run_publish(checkpoint=phases.append)
        self.assertEqual(phases,["reference_verified","objects_validated","object_written",
            "objects_visible","catalogue_written","catalogue_visible","before_pointer_swap","after_pointer_swap"])
        self.assertEqual(result["sequence"],9)
        self.assertFalse(result["publicationAllowed"])
        self.verify_new()

    def test_interruptions_before_switch_leave_prior_and_retry(self):
        for stop in ("reference_verified","objects_validated","object_written","objects_visible",
                     "catalogue_written","catalogue_visible","before_pointer_swap"):
            with self.subTest(stop=stop):
                self.store=MemoryStore(self.prior,self.raw,legacy_logos={URL:OLD})
                def fail(phase):
                    if phase==stop:
                        raise RuntimeError("interrupted")
                with self.assertRaises(RuntimeError):
                    self.run_publish(checkpoint=fail)
                self.verify_old()
                self.run_publish()
                self.verify_new()

    def test_retry_after_switch_is_idempotent(self):
        def fail(phase):
            if phase=="after_pointer_swap":
                raise RuntimeError("interrupted")
        with self.assertRaises(RuntimeError):
            self.run_publish(checkpoint=fail)
        pointer=self.store.current()
        self.verify_new()
        self.assertTrue(self.run_publish()["resumed"])
        self.assertEqual(self.store.current(),pointer)

    def test_no_change_keeps_pointer_and_version(self):
        result=publish(self.store,self.signer,self.prior,self.raw,None,expected_sha=digest(self.raw),
            expected_sequence=8,expected_candidate_sha=None,day=DAY)
        self.assertFalse(result["changed"])
        self.verify_old()

    def test_missing_logo_refuses_switch(self):
        with self.assertRaises(KeyError):
            self.run_publish(objects={})
        self.verify_old()

    def test_wrong_logo_refuses_switch(self):
        with self.assertRaisesRegex(ValueError,"logo digest"):
            self.run_publish(objects={self.path:OLD})
        self.verify_old()

    def test_extra_logo_refuses_switch(self):
        with self.assertRaisesRegex(ValueError,"unreferenced artwork"):
            self.run_publish(objects={self.path:DATA,"extra.png":DATA})
        self.verify_old()

    def test_immutable_collision_refuses_switch(self):
        self.store.put_immutable("objects/sha256/"+self.path,OLD)
        with self.assertRaisesRegex(ValueError,"immutable object conflict"):
            self.run_publish()
        self.verify_old()

    def test_corrupted_catalogue_readback_refuses_switch(self):
        def fail(phase):
            if phase=="catalogue_written":
                self.store._objects["releases/"+digest(self.body)+".json"]=b"corrupt"
        with self.assertRaisesRegex(ValueError,"catalogue readback"):
            self.run_publish(checkpoint=fail)
        self.verify_old()

    def test_corrupted_image_before_switch_refuses_switch(self):
        def fail(phase):
            if phase=="before_pointer_swap":
                self.store._objects["objects/sha256/"+self.path]=OLD
        with self.assertRaisesRegex(ValueError,"logo digest"):
            self.run_publish(checkpoint=fail)
        self.verify_old()

    def test_two_competing_publishers_only_one_wins(self):
        alternative=copy.deepcopy(self.new)
        alternative["stations"][0]["display_name"]="Competing Radio"
        other=encode(alternative)
        barrier=Barrier(2)
        def run(body):
            def sync(phase):
                if phase=="before_pointer_swap":
                    barrier.wait(timeout=5)
            try:
                publish(self.store,self.signer,self.prior,self.raw,body,expected_sha=digest(self.raw),
                    expected_sequence=8,expected_candidate_sha=digest(body),day=DAY,
                    objects={self.path:DATA},checkpoint=sync)
                return digest(body)
            except ValueError as exc:
                self.assertIn("concurrency conflict",str(exc))
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes=list(pool.map(run,[self.body,other]))
        winners=[x for x in outcomes if x]
        self.assertEqual(len(winners),1)
        verify_visible(self.store,self.store.current(),sha=winners[0],sequence=9,signer=self.signer)
        loser=other if winners[0]==digest(self.body) else self.body
        with self.assertRaises(ValueError):
            publish(self.store,self.signer,self.prior,self.raw,loser,expected_sha=digest(self.raw),
                expected_sequence=8,expected_candidate_sha=digest(loser),day=DAY,objects={self.path:DATA})

    def test_reject_bad_candidate_digest_before_writing(self):
        with self.assertRaisesRegex(ValueError,"candidate digest"):
            self.run_publish(expected_candidate_sha="0"*64)
        self.verify_old()
        with self.assertRaises(KeyError):
            self.store.get("objects/sha256/"+self.path)


if __name__=="__main__":
    unittest.main()
