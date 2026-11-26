import copy
import json
import unittest
from radio_daily_restore_preview import restore
from radio_daily_lab_signing import EphemeralLabSigner
from radio_daily_publication_simulator import MemoryStore,publish,verify_visible
from radio_daily_v9_generator import encode,digest
from test_radio_daily_baseline_selection import signed
from test_radio_daily_repair_plan import fixture,DAY,SID,UID,OLD,NEW


class RestorePreviewTests(unittest.TestCase):
    def setUp(self):
        self.signer=EphemeralLabSigner()
        raw,*_=fixture()
        self.old=json.loads(raw)
        s=self.old["stations"][0]
        s["logo"]=None
        s["editorial"].update(admission_state="approved",reviewed_at=DAY+"T00:00:00Z")
        self.current=copy.deepcopy(self.old)
        self.current.update(release_sequence=9,generated_at=DAY+"T00:00:00Z")
        s=self.current["stations"][0]
        s["display_name"]="Changed Radio"
        s["legacy_aliases"].append("new-favorite")
        s["radio_browser_uuids"].append(dict(uuid="new-favorite",state="current"))
        s["streams"][0]["url"]=NEW
        s["streams"].append(dict(stream_id="new-variant",url="https://radio.example.org/extra",
                                 priority=1,protocol="https",state="verified"))
        other=copy.deepcopy(s)
        other.update(go_station_id="go-station-000002",display_name="New Radio",
                     legacy_aliases=["other-favorite"],radio_browser_uuids=[])
        self.current["stations"].append(other)
        self.current["tombstones"].append(dict(go_station_id="go-station-000003",
            legacy_aliases=["merged-favorite"],retired_at=DAY+"T00:00:00Z",
            reason_code="merged_into_station",redirect_to=SID))

    def materials(self,doc):
        p,b=signed(doc,self.signer._key,self.signer.key_id)
        return p,b,dict(expected_sha=digest(b),expected_sequence=doc["release_sequence"],
                         public_key=self.signer.public_key,key_id=self.signer.key_id)

    def plan(self,ids=(SID,),**kw):
        p,b,a=self.materials(self.current)
        q,c,d=self.materials(self.old)
        args=dict(current_anchor=a,historical_anchor=d,day=DAY,station_ids=ids)
        args.update(kw)
        return restore(p,b,q,c,**args)

    def test_restore_monotone_and_preserve_ids_aliases_and_streams(self):
        body,report=self.plan()
        doc=json.loads(body)
        self.assertEqual(doc["release_sequence"],10)
        self.assertEqual(report["restoredStationIds"],[SID])
        self.assertTrue(report["requiresFreshStreamAndArtworkReview"])
        s=doc["stations"][0]
        self.assertEqual(s["display_name"],self.old["stations"][0]["display_name"])
        self.assertEqual(s["legacy_aliases"],self.current["stations"][0]["legacy_aliases"])
        self.assertEqual(s["radio_browser_uuids"],self.current["stations"][0]["radio_browser_uuids"])
        self.assertEqual(s["streams"][0]["url"],OLD)
        self.assertIn(NEW,s["streams"][0]["previous_urls"])
        self.assertEqual(s["streams"][1]["state"],"disabled")
        self.assertEqual(doc["stations"][1],self.current["stations"][1])
        self.assertEqual(doc["tombstones"],self.current["tombstones"])

    def test_empty_selection_no_version(self):
        body,report=self.plan(())
        self.assertIsNone(body)
        self.assertIsNone(report["candidateSequence"])

    def test_unknown_or_merged_target_refused(self):
        for sid in ("go-station-000002","go-station-000003","go-station-999999"):
            with self.assertRaisesRegex(ValueError,"target missing or merged"):
                self.plan((sid,))

    def test_old_or_equal_current_source_refused(self):
        self.old=copy.deepcopy(self.current)
        with self.assertRaisesRegex(ValueError,"source must be older"):
            self.plan()

    def test_lost_historical_alias_refused(self):
        self.current["stations"][0]["legacy_aliases"].remove(UID)
        self.current["stations"][0]["radio_browser_uuids"].pop(0)
        with self.assertRaisesRegex(ValueError,"identity continuity"):
            self.plan()

    def test_status_change_requires_requalification(self):
        self.old["stations"][0]["status"]["state"]="quarantined"
        with self.assertRaisesRegex(ValueError,"status restoration"):
            self.plan()

    def test_bad_historical_signature_refused(self):
        p,b,a=self.materials(self.current)
        q,c,d=self.materials(self.old)
        with self.assertRaises(ValueError):
            restore(p,b,q,c+b" ",current_anchor=a,historical_anchor=d,day=DAY,station_ids=[SID])

    def test_logo_revision_monotonic(self):
        from test_radio_daily_logo_plan import DATA,OLD as BLUE,URL
        for doc,art,rev in ((self.old,BLUE,2),(self.current,DATA,7)):
            sha=digest(art)
            doc["stations"][0]["logo"]=dict(asset_id="sha256:"+sha,sha256=sha,revision=rev,
                url=URL,byte_size=len(art),width=128,height=128,mime_type="image/png")
        body,_=self.plan()
        logo=json.loads(body)["stations"][0]["logo"]
        self.assertEqual(logo["sha256"],digest(BLUE))
        self.assertEqual(logo["revision"],8)

    def test_simulated_publication_and_anti_rollback(self):
        # Synthetic fixtures only: real restoration needs fresh resource review.
        p,b,a=self.materials(self.current)
        candidate,report=self.plan()
        store=MemoryStore(p,b)
        result=publish(store,self.signer,p,b,candidate,expected_sha=a["expected_sha"],
            expected_sequence=9,expected_candidate_sha=report["candidateSha256"],day=DAY)
        self.assertEqual(result["sequence"],10)
        verify_visible(store,store.current(),sha=digest(candidate),sequence=10,signer=self.signer)
        from radio_daily_baseline_selection import select
        q,c,_=self.materials(self.old)
        with self.assertRaisesRegex(ValueError,"rollback"):
            select(q,lambda path,length:c,prior_pointer=store.current(),prior_body=candidate,
                expected_sha=digest(candidate),expected_sequence=10,
                public_key=self.signer.public_key,key_id=self.signer.key_id)


if __name__=="__main__":
    unittest.main()
