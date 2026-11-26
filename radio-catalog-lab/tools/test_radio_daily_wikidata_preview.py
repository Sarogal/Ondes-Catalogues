import unittest
from radio_daily_wikidata_preview import build,research,validate_entry
from test_radio_daily_artist_research import report,MBID,DAY

def claim(value,rank="normal"):
    return {"rank":rank,"mainsnak":{"snaktype":"value","datavalue":{"value":value}}}
def request(p):
    if p["action"]=="wbsearchentities":
        return {"search":[{"id":"Q123","label":"Iron Band"}]}
    if p["ids"]=="Q123":
        return {"entities":{"Q123":{"id":"Q123","labels":{"en":{"value":"Iron Band"}},
               "claims":{"P31":[claim({"id":"Q215380"})],"P136":[claim({"id":"Q456"}),claim({"id":"Q789"},"deprecated")],
                         "P434":[claim(MBID)]}}}}
    return {"entities":{"Q456":{"id":"Q456","labels":{"en":{"value":"heavy metal"}}}}}
class WikidataTests(unittest.TestCase):
    def test_genre_and_link_provenance(self):
        row=build(report(),limit=1,request=request)["entries"]["iron band"]
        self.assertEqual(row["genresById"],{"Q456":"heavy metal"})
        self.assertEqual(row["musicbrainzIds"],[MBID])
        self.assertFalse(row["identityVerified"])
        validate_entry("iron band",row,DAY)
    def test_homonyms_held(self):
        r=research("Iron Band",lambda p:{"search":[{"id":"Q123","label":"Iron Band"},{"id":"Q124","label":"Iron Band"}]})
        self.assertEqual(r["status"],"ambiguous_or_incomplete")
    def test_incomplete_held(self):
        r=research("Iron Band",lambda p:{"search":[],"search-continue":20})
        self.assertEqual(r["status"],"ambiguous_or_incomplete")
    def test_no_network_default_and_cache(self):
        self.assertEqual(build(report(),request=lambda p:self.fail("network"))["entries"],{})
        prior=build(report(),limit=1,request=request)
        self.assertEqual(build(report("2026-11-26"),prior=prior,limit=1,request=lambda p:self.fail("cached"))["attemptedCount"],0)
    def test_service_failure_preserves_prior(self):
        prior=build(report(),limit=1,request=request)
        def fail(p):
            raise OSError("unavailable")
        out=build(report("2026-12-26"),prior=prior,limit=1,request=fail)
        self.assertEqual(out["entries"],prior["entries"])
        self.assertIsNotNone(out["serviceFailure"])
    def test_unknown_not_outside_genre(self):
        row=build(report(),limit=1,request=lambda p:{"search":[]})["entries"]["iron band"]
        self.assertEqual(row["status"],"not_found")
        self.assertNotIn("genresById",row)
    def test_forged_provenance_held(self):
        prior=build(report(),limit=1,request=request)
        prior["entries"]["iron band"]["sourceUrl"]="https://example.org"
        with self.assertRaises(ValueError):
            build(report(),prior=prior)
    def test_bounded_pagination_reaches_exact_match(self):
        def paged(p):
            if p["action"]=="wbsearchentities" and "continue" not in p:
                return {"search":[{"id":"Q999","label":"Unrelated"}],"search-continue":20}
            return request(p)
        self.assertEqual(research("Iron Band",paged)["qid"],"Q123")
    def test_old_ambiguity_reexamined_after_upgrade(self):
        prior=build(report(),limit=1,request=lambda p:{"search":[],"search-continue":20})
        prior["entries"]["iron band"].pop("researchVersion")
        self.assertEqual(build(report(),prior=prior,limit=1,request=request)["entries"]["iron band"]["qid"],"Q123")
if __name__=="__main__":
    unittest.main()
