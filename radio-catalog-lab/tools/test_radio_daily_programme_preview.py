import unittest
from radio_daily_programme_preview import build, label_bucket
from radio_daily_artist_research import build as research
from radio_daily_metadata_preview import select_queue
from radio_daily_continuity_preview import read_icy_titles
from test_radio_daily_metadata_preview import block
from test_radio_daily_artist_research import report, service, DAY, UID
from radio_daily_qualification_dossiers import safe_digest
import io

def decisions(meta):
    return {"schemaVersion":1,"scanDate":meta["scanDate"],"publicationAllowed":False,"approvedCount":0,
            "records":[{"stationuuid":UID,"streamSha256":meta["records"][0]["streamSha256"],
                        "approved":False,"publicationAllowed":False}]}

class ProgrammeTests(unittest.TestCase):
    def test_mixed_and_unknown(self):
        m=report(names=("Iron Band","Unknown"))
        r=research(m,limit=1,request=service)
        row=build(m,r,decisions(m))["records"][0]
        self.assertEqual(row["artistHintCounts"]["mixed_hint"],1)
        self.assertEqual(row["artistHintCounts"]["unclassified_hint"],1)
        self.assertEqual(row["verifiedArtistCount"],0)
        self.assertFalse(row["approved"])

    def test_genre_labels_not_substring_or_exclusion(self):
        self.assertEqual(label_bucket(["heavy metal"]), "target_hint")
        self.assertEqual(label_bucket(["pop"]), "other_hint")
        self.assertEqual(label_bucket(["pop punk"]), "target_hint")
        self.assertEqual(label_bucket(["rock"]), "unclassified_hint")
        self.assertEqual(label_bucket(["hardcore techno"]), "unclassified_hint")

    def test_repetition_not_distinct_track(self):
        m=report()
        obs=m["records"][0]["observations"]
        obs.extend([dict(obs[0]),dict(obs[0],date="2026-11-24")])
        row=build(m,research(m,limit=1,request=service),decisions(m))["records"][0]
        self.assertEqual(row["distinctArtistTitleHints"],1)
        self.assertEqual(len(row["observationDates"]),2)

    def test_stream_change_and_stale(self):
        m=report()
        r=research(m,limit=1,request=service)
        d=decisions(m)
        d["records"][0]["streamSha256"]=safe_digest("new")
        row=build(m,r,d)["records"][0]
        self.assertFalse(row["matchesDecisionStream"])
        self.assertEqual(row["artistHintCounts"]["unclassified_hint"],1)
        m["records"][0]["observations"][0]["date"]="2026-10-20"
        row=build(m,r,decisions(m))["records"][0]
        self.assertEqual(row["distinctArtistTitleHints"],0)
        self.assertEqual(row["stalePairCount"],1)

    def test_forged_source_rejected(self):
        m=report()
        r=research(m,limit=1,request=service)
        r["entries"]["iron band"]["sourceUrl"]="https://example.org"
        with self.assertRaises(ValueError):
            build(m,r,decisions(m))

    def test_rotation_reserves_revisits(self):
        q=[(True,False,str(i),"url","sha") for i in range(8)]
        q += [(False,True,"advanced","url","sha"),(True,True,"old","url","sha")]
        old={"advanced":{"observedDate":"2026-11-24"},"old":{"observedDate":"2026-11-23"}}
        picked={x[2] for x in select_queue(q,old,3)}
        self.assertEqual(picked,{"advanced","old","0"})

    def test_ampersand_is_not_url(self):
        result=read_icy_titles(io.BytesIO(block("StreamTitle='Nick Cave & The Bad Seeds - Song';")),"4",10,lambda:0)
        self.assertEqual(result["titleHints"][0]["artistHint"],"Nick Cave & The Bad Seeds")

if __name__=="__main__":
    unittest.main()
