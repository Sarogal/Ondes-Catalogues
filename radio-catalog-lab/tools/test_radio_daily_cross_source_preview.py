import unittest
from radio_daily_programme_preview import build
from radio_daily_artist_research import build as music
from radio_daily_wikidata_preview import build as wiki
from radio_daily_qualification_dossiers import safe_digest
from test_radio_daily_artist_research import report,service,MBID,UID,DAY
from test_radio_daily_wikidata_preview import request
from test_radio_daily_programme_preview import decisions
from test_radio_daily_recording_preview import fixture,request as recording_request
from radio_daily_recording_preview import build as recording

class CrossSourceTests(unittest.TestCase):
    def test_wikidata_fallback(self):
        m=report()
        r=music(m)
        w=wiki(m,limit=1,request=request)
        row=build(m,r,decisions(m),wikidata=w)["records"][0]
        self.assertEqual(row["artistHintCounts"]["target_hint"],1)
        self.assertEqual(row["sourceHintCounts"],{"wikidata_only":1})
        self.assertFalse(row["approved"])
    def test_linked_identity(self):
        m=report()
        w=wiki(m,limit=1,request=request)
        row=build(m,music(m,limit=1,request=service),decisions(m),wikidata=w)["records"][0]
        self.assertEqual(row["sourceHintCounts"],{"linked_sources":1})
        self.assertEqual(row["artistHintCounts"]["mixed_hint"],1)
    def test_conflict_and_unlinked(self):
        m=report()
        r=music(m,limit=1,request=service)
        w=wiki(m,limit=1,request=request)
        for links,reason in (([UID],"identity_conflict"),([],"cross_source_identity_unlinked")):
            w["entries"]["iron band"]["musicbrainzIds"]=links
            row=build(m,r,decisions(m),wikidata=w)["records"][0]
            self.assertEqual(row["sourceHintCounts"],{reason:1})
            self.assertEqual(row["artistHintCounts"]["unclassified_hint"],1)
    def test_genre_conflict(self):
        m=report()
        r=music(m,limit=1,request=service)
        r["entries"]["iron band"]["genres"]=["pop"]
        w=wiki(m,limit=1,request=request)
        row=build(m,r,decisions(m),wikidata=w)["records"][0]
        self.assertEqual(row["sourceHintCounts"],{"genre_conflict":1})
    def test_recording_link_and_conflict(self):
        m,r,t=fixture()
        cr=recording(m,r,t,limit=1,request=recording_request)
        w=wiki(m,limit=1,request=request)
        row=build(m,music(m),decisions(m),wikidata=w,recordings=cr)["records"][0]
        self.assertEqual(row["sourceHintCounts"],{"recording_wikidata":1})
        next(iter(cr["entries"].values()))["artistMbids"]=[UID]
        row=build(m,music(m),decisions(m),wikidata=w,recordings=cr)["records"][0]
        self.assertEqual(row["sourceHintCounts"],{"identity_conflict":1})
    def test_stale_wikidata_and_bad_provenance(self):
        m=report()
        w=wiki(m,limit=1,request=request)
        w["entries"]["iron band"]["checkedAt"]="2026-10-20"
        row=build(m,music(m),decisions(m),wikidata=w)["records"][0]
        self.assertEqual(row["artistHintCounts"]["unclassified_hint"],1)
        w["entries"]["iron band"]["sourceUrl"]="https://example.org"
        with self.assertRaises(ValueError):
            build(m,music(m),decisions(m),wikidata=w)
if __name__=="__main__":
    unittest.main()
