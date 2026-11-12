"""Zero-network tests for official Molotov recheck. Never accepts Le Dodu."""
import datetime as dt
import sys
import unittest
from pathlib import Path
the_path = Path(__file__).resolve().parent
sys.path.insert(0, str(the_path))
sys.path.insert(0, str(the_path.parents[1] / "scripts"))
import molotov_official as m

PAGE = """<article>
<h2>13</h2><h3>Nov</h3><h3>2026</h3>
<h4><b>@ Le Molotov</b></h4><h4>3 Place Paul Cézanne</h4><h4>20:30</h4>
<h1>Band Alpha + Band Beta</h1><h2>Metalcore, Metal</h2>
<p><strong>Band Alpha<br/>[Metalcore | France]</strong></p>
<p><strong>Band Beta<br/>[Metal | France]</strong></p></article>"""


def candidate():
    return {"candidateId":"molotov:2026-11-13:band-alpha-band-beta",
            "source":"agenda_officiel_molotov_genre",
            "sourceUrl":"https://lemolotov.com/events/band-alpha-band-beta/",
            "name":"Band Alpha + Band Beta","date":"2026-11-13",
            "venue":"Le Molotov","city":"Marseille",
            "classification":["Metalcore","Metal"],"reviewBucket":"genre_tag_review",
            "possibleExistingConcert":False,"reviewRequired":True,
            "publicationAllowed":False}


def catalogue():
    return {"artists":[{"id":"band-alpha","name":"Band Alpha"},
                       {"id":"band-beta","name":"Band Beta"}],
            "venues":[{"id":"le-molotov-marseille","name":"Le Molotov","city":"Marseille"}],
            "events":[]}


