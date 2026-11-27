"""Two consecutive signed releases with migrated evidence and one object store."""
import copy
import unittest
from unittest.mock import patch

from radio_daily_baseline_verify import strict_json
from radio_daily_combined_release_validation import compose
from radio_daily_lab_cycle import publish_cycle, migrate_cycle
from radio_daily_publication_simulator import MemoryStore, verify_visible
from radio_daily_maintenance_preview import build as maintenance
from radio_daily_logo_maintenance import build as logo
from radio_daily_missing_logo import build as missing
from radio_daily_repair_preview import build as repair
from radio_daily_repair_confirmation import build as confirm
from radio_daily_repair_plan import plan
from radio_daily_status_preview import build as status
from radio_daily_status_release_validation import expected_status_release
from radio_daily_v9_generator import digest
import test_radio_daily_combined_release_validation as fixture
from test_radio_daily_logo_plan import DAY, DATA, SID

DAY2 = "2026-11-27"
DAY3 = "2026-11-28"


class MultiversionCycleTests(unittest.TestCase):
    def setUp(self):
        f = fixture.CombinedGateTests()
        f.prepare(approved=False)
        self.f = f
        self.store = MemoryStore(f.pointer, f.raw)
        self.old_state = dict(f.operations["status"]["evidence"],
            logo=f.operations["logo"]["evidence"]["logo_maintenance"],
            missing=f.operations["logo"]["evidence"]["missing_logo"])
        self.v9 = compose(f.pointer, f.raw, **f.args)

    def first(self):
        f = self.f
        result, _ = publish_cycle(self.store, f.signer, f.pointer, f.raw, self.v9,
            anchor=f.anchor, day=DAY, operations=f.operations, objects=f.objects)
        self.assertEqual(result["sequence"], 9)
        report, state = migrate_cycle(self.store, f.pointer, f.raw, self.v9,
            anchor=f.anchor, day=DAY, state=self.old_state)
        self.assertTrue(report["nextSelectionVerified"])
        p9 = self.store.current()
        a9 = dict(f.anchor, expected_sequence=9, expected_sha=digest(self.v9))
        return p9, a9, state

    def observe_day(self, a9, prior, day):
        sha = a9["expected_sha"]
        raw = self.v9
        m = maintenance(raw, day, expected=sha, prior=prior["maintenance"],
            limit=20, probe=lambda u: dict(streamSha256=digest(u.encode()),
                  verdict="audio_sample_ok", frameChain="mp3"))
        lm = logo(raw, day, expected=sha, prior=prior["logo"])
        nm = missing(raw, day, expected=sha, prior=prior["missing"])
        d = dict(schemaVersion=1, scanDate=day, publicationAllowed=False, candidates=[])
        r = repair(raw, m, d, expected=sha, prior=prior["repair"])
        c = confirm(raw, r, expected=sha, prior=prior["confirmation"])
        rp = plan(raw,m,r,c,expected=sha)
        st = status(raw,m,rp,expected=sha,prior=prior["status"],limit=4,
            icy=lambda u: dict(verdict="continuous_icy_frame_indication",frameCodec="mp3"),
            hls=lambda u: dict(verdict="advancing_hls_audio_frame_indication",frameCodec="aac"))
        return dict(maintenance=m, logo=lm, missing=nm, repair=r, confirmation=c, status=st)

    def second(self):
        p9,a9,state = self.first()
        state = self.observe_day(a9,state,DAY2)
        self.assertEqual(state["status"]["proposalCount"],0)
        state = self.observe_day(a9,state,DAY3)
        self.assertEqual(state["status"]["proposalCount"],1)
        self.assertEqual(state["status"]["proposals"][0]["to"],"active")
        e = {k:state[k] for k in ("maintenance","repair","confirmation","status")}
        body = expected_status_release(self.v9, expected_sha=a9["expected_sha"],
            expected_sequence=9, day=DAY3, **e)
        operations = {"status":dict(candidate=body,evidence=e)}
        v10 = compose(p9,self.v9,anchor=a9,day=DAY3,operations=operations,objects={})
        return p9,a9,state,v10,operations

    def test_two_successors_reuse_logo_aliases_and_histories(self):
        p9,a9,state,v10,ops = self.second()
        with patch.object(self.store,"put_immutable", wraps=self.store.put_immutable) as write:
            result,_=publish_cycle(self.store,self.f.signer,p9,self.v9,v10,
                anchor=a9,day=DAY3,operations=ops,objects={})
        self.assertEqual(result["sequence"],10)
        self.assertTrue(result["retryVerified"])
        self.assertTrue(all(not call.args[0].startswith("objects/") for call in write.call_args_list))
        report,next_state=migrate_cycle(self.store,p9,self.v9,v10,anchor=a9,day=DAY3,state=state)
        self.assertTrue(report["migrationVerified"])
        self.assertTrue(report["nextSelectionVerified"])
        self.assertEqual(report["migration"]["streamHistoriesRetained"],2)
        self.assertEqual(report["migration"]["recoveryHistoriesRetained"],0)
        new=verify_visible(self.store,self.store.current(),sha=digest(v10),sequence=10,signer=self.f.signer)
        old=strict_json(self.f.raw)
        self.assertEqual([s["legacy_aliases"] for s in new["stations"]],
                         [s["legacy_aliases"] for s in old["stations"]])
        self.assertEqual([s["go_station_id"] for s in new["stations"]],
                         [s["go_station_id"] for s in old["stations"]])
        self.assertEqual(new["tombstones"],old["tombstones"])
        self.assertEqual(new["stations"][1]["status"]["state"],"active")
        self.assertEqual(self.store.logo(new["stations"][0]["logo"]["url"]),DATA)
        self.assertEqual(self.store.get("releases/"+digest(self.f.raw)+".json"),self.f.raw)
        self.assertEqual(self.store.get("releases/"+digest(self.v9)+".json"),self.v9)
        self.assertTrue(all(r["catalogBaselineSha256"]==digest(v10) for r in next_state.values()))

    def test_no_change_between_successors(self):
        p9,a9,state=self.first()
        result,unchanged=publish_cycle(self.store,self.f.signer,p9,self.v9,None,
            anchor=a9,day=DAY2,operations={},objects={},state=state)
        self.assertFalse(result["changed"])
        self.assertEqual(result["sequence"],9)
        self.assertEqual(self.store.current(),p9)
        self.assertEqual(unchanged,state)

    def test_old_predecessor_cannot_be_replayed_as_new_cycle(self):
        self.first()
        f=self.f
        with self.assertRaisesRegex(ValueError,"current predecessor"):
            publish_cycle(self.store,f.signer,f.pointer,f.raw,self.v9,
                anchor=f.anchor,day=DAY,operations=f.operations,objects=f.objects)

    def test_interruption_before_v10_switch_keeps_v9_visible(self):
        p9,a9,state,v10,ops=self.second()
        def stop(phase):
            if phase=="before_pointer_swap":
                raise RuntimeError("interrupted")
        with self.assertRaisesRegex(RuntimeError,"interrupted"):
            publish_cycle(self.store,self.f.signer,p9,self.v9,v10,
                anchor=a9,day=DAY3,operations=ops,objects={},checkpoint=stop)
        self.assertEqual(self.store.current(),p9)
        verify_visible(self.store,p9,sha=digest(self.v9),sequence=9,signer=self.f.signer)
        result,_=publish_cycle(self.store,self.f.signer,p9,self.v9,v10,
            anchor=a9,day=DAY3,operations=ops,objects={})
        self.assertEqual(result["sequence"],10)
