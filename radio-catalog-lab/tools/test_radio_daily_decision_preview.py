import unittest
from radio_daily_decision_preview import decide
from radio_daily_qualification_dossiers import safe_digest
from radio_daily_editorial_preview import ANALYZER_VERSION

A="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
DAY="2026-11-25"
BASE="a"*64
URL="https://radio.example.org/live?token=secret"
PAGE="https://radio.example.org/"
SHA=safe_digest(URL)

def inputs():
    d={"schemaVersion":1,"scanDate":DAY,"publicationAllowed":False,
       "candidates":[{"stationuuid":A,"name":"Iron Radio","streamUrl":URL,"homepage":PAGE}]}
    row={"stationuuid":A,"name":"Iron Radio","observedInScan":True,"approved":False,
         "publicationAllowed":False,"duplicateRisk":False,"editorialSignal":"target_genre_indication",
         "lastSourceObservation":{"date":DAY,"streamSha256":SHA,"classification":"unmapped_candidate"},
         "homepageEvidence":{"reportedHost":"radio.example.org","homepageSha256":safe_digest(PAGE),
             "identityNameSha256":safe_digest("iron radio"),"streamSha256":SHA,
             "analyzerVersion":ANALYZER_VERSION,"observedDate":DAY,"retrieval":"html_observed",
             "identityNameMatch":True,"signal":"identity_and_target_indication","primaryTargetTerms":["metal"],
             "declaredStreamLinked":True,"structuredProgrammeEvidence":True},
         "streamEvidence":{"streamSha256":SHA,"lastVerdict":"audio_sample_ok","lastObservedDate":DAY},
         "continuityEvidence":{"streamSha256":SHA,"observedDate":DAY,"verdict":"continuous_icy_frame_indication",
                              "positiveObservationDates":["2026-11-24",DAY]}}
    return d,{"schemaVersion":1,"scanDate":DAY,"catalogBaselineSha256":BASE,
              "publicationAllowed":False,"approvedCount":0,"records":[row]}

class DecisionTests(unittest.TestCase):
    def test_positive_staging_without_logo_never_publishes(self):
        report=decide(*inputs(),BASE)
        self.assertEqual(report["stagingReviewCount"],1)
        self.assertFalse(report["records"][0]["approved"])
        self.assertNotIn("secret",str(report))

    def test_same_day_not_enough(self):
        d,r=inputs()
        r["records"][0]["continuityEvidence"]["positiveObservationDates"]=[DAY]
        result=decide(d,r,BASE)["records"][0]
        self.assertEqual(result["decision"],"advanced_candidate")
        self.assertIn("repeat_continuity_on_distinct_days",result["blockingReasons"])

    def test_mixed_format_not_rejected(self):
        d,r=inputs()
        r["records"][0]["editorialSignal"]="mixed_genre_review"
        result=decide(d,r,BASE)["records"][0]
        self.assertIn("resolve_mixed_or_electronic_format",result["blockingReasons"])
        self.assertNotEqual(result["decision"],"ready_for_staging_review")

    def test_stale_page_or_changed_stream(self):
        for field,value in (("homepage","https://radio.example.org/new"),("streamUrl",URL+"2")):
            d,r=inputs()
            d["candidates"][0][field]=value
            self.assertEqual(decide(d,r,BASE)["stagingReviewCount"],0)

    def test_duplicate_stream_across_candidates(self):
        d,r=inputs()
        r["records"].append(dict(r["records"][0],stationuuid=B,name="Other"))
        self.assertEqual(decide(d,r,BASE)["counts"],{"identity_review":2})

    def test_negative_recent_probe_blocks_old_positive(self):
        d,r=inputs()
        r["records"][0]["streamEvidence"]["lastVerdict"]="needs_review"
        self.assertEqual(decide(d,r,BASE)["stagingReviewCount"],0)

    def test_hls_route_and_no_logo_requirement(self):
        d,r=inputs()
        row=r["records"][0]
        row["streamEvidence"]["lastVerdict"]="playlist_pending"
        row["hlsEvidence"]=dict(row.pop("continuityEvidence"),verdict="advancing_hls_audio_frame_indication")
        self.assertEqual(decide(d,r,BASE)["stagingReviewCount"],1)

    def test_absent_candidate_not_deleted(self):
        d,r=inputs()
        d["candidates"]=[]
        self.assertEqual(decide(d,r,BASE)["counts"],{"source_recheck":1})

    def test_wrong_baseline_or_approval_rejected(self):
        d,r=inputs()
        with self.assertRaises(ValueError):
            decide(d,r,"b"*64)
        r["records"][0]["approved"]=True
        with self.assertRaises(ValueError):
            decide(d,r,BASE)

if __name__=="__main__":
    unittest.main()
