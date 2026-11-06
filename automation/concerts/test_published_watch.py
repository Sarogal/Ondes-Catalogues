"""No-network, fail-closed tests for the public concert watch (no writes)."""
import datetime as dt
import unittest

import published_watch as w

TODAY=dt.date(2026,11,2)

REX_HTML="""<!doctype html><html>
 <p>ven 6 novembre 2026 - 20h30</p>
 <h2>The Browning &amp; Within Destruction</h2>
 <p>Metalcore, Deathcore</p>
 <p>15 avenue Honoré Serres - 31000 Toulouse</p>
 </html>"""
FERRAILLEUR_HTML="""<html>
  <p>vendredi 13 novembre 2026</p>
  <div>Storm Orchestra</div><div>Metal</div>
  <div>Shimmeric</div><div>Rock</div>
  <div>Réservation</div><div>Horaires début</div><div>20:30</div>
 </html>"""
BRIN_HTML="""<html><head><title>Tickets : FVZZ POPVLI (Stoner Rock)</title>
<script>Mon Nov 10, 2026</script></head><body>
<p>Mon Nov 09, 2026 from 08:30 PM to 12:00 AM</p>
<p>Le Brin de Zinc, Route de la Peysse, Barberaz, France</p>
<p>Organizer: Le Brin de Zinc</p></body></html>"""


def event(id, date, title, venue, url, artists, time=None, timeMeaning=None):
    return {"id":id,"date":date,"title":title,"venueId":venue,
            "officialUrl":url,"artistIds":artists,
            "time":time,"timeMeaning":timeMeaning,
            "status":"confirmed"}

R=event("rex-event","2026-11-06","The Browning + Within Destruction",
        "le-rex-toulouse",
        "https://www.lerextoulouse.com/fr/programmation/the-browning/",
        ["the-browning","within-destruction"])
F=event("ferrailleur-event","2026-11-13","Storm Orchestra + Shimmeric",
        "le-ferrailleur-nantes",
        "https://www.leferrailleur.fr/evenement/storm-orchestra/5194",
        ["storm-orchestra","shimmeric"],"20:30","début du concert")
B=event("brin-event","2026-11-09","Fvzz Popvli",
        "le-brin-de-zinc-barberaz",
        "https://www.billetweb.fr/fvzz-popvli-heavy-psych-garage-punk-stoner-rock-italie",
        ["fvzz-popvli"])
OTHER=event("other","2026-11-20","Mystery Band",
        "le-chabada-angers","https://some-blog.example/news/test",
        ["mystery"])

ARTISTS={"the-browning":"The Browning","within-destruction":"Within Destruction",
         "storm-orchestra":"Storm Orchestra","shimmeric":"Shimmeric",
         "fvzz-popvli":"Fvzz Popvli"}
CATALOGUE={"schemaVersion":1,"mode":"preview-public-unlisted",
           "events":[R,F,B,OTHER]+[
               event("example-%03d"%i,"2026-11-20","Unknown",
                     "venue-unchecked","https://example.org/agenda",
                     ["mystery"]) for i in range(123)],
           "artists":[{"id":k,"name":v} for k,v in ARTISTS.items()],
           "venues":[{"id":str(i)} for i in range(53)]}


