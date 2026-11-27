import copy
import json
import unittest
from radio_daily_merge_plan import plan,apply,undo
from radio_daily_v9_generator import encode,digest,check_catalog
from radio_daily_maintenance_preview import build as maintenance,digest as url_digest
from radio_daily_baseline_verify import validate_shape
from test_radio_daily_repair_plan import fixture,SID,DAY,DAY1

OTHER="go-station-000002"
def setup(change=None):
    raw,*_=fixture()
    doc=json.loads(raw)
    s=copy.deepcopy(doc["stations"][0])
    s["go_station_id"]=OTHER
    uid="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    s["legacy_aliases"]=[uid]
    s["radio_browser_uuids"]=[{"uuid":uid,"state":"current"}]
    doc["stations"].append(s)
    if change:
        change(doc)
    raw=encode(doc)
    sha=digest(raw)
    def probe(u):
        return {"streamSha256":url_digest(u),"verdict":"audio_sample_ok","frameChain":"mp3"}
    m=maintenance(raw,DAY1,expected=sha,limit=20,probe=probe)
    m=maintenance(raw,DAY,expected=sha,prior=m,limit=20,probe=probe)
    return doc,m

class MergeTests(unittest.TestCase):
    def test_exact_duplicate_redirect_preserves_alias_and_reverses(self):
        old,m=setup()
        p,d=plan(old,m,DAY)
        self.assertEqual(len(p),1)
        self.assertFalse(d)
        new=copy.deepcopy(old)
        apply(new,old,p,DAY)
        self.assertEqual(new["stations"],old["stations"][:1])
        self.assertEqual(new["tombstones"][0]["legacy_aliases"],old["stations"][1]["legacy_aliases"])
        self.assertEqual(new["tombstones"][0]["redirect_to"],SID)
        validate_shape(new)
        check_catalog(new,previous=old)
        undo(new,old,p)
        self.assertEqual(new,old)

    def test_different_variant_held(self):
        def change(doc):
            doc["stations"][1]["streams"][0]["url"]="https://radio.example.org/other"
        old,m=setup(change)
        p,d=plan(old,m,DAY)
        self.assertFalse(p)
        self.assertEqual(d[0]["reason"],"variant_transfer_requires_review")

    def test_redirect_target_survives(self):
        def change(doc):
            doc["tombstones"].append({"go_station_id":"go-station-999999","legacy_aliases":[],
            "retired_at":DAY1+"T00:00:00Z","reason_code":"merged_into_station","redirect_to":OTHER})
        old,m=setup(change)
        p,_=plan(old,m,DAY)
        self.assertEqual(p[0]["targetGoStationId"],OTHER)

    def test_network_protected(self):
        def change(doc):
            for s in doc["stations"]:
                s["display_name"]="Radio BOB! Metal"
        old,m=setup(change)
        p,d=plan(old,m,DAY)
        self.assertFalse(p)
        self.assertEqual(d[0]["reason"],"protected_or_ambiguous_identity")

    def test_same_day_not_enough(self):
        old,m=setup()
        for row in m["streams"]:
            row["observations"]=row["observations"][-1:]
        p,d=plan(old,m,DAY)
        self.assertFalse(p)
        self.assertEqual(d[0]["reason"],"await_repeated_shared_stream")

    def test_concurrent_change_held(self):
        old,m=setup()
        p,d=plan(old,m,DAY,{SID})
        self.assertFalse(p)
        self.assertEqual(d[0]["reason"],"redirect_or_concurrent_change_conflict")

if __name__=="__main__":
    unittest.main()
