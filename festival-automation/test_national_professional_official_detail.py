"""Synthetic offline professional detail research, never production data."""
import unittest
from copy import deepcopy
from national_professional_official_detail import examine, MAX_PAGES

TITLE = "Festival des Rives 2027"
TODAY = "2026-11-26"
ROOT = "https://salle-des-rives.fr/"
INDEX = ROOT + "agenda/"
DETAIL = ROOT + "festival-des-rives/"
TICKET = "https://billetterie.fr/festivals/festival-des-rives"
RESEARCH = {"status": "PROFESSIONAL_WEBSITE_HINTS", "review_only": True,
            "safe_to_publish": False, "publication_authorized": False,
            "websites": [{"website_url": ROOT, "ticket_url": TICKET,
                          "verified": False, "publication_authorized": False}]}
HTML = ('<main><h1>Festival des Rives 2027</h1>'
        '<p>Festival des Rives : les 4 et 5 juin 2027, festival metal et punk.</p>'
        '<a href="' + TICKET + '">Billetterie</a></main>')
PAGES = {ROOT: '<h1>Salle des Rives</h1><a href="/agenda/">Agenda</a>',
         INDEX: '<h1>Agenda</h1><p>Concert 3 mai 2027</p>'
                '<a href="/festival-des-rives/">Festival des Rives 2027</a>'
                '<p>Autre concert 19 août 2027</p>', DETAIL: HTML}

class OfficialDetailResearchTests(unittest.TestCase):
    def run_pages(self, pages, research=RESEARCH):
        calls = []
        def fetch(url):
            calls.append(url)
            return pages[url]
        return examine(research, TITLE, 2027, TODAY, fetch=fetch), calls

    def test_exact_named_detail_ignores_unrelated_calendar_dates(self):
        result, calls = self.run_pages(PAGES)
        self.assertEqual(calls, [ROOT, INDEX, DETAIL])
        self.assertEqual(result["status"], "OFFICIAL_DETAIL_PROOF_REVIEW_ONLY")
        self.assertEqual(result["proofs"], [{"official_detail_url": DETAIL,
                         "ticket_url": TICKET, "start_date": "2027-06-04",
                         "end_date": "2027-06-05", "publication_authorized": False}])
        self.assertFalse(result["publication_authorized"])

    def test_wrong_identity_or_ticket_or_genre_never_qualifies(self):
        for html in (HTML.replace("<h1>Festival des Rives 2027</h1>", "<h1>Autre festival</h1>"),
                     HTML.replace(TICKET, TICKET + "-autre"),
                     HTML.replace("metal et punk", "techno et house"),
                     HTML.replace("<a href=", "<a hidden href=")):
            result, _ = self.run_pages(dict(PAGES, **{DETAIL: html}))
            self.assertEqual(result["proofs"], [])

    def test_conflicting_details_do_not_qualify(self):
        other = ROOT + "festival-des-rives-bis/"
        pages = dict(PAGES)
        pages[INDEX] += '<a href="' + other + '">Festival des Rives 2027</a>'
        pages[other] = HTML.replace("4 et 5 juin", "11 et 12 juin")
        result, _ = self.run_pages(pages)
        self.assertEqual(result["proofs"], [])

    def test_hidden_or_cross_origin_link_not_followed(self):
        pages = dict(PAGES)
        pages[INDEX] = ('<a hidden href="/festival-des-rives/">Festival des Rives</a>'
                        '<a href="https://autre.fr/festival-des-rives/">Festival des Rives</a>')
        result, calls = self.run_pages(pages)
        self.assertEqual(calls, [ROOT, INDEX])
        self.assertEqual(result["proofs"], [])

    def test_request_budget_and_untrusted_input(self):
        pages = dict(PAGES)
        pages[INDEX] = "".join('<a href="/festival-%s/">Festival des Rives</a>' % i
                               for i in range(20))
        result, calls = self.run_pages(pages)
        self.assertLessEqual(len(calls), MAX_PAGES)
        self.assertEqual(result["proofs"], [])
        forged = deepcopy(RESEARCH)
        forged["publication_authorized"] = True
        result, calls = self.run_pages(PAGES, forged)
        self.assertEqual(calls, [])
        self.assertEqual(result["proofs"], [])

if __name__ == "__main__":
    unittest.main()