class MolotovRecheckTests(unittest.TestCase):
    def test_full_independent_details(self):
        result=m.verify(candidate(), PAGE, catalogue(),dt.date(2026,11,1))
        self.assertEqual(result["event"]["date"],"2026-11-13")
        self.assertEqual(result["event"]["venueId"],"le-molotov-marseille")
        self.assertEqual(result["event"]["artistIds"],["band-alpha","band-beta"])
        self.assertEqual(result["newArtists"],[])

    def test_le_dodu_is_never_the_molotov(self):
        with self.assertRaisesRegex(ValueError,"Le Molotov"):
            m.verify(candidate(),PAGE.replace("@ Le Molotov","@ Le Dodu"),
                     catalogue(),dt.date(2026,11,1))
        x=candidate()
        x["venue"]="Le Dodu"
        with self.assertRaises(ValueError):
            m.verify(x,PAGE,catalogue(),dt.date(2026,11,1))

    def test_date_requires_exact_match(self):
        x=candidate();x["date"]="2026-11-12"
        with self.assertRaises(ValueError):
            m.verify(x,PAGE,catalogue(),dt.date(2026,11,1))

    def test_no_artist_invention(self):
        c=catalogue();c["artists"].pop()
        with self.assertRaisesRegex(ValueError,"Artiste absent"):
            m.verify(candidate(),PAGE,c,dt.date(2026,11,1))

    def test_no_aggregator_or_general_calendar(self):
        x=candidate();x["sourceUrl"]="https://www.ticketmaster.fr/event/band-alpha-band-beta"
        with self.assertRaisesRegex(ValueError,"individuelle"):
            m.verify(x,PAGE,catalogue(),dt.date(2026,11,1))
        x=candidate();x["sourceUrl"]="https://lemolotov.com/events/"
        with self.assertRaisesRegex(ValueError,"individuelle"):
            m.verify(x,PAGE,catalogue(),dt.date(2026,11,1))

    def test_genre_and_title_must_match(self):
        x=candidate();x["classification"]=["Rap"]
        with self.assertRaisesRegex(ValueError,"Genres"):
            m.verify(x,PAGE,catalogue(),dt.date(2026,11,1))
        x=candidate();x["name"]="Band Omega"
        with self.assertRaisesRegex(ValueError,"Affiche incohérente"):
            m.verify(x,PAGE,catalogue(),dt.date(2026,11,1))

    def test_festival_and_incomplete_lineup_blocked(self):
        with self.assertRaises(ValueError):
            m.verify(candidate(),PAGE.replace("Band Alpha + Band Beta",
                    "Festival Band Alpha + Band Beta"),catalogue(),dt.date(2026,11,1))


    def test_known_headliner_and_guest_are_approvable_as_main_act(self):
        from concerts_cloud_sync import validate_approval
        page = PAGE.replace("Band Alpha + Band Beta", "Band Alpha + Guest")
        item = candidate()
        item["name"] = "Band Alpha + Guest"
        cat = catalogue()
        checked = m.verify(item, page, cat, dt.date(2026, 11, 1))
        self.assertEqual(checked["event"]["artistIds"], ["band-alpha"])
        self.assertEqual(checked["event"]["title"], "Band Alpha")
        self.assertEqual(checked["newArtists"], [])
        self.assertEqual(
            checked["officialEvidence"][0]["unannouncedSupportLabel"], "guest")
        approved, added = validate_approval(
            checked, {x["id"]: x for x in cat["venues"]},
            {x["id"]: x for x in cat["artists"]}, dt.date(2026, 11, 1))
        self.assertEqual(approved["artistIds"], ["band-alpha"])
        self.assertEqual(added, {})

    def test_guest_in_the_middle_and_unconfirmed_headliner_fail(self):
        for title in ("Guest + Band Alpha",
                      "Band Alpha + Guest + Band Beta",
                      "Festival Band Alpha + Guest"):
            page = PAGE.replace("Band Alpha + Band Beta", title)
            item = candidate()
            item["name"] = title
            with self.subTest(title=title), self.assertRaises(ValueError):
                m.verify(item, page, catalogue(), dt.date(2026, 11, 1))
        page = PAGE.replace("Band Alpha + Band Beta", "Unknown Main + Guest")
        item = candidate()
        item["name"] = "Unknown Main + Guest"
        with self.assertRaisesRegex(ValueError, "Artiste absent"):
            m.verify(item, page, catalogue(), dt.date(2026, 11, 1))

    def test_publisher_rejects_guest_proof_tampering(self):
        import copy
        from concerts_cloud_sync import validate_approval
        page = PAGE.replace("Band Alpha + Band Beta", "Band Alpha + Guest")
        item = candidate()
        item["name"] = "Band Alpha + Guest"
        cat = catalogue()
        row = m.verify(item, page, cat, dt.date(2026, 11, 1))
        for key, value in (
                ("unannouncedSupportLabel", "festival"),
                ("sourceStructure", "generic-event"),
                ("officialArtistNames", ["Guest"]),
        ):
            wrong = copy.deepcopy(row)
            wrong["officialEvidence"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_approval(
                    wrong, {x["id"]: x for x in cat["venues"]},
                    {x["id"]: x for x in cat["artists"]},
                    dt.date(2026, 11, 1))

    def test_duplicate_is_held(self):
        c=catalogue();c["events"]=[{"id":"already","date":"2026-11-13",
                       "venueId":"le-molotov-marseille","artistIds":["band-alpha"]}]
        with self.assertRaisesRegex(ValueError,"déjà référencé"):
            m.verify(candidate(),PAGE,c,dt.date(2026,11,1))



    @staticmethod
    def wordpress_card(title="Band Alpha + Band Beta", header=None,
                       genres="Metalcore, Metal", venue="Le Molotov",
                       date_day="13", date_year="2026"):
        # Reproduces the two H1 headings on real /events/ WordPress pages.
        return (
            '<article class="event">'
            '<header class="entry-header"><h1 class="entry-title">' +
            (header if header is not None else title) + '</h1></header>'
            '<div id="eveCardsolo"><div class="eveDate">'
            '<h2>' + date_day + '</h2><h3>Nov</h3><h3>' + date_year + '</h3>'
            '</div><div class="evePlusolo"><h4>@ ' + venue + '</h4>'
            '<h4>3 Place Paul Cézanne</h4><h4>20:30</h4></div>'
            '<div class="eveInfo"><div id="eveName"><h1>' + title +
            '</h1><h2>' + genres + '</h2></div></div></div>'
            '<p><strong>Band Alpha<br/>[Metalcore | France]</strong></p>'
            '</article>'
        )

    def test_live_wordpress_duplicate_heading_is_one_event(self):
        page = self.wordpress_card()
        row = m.verify(candidate(), page, catalogue(), dt.date(2026, 11, 1))
        self.assertEqual(row["event"]["artistIds"], ["band-alpha", "band-beta"])
        self.assertEqual(row["event"]["date"], "2026-11-13")

    def test_wordpress_header_and_card_must_agree(self):
        with self.assertRaisesRegex(ValueError, "Une seule affiche"):
            m.verify(candidate(),
                     self.wordpress_card(header="Other concert"),
                     catalogue(), dt.date(2026, 11, 1))

    def test_duplicate_heading_requires_exact_official_card_structure(self):
        page = self.wordpress_card().replace('id="eveName"', 'id="other"')
        with self.assertRaisesRegex(ValueError, "Une seule affiche"):
            m.verify(candidate(), page, catalogue(), dt.date(2026, 11, 1))

    def test_two_event_cards_cannot_merge(self):
        page = self.wordpress_card().replace(
            "</article>",
            '<div id="eveCardsolo"><div id="eveName">'
            '<h1>Second concert</h1></div></div></article>')
        with self.assertRaisesRegex(ValueError, "Une seule affiche"):
            m.verify(candidate(), page, catalogue(), dt.date(2026, 11, 1))

    def test_duplicate_header_does_not_override_date_or_venue(self):
        for kwargs in ({"date_day": "14"}, {"venue": "Le Dodu"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                m.verify(candidate(), self.wordpress_card(**kwargs),
                         catalogue(), dt.date(2026, 11, 1))

    def test_multiple_named_acts_and_plural_guests_only_publish_known(self):
        from concerts_cloud_sync import validate_approval
        title = "Band Alpha + Band Beta + Guests"
        item = candidate()
        item["name"] = title
        page = self.wordpress_card(title=title)
        checked = m.verify(item, page, catalogue(), dt.date(2026, 11, 1))
        self.assertEqual(checked["event"]["artistIds"], ["band-alpha", "band-beta"])
        self.assertEqual(checked["event"]["title"], "Band Alpha + Band Beta")
        self.assertEqual(checked["newArtists"], [])
        self.assertEqual(checked["officialEvidence"][0]["unannouncedSupportLabel"], "guest")
        approved, added = validate_approval(
            checked, {v["id"]: v for v in catalogue()["venues"]},
            {a["id"]: a for a in catalogue()["artists"]}, dt.date(2026, 11, 1))
        self.assertEqual(approved["artistIds"], ["band-alpha", "band-beta"])
        self.assertFalse(added)

    def test_post_hardcore_is_an_explicit_eligible_genre(self):
        item = candidate()
        item["classification"] = ["Post Hardcore"]
        row = m.verify(item, self.wordpress_card(genres="Alt Rock, Post Hardcore"),
                       catalogue(), dt.date(2026, 11, 1))
        self.assertEqual(row["event"]["date"], "2026-11-13")


if __name__=="__main__":
    unittest.main()
