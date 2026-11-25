import io
import json
import unittest
from radio_daily_recording_preview import resolve,build
from radio_daily_metadata_preview import collect
from radio_daily_continuity_preview import read_icy_titles
from radio_daily_qualification_dossiers import safe_digest
from test_radio_daily_metadata_preview import block,reports
from test_radio_daily_artist_research import report,UID,MBID,DAY

RID="cccccccc-cccc-4ccc-8ccc-cccccccccccc"
def recording(mid=MBID,title="Song",name="Iron Band"):
    return {"id":RID,"title":title,"artist-credit":[{"name":name,"artist":{"id":mid}}]}
def request(*args):
    return {"count":1,"recordings":[recording()]}
def fixture():
    m=report()
    row=m["records"][0]
    t={"stationuuid":UID,"streamSha256":row["streamSha256"],"artistHint":"Iron Band",
       "titleHint":"song","titleSha256":safe_digest("song")}
    r={"schemaVersion":1,"scanDate":DAY,"publicationAllowed":False,"approvedCount":0}
    return m,r,[t]

class RecordingTests(unittest.TestCase):
    def test_exact_credit_and_title(self):
        r=resolve("Iron Band","song",request)
        self.assertEqual(r["artistMbids"],[MBID])
        self.assertEqual(r["recordingMbids"],[RID])
    def test_homonyms_same_song_held(self):
        r=resolve("Iron Band","Song",lambda p:{"count":2,"recordings":[recording(),recording(UID)]})
        self.assertEqual(r["status"],"ambiguous_credit")
    def test_truncated_or_wrong_title_held(self):
        self.assertEqual(resolve("Iron Band","Song",lambda p:{"count":51,"recordings":[recording()]})["status"],"incomplete_search")
        self.assertEqual(resolve("Iron Band","Song",lambda p:{"count":1,"recordings":[recording(title="Other")]})["status"],"no_exact_credit")
    def test_no_title_persisted(self):
        m,r,t=fixture()
        out=build(m,r,t,limit=1,request=request)
        self.assertEqual(out["attemptedCount"],1)
        self.assertNotIn('"song"',json.dumps(out))
        self.assertFalse(next(iter(out["entries"].values()))["identityVerified"])
    def test_service_failure_or_unbound_pair(self):
        m,r,t=fixture()
        r["serviceFailure"]="http_503"
        self.assertEqual(build(m,r,t,limit=1,request=lambda p:self.fail("service held"))["attemptedCount"],0)
        r["serviceFailure"]=None
        t[0]["streamSha256"]=safe_digest("different")
        self.assertEqual(build(m,r,t,limit=1,request=lambda p:self.fail("unbound"))["attemptedCount"],0)
    def test_transient_opt_in(self):
        data=block("StreamTitle='Iron Band - Song';")
        h=read_icy_titles(io.BytesIO(data),"4",10,lambda:0)
        self.assertNotIn("titleHint",h["titleHints"][0])
        h=read_icy_titles(io.BytesIO(data),"4",10,lambda:0,include_title=True)
        transient=[]
        m=collect(*reports(),limit=1,observe=lambda u:h,transient_titles=transient)
        self.assertEqual(transient[0]["titleHint"],"Song")
        self.assertNotIn("titleHint",m["records"][0]["observations"][0])
    def test_collaboration_exact_credit(self):
        row=recording()
        row["artist-credit"][0]["joinphrase"]=", "
        row["artist-credit"].append({"name":"Other Band","artist":{"id":UID}})
        r=resolve("Iron Band, Other Band","Song",lambda p:{"count":1,"recordings":[row]})
        self.assertEqual(r["artistMbids"],[MBID,UID])

if __name__=="__main__":
    unittest.main()
