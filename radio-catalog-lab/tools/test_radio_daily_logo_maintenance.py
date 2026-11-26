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

if __name__=="__main__":
    unittest.main()
