"""Offline regression fixtures model the observed Drupal Rocher HTML structure."""
import datetime as dt
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parent))
import rocher_palmer_adapter as rocher
import discover

SOURCE={"name":"Le Rocher de Palmer","city":"Cenon","department":"33",
        "url":rocher.AGENDA,"priority":"P1",
        "adapter":"rocher_palmer_official_detail",
        "maxDetailPagesPerRun":8,"maxAgendaPagesPerRun":1}


def card(slug="uuhai",name="UUHAI",date=(26,"Mars",2027),
         badge="",intro="Folk metal mongol et groupe ACYL"):
    d,m,y=date
    return (
        '<div class="views-row" role="listitem"><article>'
        f'<a class="zoom-survol" aria-label="{name}" href="/agenda/{slug}">'
        f'<div class="evt-date" data-day="{d}" data-month="{m}" '
        f'data-year="{y}">Ven. {d} {m} {y}</div>'
        f'<p>{intro}</p><span data-term-name="{badge}">{badge}</span>'
        f'<h2>{name}</h2></a></article></div>'
    )


def detail(name="UUHAI",date=(26,"Mars",2027),category="metal-punk",
           intro="UUHAI est un groupe de folk metal venu de Mongolie.",
           venue="Le Rocher de Palmer",status="",start="19:00",
           extra="avec ACYL en première partie"):
    d,m,y=date
    return (
        '<article class="node node--type-evenement view--full">'
        f'<div class="field--name-field-intro">{intro}</div>'
        f'<div class="field--name-field-texte"> {extra} </div>'
        f'<div class="full--evt-categories"><span data-term-name="{category}">'
        f'{category}</span></div>'
        f'<div data-term-name="{status}">{status}</div>'
        f'<h1>{name}</h1>'
        f'<span class="evt-date lb_session-date" data-day="{d}" '
        f'data-month="{m}" data-year="{y}">Ven. {d} {m} {y}</span>'
        f'<span class="lb_session--evt-location-location">{venue}</span>'
        f'<p>OUVERTURE DES PORTES : 18:30 / DÉBUT DES CONCERTS : {start}</p>'
        '</article><article><h1>Recommandation métal sans lien</h1></article>'
    )


def record(agenda=None,body=None,url="https://lerocherdepalmer.fr/agenda/uuhai"):
    cards=rocher.agenda_cards(agenda or card())
    return rocher.detail_candidate(body or detail(),url,cards[0],SOURCE,"2026-11-02")


