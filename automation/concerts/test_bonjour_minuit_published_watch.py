"""Read-only published Bonjour Minuit status/date/lineup tests."""
import copy
import datetime as dt
import unittest

import published_watch as w

MAGMA="https://bonjour-minuit.fr/evenement/magma-02dec26/"
SBRBS="https://bonjour-minuit.fr/evenement/sbrbs-30janv27/"
ARTS={"magma":"Magma","sbrbs":"SBRBS","atoem":"Atoem",
      "sarakiniko":"Sarakiniko","dj-cup-of-tea":"DJ Cup of Tea"}

def published(id_,date,title,url,ids):
    return {"id":id_,"date":date,"title":title,
            "venueId":"bonjour-minuit-saint-brieuc",
            "officialUrl":url,"artistIds":ids,
            "status":"confirmed","time":None,"timeMeaning":"non confirmé"}

M=published("go-c-20261202-saint-brieuc-magma",
            "2026-12-02","Magma",MAGMA,["magma"])
S=published("go-c-20270130-saint-brieuc-sbrbs","2027-01-30",
            "SBRBS + Atoem + Sarakiniko + DJ Cup of Tea",SBRBS,
            ["sbrbs","atoem","sarakiniko","dj-cup-of-tea"])

def html(multi=False,date=None,room="Grande Salle",extra="",remove=None):
    title=("SBRBS release party Atoem Sarakiniko DJ Cup of Tea"
           if multi else "Magma")
    day=date or ("samedi 30 janvier 2027" if multi
                 else "mercredi 02 décembre 2026")
    groups=(["SBRBS release party","Atoem","Sarakiniko","DJ Cup of Tea"]
            if multi else ["Magma"])
    genre=["rock indéSaint-Brieuc","electroRennes","popBretagne","dj setRennes"] if multi else ["rock progressifFRA"]
    parts="".join("<h2>"+n+"</h2><p>"+g+"</p><p>Sa biographie est connue.</p>"
                  for n,g in zip(groups,genre) if n!=remove)
    return ("<main><article><h1>"+title+"</h1><p>"+day+"</p>"
            "<p>"+room+" • 20h30</p>"
            "<p>20h30 : ouverture des portes</p>"
            "<p>Ces horaires sont donnés à titre indicatif.</p>"
            +("<p>"+extra+"</p>" if extra else "")+parts+"</article></main>")

