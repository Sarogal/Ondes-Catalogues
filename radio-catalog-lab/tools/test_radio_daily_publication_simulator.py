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




class GeneratedMultiversionTests(unittest.TestCase):
    """Exercise the actual generator, signer, pointer and snapshot together.

    All observations are synthetic; no production key, network or remote store.
    The bootstrap fixture is already approved, not a promotion of TEST v8.
    """

    def test_two_generated_logo_releases_and_resume(self):
        import tempfile
        from pathlib import Path
        from radio_daily_state_snapshot import transition, POINTER, BODY
        from radio_daily_release_context import STATE_FILES, REQUALIFY
        from radio_daily_unified_generator import build
        from radio_daily_decision_preview import decide
        from radio_daily_maintenance_preview import build as maintenance
        from radio_daily_repair_preview import build as repair
        from radio_daily_repair_confirmation import build as confirm
        from radio_daily_repair_plan import plan
        from radio_daily_status_preview import build as status
        from radio_daily_logo_maintenance import build as logo, official_source
        from radio_daily_missing_logo import build as missing
        from test_radio_daily_logo_plan import material, DAY1

        signer = EphemeralLabSigner()
        raw, *_ = reports()
        doc = json.loads(raw)
        doc["stations"][0]["editorial"].update(
            admission_state="approved", reviewed_at=DAY1+"T00:00:00Z")
        pointer, raw = signed(doc, signer._key, signer.key_id)
        store = MemoryStore(pointer, raw)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            snapshot = root/"v8"
            snapshot.mkdir()
            (snapshot/POINTER).write_bytes(pointer)
            (snapshot/BODY).write_bytes(raw)
            for seq, days, image in ((8, (DAY1, DAY), DATA),
                                     (9, ("2026-11-27", "2026-11-28"), OLD)):
                raw = (snapshot/BODY).read_bytes()
                pointer = (snapshot/POINTER).read_bytes()
                sha = digest(raw)
                state = {k: json.loads((snapshot/name).read_bytes())
                         for k, name in STATE_FILES.items()
                         if (snapshot/name).exists()}
                observed_urls = []
                def fetch_image(url, host):
                    observed_urls.append(url)
                    return image, "image/png"
                for day in days:
                    discovery = dict(schemaVersion=1, scanDate=day,
                                     publicationAllowed=False, candidates=[])
                    dossiers = dict(schemaVersion=1, scanDate=day,
                                    publicationAllowed=False, approvedCount=0,
                                    catalogBaselineSha256=sha, records=[])
                    m = maintenance(raw, day, expected=sha, prior=state.get("maintenance"))
                    r = repair(raw, m, discovery, expected=sha, prior=state.get("repair"))
                    c = confirm(raw, r, expected=sha, prior=state.get("confirmation"))
                    rp = plan(raw, m, r, c, expected=sha)
                    st = status(raw, m, rp, expected=sha)
                    lm = logo(raw, day, expected=sha, prior=state.get("logo"),
                              limit=8, fetch=fetch_image)
                    nm = missing(raw, day, expected=sha, prior=state.get("missing"),
                                 limit=4, fetch_page=lambda u: (material()["pageUrl"],
                                                               material()["pageBytes"]),
                                 fetch_image=fetch_image)
                    state = dict(maintenance=m, repair=r, confirmation=c,
                                 status=st, logo=lm, missing=nm)
                self.assertEqual(observed_urls, [URL, URL])
                args = (raw, discovery, dossiers, decide(discovery, dossiers, sha),
                        m, r, c, rp, st, lm, nm)
                artwork = {doc["stations"][0]["go_station_id"]:
                           dict(material(), imageBytes=image)}
                objects = {}
                candidate, report = build(*args, expected=sha, expected_sequence=seq,
                                          artwork=artwork, object_output=objects)
                self.assertEqual(report["candidateSequence"], seq+1)
                self.assertEqual(len(report["logoChanges"]), 1)
                self.assertEqual(objects, {digest(image)+".png": image})
                # Replay evidence rather than trust the generator's summary.
                replay = {}
                rebuilt, _ = build(*args, expected=sha, expected_sequence=seq,
                                   artwork=artwork, object_output=replay)
                self.assertEqual((candidate, objects), (rebuilt, replay))
                args_publish = dict(expected_sha=sha, expected_sequence=seq,
                                    expected_candidate_sha=digest(candidate),
                                    day=day, objects=objects)
                stop = "before_pointer_swap" if seq == 8 else "after_pointer_swap"
                def interrupt(phase):
                    if phase == stop:
                        raise RuntimeError("laboratory interruption")
                with self.assertRaisesRegex(RuntimeError, "laboratory interruption"):
                    publish(store, signer, pointer, raw, candidate,
                            checkpoint=interrupt, **args_publish)
                if seq == 8:
                    self.assertEqual(store.current(), pointer)
                else:
                    self.assertNotEqual(store.current(), pointer)
                result = publish(store, signer, pointer, raw, candidate, **args_publish)
                self.assertEqual(result["resumed"], seq == 9)
                visible = store.current()
                self.assertEqual(verify_visible(store, visible, sha=digest(candidate),
                                 sequence=seq+1, signer=signer), json.loads(candidate))
                for k, name in STATE_FILES.items():
                    (snapshot/name).write_bytes(encode(state[k]))
                (snapshot/REQUALIFY[0]).write_bytes(encode(dossiers))
                before = {p.name: p.read_bytes() for p in snapshot.iterdir()}
                target = root/("v"+str(seq+1))
                ctx = transition(snapshot, target, visible,
                                 lambda path, length: store.get(path), day=day,
                                 anchor=dict(expected_sha=sha, expected_sequence=seq,
                                             public_key=signer.public_key, key_id=signer.key_id))
                self.assertEqual(ctx["selectedSequence"], seq+1)
                self.assertEqual((target/BODY).read_bytes(), candidate)
                self.assertFalse((target/REQUALIFY[0]).exists())
                self.assertEqual(before, {p.name: p.read_bytes() for p in snapshot.iterdir()})
                snapshot = target
                self.assertEqual(official_source(json.loads(candidate)["stations"][0]), URL)

            # A fresh collection of the now-current image must not create v11.
            raw = (snapshot/BODY).read_bytes()
            pointer = (snapshot/POINTER).read_bytes()
            sha = digest(raw)
            day = "2026-11-29"
            state = {k: json.loads((snapshot/name).read_bytes()) for k, name in STATE_FILES.items()}
            d = dict(schemaVersion=1, scanDate=day, publicationAllowed=False, candidates=[])
            e = dict(schemaVersion=1, scanDate=day, publicationAllowed=False,
                     approvedCount=0, catalogBaselineSha256=sha, records=[])
            m = maintenance(raw, day, expected=sha, prior=state["maintenance"])
            r = repair(raw, m, d, expected=sha, prior=state["repair"])
            c = confirm(raw, r, expected=sha, prior=state["confirmation"])
            rp = plan(raw, m, r, c, expected=sha)
            lm = logo(raw, day, expected=sha, prior=state["logo"], limit=8,
                      fetch=lambda u, h: (OLD, "image/png"))
            nm = missing(raw, day, expected=sha, prior=state["missing"])
            candidate, report = build(raw, d, e, decide(d, e, sha), m, r, c, rp,
                                      status(raw, m, rp, expected=sha), lm, nm,
                                      expected=sha, expected_sequence=10)
            self.assertIsNone(candidate)
            self.assertFalse(report["changed"])
            result = publish(store, signer, pointer, raw, candidate,
                             expected_sha=sha, expected_sequence=10,
                             expected_candidate_sha=None, day=day)
            self.assertFalse(result["changed"])
            self.assertEqual(store.current(), pointer)


if __name__=="__main__":
    unittest.main()
