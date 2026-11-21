"""Security and non-destructive regression tests for private tour research."""
import copy
from datetime import date
import unittest

import festival_tour_stage_reconciliation as r


def row(cid, source, url, *, name, date_="2027-02-11", city="Toulouse", venue="Le Rex", artist="Aster", lineup=None, bucket="tour_source_research", stable=1):
    candidate = dict(candidateId=cid, source=source, sourceUrl=url,
                     name=name, date=date_, city=city, venue=venue,
                     leadArtist=artist, reviewBucket=bucket,
                     reviewRequired=True, publicationAllowed=False)
    if source == "festival_published_tour_research":
        candidate.update(festivalCatalogueHintsOnly=True,
                         requiresArtistAndVenueReproof=True,
                         festivalReferenceSlug="fake-fest-2027-toulouse",
                         artistNamesFromFestivalOnly=lineup or ["Aster", "Volta"])
    if source == "festival_to_concerts_handoff":
        candidate.update(requiresArtistAndVenueReproof=True)
    return {"candidateId":cid, "candidate":candidate,
            "status":"pending_review", "stableObservations":stable}


class StageReconcileTest(unittest.TestCase):
    def setUp(self):
        self.a=row("arc", "festival_published_tour_research", "https://show.example.org/",
                   name="Shining Fest 2027 — Toulouse", venue="Le Rex, 15 rue du Midi",
                   lineup=["Aster", "Volta"])
        self.b=row("venue", "agenda_officiel", "https://the-venue.example.org/show",
                   name="Shining Fest : Aster & Volta", artist="Shining Fest: Aster & Volta",
                   bucket="festival_overlap_review",stable=13)
        self.c=row("city", "festival_to_concerts_handoff", "https://mairie.example.org/agenda/shining",
                   name="Shining Fest 2027", city=None, venue=None, artist=None)
        self.d={"schema":r.REGISTRY_SCHEMA,"items":{x["candidateId"]:x for x in (self.a,self.b,self.c)}}

    def test_tour_venue_and_missing_place_municipal_independent_leads(self):
        before=copy.deepcopy(self.d)
        result=r.build(self.d,date(2026,11,21))
        self.assertEqual(result["linkedArchiveStages"],1)
        self.assertEqual({x["candidateId"] for x in result["matches"][0]["possibleSameShowLeads"]},{"venue","city"})
        self.assertFalse(result["canRemoveFestival"])
        self.assertFalse(result["publicationAllowed"])
        self.assertFalse(result["matches"][0]["archiveStableOnDistinctDays"])
        self.assertEqual(self.d,before)

    def test_same_city_date_different_venue_never_matched(self):
        self.b["candidate"]["venue"]="Le Rex Club"
        result=r.build(self.d,date(2026,11,21))
        self.assertEqual([x["candidateId"] for x in result["matches"][0]["possibleSameShowLeads"]],["city"])

    def test_one_band_shared_is_not_enough_for_multi_act_tour(self):
        self.b["candidate"]["name"]="Aster with the Electronic Kids"
        self.b["candidate"]["leadArtist"]="Aster"
        self.assertEqual([x["candidateId"] for x in r.build(self.d,date(2026,11,21))["matches"][0]["possibleSameShowLeads"]],["city"])

    def test_different_day_or_city_never_matches_venue(self):
        self.b["candidate"]["date"]="2027-02-12"
        self.c["candidate"]["name"]="A completely unrelated event"
        self.assertEqual(r.build(self.d,date(2026,11,21))["matches"],[])

    def test_arbitrary_larger_lineup_not_bounded_by_four(self):
        names=[f"Band {i}" for i in range(1,26)]
        self.a["candidate"]["artistNamesFromFestivalOnly"]=names
        self.b["candidate"]["name"]="Bill: Band 1 + Band 7"
        self.b["candidate"]["leadArtist"]="Band 1"
        out=r.build(self.d,date(2026,11,21))
        self.assertIn("venue", [x["candidateId"] for x in out["matches"][0]["possibleSameShowLeads"]])

    def test_unapproved_and_malicious_rows_cannot_join(self):
        self.b["candidate"]["publicationAllowed"]=True
        self.c["candidate"]["sourceUrl"]="http://mairie.example.org/fake"
        self.assertEqual(r.build(self.d,date(2026,11,21))["matches"],[])

    def test_absent_artist_cannot_qualify_festival_overlap(self):
        self.b["candidate"]["name"]="Shining Fest: Jazz ensemble"
        self.b["candidate"]["leadArtist"]="Jazz ensemble"
        self.assertEqual([x["candidateId"] for x in r.build(self.d,date(2026,11,21))["matches"][0]["possibleSameShowLeads"]],["city"])

    def test_title_only_multiple_same_day_ambiguous(self):
        extra=copy.deepcopy(self.a)
        extra["candidateId"]="arc2"
        extra["candidate"]["candidateId"]="arc2"
        extra["candidate"]["festivalReferenceSlug"]="another-fest-2027"
        self.d["items"]["arc2"]=extra
        out=r.build(self.d,date(2026,11,21))
        self.assertTrue(all(not any(x["candidateId"]=="city" for x in m["possibleSameShowLeads"])
                            for m in out["matches"]))

    def test_no_silent_cutoff_after_thirty_municipal_hints(self):
        for n in range(40):
            lead=copy.deepcopy(self.c)
            lead["candidateId"]=f"municipality-{n}"
            lead["candidate"]["candidateId"]=lead["candidateId"]
            lead["candidate"]["sourceUrl"]=f"https://mairie{n}.example.org/event"
            self.d["items"][lead["candidateId"]]=lead
        out=r.build(self.d,date(2026,11,21))
        self.assertEqual(len(out["matches"][0]["possibleSameShowLeads"]),42)
        self.assertFalse(out["publicationAllowed"])

    def test_expired_records_disappear_and_invalid_schema_refused(self):
        self.assertEqual(r.build(self.d,date(2028,1,1))["matches"],[])
        self.d["schema"]="untrusted"
        with self.assertRaises(ValueError):
            r.build(self.d,date(2026,11,21))

    def test_suspicious_host_identity_cannot_be_joined(self):
        self.b["candidate"]["sourceUrl"]="https://127.0.0.1/events"
        out=r.build(self.d,date(2026,11,21))
        self.assertEqual([x["candidateId"] for x in out["matches"][0]["possibleSameShowLeads"]],["city"])


if __name__ == "__main__":
    unittest.main()
