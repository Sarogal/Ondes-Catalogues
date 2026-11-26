import copy
import hashlib
import json
import unittest
from radio_daily_logo_maintenance import build
from radio_daily_v9_generator import encode
from test_radio_daily_repair_plan import fixture

DAY="2026-11-26"
DAY1="2026-11-25"
BYTES=b"existing image"
NEW=b"changed image"
URL="https://radio.example.org/logo.png"

def setup(query=False):
    raw,*_=fixture()
    doc=json.loads(raw)
    station=doc["stations"][0]
    sha=hashlib.sha256(BYTES).hexdigest()
    station["logo"].update(asset_id="sha256:"+sha,sha256=sha,byte_size=len(BYTES),width=128,height=128,
                           url=URL+("?token=secret" if query else ""))
    for i in (2,3):
        s=copy.deepcopy(station)
        s["go_station_id"]=f"go-station-{i:06}"
        s["legacy_aliases"]=[]
        s["radio_browser_uuids"]=[]
        if i==3:
            s["logo"]=None
        doc["stations"].append(s)
    raw=encode(doc)
    return raw,hashlib.sha256(raw).hexdigest()

def decode(data):
    return "image/png",128,128

def run(raw,sha,day=DAY,prior=None,fetch=lambda u,h:(BYTES,"image/png"),limit=8):
    return build(raw,day,expected=sha,prior=prior,limit=limit,fetch=fetch,decode=decode)

class LogoMaintenanceTests(unittest.TestCase):
    def test_shared_address_one_fetch_and_missing(self):
        raw,sha=setup()
        calls=[]
        def fetch(u,h):
            calls.append(u)
            return BYTES,"image/png"
        r=run(raw,sha,fetch=fetch)
        self.assertEqual(calls,[URL])
        self.assertEqual(r["counts"],{"missing_logo":1,"unchanged":2})
        self.assertFalse(r["catalogChanged"])
        self.assertEqual(r["approvedLogoCount"],0)
        self.assertNotIn(URL,json.dumps(r))

    def test_no_redundant_download_same_day_or_next_day(self):
        raw,sha=setup()
        r=run(raw,sha,DAY1)
        for day in (DAY1,DAY):
            r=run(raw,sha,day,r,fetch=lambda u,h:self.fail("unnecessary fetch"))
            self.assertEqual(r["attemptedCount"],0)

    def test_repeated_changed_bytes_are_review_only(self):
        raw,sha=setup()
        fetch=lambda u,h:(NEW,"image/png")
        r=run(raw,sha,DAY1,fetch=fetch)
        self.assertEqual(r["counts"]["changed_image_review"],2)
        r=run(raw,sha,DAY,r,fetch=fetch)
        self.assertEqual(r["counts"]["repeated_changed_image_review"],2)
        self.assertFalse(r["records"][0]["logoApproved"])

    def test_failure_never_removes_logo_and_breaks_change_streak(self):
        raw,sha=setup()
        r=run(raw,sha,"2026-11-24",fetch=lambda u,h:(NEW,"image/png"))
        def fail(u,h):raise OSError("unavailable")
        r=run(raw,sha,DAY1,r,fetch=fail)
        self.assertEqual(r["counts"]["source_unavailable_review"],2)
        self.assertIsNotNone(r["records"][0]["expectedImageSha256"])
        r=run(raw,sha,DAY,r,fetch=lambda u,h:(NEW,"image/png"))
        self.assertEqual(r["counts"]["changed_image_review"],2)

    def test_query_source_held_and_not_leaked(self):
        raw,sha=setup(query=True)
        r=run(raw,sha,fetch=lambda u,h:self.fail("query source"))
        self.assertEqual(r["attemptedCount"],0)
        self.assertEqual(r["counts"]["query_source_held"],2)
        self.assertNotIn("secret",json.dumps(r))

    def test_prior_tampering_refused(self):
        raw,sha=setup()
        r=run(raw,sha)
        r["sources"][0]["observations"][0]["image"]["width"]=0
        with self.assertRaises(ValueError):
            run(raw,sha,prior=r)

    def test_same_hash_descriptor_mismatch(self):
        raw,_=setup()
        doc=json.loads(raw)
        for s in doc["stations"]:
            if s["logo"]:
                s["logo"]["width"]=256
        raw=encode(doc)
        r=run(raw,hashlib.sha256(raw).hexdigest())
        self.assertEqual(r["counts"]["descriptor_mismatch_review"],2)

