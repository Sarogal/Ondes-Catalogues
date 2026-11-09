"""Offline safety suite for Atabal known-artist official-detail pilot."""
import copy
import datetime as dt
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import atabal_recheck as a
import official_recheck as official

NOW = dt.date(2026, 11, 6)
PAGE = """<html><head><script>festival=1</script></head><body>
<article><section><p>08 avril 2027 19H30</p>
<h1>PETER HOOK &amp; THE LIGHT</h1><h2>A Joy Division Celebration</h2>
</section><h2>PETER HOOK &amp; THE LIGHT</h2>
<h3>A Joy Division Celebration</h3><p>Joy Division et New Order</p>
<h5>POST PUNK</h5><h4>Vous devriez aimer:</h4>
<h3>SLIFT</h3><h5>Metal</h5></article>
</body></html>"""


def candidate():
    return {
        "candidateId": "atabal:2027-04-08:peter-hook-the-light-a-joy-division-celebration-jeudi-08-avril-2027",
        "source": "agenda_officiel_atabal_detail",
        "sourceUrl": a.URL,
        "name": a.ARTIST,
        "date": a.DATE,
        "venue": "Atabal",
        "venueCatalogueId": a.VENUE,
        "city": "Biarritz",
        "classification": ["Post Punk"],
        "reviewBucket": "genre_tag_review",
        "possibleExistingConcert": False,
        "officialDetailFound": True,
        "reviewRequired": True,
        "publicationAllowed": False
    }


def catalogue():
    return {
        "schemaVersion": 1, "mode": "preview-public-unlisted",
        "venues": [{"id":a.VENUE,"name":"Atabal","city":"Biarritz"}],
        "artists": [{"id":a.ARTIST_ID,"name":"Peter Hook and The Light"}],
        "events": []
    }


class AtabalRecheckTests(unittest.TestCase):
    def test_known_artist_first_party_event_only(self):
        approval = official.verify(candidate(),PAGE,catalogue(),NOW)
        self.assertEqual(approval["event"]["id"],a.EVENT_ID)
        self.assertEqual(approval["event"]["artistIds"],[a.ARTIST_ID])
        self.assertEqual(approval["event"]["title"],a.ARTIST)
        self.assertEqual(approval["event"]["genres"],["Post Punk"])
        self.assertIsNone(approval["event"]["time"])
        self.assertEqual(approval["newArtists"],[])
        self.assertEqual(approval["officialEvidence"][0]["officialArtistNames"],[a.ARTIST])

    def test_no_duplicate_or_missing_artist(self):
        cat=catalogue()
        cat["artists"]=[]
        with self.assertRaisesRegex(ValueError,"Identité"):
            official.verify(candidate(),PAGE,cat,NOW)
        cat=catalogue()
        cat["events"]=[{"id":"known","date":a.DATE,
                        "venueId":a.VENUE,"artistIds":[a.ARTIST_ID]}]
        with self.assertRaisesRegex(ValueError,"déjà"):
            official.verify(candidate(),PAGE,cat,NOW)

    def test_date_genre_venue_and_support_must_be_unchanged(self):
        variants=[
            (PAGE.replace("08 avril 2027","09 avril 2027"),"Date"),
            (PAGE.replace("POST PUNK","REGGAE"),"Genre"),
            (PAGE.replace("<h5>POST PUNK</h5>",""),"Genre"),
            (PAGE.replace("PETER HOOK &amp; THE LIGHT</h1>","PETER HOOK</h1>"),"Titre"),
            (PAGE.replace("</h5><h4>","</h5><p>Première partie : OTHER ACT</p><h4>"),"modifiée"),
            (PAGE.replace("</h5><h4>","</h5><p>Concert annulé</p><h4>"),"annulee"),
            (PAGE.replace("</h5><h4>","</h5><p>Festival</p><h4>"),"festival"),
        ]
        for raw, reason in variants:
            with self.subTest(reason=reason),self.assertRaisesRegex(ValueError,reason):
                official.verify(candidate(),raw,catalogue(),NOW)

    def test_not_faked_by_js_recommendations_or_bio_date(self):
        bad=PAGE.replace("08 avril 2027 19H30","Tarif 19H30").replace(
            "<h3>SLIFT</h3>","<p>08 avril 2027</p><h3>SLIFT</h3>")
        with self.assertRaisesRegex(ValueError,"Date"):
            official.verify(candidate(),bad,catalogue(),NOW)
        bad=PAGE.replace("<h5>POST PUNK</h5>","<p>POST PUNK</p>").replace(
            "<h3>SLIFT</h3>","<h5>POST PUNK</h5><h3>SLIFT</h3>")
        with self.assertRaisesRegex(ValueError,"Genre"):
            official.verify(candidate(),bad,catalogue(),NOW)

    def test_untrusted_candidates_fail_closed(self):
        variants=[
            {"source":"third_party_calendar"},
            {"sourceUrl":a.URL+"?auth=1"},
            {"date":"2027-04-09"},
            {"venue":"Elsewhere"},
            {"city":"Paris"},
            {"venueCatalogueId":"other"},
            {"classification":["Reggae"]},
            {"reviewBucket":"possible_duplicate"},
            {"possibleExistingConcert":True},
            {"officialDetailFound":False},
            {"reviewRequired":False},
            {"publicationAllowed":True}
        ]
        for change in variants:
            c=candidate(); c.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                official.verify(c,PAGE,catalogue(),NOW)

    def test_outside_pilot_artist_stays_in_private_review(self):
        c=candidate()
        c["name"]="ADELE CASTILLON"
        with self.assertRaisesRegex(ValueError,"pilote"):
            official.verify(c,PAGE,catalogue(),NOW)

    def test_two_observations_one_approval_and_no_repeat_fetch(self):
        queue={"schema":"grossesondes.concert.approvals.v1","approvals":[]}
        reg={"items":{"atabal":{"candidate":candidate(),"observations":2,
                                 "stableObservations":2}}}
        cat=catalogue()
        saved=copy.deepcopy(cat)
        reviewed,report=official.process(reg,cat,queue,NOW,
                                         fetch=lambda url,cache:PAGE)
        self.assertEqual(report["newApprovals"],[a.EVENT_ID])
        self.assertEqual(cat,saved)
        self.assertEqual(queue["approvals"],[])
        next_review,report2=official.process(
            reg,cat,reviewed,NOW,
            fetch=lambda url,cache:(_ for _ in ()).throw(
                AssertionError("repeated download")))
        self.assertEqual(len(next_review["approvals"]),1)
        self.assertEqual(report2["evaluated"],0)
        self.assertEqual(report2["alreadyApprovedSkipped"],1)

    def test_single_observation_is_never_approved(self):
        reg={"items":{"atabal":{"candidate":candidate(),"observations":1}}}
        queue={"schema":"grossesondes.concert.approvals.v1","approvals":[]}
        reviewed,report=official.process(reg,catalogue(),queue,NOW,
                                         fetch=lambda url,cache:PAGE)
        self.assertEqual(report["evaluated"],0)
        self.assertEqual(reviewed,queue)


if __name__=="__main__":
    unittest.main()
