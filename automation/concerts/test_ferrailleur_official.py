"""Offline regression tests based on individual official Ferrailleur page structures."""
import copy
import datetime as dt
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ferrailleur_official as f

PAGE = """<html><body>
<div>samedi 19 décembre 2026</div>
<div><span>Arkona</span><span>Folk</span><span>,</span><span>Black Metal</span><span>,</span><span>Pagan</span></div>
<div><span>Seth</span><span>Black Metal</span></div>
<div><span>The Great Old Ones</span><span>Black Metal</span></div>
<a href="https://dice.fm/x">Réservation</a><span>Partagez</span>
<span>horaires début</span><strong>19:00</strong>
<p>prix 31.00€ sur place</p>
<p>Les concerts</p>
</body></html>"""


def candidate():
    return {
        "candidateId": "ferrailleur:2026-12-19:arkona-seth-the-great-old-ones",
        "source": "agenda_officiel_ferrailleur_genre",
        "sourceUrl": "https://www.leferrailleur.fr/evenement/arkona-seth-the-great-old-ones/5368",
        "officialDetailFound": True,
        "name": "Arkona + Seth + The Great Old Ones",
        "date": "2026-12-19", "localTime": "19:00",
        "venue": "Le Ferrailleur", "city": "Nantes",
        "classification": ["Folk", "Black Metal", "Pagan", "Black Metal", "Black Metal"],
        "reviewBucket": "genre_tag_review",
        "reviewRequired": True,
        "publicationAllowed": False,
    }


def catalogue():
    return {
        "artists": [
            {"id": "arkona", "name": "Arkona"},
            {"id": "seth", "name": "Seth"},
            {"id": "the-great-old-ones", "name": "The Great Old Ones"}
        ],
        "venues": [{
            "id": "le-ferrailleur-nantes", "name": "Le Ferrailleur",
            "city": "Nantes", "address": "Quai des Antilles", "postalCode": "44200",
            "latitude": 47.20058, "longitude": -1.57365,
            "geoSource": "Adresse officielle ; OpenStreetMap node 373218467"
        }],
        "events": []
    }


