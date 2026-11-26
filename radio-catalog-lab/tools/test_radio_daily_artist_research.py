import unittest
import uuid
from radio_daily_artist_research import search_pages
from radio_daily_artist_research import build, research
from radio_daily_qualification_dossiers import safe_digest

UID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MBID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
DAY = "2026-11-25"

def report(day=DAY, names=("Iron Band",)):
    return {"schemaVersion":1, "scanDate":day, "publicationAllowed":False,
            "approvedCount":0, "records":[{"stationuuid":UID, "streamSha256":safe_digest("stream"),
            "observedDate":day, "publicationAllowed":False, "approved":False,
            "observations":[{"date":day,"artistHint":n,"titleSha256":safe_digest("song")} for n in names]}]}

def service(path, params):
    if not path:
        return {"count":1,"artists":[{"id":MBID,"name":"Iron Band"}]}
    return {"id":MBID,"name":"Iron Band","genres":[{"name":"heavy metal","count":2},{"name":"pop","count":1}]}

class ArtistResearchTests(unittest.TestCase):
    def test_exact_hypothesis_and_all_genres(self):
        row = build(report(), limit=1, request=service)["entries"]["iron band"]
        self.assertEqual(row["mbid"],MBID)
        self.assertEqual(row["genres"],["heavy metal","pop"])
        self.assertFalse(row["identityVerified"])
        self.assertFalse(row["publicationAllowed"])
        self.assertEqual(row["sourceUrl"],"https://musicbrainz.org/artist/"+MBID)

    def test_homonyms_held(self):
        result = research("Iron Band",lambda *a:{"count":2,"artists":[
            {"id":MBID,"name":"Iron Band"},{"id":UID,"name":"Iron Band"}]})
        self.assertEqual(result,{"status":"ambiguous_or_incomplete"})

    def test_incomplete_results_held(self):
        self.assertEqual(research("Iron Band",lambda *a:{"count":50,"artists":[{"id":MBID,"name":"Iron Band"}]})["status"],"ambiguous_or_incomplete")

    def test_paginated_exact_artist_with_punctuation(self):
        rows = [{"id": str(uuid.UUID(int=i+1)), "name": "Other Artist"}
                for i in range(25)] + [{"id": MBID, "name": "AC/DC"}]
        offsets = []
        def paged(path, params):
            if path:
                return {"id": MBID, "name": "AC/DC", "genres": []}
            self.assertEqual(params["query"], 'artist:"AC/DC"')
            off = params.get("offset", 0)
            offsets.append(off)
            return {"count": len(rows), "offset": off, "artists": rows[off:off+25]}
        self.assertEqual(research("AC/DC", paged)["mbid"], MBID)
        self.assertEqual(offsets, [0, 25])
        rows[0]["name"] = "AC/DC"
        self.assertEqual(research("AC/DC", paged)["status"], "ambiguous_or_incomplete")

    def test_pagination_bounds_and_moving_results(self):
        def row(i):
            return {"id": str(uuid.UUID(int=i+1))}
        calls = []
        def over_budget(p):
            calls.append(p)
            return {"count": 101, "artists": [row(i) for i in range(25)]}
        self.assertIsNone(search_pages(over_budget, "x", "artists", 25))
        self.assertEqual(len(calls), 1)
        def moving(p):
            off = p.get("offset", 0)
            return {"count": 26 if not off else 27,
                    "artists": [row(i) for i in range(off, 25 if not off else 27)]}
        self.assertIsNone(search_pages(moving, "x", "artists", 25))

    def test_repeated_page_id_held(self):
        def repeated(p):
            off = p.get("offset", 0)
            return {"count": 26, "artists": [{"id": str(uuid.UUID(int=i+1))}
                       for i in range(25 if not off else 1)]}
        self.assertIsNone(search_pages(repeated, "x", "artists", 25))

    def test_unknown_is_not_nonmetal(self):
        row = build(report(),limit=1,request=lambda *a:{"count":0,"artists":[]})["entries"]["iron band"]
        self.assertEqual(row["status"],"not_found")
        self.assertNotIn("genres",row)

    def test_cache_and_retry(self):
        prior=build(report(),limit=1,request=service)
        cached=build(report("2026-11-26"),prior=prior,limit=1,request=lambda *a:self.fail("cached"))
        self.assertEqual(cached["attemptedCount"],0)
        def fail(*args):
            raise OSError("network")
        retry=build(report("2026-12-26"),prior=prior,limit=1,request=fail)
        self.assertEqual(retry["entries"],prior["entries"])
        self.assertIsNotNone(retry["serviceFailure"])

    def test_no_network_default(self):
        self.assertEqual(build(report(),request=lambda *a:self.fail("network"))["entries"],{})

    def test_unknown_researched_again(self):
        prior=build(report(),limit=1,request=lambda *a:{"count":0,"artists":[]})
        result=build(report("2026-12-02"),prior=prior,limit=1,request=service)
        self.assertEqual(result["entries"]["iron band"]["status"],"name_hypothesis")

    def test_untrusted_prior_and_future_observation(self):
        prior=build(report(),limit=1,request=service)
        prior["entries"]["iron band"]["identityVerified"]=True
        with self.assertRaises(ValueError):
            build(report(),prior=prior)
        bad=report()
        bad["records"][0]["observations"][0]["date"]="2026-11-26"
        with self.assertRaises(ValueError):
            build(bad)

    def test_spelling_collision_held(self):
        result=build(report(names=("Iron Band","IRON BAND")),limit=1,
                     request=lambda *a:self.fail("ambiguous spelling"))
        self.assertEqual(result["attemptedCount"],0)

if __name__ == "__main__":
    unittest.main()