class PublishedWatchTests(unittest.TestCase):
    @staticmethod
    def gwendoline_event():
        return event("go-c-20261107-cenon-gwendoline","2026-11-07",
            "Gwendoline","le-rocher-de-palmer-cenon",
            "https://lerocherdepalmer.fr/agenda/gwendoline",
            ["gwendoline"],"20:30","début du concert")

    @staticmethod
    def gwendoline_page(support="+ BLEU PANIQUE",day=7,time="20:30"):
        return (
            '<html><body><script>Fake + OTHER ARTIST</script>'
            '<article class="node node--type-evenement view--full">'
            '<h1>Musiques de Nuit présente GWENDOLINE</h1>'
            + (f'<p>{support}</p>' if support else '')
            + f'<span class="evt-date" data-day="{day}" '
              'data-month="Novembre" data-year="2026"></span>'
              '<span class="lb_session--evt-location-location">'
              'Le Rocher de Palmer</span>'
            + f'<p>OUVERTURE DES PORTES : 19:30 / '
              f'DÉBUT DU CONCERT : {time}</p>'
              '</article><article><h1>Another gig</h1>'
              '<p>+ UNRELATED RECOMMENDATION</p></article></body></html>'
        )

    def test_rocher_exact_gwendoline_url_is_checked_not_arbitrary_pages(self):
        item=self.gwendoline_event()
        self.assertEqual(w.source_kind(item),"rocher")
        for mutant in (
                dict(item,officialUrl="https://lerocherdepalmer.fr/agenda/stranglers"),
                dict(item,officialUrl=item["officialUrl"]+"?token=secret"),
                dict(item,officialUrl=item["officialUrl"].replace(
                    "lerocherdepalmer.fr","attacker.example")),
                dict(item,id="different-concert")):
            self.assertIsNone(w.source_kind(mutant))

    def test_gwendoline_new_named_support_is_review_only(self):
        item=self.gwendoline_event()
        result=w.inspect(item,self.gwendoline_page(),
                         dict(ARTISTS,gwendoline="Gwendoline"))
        self.assertEqual(result["status"],"lineup_review")
        self.assertEqual(result["observedArtists"],
                         ["Gwendoline","BLEU PANIQUE"])
        self.assertEqual(result["observedDate"],"2026-11-07")
        self.assertIn("premières parties",result["reason"])
        cloud=__import__("copy").deepcopy(CATALOGUE)
        cloud["events"].append(item)
        cloud["artists"].append({"id":"gwendoline","name":"Gwendoline"})
        source={R["officialUrl"]:REX_HTML,
                F["officialUrl"]:FERRAILLEUR_HTML,
                B["officialUrl"]:BRIN_HTML,
                item["officialUrl"]:self.gwendoline_page()}
        out=w.run(cloud,TODAY,10,
            fetch=lambda url:(source[url],url),
            robots=lambda url,cache:True)
        self.assertEqual(out["counts"],{"matched":3,"lineup_review":1})
        self.assertEqual(len(out["needsReview"]),1)
        self.assertEqual(out["needsReview"][0]["id"],item["id"])
        self.assertFalse(out["publicationAllowed"])

    def test_gwendoline_nominal_match_unrelated_recommendation_ignored(self):
        item=self.gwendoline_event()
        found=w.inspect(item,self.gwendoline_page(support=""),
                        dict(ARTISTS,gwendoline="Gwendoline"))
        self.assertEqual(found["status"],"matched")
        self.assertEqual(found["observedDate"],"2026-11-07")

    def test_gwendoline_changed_day_and_start_are_not_cancellations(self):
        item=self.gwendoline_event()
        found=w.inspect(item,self.gwendoline_page(day=8),
                        dict(ARTISTS,gwendoline="Gwendoline"))
        self.assertEqual(found["status"],"date_review")
        item["artistIds"]=["gwendoline","bleu-panique"]
        found=w.inspect(item,self.gwendoline_page(time="21:00"),
                        dict(ARTISTS,gwendoline="Gwendoline",
                             **{"bleu-panique":"Bleu Panique"}))
        self.assertEqual(found["status"],"time_review")
        found=w.inspect(item,"<html><h1>403 Forbidden</h1></html>",
                        dict(ARTISTS,gwendoline="Gwendoline"))
        self.assertEqual(found["status"],"unverifiable")

    def test_only_approved_individual_first_party_urls(self):
        self.assertEqual(w.source_kind(R),"rex")
        self.assertEqual(w.source_kind(F),"ferrailleur")
        self.assertEqual(w.source_kind(B),"brin")
        self.assertIsNone(w.source_kind(OTHER))
        for url in (
            "http://www.billetweb.fr/fvzz-popvli",
            "https://www.billetweb.fr/multi_event.php?multi=11236",
            "https://www.billetweb.fr/other?redirect=1",
            "https://www.lerextoulouse.com/fr/programmation/",
            "https://www.leferrailleur.fr/agenda",
            "https://fake.example/fr/programmation/the-browning/",
            "https://www.billetweb.fr@fake.example/fvzz-popvli",
        ):
            with self.subTest(url=url):
                e=dict(B);e["officialUrl"]=url
                self.assertIsNone(w.source_kind(e))


    def test_jokers_first_party_lineup_is_not_date_verification(self):
        entry=event("jokers","2026-11-27","Charles de Goal",
            "jokers-pub-angers",
            "https://www.jokerspubangers.com/jokers-concert-programmation-charles-goal-1702.html",
            ["charles-de-goal"])
        self.assertEqual(w.source_kind(entry),"jokers")
        html="<html><h1>CHARLES DE GOAL</h1><p>"+("description "*30)+"</p></html>"
        result=w.inspect(entry,html,{"charles-de-goal":"Charles de Goal"})
        self.assertEqual(result["status"],"lineup_only")
        self.assertIn("date non revérifiable",result["reason"])
        changed=html.replace("<h1>CHARLES DE GOAL</h1>","<h1>Autre artiste</h1>")
        self.assertEqual(w.inspect(entry,changed,{"charles-de-goal":"Charles de Goal"})["status"],"lineup_review")
        self.assertEqual(w.inspect(entry,"<html>error</html>",{"charles-de-goal":"Charles de Goal"})["status"],"unverifiable")
        wrong=dict(entry,officialUrl="https://www.jokerspubangers.com/jokers-pub-angers-programmation.php")
        self.assertIsNone(w.source_kind(wrong))

    def test_joker_two_artists_require_two_headings(self):
        entry=event("jokers2","2026-12-11","Aurore + Brutaliste",
            "jokers-pub-angers",
            "https://www.jokerspubangers.com/jokers-concert-programmation-aurore-+-brutaliste-1668.html",
            ["aurore","brutaliste"])
        page="<html><h1>AURORE</h1><h1>BRUTALISTE</h1><p>"+("texte "*40)+"</p></html>"
        names={"aurore":"Aurore","brutaliste":"Brutaliste"}
        self.assertEqual(w.inspect(entry,page,names)["status"],"lineup_only")
        page=page.replace("<h1>BRUTALISTE</h1>","<p>Brutaliste</p>")
        self.assertEqual(w.inspect(entry,page,names)["status"],"lineup_review")

    def test_rex_positive_match(self):
        self.assertEqual(w.inspect(R,REX_HTML,ARTISTS)["status"],"matched")

    def test_rex_official_changed_date_is_review_only(self):
        report=w.inspect(R,REX_HTML.replace("6 novembre","7 novembre"),ARTISTS)
        self.assertEqual(report["status"],"date_review")
        self.assertEqual(report["observedDate"],"2026-11-07")

    def test_rex_opener_disagreement_is_not_called_cancelled(self):
        report=w.inspect(R,REX_HTML.replace(" &amp; Within Destruction",""),ARTISTS)
        self.assertEqual(report["status"],"lineup_review")

    def test_rex_special_guest_is_real_lineup_not_false_alert(self):
        entry=dict(R)
        entry["title"]="Revnoir + Ice Sealed Eyes"
        entry["artistIds"]=["revnoir","ice-sealed-eyes"]
        page=REX_HTML.replace("The Browning &amp; Within Destruction",
                              "Revnoir").replace(
                              "<p>Metalcore, Deathcore</p>",
                              "<p>Metal</p><p>+ Special Guest : Ice Sealed Eyes</p>")
        names=dict(ARTISTS,revnoir="Revnoir")
        names["ice-sealed-eyes"]="Ice Sealed Eyes"
        self.assertEqual(w.inspect(entry,page,names)["status"],"matched")
        styled=page.replace("Special Guest : Ice Sealed Eyes",
                            "𝗦𝗽𝗲𝗰𝗶𝗮𝗹 𝗚𝘂𝗲𝘀𝘁 : 𝗜𝗰𝗲 𝗦𝗲𝗮𝗹𝗲𝗱 𝗘𝘆𝗲𝘀")
        self.assertEqual(w.inspect(entry,styled,names)["status"],"matched")
        self.assertEqual(w.inspect(
            entry,page.replace("+ Special Guest : Ice Sealed Eyes",
                               "Texte promotionnel générique"),names)["status"],
                         "lineup_review")

    def test_rex_parse_failure_never_declares_cancellation(self):
        report=w.inspect(R,"<html><h2>Error 503</h2></html>",ARTISTS)
        self.assertEqual(report["status"],"unverifiable")

    def test_ferrailleur_exact_lineup_and_clock(self):
        self.assertEqual(w.inspect(F,FERRAILLEUR_HTML,ARTISTS)["status"],"matched")
        changed=FERRAILLEUR_HTML.replace("20:30","21:00")
        self.assertEqual(w.inspect(F,changed,ARTISTS)["status"],"time_review")

    def test_lost_kyiv_explicit_official_typo_and_added_arabrot(self):
        show=event("go-c-20261212-nantes-lost-in-kyiv","2026-12-12",
            "Lost in Kyiv + Årabrot","le-ferrailleur-nantes",
            "https://www.leferrailleur.fr/evenement/lost-in-kyiv/5307",
            ["lost-in-kyiv","arabrot"],"20:30","début du concert")
        names={"lost-in-kyiv":"Lost in Kyiv","arabrot":"Årabrot"}
        page=FERRAILLEUR_HTML.replace(
            "vendredi 13 novembre 2026","samedi 12 décembre 2026"
        ).replace("Storm Orchestra","Lost in Kiyv").replace(
            "Shimmeric","Årabrot")
        self.assertEqual(w.inspect(show,page,names)["status"],"matched")
        self.assertEqual(
            w.inspect(show,page.replace("Årabrot","Autre artiste"),names)["status"],
            "lineup_review")
        other=dict(show,id="go-c-20261212-nantes-unrelated")
        self.assertEqual(w.inspect(other,page,names)["status"],"lineup_review")

    def test_ferrailleur_removed_support_act_is_not_auto_deletion(self):
        page=FERRAILLEUR_HTML.replace(
            "<div>Shimmeric</div><div>Rock</div>","<div>Another Artist</div><div>Rock</div>")
        self.assertEqual(w.inspect(F,page,ARTISTS)["status"],"lineup_review")

    def test_brin_ticketing_date_and_no_start_inference(self):
        self.assertEqual(w.inspect(B,BRIN_HTML,ARTISTS)["status"],"matched")
        changed=BRIN_HTML.replace("Mon Nov 09, 2026","Tue Nov 10, 2026")
        self.assertEqual(w.inspect(B,changed,ARTISTS)["status"],"date_review")

    def test_brin_missing_venue_or_multiple_dates_unverifiable(self):
        p=BRIN_HTML.replace("Le Brin de Zinc","Other Hall")
        self.assertEqual(w.inspect(B,p,ARTISTS)["status"],"unverifiable")
        p=BRIN_HTML.replace(
            "</body>","<p>Thu Nov 12, 2026</p></body>")
        self.assertEqual(w.inspect(B,p,ARTISTS)["status"],"unverifiable")

    def test_robots_denied_or_network_failure_never_cancelled(self):
        output=w.run(CATALOGUE,TODAY,10,robots=lambda url,cache:False,
                     fetch=lambda url: (_ for _ in ()).throw(AssertionError("not fetched")))
        self.assertEqual(output["checked"],3)
        self.assertEqual(output["counts"],{"source_unavailable":3})
        self.assertEqual(output["needsReview"],[])
        self.assertFalse(output["publicationAllowed"])

    def test_run_reads_each_official_url_and_reports_review_no_write(self):
        content={R["officialUrl"]:REX_HTML,
                 F["officialUrl"]:FERRAILLEUR_HTML,
                 B["officialUrl"]:BRIN_HTML}
        calls=[]
        def fetch(url):
            calls.append(url)
            return content[url],url
        output=w.run(CATALOGUE,TODAY,10,fetch=fetch,
                     robots=lambda url,cache:True)
        self.assertEqual(output["checked"],3)
        self.assertEqual(output["counts"],{"matched":3})
        self.assertEqual(output["otherNotAutomaticallyVerifiable"],124)
        self.assertEqual(set(calls),set(content))
        self.assertEqual(output["needsReview"],[])
        self.assertIn("lecture seule",w.markdown(output))

    def test_redirect_or_404_cannot_signal_cancellation(self):
        output=w.run(CATALOGUE,TODAY,10,
                     fetch=lambda url: ("<html>ANNULÉ</html>",
                                         "https://www.another.example/bad"),
                     robots=lambda url,cache:True)
        self.assertEqual(output["counts"],{"source_unavailable":3})
        self.assertEqual(output["needsReview"],[])


    def test_glazart_exact_individual_url_only_and_unlisted_source(self):
        glazart=event("glazart-lagrimas","2026-11-06","Lagrimas",
            "glazart-paris","https://www.glazart.com/06-11-26-concert-lagrimas/",
            ["lagrimas"])
        self.assertEqual(w.source_kind(glazart),"glazart")
        for url in (
            "https://www.glazart.com/agenda-concerts/portfolio-category/concert/",
            "https://www.glazart.com/06-11-26-concert-lagrimas/?ref=1",
            "https://www.glazart.com/06-11-26-concert-lagrimas/#x",
            "http://www.glazart.com/06-11-26-concert-lagrimas/",
            "https://www.glazart.com@evil.test/06-11-26-concert-lagrimas/",
            "https://evil.test/06-11-26-concert-lagrimas/",
            "https://www.glazart.com/99-11-26-concert-lagrimas/",
        ):
            with self.subTest(url=url):
                self.assertIsNone(w.source_kind(dict(glazart, officialUrl=url)))
        self.assertIsNone(w.source_kind(dict(glazart,venueId="other-venue")))

    def test_glazart_proves_only_event_date_not_complete_lineup(self):
        glazart=event("glazart-lagrimas","2026-11-06","Lagrimas",
            "glazart-paris","https://www.glazart.com/06-11-26-concert-lagrimas/",
            ["lagrimas"])
        doc="""<html><head><title>06.11.26 – Concert : LAGRIMAS → GLAZART</title>
          <script>Concert ANNULÉ en 2037</script></head><body>
          <p>Vendredi 06.11.26</p><p>Lagrimas screamo et hardcore à Paris</p>
          <p>Ouverture des portes 19h (pas un début de concert)</p></body></html>"""
        result=w.inspect(glazart,doc,{"lagrimas":"Lagrimas"})
        self.assertEqual(result["status"],"date_only")
        self.assertEqual(result["observedDate"],"2026-11-06")
        self.assertIn("non revérifiés",result["reason"])
        # No URL-only dating and no implicit postponement from an invalid page.
        self.assertEqual(w.inspect(
            glazart,doc.replace("<p>Vendredi 06.11.26</p>","<p>Vendredi</p>"),
            {"lagrimas":"Lagrimas"})["status"],"unverifiable")
        self.assertEqual(w.inspect(
            glazart,doc.replace("06.11.26</p>","07.11.26</p>"),
            {"lagrimas":"Lagrimas"})["status"],"unverifiable")

    def test_glazart_explicit_change_requires_human_review_not_deletion(self):
        glazart=event("glazart-lagrimas","2026-11-06","Lagrimas",
            "glazart-paris","https://www.glazart.com/06-11-26-concert-lagrimas/",
            ["lagrimas"])
        doc="""<html><head><title>06.11.26 – Concert : LAGRIMAS → GLAZART</title>
          </head><body><main><p>CONCERT ANNULÉ : date reportée, contactez la salle.</p>
          <p>Vendredi 06.11.26</p></main></body></html>"""
        result=w.inspect(glazart,doc,{"lagrimas":"Lagrimas"})
        self.assertEqual(result["status"],"content_review")
        self.assertNotIn("observedDate",result)
        catalog=dict(CATALOGUE,events=CATALOGUE["events"]+[glazart])
        report=w.run(catalog,TODAY,10,
            fetch=lambda url:(doc,url) if url==glazart["officialUrl"] else
                              ("<html></html>",url),
            robots=lambda url,cache:True)
        self.assertEqual(report["checked"],4)
        self.assertIn("glazart-lagrimas",[r["id"] for r in report["needsReview"]])
        self.assertFalse(report["publicationAllowed"])
        self.assertIn("content_review",w.markdown(report))

    def test_trabendo_first_party_date_and_single_artist_are_checked(self):
        entry=event("go-c-20270122-paris-wage-war","2027-01-22",
            "Wage War","le-trabendo-paris",
            "https://www.letrabendo.net/programmation/wage-war/",
            ["wage-war"])
        entry["genres"]=["Metalcore"]
        page="""<html><head><title>Wage War – Trabendo</title>
          <script>concert annulé en 1998</script></head><body>
          <h1>Trabendo</h1><h2>Live Nation présente</h2>
          <p>Album Wage War paru en 2021 et 2022.</p>
          <div><span>22</span>―<span>janvier</span><span>2027</span>
          <strong>Wage War</strong><p>concert ― Metalcore</p>
          <p>→ Trabendo - Salle de concert</p></div>
          <p>Ouverture des portes 19:00</p>
          <section>Vous devriez aimer
          <p>03 ― février 2027</p><p>Whitechapel</p>
          <p>concert ― Metalcore</p><p>Trabendo - Salle de concert</p>
          </section></body></html>"""
        self.assertEqual(w.source_kind(entry),"trabendo")
        self.assertEqual(w.inspect(entry,page,{"wage-war":"Wage War"})["status"],"matched")
        changed=page.replace("22</span>―<span>janvier</span><span>2027",
                             "23</span>―<span>janvier</span><span>2027")
        output=w.inspect(entry,changed,{"wage-war":"Wage War"})
        self.assertEqual(output["status"],"date_review")
        self.assertEqual(output["observedDate"],"2027-01-23")
        # A former first-party page no longer proves an active concert.
        canceled=page.replace(
            "<p>Ouverture des portes 19:00</p>",
            "<p>Concert reporté pour des raisons techniques</p>")
        output=w.inspect(entry,canceled,{"wage-war":"Wage War"})
        self.assertEqual(output["status"],"content_review")
        self.assertNotIn("observedDate",output)
        self.assertEqual(w.inspect(entry,"<html>404</html>",
                          {"wage-war":"Wage War"})["status"],"unverifiable")

    def test_trabendo_no_generic_agenda_or_fake_artist_and_no_published_write(self):
        show=event("go-c-20270203-paris-whitechapel","2027-02-03",
            "Whitechapel","le-trabendo-paris",
            "https://www.letrabendo.net/programmation/whitechapel/",
            ["whitechapel"])
        show["genres"]=["Metalcore"]
        for url in (
            "https://www.letrabendo.net/programmation/",
            "http://www.letrabendo.net/programmation/whitechapel/",
            "https://www.letrabendo.net/programmation/whitechapel/?ref=1",
            "https://evil.test/programmation/whitechapel/",
            "https://www.letrabendo.net@evil.test/programmation/whitechapel/",
        ):
            with self.subTest(url=url):
                self.assertIsNone(w.source_kind(dict(show,officialUrl=url)))
        page="""<html><head><title>Whitechapel – Trabendo</title></head>
          <body><p>03 ― février 2027</p><p>Whitechapel</p>
          <p>concert ― Metalcore</p>
          <p>→ Trabendo - Salle de concert</p></body></html>"""
        self.assertEqual(w.inspect(show,page,{"whitechapel":"A Different Band"})["status"],
                         "lineup_review")
        self.assertEqual(w.inspect(show,page,{"whitechapel":"Whitechapel"})["status"],
                         "matched")
        self.assertEqual(w.inspect(dict(show,genres=["Electro"]),
                         page,{"whitechapel":"Whitechapel"})["status"],
                         "lineup_review")
        collection=dict(CATALOGUE,events=CATALOGUE["events"]+[show],
                        artists=CATALOGUE["artists"]+[
                            {"id":"whitechapel","name":"Whitechapel"}])
        report=w.run(collection,TODAY,limit=24,
            fetch=lambda url:(page,url) if url==show["officialUrl"] else
                  ("<html>error</html>",url),
            robots=lambda url,cache:url==show["officialUrl"])
        self.assertEqual(report["checked"],4)
        self.assertEqual(report["counts"].get("matched"),1)
        self.assertFalse(report["publicationAllowed"])
        self.assertNotIn(show["id"],[r["id"] for r in report["needsReview"]])

    def test_maroquinerie_full_date_allt_only_not_fake_support(self):
        entry=event("go-c-20261110-paris-allt","2026-11-10",
            "Allt + Avralize + Bite Down","la-maroquinerie-paris",
            "https://www.lamaroquinerie.fr/fr/agenda/view/2212/allt/?of=7",
            ["allt","avralize","bite-down"])
        artists={"allt":"Allt","avralize":"Avralize","bite-down":"Bite Down"}
        page="""<html><head><title>ALLT - La Maroquinerie - Agenda</title></head>
        <body><h1>ALLT</h1><p>VERYSHOW présente</p>
        <p>Formé en 2020, Allt est un groupe de metalcore progressif.</p>
        <p>Avec Avralize et Bite Down en invités spéciaux.</p>
        <p>Retrouvez Allt le 10 novembre 2026 à la Maroquinerie (Paris)
        avec Avralize et Bite Down.</p>
        <p>La Maroquinerie, 23 rue Boyer, 75020 Paris</p>
        <p>Ouverture des portes à 19h30</p></body></html>"""
        self.assertEqual(w.source_kind(entry),"maroquinerie")
        status=w.inspect(entry,page,artists)
        self.assertEqual(status["status"],"date_only")
        self.assertEqual(status["observedDate"],"2026-11-10")
        self.assertNotIn("lineup",status)
        changed=page.replace("10 novembre 2026","11 novembre 2026")
        self.assertEqual(w.inspect(entry,changed,artists)["status"],"date_review")
        cancelled=page.replace("Ouverture des portes",
                               "Concert déplacé, Ouverture des portes")
        self.assertEqual(w.inspect(entry,cancelled,artists)["status"],"content_review")
        self.assertEqual(w.inspect(entry,"<html>404</html>",artists)["status"],
                         "unverifiable")

    def test_maroquinerie_horskh_lineup_only_year_unproven(self):
        entry=event("go-c-20261121-paris-horskh","2026-11-21",
            "Horskh + We Are Magonia","la-maroquinerie-paris",
            "https://www.lamaroquinerie.fr/fr/agenda/view/2180/horskh/?of=18",
            ["horskh","we-are-magonia"])
        artists={"horskh":"Horskh","we-are-magonia":"We Are Magonia"}
        page="""<html><head><title>HORSKH - La Maroquinerie - Agenda</title></head>
        <body><p>Base Productions présente : HORSKH</p>
        <p>Première partie : WE ARE MAGONIA</p>
        <p>HORSKH fusionne Métal, grunge et electro. Trio néo industriel.</p>
        <p>La Maroquinerie 23 rue Boyer 75020 Paris.</p>
        <p>Ouverture des portes à 19h30</p></body></html>"""
        self.assertEqual(w.source_kind(entry),"maroquinerie")
        a=w.inspect(entry,page,artists)
        self.assertEqual(a["status"],"lineup_only")
        self.assertNotIn("observedDate",a)
        self.assertEqual(w.inspect(entry,
            page.replace("WE ARE MAGONIA","AUTRE GROUPE"),
            artists)["status"],"lineup_review")
        self.assertEqual(w.inspect(entry,page.replace(
            "Ouverture des portes","Concert annulé. Ouverture des portes"),
            artists)["status"],"content_review")

    def test_boule_noire_proven_date_no_invented_hour_and_exact_domain(self):
        entry=event("go-c-20261115-paris-ice-sealed-eyes","2026-11-15",
            "Ice Sealed Eyes + Eiga","la-boule-noire-paris",
            "https://laboule-noire.fr/ice-sealed-eyes/",
            ["ice-sealed-eyes","eiga"])
        artists={"ice-sealed-eyes":"Ice Sealed Eyes","eiga":"Eiga"}
        page="""<html><head><title>ICE SEALED EYES - La Boule Noire</title></head>
        <body><h1>ICE SEALED EYES</h1><p>En cours</p>
        <p>2026-11-15 19:00:00</p>
        <p>DIMANCHE 15 NOVEMBRE 2026 - 19H00</p>
        <p>ICE SEALED EYES est un groupe de newcore belge.</p>
        <p>Première partie : Eiga, groupe de metalcore et de hardcore.</p>
        </body></html>"""
        self.assertEqual(w.source_kind(entry),"boule-noire")
        self.assertEqual(w.inspect(entry,page,artists)["status"],"date_only")
        changed=page.replace("2026-11-15","2026-11-16").replace(
            "15 NOVEMBRE","16 NOVEMBRE")
        a=w.inspect(entry,changed,artists)
        self.assertEqual((a["status"],a["observedDate"]),
                         ("date_review","2026-11-16"))
        self.assertEqual(w.inspect(entry,page.replace(
            "En cours","Annulé"),artists)["status"],"content_review")
        for url in ("https://laboule-noire.fr/","https://laboule-noire.fr/ice-sealed-eyes/?ref=1",
                    "https://evil.example/ice-sealed-eyes/",
                    "https://laboule-noire.fr/la-cigale/"):
            self.assertIsNone(w.source_kind(dict(entry,officialUrl=url)))
        for url in ("https://www.lamaroquinerie.fr/fr/agenda/",
                    "https://www.lamaroquinerie.fr/fr/agenda/view/2180/horskh/?of=0",
                    "https://evil.example/fr/agenda/view/2180/horskh/?of=18"):
            alt=event("dummy","2026-11-21","Horskh + We Are Magonia",
                "la-maroquinerie-paris",url,["horskh","we-are-magonia"])
            self.assertIsNone(w.source_kind(alt))

    def test_forum_precise_first_party_lineup_and_french_date_only(self):
        v=event("go-c-20261107-vaureal-wolves-throne-room","2026-11-07",
                "Wolves in the Throne Room + Worm + Final Dose",
                "le-forum-vaureal",
                "https://leforum.cergypontoise.fr/agenda/wolves-throne-room",
                ["wolves-in-the-throne-room","worm","final-dose"])
        artists={
            "wolves-in-the-throne-room":"Wolves in the Throne Room",
            "worm":"Worm","final-dose":"Final Dose"}
        page="""<html><body><main>
          <article>BLACK METAL METAL<h1>WOLVES IN THE THRONE ROOM</h1>
          <p>+ WORM + FINAL DOSE</p>
          <p>Samedi 07 Novembre 2026 18:30</p>
          <p>Production : Le Forum</p>
          <p>Le Forum, Grande Salle</p>
          <p>Ouverture des portes : 20h</p>
          <p>Début du concert : 20h30</p>
          <article><h2>WORM</h2><p>Album sorti en 2027</p></article>
          <section>Vous aimerez aussi <p>12 janvier 2028 AUTRE CONCERT</p></section>
          </article></main></body></html>"""
        self.assertEqual(w.source_kind(v),"forum")
        result=w.inspect(v,page,artists)
        self.assertEqual(result["status"],"date_only")
        self.assertEqual(result["observedDate"],"2026-11-07")
        self.assertNotIn("time",result)
        changed=page.replace("07 Novembre 2026","08 Novembre 2026")
        result=w.inspect(v,changed,artists)
        self.assertEqual((result["status"],result["observedDate"]),
                         ("date_review","2026-11-08"))
        year_missing=page.replace("07 Novembre 2026","07 Novembre")
        self.assertEqual(w.inspect(v,year_missing,artists)["status"],"lineup_only")
        self.assertEqual(w.inspect(v,page.replace("+ WORM + FINAL DOSE",
                         "+ WORM + AUTRE GROUPE"),artists)["status"],
                         "lineup_review")
        canceled=page.replace("Samedi 07 Novembre 2026 18:30",
                              "Concert reporté - Samedi 07 Novembre 2026 18:30")
        self.assertEqual(w.inspect(v,canceled,artists)["status"],"content_review")
        for url in ("http://leforum.cergypontoise.fr/agenda/wolves-throne-room",
                    "https://leforum.cergypontoise.fr/agenda",
                    "https://leforum.cergypontoise.fr/agenda/other-band",
                    "https://evil.test/agenda/wolves-throne-room",
                    v["officialUrl"]+"?ref=1"):
            with self.subTest(url=url):
                self.assertIsNone(w.source_kind(dict(v,officialUrl=url)))

    def test_forum_mass_hysteria_sold_out_is_not_cancelled(self):
        v=event("go-c-20261112-vaureal-mass-hysteria","2026-11-12",
                "Mass Hysteria","le-forum-vaureal",
                "https://leforum.cergypontoise.fr/agenda/mass-hysteria",
                ["mass-hysteria"],"20:30","début du concert")
        page="""<html><body><main><article>ROCK
        <h1>MASS HYSTERIA</h1><p>SANS DÉTOUR</p>
        <p>Jeudi 12 Novembre 2026 20:30 Complet</p>
        <p>Production : Le Forum</p><p>Ouverture des portes : 20h</p>
        <p>Début du concert : 20h30</p>
        <p>Cette formation joue du métal français depuis 30 ans.</p>
        </article></main></body></html>"""
        a=w.inspect(v,page,{"mass-hysteria":"Mass Hysteria"})
        self.assertEqual(a["status"],"date_only")
        self.assertEqual(a["observedDate"],"2026-11-12")
        self.assertNotIn("cancelled",str(a).lower())
        wrong=page.replace("Jeudi 12 Novembre","Jeudi 13 Novembre")
        self.assertEqual(w.inspect(v,wrong,{"mass-hysteria":"Mass Hysteria"})
                         ["status"],"date_review")

    def test_forum_hard_rock_three_artists_and_unnamed_support(self):
        v=event("go-c-20270522-vaureal-hard-rock-party","2027-05-22",
                "Harsh + Furies + Charcoal","le-forum-vaureal",
                "https://leforum.cergypontoise.fr/agenda/hard-rock-party",
                ["harsh","furies","charcoal"],"20:00","début du concert")
        page="""<html><main><article>HARD ROCK<h1>HARD ROCK PARTY</h1>
           <p>HARSH + FURIES + CHARCOAL</p>
           <p>Samedi 22 Mai 2027 20:00</p>
           <p>Production : Le Forum</p>
           <p>Début du concert : 20h</p></article></main></html>"""
        good=w.inspect(v,page,{"harsh":"Harsh","furies":"Furies",
                               "charcoal":"Charcoal"})
        self.assertEqual(good["status"],"date_only")
        self.assertEqual(w.inspect(v,page.replace("FURIES","TOURING ACT"),
                          {"harsh":"Harsh","furies":"Furies",
                           "charcoal":"Charcoal"})["status"],"lineup_review")
        m=event("go-c-20270317-vaureal-michael-schenker-group","2027-03-17",
                "Michael Schenker Group","le-forum-vaureal",
                "https://leforum.cergypontoise.fr/agenda/michael-schenker-group",
                ["michael-schenker-group"])
        html="""<html><main><h1>DON'T SELL YOUR SOUL TOUR 2027 MICHAEL SCHENKER GROUP</h1>
        <p>+ 1ÈRES PARTIES</p><p>Mercredi 17 Mars 2027 19:30</p>
        <p>Production : Le Forum</p></main></html>"""
        self.assertEqual(w.inspect(m,html,{"michael-schenker-group":"Michael Schenker Group"})
                         ["status"],"date_only")

    def test_invalid_catalogue_and_bad_limits_rejected(self):
        broken=dict(CATALOGUE);broken["mode"]="public-unrestricted"
        with self.assertRaises(ValueError):
            w.run(broken,TODAY,10,robots=lambda u,c:True)
        with self.assertRaises(ValueError):
            w.choose(CATALOGUE,TODAY,41)

    def test_nearterm_priority_and_rotation_without_duplicate(self):
        picks,eligible=w.choose(CATALOGUE,TODAY,2)
        self.assertEqual(eligible,3)
        self.assertEqual(len(picks),len({e["id"] for e in picks}))
        self.assertEqual(picks[0]["id"],"rex-event")
        self.assertEqual(picks[1]["id"],"brin-event")


if __name__=="__main__":
    unittest.main()
