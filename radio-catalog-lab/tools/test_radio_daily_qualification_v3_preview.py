import copy
import unittest
from radio_daily_decision_preview import decide
from radio_daily_qualification_v3_preview import evaluate
from test_radio_daily_decision_preview import inputs,BASE,DAY,SHA,A
from radio_daily_programme_preview import BUCKETS

def fixture():
    d=decide(*inputs(),BASE)
    p={"schemaVersion":1,"scanDate":DAY,"publicationAllowed":False,"approvedCount":0,
       "verifiedArtistCount":0,"freshnessDays":30,"records":[{
       "stationuuid":A,"streamSha256":SHA,"matchesDecisionStream":True,"approved":False,
       "publicationAllowed":False,"verifiedArtistCount":0,"distinctArtistHints":1,
       "distinctArtistTitleHints":1,"observationDates":[DAY],"reportedBroadcastDates":[],
       "artistHintCounts":{"target_hint":1},"artistTitleHintCounts":{"target_hint":1},
       "sourceHintCounts":{"linked_sources":1}}]}
    return d,p

class V3Tests(unittest.TestCase):
    def test_convergence_never_approves_and_v2_unchanged(self):
        d,p=fixture()
        original=copy.deepcopy(d)
        result=evaluate(d,p,BASE)
        r=result["records"][0]
        self.assertEqual(r["shadowDecision"],"declared_and_observed_target_review")
        self.assertEqual(r["crossSourcePairHintCount"],1)
        self.assertFalse(r["approved"])
        self.assertFalse(result["publicationAllowed"])
        self.assertEqual(d,original)

    def test_no_music_or_changed_stream_is_unknown(self):
        for mode in ("absent","changed"):
            d,p=fixture()
            if mode=="absent":
                p["records"]=[]
            else:
                p["records"][0]["streamSha256"]="b"*64
            r=evaluate(d,p,BASE)["records"][0]
            self.assertEqual(r["shadowDecision"],"declared_format_review")
            self.assertEqual(r["programmeEvidenceStatus"],"no_bound_programme_evidence")

    def test_mixed_and_other_are_context_not_rejection(self):
        for bucket in ("mixed_hint","other_hint"):
            d,p=fixture()
            row=p["records"][0]
            row["artistHintCounts"]=row["artistTitleHintCounts"]={bucket:1}
            r=evaluate(d,p,BASE)["records"][0]
            self.assertEqual(r["shadowDecision"],"programme_context_review")
            self.assertFalse(r["approved"])

    def test_conflicts_and_duplicate_precedence(self):
        d,p=fixture()
        p["records"][0]["sourceHintCounts"]={"identity_conflict":1}
        r=evaluate(d,p,BASE)["records"][0]
        self.assertEqual(r["shadowDecision"],"programme_conflict_review")
        d["records"][0]["decision"]="identity_review"
        r=evaluate(d,p,BASE)["records"][0]
        self.assertEqual(r["shadowDecision"],"identity_review")

    def test_music_cannot_bypass_technical_gate(self):
        d,p=fixture()
        d["records"][0]["decision"]="technical_review"
        d["records"][0]["blockingReasons"]=["obtain_current_continuity_evidence"]
        r=evaluate(d,p,BASE)["records"][0]
        self.assertEqual(r["shadowDecision"],"observed_music_candidate")
        self.assertEqual(r["v2BlockingReasons"],["obtain_current_continuity_evidence"])
        self.assertFalse(r["approved"])

    def test_history_not_independent_days(self):
        d,p=fixture()
        p["records"][0]["observationDates"]=[]
        p["records"][0]["reportedBroadcastDates"]=["2026-11-23","2026-11-24"]
        r=evaluate(d,p,BASE)["records"][0]
        self.assertEqual(r["programmeEvidence"]["independentObservationDays"],[])
        self.assertEqual(len(r["programmeEvidence"]["reportedBroadcastDays"]),2)

    def test_bad_counts_future_date_wrong_baseline_rejected(self):
        d,p=fixture()
        with self.assertRaises(ValueError):
            evaluate(d,p,"b"*64)
        p["records"][0]["artistTitleHintCounts"]={"target_hint":2}
        with self.assertRaises(ValueError):
            evaluate(d,p,BASE)
        d,p=fixture()
        p["records"][0]["observationDates"]=["2026-11-26"]
        with self.assertRaises(ValueError):
            evaluate(d,p,BASE)
        d,p=fixture()
        p["records"][0]["approved"]=True
        with self.assertRaises(ValueError):
            evaluate(d,p,BASE)

    def test_staging_without_v2_continuity_rejected(self):
        d,p=fixture()
        d["records"][0]["positiveContinuityDays"]=[DAY]
        with self.assertRaises(ValueError):
            evaluate(d,p,BASE)

if __name__=="__main__":
    unittest.main()
