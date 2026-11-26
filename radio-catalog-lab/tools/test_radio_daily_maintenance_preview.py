import hashlib
import json
import unittest
from radio_daily_maintenance_preview import build,digest

DAY="2026-11-26"
A="go-station-1"
B="go-station-2"
URL="https://radio.example.org/live?token=secret"
ALT="https://radio.example.org/alt"
Q="https://radio.example.org/quarantine"

def fixture():
    def station(sid,status,urls):
        return {"go_station_id":sid,"status":{"state":status},
                "streams":[{"stream_id":str(i),"url":u} for i,u in enumerate(urls)]}
    raw=json.dumps({"release_sequence":8,"stations":[station(A,"active",[URL,ALT]),
                                                   station(B,"quarantined",[Q])]}).encode()
    return raw,hashlib.sha256(raw).hexdigest()

def probe(url,good=False):
    return {"streamSha256":digest(url),"verdict":"audio_sample_ok" if good else "needs_review",
            "frameChain":"mp3" if good else "", "reason":"http_not_successful"}

def run(day=DAY,prior=None,limit=3,fn=probe):
    raw,sha=fixture()
    return build(raw,day,expected=sha,prior=prior,limit=limit,probe=fn)

class MaintenanceTests(unittest.TestCase):
    def test_inventory_and_no_network_default(self):
        r=run(limit=0,fn=lambda u:self.fail("network"))
        self.assertEqual(r["stationCount"],2)
        self.assertEqual(r["streamCount"],3)
        self.assertEqual(r["reviewCounts"],{"awaiting_probe":2})

    def test_same_day_never_accumulates(self):
        r=run()
        r=run(prior=r,fn=lambda u:self.fail("same day"))
        self.assertEqual(r["checkedCount"],0)
        self.assertEqual(r["everObservedStreamCount"],3)

    def test_all_variants_three_separate_days_review_only(self):
        r=run("2026-11-24")
        r=run("2026-11-25",r)
        r=run(DAY,r)
        self.assertEqual(r["records"][0]["reviewStatus"],"quarantine_review")
        self.assertEqual(r["records"][1]["catalogueStatus"],"quarantined")
        self.assertFalse(r["records"][0]["approved"])
        self.assertEqual(r["approvedCount"],0)
        self.assertNotIn("secret",json.dumps(r))

    def test_working_variant_prevents_quarantine(self):
        def mixed(u):return probe(u,u==ALT)
        r=run("2026-11-24",fn=mixed)
        r=run("2026-11-25",r,fn=mixed)
        r=run(DAY,r,fn=mixed)
        self.assertEqual(r["records"][0]["reviewStatus"],"audio_sample_observed")

    def test_quarantined_positive_review_not_restored(self):
        r=run(fn=lambda u:probe(u,True))
        self.assertEqual(r["records"][1]["reviewStatus"],"restoration_probe_review")
        self.assertEqual(r["records"][1]["catalogueStatus"],"quarantined")

    def test_inconclusive_is_not_failure(self):
        r=run("2026-11-24")
        r=run("2026-11-25",r)
        r=run(DAY,r,fn=lambda u:{"streamSha256":digest(u),"verdict":"playlist_pending"})
        self.assertNotIn("quarantine_review",r["reviewCounts"])
        self.assertEqual(r["sampleCounts"],{"inconclusive":3})

    def test_rotation_covers_unseen(self):
        r=run(limit=1)
        r=run(prior=r,limit=1)
        r=run(prior=r,limit=1)
        self.assertEqual(r["everObservedStreamCount"],3)

    def test_mismatched_baseline_or_fingerprint_rejected(self):
        raw,sha=fixture()
        with self.assertRaises(ValueError):
            build(raw,DAY,expected="a"*64)
        with self.assertRaises(ValueError):
            run(fn=lambda u:{"streamSha256":"a"*64})
        r=run()
        r["streams"][0]["streamSha256"]="a"*64
        with self.assertRaises(ValueError):
            run(prior=r)

if __name__=="__main__":
    unittest.main()
