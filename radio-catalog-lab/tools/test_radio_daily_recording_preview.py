import io
import json
import unittest
import uuid
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
        r=resolve("Iron Band","Song",lambda p:{"count":2,"recordings":[recording(),dict(recording(UID),id=UID)]})
        self.assertEqual(r["status"],"ambiguous_credit")
    def test_truncated_or_wrong_title_held(self):
        self.assertEqual(resolve("Iron Band","Song",lambda p:{"count":51,"recordings":[recording()]})["status"],"incomplete_search")
        self.assertEqual(resolve("Iron Band","Song",lambda p:{"count":1,"recordings":[recording(title="Other")]})["status"],"no_exact_credit")
    def test_paginated_recording_credit_and_late_conflict(self):
        rows = [dict(recording(title="Other"), id=str(uuid.UUID(int=i+1)))
                for i in range(50)] + [recording()]
        offsets = []
        def paged(params):
            off = params.get("offset", 0)
            offsets.append(off)
            return {"count": len(rows), "offset": off, "recordings": rows[off:off+50]}
        self.assertEqual(resolve("Iron Band", "Song", paged)["artistMbids"], [MBID])
        self.assertEqual(offsets, [0, 50])
        rows[0] = dict(recording(UID), id=str(uuid.UUID(int=1)))
        self.assertEqual(resolve("Iron Band", "Song", paged)["status"], "ambiguous_credit")

    def test_many_recordings_same_exact_credit(self):
        rows = [dict(recording(), id=str(uuid.UUID(int=i+1))) for i in range(51)]
        def paged(params):
            off = params.get("offset", 0)
            return {"count": len(rows), "offset": off, "recordings": rows[off:off+50]}
        result = resolve("Iron Band", "Song", paged)
        self.assertEqual(result["artistMbids"], [MBID])
        self.assertEqual(len(result["recordingMbids"]), 51)

    def test_direct_credit_genres_and_exact_id(self):
        m,r,t=fixture()
        def artist(mid, params):
            self.assertEqual(mid, MBID)
            self.assertEqual(params, {"inc":"genres"})
            return {"id":mid,"name":"Canonical Artist","genres":[{"name":"hard rock","count":3}]}
        out=build(m,r,t,limit=1,request=request,artist_request=artist)
        e=next(iter(out["entries"].values()))
        self.assertEqual(e["creditGenreEvidence"]["genres"],["hard rock"])
        self.assertEqual(e["creditGenreEvidence"]["mbid"],MBID)
        self.assertEqual(out["genreLookupAttemptedCount"],1)
        self.assertFalse(e["identityVerified"])
        bad=build(m,r,t,limit=1,request=request,artist_request=lambda *a:{"id":UID,"name":"Other"})
        self.assertEqual(next(iter(bad["entries"].values()))["status"],"recording_credit_hypothesis")
        self.assertEqual(bad["creditGenreEvidenceCount"],0)
        self.assertIsNotNone(bad["serviceFailure"])

    def test_genre_failure_keeps_recording_credit(self):
        m,r,t=fixture()
        def fail(*a):
            raise OSError("network")
        out=build(m,r,t,limit=1,request=request,artist_request=fail)
        self.assertEqual(out["creditGenreEvidenceCount"],0)
        self.assertEqual(next(iter(out["entries"].values()))["artistMbids"],[MBID])
        self.assertIsNotNone(out["serviceFailure"])

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