class BonjourMinuitPublishedWatch(unittest.TestCase):
    def test_exact_first_party_event_ids_only(self):
        self.assertEqual(w.source_kind(M),"bonjour")
        self.assertEqual(w.source_kind(S),"bonjour")
        for bad in (
            dict(M,id="go-c-20270130-saint-brieuc-unknown"),
            dict(M,officialUrl="https://bonjour-minuit.fr/agenda/"),
            dict(M,officialUrl=SBRBS),
            dict(M,officialUrl=MAGMA+"?redirect=1"),
            dict(M,venueId="antipode-rennes"),
            dict(M,officialUrl="https://bonjour-minuit.fr.evil.example/evenement/magma-02dec26/"),
        ):
            with self.subTest(bad=bad):
                self.assertIsNone(w.source_kind(bad))

    def test_named_magma_and_four_sbrbs_artists_are_verified_without_clock(self):
        for ev,page in ((M,html()),(S,html(multi=True))):
            with self.subTest(event=ev["id"]):
                x=w.inspect(ev,page,ARTS)
                self.assertEqual(x["status"],"matched")
                self.assertEqual(x["observedDate"],ev["date"])
                self.assertNotIn("observedTime",x)
                self.assertNotIn("publicationAllowed",x)

    def test_real_div_span_event_meta_badge_and_biography_are_separate(self):
        # Actual first-party pages: date and hall are DIV/SPAN, not P.
        text=(
            "<main><h1>Magma</h1>"
            "<div><span>mercredi</span><span>02</span>"
            "<span>décembre</span><span>2026</span></div>"
            "<div>Grande Salle • 20h00</div>"
            "<div>Ces horaires sont donnés à titre indicatif.</div>"
            "<h2>Magma</h2><div><span>rock progressif</span>"
            "<span>FRA</span></div>"
            "<p>Un long portrait du groupe et ses influences.</p>"
            "<footer><p>Cookies : metal punk rock</p></footer></main>"
        )
        r=w.inspect(M,text,ARTS)
        self.assertEqual(r["status"],"matched")
        self.assertEqual(r["observedDate"],"2026-12-02")
        self.assertNotIn("observedTime",r)
        # Promo copy cannot become an official genre after the badge vanishes.
        bad=text.replace("rock progressif","chanson")
        self.assertEqual(w.inspect(M,bad,ARTS)["status"],"unverifiable")
        self.assertEqual(w.inspect(M,text.replace("2026",""),ARTS)["status"],
                         "unverifiable")

    def test_changed_date_room_and_named_support_are_review_only(self):
        d=w.inspect(S,html(multi=True,date="dimanche 31 janvier 2027"),ARTS)
        self.assertEqual(d["status"],"date_review")
        self.assertEqual(d["observedDate"],"2027-01-31")
        room=w.inspect(S,html(multi=True,room="Club"),ARTS)
        self.assertEqual(room["status"],"content_review")
        missing=w.inspect(S,html(multi=True,remove="Atoem"),ARTS)
        self.assertEqual(missing["status"],"lineup_review")
        renamed=w.inspect(M,html().replace("<h1>Magma</h1>","<h1>Another band</h1>"),ARTS)
        self.assertEqual(renamed["status"],"lineup_review")

    def test_cancelled_reported_and_soldout_never_changed_automatically(self):
        for note,expected in (
            ("Concert annulé","cancelled_notice"),
            ("Concert reporté","postponement_notice"),
            ("Concert complet","sold_out_notice"),
        ):
            with self.subTest(note=note):
                x=w.inspect(M,html(extra=note),ARTS)
                self.assertEqual(x["status"],"content_review")
                self.assertEqual(x["observedSourceStatus"],expected)
                self.assertEqual(M["status"],"confirmed")
                self.assertIsNone(M["time"])

    def test_missing_year_or_layout_is_unverifiable_not_an_annulation(self):
        for page in ("<html><p>404 Not Found</p></html>",
                     html(date="mercredi 02 décembre"),
                     html().replace("<h2>Magma</h2>","<h3>Magma</h3>")):
            x=w.inspect(M,page,ARTS)
            self.assertEqual(x["status"],"unverifiable")
            self.assertNotIn("observedSourceStatus",x)

    def test_daily_read_only_run_does_not_mutate_public_catalogue(self):
        fillers=[{"id":"other-"+str(i),"date":"2027-04-03","title":"Other",
                  "venueId":"unknown","officialUrl":"https://other.invalid/event",
                  "artistIds":[],"status":"confirmed"} for i in range(127)]
        cat={"schemaVersion":1,"mode":"preview-public-unlisted",
             "events":fillers+[M,S],"artists":[{"id":id_,"name":name}
                                         for id_,name in ARTS.items()],
             "venues":[{"id":str(i)} for i in range(53)]}
        original=copy.deepcopy(cat)
        pages={MAGMA:html(),SBRBS:html(multi=True)}
        fetched=[]
        def fetch(url):
            fetched.append(url)
            return pages[url],url
        result=w.run(cat,dt.date(2026,11,3),limit=24,
                     fetch=fetch,robots=lambda url,cache:True)
        self.assertEqual(result["checked"],2)
        self.assertEqual(result["eligibleOfficialIndividual"],2)
        self.assertEqual(result["counts"],{"matched":2})
        self.assertEqual(result["needsReview"],[])
        self.assertFalse(result["publicationAllowed"])
        self.assertEqual(set(fetched),{MAGMA,SBRBS})
        self.assertEqual(cat,original)

    def test_robots_or_redirects_are_source_unavailable_never_cancelled(self):
        fillers=[{"id":"other-"+str(i),"date":"2027-04-03","title":"Other",
                  "venueId":"unknown","officialUrl":"https://other.invalid/event",
                  "artistIds":[]} for i in range(127)]
        cat={"schemaVersion":1,"mode":"preview-public-unlisted",
             "events":fillers+[M,S],"artists":[{"id":id_,"name":name}
                                         for id_,name in ARTS.items()],
             "venues":[{"id":str(i)} for i in range(53)]}
        r=w.run(cat,dt.date(2026,11,3),limit=24,
                fetch=lambda url:(html(),"https://bonjour-minuit.fr/agenda/"),
                robots=lambda url,cache:url!=SBRBS)
        self.assertEqual(r["counts"],{"source_unavailable":2})
        self.assertEqual(r["needsReview"],[])
        self.assertFalse(r["publicationAllowed"])

if __name__=="__main__":
    unittest.main()
