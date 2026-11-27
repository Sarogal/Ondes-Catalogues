"""Published public OpenAgenda event page, original source, offline tests."""
import json
import unittest

from automation.concerts import openagenda_official_concert as oa

URL = ("https://openagenda.com/fr/shotgun/events/"
       "31421187_poesie-zero-king-kong-meuf")
DATE = "2026-12-11"
VENUE = {
    "name": "Big Band Café", "city": "Hérouville-Saint-Clair",
    "address": "1 Avenue du Haut Crépon", "postalCode": "14200",
}


def html(*, status="EventScheduled", title="POESIE ZERO + KING KONG MEUF",
         genre="punk", artist="POÉSIE ZERO",
         address="1 Avenue du Haut Crépon", name="Big Band Café",
         day=DATE):
    node = {
        "@type": "Event", "name": title,
        "startDate": day + "T20:00:00+01:00",
        "eventStatus": "https://schema.org/" + status,
        "genre": genre,
        "performer": [{"@type": "MusicGroup", "name": artist}],
        "location": {"@type": "Place", "name": name, "address": address},
    }
    return ('<html><head><script type="application/ld+json">' +
            json.dumps(node, ensure_ascii=False) +
            '</script></head><body><h1>' + title + '</h1></body></html>')


class OfficialOpenAgendaEventTests(unittest.TestCase):
    def test_real_format_with_partial_schema_performers_has_full_named_bill(self):
        bill, genres = oa.verified_bill(html(), URL, DATE, VENUE)
        self.assertEqual(bill, ["POESIE ZERO", "KING KONG MEUF"])
        self.assertEqual(genres, ["punk"])

    def test_one_source_fails_closed_on_contradictory_date_genre_or_location(self):
        tests = (
            {"status": "EventCancelled"},
            {"status": "EventPostponed"},
            {"genre": "Hardcore Techno"},
            {"name": "Different Location"},
            {"address": "300 Rue du Faux Concert"},
            {"artist": "Unrelated Fake Group"},
            {"day": "2026-12-12"},
            {"title": "Festival des arts punk"},
        )
        for changed in tests:
            with self.subTest(changed=changed):
                with self.assertRaises(ValueError):
                    oa.verified_bill(html(**changed), URL, DATE, VENUE)

    def test_unnamed_guest_with_exact_location_suffix_is_not_an_artist(self):
        venue = dict(VENUE, name="La Example Room", city="Example City")
        for suffix in ("guest - Example Room, Example City",
                       "GUESTS – La Example Room, Example City"):
            self.assertEqual(oa._bill({"@type": "MusicEvent",
                                      "name": "Headliner + " + suffix},
                                     venue=venue), ["Headliner"])
        for suffix in ("Guest House - Example Room, Example City",
                       "guest - Other Room, Example City",
                       "guest - Example Room, Other City",
                       "guests : Other Band"):
            self.assertFalse(oa.unnamed_venue_suffix(suffix, venue))
        self.assertEqual(oa._bill({"@type": "MusicEvent",
                                  "name": "Headliner + guests : Other Band"},
                                 venue=venue), ["Headliner", "Other Band"])
        with self.assertRaises(ValueError):
            oa._bill({"@type": "MusicEvent",
                      "name": "guest - Example Room, Example City"}, venue=venue)

    def test_multiple_official_event_cards_remain_ambiguous(self):
        page = html()
        duplicate = html(title="Other Gig")
        with self.assertRaises(ValueError):
            oa.verified_bill(page + duplicate, URL, DATE, VENUE)


if __name__ == "__main__":
    unittest.main()
