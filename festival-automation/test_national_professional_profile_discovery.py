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

    def test_inclusive_french_profile_counts_are_not_identity(self):
        for count in ("84 abonné·e·s 5 évènements", "1 abonné 1 évènement",
                      "12 abonnés 2 événements"):
            with self.subTest(count=count):
                page = EVENT_PAGE.replace("27 followers 3 events", count)
                result = discover(HINTS, TITLE, 2027, fetch=lambda url:
                    {FEST: page, PROFILE: PROFILE_PAGE}[url])
                self.assertEqual(result["status"], "PROFESSIONAL_WEBSITE_HINTS")
                self.assertEqual(result["websites"][0]["website_url"], SITE)
        for suffix in ("84 abonné·e·s 5 évènements autre organisateur",
                       "Autre production 84 abonné·e·s"):
            page = EVENT_PAGE.replace("27 followers 3 events", suffix)
            result = discover(HINTS, TITLE, 2027, fetch=lambda url:
                {FEST: page, PROFILE: PROFILE_PAGE}[url])
            self.assertEqual(result["websites"], [])

    def test_provider_pass_heading_has_generic_festival_suffix(self):
        page = EVENT_PAGE.replace("Festival des Rives</h1>",
            "Ombres du Nord Festival 2027 - 4j Pass (4-Events)</h1>")
        result = discover(HINTS, "Ombres du Nord 2027", 2027,
                          fetch=lambda url: {FEST: page, PROFILE: PROFILE_PAGE}[url])
        self.assertEqual(result["status"], "PROFESSIONAL_WEBSITE_HINTS")
        self.assertEqual(result["websites"][0]["website_url"], SITE)
        wrong = page.replace("Ombres du Nord", "Ombres du Sud")
        result = discover(HINTS, "Ombres du Nord 2027", 2027,
                          fetch=lambda url: {FEST: wrong, PROFILE: PROFILE_PAGE}[url])
        self.assertEqual(result["websites"], [])

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

    def test_diagnostics_distinguish_transport_heading_year_and_backlink(self):
        from dns_pinned_https import OfficialHTTPStatusError
        def fetch(url):
            if url == EVENT:
                raise OfficialHTTPStatusError(404)
            return {FEST: EVENT_PAGE, PROFILE: PROFILE_PAGE.replace(
                "festival-des-rives", "autre-festival")}[url]
        result = discover(HINTS, TITLE, 2027, fetch=fetch)
        self.assertEqual(result["diagnostics"], [
            {"stage": "TICKET_EVENTS", "outcome": "HTTP_STATUS_REJECTED", "http_status": 404},
            {"stage": "TICKET_FESTIVALS", "outcome": "PROFILES_FOUND", "profile_count": 1},
            {"stage": "PROFILE", "outcome": "EXACT_EVENT_BACKLINK_ABSENT"}])
        self.assertEqual(result["websites"], [])
        for page, reason in (
                (EVENT_PAGE.replace("Festival des Rives", "Autre festival"), "EVENT_HEADING_MISMATCH"),
                (EVENT_PAGE.replace("2027", "2028"), "EVENT_YEAR_NOT_VISIBLE")):
            result = discover(HINTS, TITLE, 2027, fetch=lambda _: page)
            self.assertTrue(all(d["outcome"] == reason for d in result["diagnostics"]))
            self.assertEqual(result["websites"], [])
        self.assertLessEqual(len(result["diagnostics"]), 5)

    def test_429_defers_same_host_without_spending_other_dossier_budget(self):
        from dns_pinned_https import OfficialHTTPStatusError
        blocked = set()
        calls = []
        def fetch(url):
            calls.append(url)
            from urllib.parse import urlsplit
            if urlsplit(url).hostname == "billetterie.fr":
                raise OfficialHTTPStatusError(429)
            return "<h1>Autre événement</h1>"
        result = discover(HINTS, TITLE, 2027, fetch=fetch,
                          rate_limited_hosts=blocked)
        self.assertEqual(calls, [EVENT])
        self.assertEqual(result["requests"], 1)
        self.assertEqual(result["status"], "PROFESSIONAL_RATE_LIMITED")
        self.assertEqual(result["diagnostics"], [
            {"stage": "TICKET_EVENTS", "outcome": "HTTP_STATUS_REJECTED", "http_status": 429}])
        self.assertEqual(blocked, {"billetterie.fr"})
        other = dict(HINTS, links=[
            {"field": "registration", "url": EVENT.replace("festival-des-rives", "festival-du-nord")},
            {"field": "links", "url": "https://autre-billetterie.fr/events/festival-des-rives"}])
        result = discover(other, TITLE, 2027, fetch=fetch,
                          rate_limited_hosts=blocked)
        self.assertEqual(result["requests"], 2)
        self.assertEqual(len(calls), 3)
        self.assertTrue(all("autre-billetterie.fr" in url for url in calls[1:]))
        self.assertEqual(result["websites"], [])
        self.assertFalse(result["publication_authorized"])
        # A later independent collection can retry normally.
        result = discover(HINTS, TITLE, 2027,
                          fetch=lambda url: {FEST: EVENT_PAGE, PROFILE: PROFILE_PAGE}[url])
        self.assertEqual(result["status"], "PROFESSIONAL_WEBSITE_HINTS")

    def test_total_budget_and_no_cross_host_profile(self):
        other = EVENT_PAGE.replace("/fr/venues/production-des-rives",
                                   "https://other.fr/venues/production-des-rives")
        result = discover(HINTS, TITLE, 2027, fetch=lambda _: other)
        self.assertEqual(result["requests"], 2)
        self.assertEqual(result["websites"], [])

if __name__ == "__main__":
    unittest.main()
