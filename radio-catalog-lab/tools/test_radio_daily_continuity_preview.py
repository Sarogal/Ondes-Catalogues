import unittest
from radio_daily_continuity_preview import assess, collect, WINDOW_BYTES
from radio_daily_qualification_dossiers import safe_digest

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
DAY = "2026-11-25"
URL = "https://radio.example.org/live"


def frames(value):
    # MPEG1 layer III, 128 kbps, 44100 Hz, 417-byte frames.
    frame = b"\xff\xfb\x90\x00" + bytes([value])*413
    return frame*9


def inputs():
    common = {"schemaVersion":1,"publicationAllowed":False,"scanDate":DAY}
    d = {**common,"candidates":[{"stationuuid":u,"streamUrl":URL+str(i),
        "editorialSignal":"target_genre_indication"} for i,u in enumerate((A,B))]}
    r = {"schemaVersion":1,"scanDate":DAY,"automaticAdmissionAllowed":False,"catalogChanged":False,
         "candidates":[{"stationuuid":u,"classification":"unmapped_candidate"} for u in (A,B)]}
    a = {"schemaVersion":1,"publicationAllowed":False,"observationDate":DAY,"technicallyQualifiedCount":0,
         "records":[{"stationuuid":x["stationuuid"],"streamSha256":safe_digest(x["streamUrl"]),
                     "lastVerdict":"audio_sample_ok","liveFrameEvidenceDates":[DAY],
                     "technicalQualified":False,"publicationAllowed":False} for x in d["candidates"]]}
    e = {**common,"editoriallyApprovedCount":0,"records":[]}
    return d,r,a,e


class ContinuityTests(unittest.TestCase):
    def test_three_distinct_coherent_windows(self):
        a = assess([frames(1),frames(2),frames(3)],finite=False,icy=True,elapsed=4.2,ended=False)
        self.assertEqual(a["verdict"],"continuous_icy_frame_indication")
        self.assertEqual(a["coherentWindowCount"],3)

    def test_finite_or_early_end_not_live(self):
        x=[frames(i) for i in (1,2,3)]
        self.assertEqual(assess(x,finite=True,icy=True,elapsed=5,ended=False)["verdict"],"finite_response_review")
        self.assertEqual(assess(x,finite=False,icy=True,elapsed=5,ended=True)["verdict"],"early_end_review")

    def test_repeated_payload_or_short_duration_insufficient(self):
        for x,t in (([frames(1)]*3,5),([frames(i) for i in (1,2,3)],1)):
            self.assertEqual(assess(x,finite=False,icy=True,elapsed=t,ended=False)["verdict"],"insufficient_continuity_evidence")

    def test_no_icy_is_separate(self):
        self.assertEqual(assess([frames(i) for i in (1,2,3)],finite=False,icy=False,elapsed=5,ended=False)["verdict"],"continuous_frames_unbound")

    def test_priority_and_no_repeat_same_day(self):
        d,r,a,e=inputs()
        e["records"]=[{"stationuuid":B,"declaredStreamLinked":True,"streamSha256":a["records"][1]["streamSha256"]}]
        calls=[]
        def observe(url):
            calls.append(url)
            return {"verdict":"continuous_icy_frame_indication","windowCount":3}
        first=collect(d,r,a,e,limit=1,observe=observe)
        self.assertEqual(calls,[URL+"1"])
        self.assertEqual(first["technicallyQualifiedCount"],0)
        second=collect(d,r,a,e,limit=1,previous=first,observe=observe)
        self.assertEqual(calls,[URL+"1",URL+"0"])
        self.assertEqual(len(second["records"]),2)

    def test_changed_stream_invalidates_old_evidence(self):
        d,r,a,e=inputs()
        first=collect(d,r,a,e,limit=1,observe=lambda u:{"verdict":"finite_response_review"})
        d["candidates"][0]["streamUrl"]=URL+"changed"
        second=collect(d,r,a,e,limit=0,previous=first)
        self.assertEqual(second["records"],[])

    def test_retains_unseen_candidate(self):
        d,r,a,e=inputs()
        first=collect(d,r,a,e,limit=1,observe=lambda u:{"verdict":"finite_response_review"})
        d["candidates"]=d["candidates"][1:]
        r["candidates"]=r["candidates"][1:]
        second=collect(d,r,a,e,limit=0,previous=first)
        self.assertFalse(second["records"][0]["observedInScan"])

    def test_default_no_network_and_cap(self):
        self.assertEqual(collect(*inputs(),observe=lambda u:self.fail("network"))["attemptedCount"],0)
        with self.assertRaises(ValueError):
            collect(*inputs(),limit=7)


if __name__ == "__main__":
    unittest.main()