class OfficialSourceTests(unittest.TestCase):
    def candidate(self):
        from radio_daily_unified_generator import build as generate
        from radio_daily_decision_preview import decide
        from radio_daily_repair_plan import plan
        from radio_daily_maintenance_preview import build as maintenance
        from radio_daily_repair_preview import build as repair
        from radio_daily_repair_confirmation import build as confirm
        from test_radio_daily_logo_plan import reports,material,DATA
        raw,sha,l,n=reports()
        d=dict(schemaVersion=1,scanDate=DAY,publicationAllowed=False,candidates=[])
        e=dict(schemaVersion=1,scanDate=DAY,publicationAllowed=False,
               approvedCount=0,catalogBaselineSha256=sha,records=[])
        m=maintenance(raw,DAY,expected=sha)
        r=repair(raw,m,d,expected=sha)
        c=confirm(raw,r,expected=sha)
        objects={}
        body,report=generate(raw,d,e,decide(d,e,sha),m,r,c,plan(raw,m,r,c,expected=sha),
            logo_maintenance=l,missing_logo=n,artwork={"go-station-000001":material()},
            object_output=objects,expected=sha)
        self.assertEqual(len(report["logoChanges"]),1)
        self.assertEqual(list(objects.values()),[DATA])
        return body

    def test_generator_binds_official_source_and_future_scan_uses_it(self):
        from radio_daily_logo_maintenance import official_source
        from radio_daily_logo_plan import PREVIEW_BASE
        from test_radio_daily_logo_plan import DATA,OLD
        raw=self.candidate()
        station=json.loads(raw)["stations"][0]
        self.assertTrue(station["logo"]["url"].startswith(PREVIEW_BASE))
        self.assertEqual(official_source(station),URL)
        calls=[]
        def fetch(u,h):
            calls.append(u)
            return OLD,"image/png"
        sha=hashlib.sha256(raw).hexdigest()
        r=build(raw,DAY,expected=sha,limit=8,fetch=fetch)
        r=build(raw,"2026-11-27",expected=sha,prior=r,limit=8,fetch=fetch)
        self.assertEqual(calls,[URL,URL])
        self.assertEqual(r["counts"],{"repeated_changed_image_review":1})
        self.assertNotIn(URL,json.dumps(r))

    def test_missing_provenance_never_probes_own_storage(self):
        raw=self.candidate()
        doc=json.loads(raw)
        doc["stations"][0]["editorial"]["evidence_refs"]=[]
        raw=encode(doc)
        result=build(raw,DAY,expected=hashlib.sha256(raw).hexdigest(),limit=8,
            fetch=lambda u,h:self.fail("must not fetch storage URL"))
        self.assertEqual(result["counts"],{"official_source_missing_review":1})
        self.assertEqual(result["attemptedCount"],0)

    def test_bad_digest_or_ambiguous_source_rejected(self):
        from radio_daily_logo_maintenance import official_source,SOURCE_PREFIX
        station=json.loads(self.candidate())["stations"][0]
        refs=station["editorial"]["evidence_refs"]
        original=refs[-1]
        refs[-1]=SOURCE_PREFIX+"0"*64+":"+URL
        with self.assertRaisesRegex(ValueError,"digest mismatch"):
            official_source(station)
        refs[-1]=original
        refs.append(original)
        with self.assertRaisesRegex(ValueError,"ambiguous"):
            official_source(station)

    def test_query_and_storage_source_refused(self):
        from radio_daily_logo_maintenance import source_reference
        station=json.loads(self.candidate())["stations"][0]
        for url in (URL+"?token=secret",station["logo"]["url"]):
            with self.assertRaises(ValueError):
                source_reference(station["logo"],url)


if __name__=="__main__":
    unittest.main()
