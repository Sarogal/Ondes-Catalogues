import copy
import hashlib
import json
import unittest

from radio_daily_status_preview import build
from radio_daily_maintenance_preview import build as maintenance,digest
from radio_daily_v9_generator import encode
from test_radio_daily_repair_plan import fixture, SID, DAY, DAY1, OLD

def setup(quarantined=False,redirect=False,count=1):
    raw,_,_,_,_=fixture(quarantine=quarantined)
    doc=json.loads(raw)
    for i in range(2,count+1):
        s=copy.deepcopy(doc["stations"][0])
        s["go_station_id"]=f"go-station-{i:06}"
        s["legacy_aliases"]=[]
        s["radio_browser_uuids"]=[]
        s["streams"][0]["url"]=f"https://radio.example.org/{i}"
        doc["stations"].append(s)
    if redirect:
        doc["tombstones"]=[{"go_station_id":"go-station-999999","legacy_aliases":[],
                           "retired_at":"2026-11-23T00:00:00Z","reason_code":"merged_into_station","redirect_to":SID}]
    raw=encode(doc)
    return raw,hashlib.sha256(raw).hexdigest()

def repair(sha,day):
    return {"schemaVersion":1,"scanDate":day,"catalogBaselineSha256":sha,"publicationAllowed":False,
            "approvedCount":0,"signed":False,"candidateCatalogueWritten":False,"proposals":[]}

def probe(u,positive=False):
    return {"streamSha256":digest(u),"verdict":"audio_sample_ok" if positive else "needs_review",
            "reason":"http_not_successful","frameChain":"mp3" if positive else ""}

def good(u):
    return {"verdict":"continuous_icy_frame_indication"}

def run(raw,sha,day,m=None,p=None,positive=False,observer=good,limit=4):
    m=maintenance(raw,day,expected=sha,prior=m,limit=20,probe=lambda u:probe(u,positive))
    result=build(raw,m,repair(sha,day),expected=sha,prior=p,limit=limit,icy=observer,hls=observer)
    return m,result

class StatusTests(unittest.TestCase):
    def test_restore_requires_two_distinct_days_and_never_writes(self):
        raw,sha=setup(quarantined=True)
        m,p=run(raw,sha,DAY1,positive=True)
        self.assertEqual(p["proposalCount"],0)
        self.assertEqual(p["counts"],{"await_repeated_continuity":1})
        m,p=run(raw,sha,DAY,m,p,positive=True)
        self.assertEqual(p["proposalCount"],1)
        self.assertEqual(p["proposals"][0]["to"],"active")
        self.assertFalse(p["candidateCatalogueWritten"])
        self.assertFalse(p["proposals"][0]["approved"])
        self.assertEqual(json.loads(raw)["stations"][0]["status"]["state"],"quarantined")

    def test_sample_is_not_continuity_and_same_day_not_repeated(self):
        raw,sha=setup(quarantined=True)
        m,p=run(raw,sha,DAY,positive=True,observer=lambda u:{"verdict":"finite_response_review"})
        self.assertEqual(p["proposalCount"],0)
        m,p=run(raw,sha,DAY,m,p,positive=True,observer=lambda u:self.fail("same day"))
        self.assertEqual(p["attemptedCount"],0)

    def test_negative_sample_blocks_recovery(self):
        raw,sha=setup(quarantined=True)
        m,p=run(raw,sha,DAY1,positive=True)
        m,p=run(raw,sha,DAY,m,p)
        self.assertEqual(p["proposalCount"],0)
        self.assertEqual(p["attemptedCount"],0)

    def test_three_failure_days_and_redirect_protection(self):
        for redirect in (False,True):
            raw,sha=setup(redirect=redirect)
            m=p=None
            for day in ("2026-11-24",DAY1,DAY):
                m,p=run(raw,sha,day,m,p)
            self.assertEqual(p["proposalCount"],0 if redirect else 1)
            self.assertEqual(p["records"][0]["decision"],"redirect_target_held" if redirect else "quarantine_transition_review")

    def test_mass_transition_held(self):
        raw,sha=setup(count=4)
        m=p=None
        for day in ("2026-11-24",DAY1,DAY):
            m,p=run(raw,sha,day,m,p)
        self.assertTrue(p["massTransitionHeld"])
        self.assertEqual(p["proposalCount"],0)

    def test_forged_maintenance_derived_state_refused(self):
        raw,sha=setup()
        m,p=run(raw,sha,DAY)
        m["records"][0]["reviewStatus"]="quarantine_review"
        with self.assertRaises(ValueError):
            build(raw,m,repair(sha,DAY),expected=sha)

if __name__=="__main__":
    unittest.main()
