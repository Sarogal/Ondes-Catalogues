"""Offline rehearsal of generic professional profile research (not publication)."""
import unittest
from national_professional_profile_discovery import discover, ticket_variants

TITLE = "Festival des Rives 2027"
EVENT = "https://billetterie.fr/events/festival-des-rives"
FEST = "https://billetterie.fr/festivals/festival-des-rives"
PROFILE = "https://billetterie.fr/fr/venues/production-des-rives"
SITE = "https://production-des-rives.fr/"
HINTS = {"location_name": None, "originagenda_title": None, "verified": False,
         "links": [{"field": "registration", "url": EVENT}]}
EVENT_PAGE = '<h1>Festival des Rives</h1><p>6 février 2027</p><a href="/fr/venues/production-des-rives">Production des Rives 27 followers 3 events</a>'
PROFILE_PAGE = '<h1>Production des Rives</h1><a href="https://production-des-rives.fr/">production-des-rives.fr</a><a href="/fr/festivals/festival-des-rives">Festival des Rives</a>'

class ProfessionalProfileDiscoveryTests(unittest.TestCase):
    def test_alternate_ticket_route_and_profile_backlink(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return {FEST: EVENT_PAGE, PROFILE: PROFILE_PAGE}[url]
        result = discover(HINTS, TITLE, 2027, fetch=fetch)
        self.assertEqual(calls, [EVENT, FEST, PROFILE])
        self.assertEqual(result["status"], "PROFESSIONAL_WEBSITE_HINTS")
        self.assertEqual(result["websites"], [{"ticket_url": FEST, "profile_url": PROFILE,
            "website_url": SITE, "verified": False, "publication_authorized": False}])
        self.assertFalse(result["publication_authorized"])
        self.assertNotIn(SITE, calls)

    def test_wrong_event_and_hidden_profile_do_not_trigger_fetch(self):
        for html in (EVENT_PAGE.replace("Festival des Rives", "Festival du Nord"),
                     EVENT_PAGE.replace("<a ", "<a hidden ")):
            calls = []
            def fetch(url):
                calls.append(url)
                return html
            result = discover(HINTS, TITLE, 2027, fetch=fetch)
            self.assertNotIn(PROFILE, calls)
            self.assertEqual(result["websites"], [])

    def test_unrelated_or_wrong_profile_and_unsafe_url_rejected(self):
        for page in (PROFILE_PAGE.replace("festival-des-rives", "festival-du-nord"),
                     PROFILE_PAGE.replace("<h1>Production des Rives", "<h1>Autre production"),
                     PROFILE_PAGE.replace(SITE, "https://127.0.0.1/")):
            def fetch(url):
                return {FEST: EVENT_PAGE, PROFILE: page}[url]
            self.assertEqual(discover(HINTS, TITLE, 2027, fetch=fetch)["websites"], [])
        self.assertEqual(ticket_variants("https://127.0.0.1/events/festival-des-rives"), [])
        forged = dict(HINTS, verified=True)
        self.assertEqual(discover(forged, TITLE, 2027, fetch=lambda _: self.fail("unsafe fetch"))["requests"], 0)

    def test_retry_when_first_event_route_has_no_profiles(self):
        pages = {EVENT: '<h1>Festival des Rives</h1><p>Festival annoncé le 6 février 2027</p>',
                 FEST: EVENT_PAGE, PROFILE: PROFILE_PAGE}
        calls = []
        def fetch(url):
            calls.append(url)
            return pages[url]
        result = discover(HINTS, TITLE, 2027, fetch=fetch)
        self.assertEqual(calls, [EVENT, FEST, PROFILE])
        self.assertEqual(result["status"], "PROFESSIONAL_WEBSITE_HINTS")

    def test_total_budget_and_no_cross_host_profile(self):
        other = EVENT_PAGE.replace("/fr/venues/production-des-rives",
                                   "https://other.fr/venues/production-des-rives")
        result = discover(HINTS, TITLE, 2027, fetch=lambda _: other)
        self.assertEqual(result["requests"], 2)
        self.assertEqual(result["websites"], [])

if __name__ == "__main__":
    unittest.main()
