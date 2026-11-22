"""First-party TEC API is evidence, never an event-discovery trust bypass."""
import copy
import json
import unittest

import event_site_pair_recheck as reviewer
import test_event_site_pair_recheck as fx

EVENT_ID = 26788
URL = fx.EVENT
API = "https://7weeks.fr/wp-json/tribe/events/v1/events/" + str(EVENT_ID)
TITLE = "7WEEKS + NEW METAL SUPPORT"


def official_api():
    return {
        "id": EVENT_ID, "url": URL, "status": "publish",
        "title": TITLE, "start_date": fx.DATE + " 20:00:00",
        "timezone": "Europe/Paris",
        "description": (
            '<p><strong>7WEEKS — Heavy Metal | Paris</strong></p>'
            '<p><strong>NEW METAL SUPPORT — Metalcore | France</strong></p>'
        ),
        "venue": {
            "venue": "Esplanade des Tests", "address": "Avenue des Essais",
            "city": "Paris", "zip": "75007",
            "country": "France", "province": "Île-de-France",
        },
    }


def page(*, title=TITLE, postid=EVENT_ID, bill=True):
    html = (
        '<html><body class="single-tribe_events postid-' + str(postid) +
        '"><main><h1>' + title + '</h1></main></body></html>'
    )
    if not bill:
        return html + '<script type="application/ld+json">' + json.dumps({
            "@type": "Event", "name": TITLE, "url": URL,
            "startDate": fx.DATE, "performer": [{
                "@type": "MusicGroup", "name": "False performer"}],
        }) + '</script>'
    return html


def fetch(api):
    def get(request):
        if request != API:
            raise AssertionError("Unexpected or cross-origin TEC URL: " + request)
        return json.dumps(api, ensure_ascii=False)
    return get


class FirstPartyTecProof(unittest.TestCase):
    def test_exact_first_party_api_restores_complete_artist_roster(self):
        lead, raw, _, _ = fx.fixture()
        result = reviewer._official_event(
            lead, page(), URL, fx.DAY, first_party_fetch=fetch(official_api()))
        self.assertEqual(result[1], ["7WEEKS", "NEW METAL SUPPORT"])
        self.assertEqual(result[3], ["Heavy Metal", "Metalcore"])
        self.assertEqual(result[4]["postalCode"], "75007")
        self.assertEqual(result[4]["city"], "Paris")
        self.assertEqual(result[0]["url"], URL)

    def test_negative_api_identity_event_date_and_venue_fail_closed(self):
        lead, _, _, _ = fx.fixture()
        for change in (
            {"id": 1234},
            {"url": "https://other-official.example/event/"},
            {"status": "draft"},
            {"start_date": "2027-05-18 20:00:00"},
            {"title": "Unrelated Group"},
            {"description": '<p><strong>7WEEKS — Techno</strong></p>'},
            {"description": (
                '<p><strong>7WEEKS — Heavy Metal</strong></p>'
                '<p><strong>Unannounced band — Metalcore</strong></p>')},
            {"venue": dict(official_api()["venue"], city="Lyon")},
            {"venue": dict(official_api()["venue"], country="Belgique")},
            {"venue": dict(official_api()["venue"], zip="99999")},
        ):
            with self.subTest(change=list(change)):
                data = dict(official_api(), **change)
                with self.assertRaises(ValueError):
                    reviewer._official_event(
                        lead, page(), URL, fx.DAY, first_party_fetch=fetch(data))

    def test_page_post_id_h1_and_missing_venue_country_are_not_inferred(self):
        lead, _, _, _ = fx.fixture()
        for html in (
            page(title="Unrelated concert"), page(postid=26789),
            page().replace("postid-26788", "postid-26788 postid-26789"),
            page().replace("<h1>", "<h1>Unrelated</h1><h1>"),
        ):
            with self.subTest(html=html[:95]), self.assertRaises(ValueError):
                reviewer._official_event(
                    lead, html, URL, fx.DAY,
                    first_party_fetch=fetch(official_api()))
        countryless = official_api()
        countryless["venue"].pop("country")
        with self.assertRaises(ValueError):
            reviewer._official_event(lead, page(), URL, fx.DAY,
                                     first_party_fetch=fetch(countryless))

    def test_preexisting_contradictory_schema_may_never_be_masked_by_api(self):
        lead, raw, _, _ = fx.fixture()
        wrong = dict(raw, startDate="2027-05-18", performer=None)
        html = page() + '<script type="application/ld+json">' + json.dumps(
            wrong) + '</script>'
        with self.assertRaises(ValueError):
            reviewer._official_event(
                lead, html, URL, fx.DAY,
                first_party_fetch=fetch(official_api()))
        # If a structured artist roster exists, the API cannot replace it.
        with self.assertRaises(ValueError):
            reviewer._official_event(
                lead, page(bill=False), URL, fx.DAY,
                first_party_fetch=lambda u: self.fail(
                    "Nonempty structured artist evidence cannot be replaced"))

    def test_agenda_does_not_override_cancelled_or_festival_claims(self):
        lead, raw, _, _ = fx.fixture()
        cancelled = dict(raw, performer=None,
                         eventStatus="https://schema.org/EventCancelled")
        html = page() + '<script type="application/ld+json">' + json.dumps(
            cancelled) + '</script>'
        with self.assertRaises(ValueError):
            reviewer._official_event(
                lead, html, URL, fx.DAY,
                first_party_fetch=fetch(official_api()))
        festival = dict(official_api(), title="7WEEKS FESTIVAL")
        with self.assertRaises(ValueError):
            reviewer._official_event(
                dict(lead, name="7WEEKS FESTIVAL"), page(title="7WEEKS FESTIVAL"),
                URL, fx.DAY, first_party_fetch=fetch(festival))


if __name__ == "__main__":
    unittest.main()