class RocherParserTests(unittest.TestCase):
    def test_official_dated_card_and_named_venue_candidate(self):
        row=record()
        self.assertEqual(row["candidateId"],"rocher-palmer:2027-03-26:uuhai")
        self.assertEqual(row["date"],"2027-03-26")
        self.assertEqual(row["localTime"],"19:00")
        self.assertEqual(row["classification"],["Metal, Punk"])
        self.assertEqual(row["venueCatalogueId"],rocher.VENUE)
        self.assertFalse(row["publicationAllowed"])
        self.assertTrue(row["reviewRequired"])
        self.assertTrue(row["officialDetailFound"])

    def test_rock_only_needs_explicit_subgenre_in_first_party_description(self):
        ugly=card(slug="ugly-kid-joe",name="UGLY KID JOE",
                  date=(10,"Février",2027),badge="rock",
                  intro="Retour au hard rock")
        page=detail(name="Musiques de Nuit présente UGLY KID JOE",
                    date=(10,"Février",2027),category="rock",
                    intro="Un groupe de hard rock californien")
        x=record(ugly,page,"https://lerocherdepalmer.fr/agenda/ugly-kid-joe")
        self.assertEqual(x["classification"],["Hard Rock"])
        with self.assertRaisesRegex(ValueError,"Genre"):
            record(ugly,detail(name="UGLY KID JOE",date=(10,"Février",2027),
                               category="rock",intro="Ce groupe chante avec énergie.",
                               extra="sans classement"),"https://lerocherdepalmer.fr/agenda/ugly-kid-joe")

    def test_historical_punk_in_reggae_bio_is_not_the_concert_genre(self):
        # Real-world Jahneration pattern: official "Reggae, Dub", biography
        # explains they moved from Punk Rock *to* Reggae. Never create a
        # genre_tag_review concert from that historical mention.
        agenda=card(slug="jahneration",name="JAHNERATION",
                    date=(4,"Mars",2027),intro="du punk rock au reggae")
        page=detail(name="PEEL PRODUCTIONS et OVASTAND présentent : JAHNERATION",
                    date=(4,"Mars",2027),category="Reggae, Dub / France",
                    intro="Ils décident de troquer le Punk Rock pour le Reggae.",
                    extra="Le groupe est incontournable du reggae hexagonal.")
        with self.assertRaisesRegex(ValueError,"catégorie officielle"):
            record(agenda,page,"https://lerocherdepalmer.fr/agenda/jahneration")

    def test_first_party_concert_genre_overrides_incidental_biographies(self):
        # A tag on THIS event is usable even without a metal/punk biography.
        agenda=card(intro="Un événement live")
        self.assertEqual(
            record(agenda,detail(category="Punk Rock",
                                 intro="Une nouvelle création musicale",
                                 extra="Pas d'étiquette dans la biographie"))
              ["classification"],["Punk"])
        # Other explicitly non-target genres cannot inherit a distant mention.
        for category in ("Jazz, Soul", "Reggae, Dub", "Hip Hop", "Electro"):
            with self.subTest(category=category), self.assertRaisesRegex(
                    ValueError,"catégorie officielle"):
                record(agenda,detail(category=category,
                    intro="A joué autrefois dans un groupe de thrash metal.",
                    extra="Le concert actuel est une autre proposition."))

    def test_stranglers_and_brother_junior_full_official_bill(self):
        # The real official card's accessible label may omit the support,
        # while the first-party H1 has an immediately following "+ BAND".
        agenda=card("stranglers","THE STRANGLERS",
                    date=(24,"Novembre",2026),badge="rock",
                    intro="Nés dans la fureur punk")
        page=detail(
            name="Musiques de Nuit présente THE STRANGLERS",
            date=(24,"Novembre",2026), category="rock",
            intro="Le punk les a portés",
            extra="BROTHER JUNIOR 1ÈRE PARTIE",
            start="20:30"
        ).replace("</h1>","</h1><p>+ BROTHER JUNIOR</p>",1)
        page=page.replace("DÉBUT DES CONCERTS", "DÉBUT DU CONCERT")
        x=record(agenda,page,"https://lerocherdepalmer.fr/agenda/stranglers")
        self.assertEqual(x["name"],"THE STRANGLERS + BROTHER JUNIOR")
        self.assertEqual(x["leadArtist"],"THE STRANGLERS")
        self.assertEqual(x["officialArtistNames"],
                         ["THE STRANGLERS","BROTHER JUNIOR"])
        self.assertEqual(x["localTime"],"20:30")
        self.assertEqual(x["classification"],["Punk"])
        self.assertFalse(x["publicationAllowed"])

    def test_nested_h1_and_duplicate_biography_text_use_markup_boundary(self):
        agenda=card("gwendoline","GWENDOLINE",
                    date=(7,"Novembre",2026),badge="rock",
                    intro="GWENDOLINE est un groupe post-punk")
        page=detail(name="Musiques de Nuit présente GWENDOLINE",
                    date=(7,"Novembre",2026), category="rock",
                    intro="GWENDOLINE cultive le post-punk",
                    extra="GWENDOLINE a déjà joué de nombreux concerts")
        page=page.replace(
            "<h1>Musiques de Nuit présente GWENDOLINE</h1>",
            "<h1><span>Musiques de Nuit présente </span>"
            "<strong>GWENDOLINE</strong></h1>"
            "<p>+ BLEU PANIQUE</p>",1)
        row=rocher.parse_detail(page)
        self.assertIsInstance(row["h1VisibleStart"],int)
        self.assertIsInstance(row["h1VisibleEnd"],int)
        self.assertGreater(row["h1VisibleEnd"],row["h1VisibleStart"])
        found=record(agenda,page,"https://lerocherdepalmer.fr/agenda/gwendoline")
        self.assertEqual(found["officialArtistNames"],
                         ["GWENDOLINE","BLEU PANIQUE"])
        self.assertEqual(found["name"],"GWENDOLINE + BLEU PANIQUE")

    def test_unnamed_support_and_headliner_only_are_rejected(self):
        agenda=card("stranglers","THE STRANGLERS",
                    date=(24,"Novembre",2026),badge="rock")
        page=detail(name="THE STRANGLERS",
                    date=(24,"Novembre",2026),category="metal-punk",
                    extra="<p>1ÈRE PARTIE</p>")
        with self.assertRaisesRegex(ValueError,"Première partie annoncée"):
            record(agenda,page,"https://lerocherdepalmer.fr/agenda/stranglers")
        for label in ("+ PREMIÈRE PARTIE", "+ GUESTS", "+ TBA"):
            with self.subTest(label=label),self.assertRaises(ValueError):
                record(agenda,page.replace("</h1>",f"</h1><p>{label}</p>",1),
                       "https://lerocherdepalmer.fr/agenda/stranglers")

    def test_venue_card_support_must_match_official_detail(self):
        agenda=card("stranglers","THE STRANGLERS + WRONG BAND",
                    date=(24,"Novembre",2026),badge="rock")
        page=detail(name="THE STRANGLERS",
                    date=(24,"Novembre",2026),category="metal-punk")
        page=page.replace("</h1>","</h1><p>+ BROTHER JUNIOR</p>",1)
        with self.assertRaisesRegex(ValueError,"différente"):
            record(agenda,page,"https://lerocherdepalmer.fr/agenda/stranglers")

    def test_full_names_inside_h1_dont_require_extra_suffix(self):
        agenda=card("ocean","THE OCEAN + A.A. WILLIAMS",
                    date=(31,"Janvier",2027),badge="metal-punk")
        page=detail(name="THE OCEAN + A.A. WILLIAMS",
                    date=(31,"Janvier",2027),category="metal-punk")
        x=record(agenda,page,"https://lerocherdepalmer.fr/agenda/ocean")
        self.assertEqual(x["officialArtistNames"],
                         ["THE OCEAN","A.A. WILLIAMS"])
        self.assertEqual(x["name"],"THE OCEAN + A.A. WILLIAMS")
        self.assertEqual(x["localTime"],"19:00")

    def test_date_title_out_of_venue_and_cancellation_are_blocked(self):
        variants=[
            (detail(date=(25,"Mars",2027)), "Date"),
            (detail(name="Un autre groupe"), "Titre"),
            (detail(venue="Arkéa Arena"), "Salle"),
            (detail(status="annule"), "Annonce"),
            (detail(status="hors-les-murs"), "Annonce"),
            (detail(date=(26,"Mars",2025)), "Date"),
        ]
        for page, message in variants:
            with self.subTest(message=message,page=page[:90]),self.assertRaisesRegex(ValueError,message):
                record(body=page)

    def test_no_guess_of_hour_and_unrelated_recommendations(self):
        x=record(body=detail(start="19:00").replace("DÉBUT DES CONCERTS : 19:00",""))
        self.assertIsNone(x["localTime"])
        with self.assertRaisesRegex(ValueError,"Genre"):
            record(body=detail(intro="Le groupe joue à Cenon",extra="Ambiance rock",
                               category="rock").replace(
                               "Ambiance rock","Ambiance électronique")
                   + '<article><span data-term-name="metal-punk">Un autre concert</span></article>')

    def test_multiple_dates_and_missing_card_year_are_blocked(self):
        c=card().replace(' data-year="2027"','')
        self.assertEqual(rocher.agenda_cards(c),[])
        with self.assertRaisesRegex(ValueError,"session unique"):
            record(body=detail().replace('</article>',
                '<span class="evt-date" data-day="27" data-month="Mars" '
                'data-year="2027"></span></article>',1))

    def test_robots_safe_links_and_no_footer_links(self):
        self.assertIsNone(rocher.exact_link("http://lerocherdepalmer.fr/agenda/uuhai"))
        self.assertIsNone(rocher.exact_link("https://evil.example/agenda/uuhai"))
        self.assertIsNone(rocher.exact_link("/agenda/uuhai?token=secret"))
        self.assertIsNone(rocher.exact_link("/agenda/archives"))
        self.assertIsNone(rocher.exact_link("/agenda/micro-folie"))
        agenda='<a aria-label="footer" href="/agenda/uuhai">No date</a>'+card()
        self.assertEqual(len(rocher.agenda_cards(agenda)),1)

    def test_deduplication_and_genre_priority(self):
        x=rocher.agenda_cards(card()+card()+
                  card("gwendoline","Gwendoline",date=(7,"Novembre",2026),
                       badge="",intro="Post-punk de Rennes"))
        self.assertEqual(len(x),2)
        self.assertGreater(rocher.card_priority(x[0]),0)
        self.assertGreater(rocher.card_priority(x[1]),0)

    def test_scan_venues_is_read_only_and_detects_prior_known_url(self):
        page=card()
        target="https://lerocherdepalmer.fr/agenda/uuhai"
        known={("officialUrl",target)}
        with (mock.patch.object(discover,"download",side_effect=lambda url,**kw:
                    (page if url==rocher.AGENDA else detail(),url)),
              mock.patch.object(discover,"robots_allow",return_value=True)):
            diagnostics=[]
            found=discover.scan_venues({"venues":[SOURCE]},known,
                                       dt.date(2026,11,2),diagnostics)
        matches=[e for e in found if e.get("source")==
                 "agenda_officiel_rocher_de_palmer_detail"]
        self.assertEqual(len(matches),1)
        self.assertTrue(matches[0]["possibleExistingConcert"])
        self.assertFalse(matches[0]["publicationAllowed"])
        self.assertEqual(diagnostics[0]["adapterDiagnostic"]["datedGenreLeads"],1)
        self.assertEqual(diagnostics[0]["adapterDiagnostic"]["alreadyLikelyPublished"],1)


if __name__=="__main__":
    unittest.main()