class FerrailleurOfficialTests(unittest.TestCase):
    def test_exact_page_can_be_independently_verified(self):
        a=f.verify(candidate(),PAGE,catalogue(),dt.date(2026,11,1))
        self.assertEqual(a["event"]["date"],"2026-12-19")
        self.assertEqual(a["event"]["time"],"19:00")
        self.assertEqual(a["event"]["artistIds"],
                         ["arkona","seth","the-great-old-ones"])
        self.assertEqual(a["newArtists"],[])
        self.assertEqual(a["reviewedBy"],"automated-official-recheck")
        self.assertEqual(a["officialEvidence"][0]["checkedFields"],
                         ["artists","date","venue","genre"])

    def test_changed_date_or_time_never_autoapproves(self):
        for field,value in (("date","2026-12-20"),("localTime","20:00")):
            with self.subTest(field=field):
                x=candidate();x[field]=value
                with self.assertRaises(ValueError):
                    f.verify(x,PAGE,catalogue(),dt.date(2026,11,1))

    def test_extra_unannounced_band_is_held(self):
        p=PAGE.replace('<a href="https://dice.fm/x">',
                       '<span>Surprise Band</span><span>Metal</span><a href="https://dice.fm/x">')
        with self.assertRaisesRegex(ValueError,"Genre|Artiste"):
            f.verify(candidate(),p,catalogue(),dt.date(2026,11,1))

    def test_renamed_or_missing_band_is_held(self):
        for p in (PAGE.replace("<span>Seth</span>","<span>Unknown Band</span>"),
                  PAGE.replace("<span>Seth</span><span>Black Metal</span>","")):
            with self.subTest(page=p):
                with self.assertRaises(ValueError):
                    f.verify(candidate(),p,catalogue(),dt.date(2026,11,1))

    def test_missing_genre_is_held(self):
        with self.assertRaisesRegex(ValueError,"Genre"):
            f.verify(candidate(),PAGE.replace("<span>Seth</span><span>Black Metal</span>","<span>Seth</span><span>Pop</span>"),
                     catalogue(),dt.date(2026,11,1))

    def test_aggregator_and_general_agenda_links_never_autoapprove(self):
        for link in ("https://ticketmaster.fr/concert/arkona",
                     "https://www.leferrailleur.fr/agenda",
                     "https://www.leferrailleur.fr/evenement/arkona/5368?ref=ad"):
            with self.subTest(link=link):
                x=candidate();x["sourceUrl"]=link
                with self.assertRaises(ValueError):
                    f.verify(x,PAGE,catalogue(),dt.date(2026,11,1))

    def test_exactly_one_unknown_artist_can_be_recorded_from_official_roster(self):
        c=catalogue();c["artists"].pop()
        approved=f.verify(candidate(),PAGE,c,dt.date(2026,11,1))
        self.assertEqual(approved["newArtists"],
                         [{"id":"the-great-old-ones","name":"The Great Old Ones"}])
        self.assertEqual(approved["officialEvidence"][0]["verifiedNewArtists"],
                         ["The Great Old Ones"])
        self.assertEqual(approved["officialEvidence"][0]["officialArtistNames"],
                         ["Arkona","Seth","The Great Old Ones"])

    def test_two_unknown_artists_can_be_registered_from_exact_official_bill(self):
        c=catalogue();c["artists"]=[]
        c["artists"].append({"id":"arkona","name":"Arkona"})
        approved=f.verify(candidate(),PAGE,c,dt.date(2026,11,1))
        self.assertEqual([x["id"] for x in approved["newArtists"]],
                         ["seth","the-great-old-ones"])

    def test_all_three_named_unknown_artists_can_be_registered(self):
        cat = catalogue()
        cat["artists"] = []
        row = f.verify(candidate(), PAGE, cat, dt.date(2026, 11, 1))
        self.assertEqual(len(row["newArtists"]), 3)
        from concerts_cloud_sync import validate_approval
        event, artists = validate_approval(
            row, {v["id"]: v for v in cat["venues"]}, {},
            dt.date(2026, 11, 1))
        self.assertEqual(len(event["artistIds"]), 3)
        self.assertEqual(len(artists), 3)

    def test_twenty_new_and_mixed_named_bands_reach_real_publisher(self):
        from concerts_cloud_sync import validate_approval
        names = ["ACT %02d" % i for i in range(1, 21)]
        bill = " + ".join(names)
        page = (
            "<html><body><div>samedi 19 décembre 2026</div>"
            + "".join("<div><span>" + name +
                      "</span><span>Black Metal</span></div>"
                      for name in names)
            + '<a href="https://dice.fm/x">Réservation</a>'
              "<span>Partagez</span><span>horaires début</span>"
              "<strong>19:00</strong></body></html>"
        )
        item = candidate()
        item["name"] = bill
        item["classification"] = ["Black Metal"]
        cat = catalogue()
        cat["artists"] = []
        approval = f.verify(item, page, cat, dt.date(2026, 11, 1))
        self.assertEqual(len(approval["newArtists"]), 20)
        event, artists = validate_approval(
            approval, {v["id"]: v for v in cat["venues"]}, {},
            dt.date(2026, 11, 1))
        self.assertEqual(len(event["artistIds"]), 20)
        self.assertEqual(len(artists), 20)

        cat["artists"] = [{"id": "act-01", "name": "ACT 01"},
                          {"id": "act-02", "name": "ACT 02"}]
        mixed = f.verify(item, page, cat, dt.date(2026, 11, 1))
        self.assertEqual(len(mixed["newArtists"]), 18)
        _, newer = validate_approval(
            mixed, {v["id"]: v for v in cat["venues"]},
            {v["id"]: v for v in cat["artists"]}, dt.date(2026, 11, 1))
        self.assertEqual(len(newer), 18)

        altered = copy.deepcopy(approval)
        altered["officialEvidence"][0]["officialArtistNames"][4] = "FAKE"
        with self.assertRaises(ValueError):
            validate_approval(
                altered, {v["id"]: v for v in cat["venues"]}, {},
                dt.date(2026, 11, 1))
        with self.assertRaises(ValueError):
            f.verify(item, page.replace("<span>ACT 20</span>",
                                        "<span>OTHER</span>"),
                     catalogue(), dt.date(2026, 11, 1))

    def test_alias_and_slug_collisions_are_held(self):
        c=catalogue();c["artists"].pop()
        c["artists"][0]["aliases"]=["The Great Old Ones"]
        with self.assertRaisesRegex(ValueError,"alias"):
            f.verify(candidate(),PAGE,c,dt.date(2026,11,1))
        c=catalogue();c["artists"].pop()
        c["artists"].append({"id":"the-great-old-ones","name":"Other Project"})
        with self.assertRaisesRegex(ValueError,"identifiant"):
            f.verify(candidate(),PAGE,c,dt.date(2026,11,1))

    def test_unverified_coordinates_are_held(self):
        c=catalogue();c["venues"][0]["latitude"]=47.217
        with self.assertRaisesRegex(ValueError,"Position réelle"):
            f.verify(candidate(),PAGE,c,dt.date(2026,11,1))

    def test_pop_only_genre_cannot_publish(self):
        c=catalogue()
        p=PAGE.replace("Folk","Pop").replace("Black Metal","Pop").replace("Pagan","Pop")
        x=candidate();x["classification"]=["Pop"]
        with self.assertRaisesRegex(ValueError,"métal ou punk"):
            f.verify(x,p,c,dt.date(2026,11,1))

    def test_duplicate_artist_venue_day_is_held(self):
        c=catalogue()
        c["events"].append({
            "id":"already","date":"2026-12-19","venueId":"le-ferrailleur-nantes",
            "artistIds":["seth"]
        })
        with self.assertRaisesRegex(ValueError,"déjà publié"):
            f.verify(candidate(),PAGE,c,dt.date(2026,11,1))

    def test_only_review_bucket_with_evidence_allowed(self):
        x=candidate();x["reviewBucket"]="possible_duplicate"
        with self.assertRaises(ValueError):
            f.verify(x,PAGE,catalogue(),dt.date(2026,11,1))
        x=candidate();x["officialDetailFound"]=False
        with self.assertRaises(ValueError):
            f.verify(x,PAGE,catalogue(),dt.date(2026,11,1))

    def test_ticket_button_optional_but_explicit_time_mandatory(self):
        approved = f.verify(candidate(), PAGE.replace('<a href="https://dice.fm/x">Réservation</a>',""),
                            catalogue(),dt.date(2026,11,1))
        self.assertEqual(approved["event"]["time"], "19:00")
        with self.assertRaises(ValueError):
            f.verify(candidate(),
                     PAGE.replace("<strong>19:00</strong>","<strong>à confirmer</strong>"),
                     catalogue(),dt.date(2026,11,1))


if __name__ == "__main__":
    unittest.main()
