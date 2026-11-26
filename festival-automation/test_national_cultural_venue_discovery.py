"""Offline contract for ministry cultural registry -> independent official detail."""
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from national_cultural_venue_discovery import cultural_detail, registry_path, PAGE_SIZE

DAY = "2026-11-26"
TITLE = "Festival des Rives 2027"
ROOT = "https://salle-des-rives.fr/"
DETAIL = ROOT + "festival-des-rives/"
TICKET = "https://billetterie.fr/festivals/festival-des-rives"
LEAD = {"city_hint_review_only": "Exemple", "region_hint": "Île-de-France",
        "professional_source_hints_review_only": {
            "location_name": None, "originagenda_title": None, "verified": False,
            "links": [{"field": "registration", "url": TICKET.replace("/festivals/", "/events/")}]}}
ROW = {"commune": "EXEMPLE", "region": "Île-de-France", "code_commune": "93000",
       "domaines": '["Arts du spectacle"]', "sous_domaines": '["Cabaret"]',
       "site_internet_et_autres_liens": [ROOT, "https://127.0.0.1/", "https://facebook.com/exemple"]}
HTML = ('<main><h1>Festival des Rives 2027</h1>'
        '<p>Festival des Rives : les 4 et 5 juin 2027, festival metal et punk.</p>'
        '<a href="' + TICKET + '">Billetterie</a></main>')
PAGES = {ROOT: '<h1>Salle des Rives</h1><a href="/festival-des-rives/">Festival des Rives 2027</a>',
         DETAIL: HTML}

def registry(city, region, page):
    assert (city, region, page) == ("Exemple", "Île-de-France", 1)
    return {"meta": {"page": 1, "page_size": PAGE_SIZE, "total": 1}, "data": [ROW]}

class CulturalVenueDiscoveryTests(unittest.TestCase):
    def test_fixed_registry_and_official_venue_backlink_without_ticket_request(self):
        query = parse_qs(urlsplit(registry_path("Exemple", "Île-de-France")).query)
        self.assertEqual(query["commune__exact"], ["EXEMPLE"])
        self.assertEqual(query["domaines__contains"], ["Arts du spectacle"])
        self.assertIsNone(registry_path("Exemple&inject=x", "Île-de-France"))
        self.assertIsNone(registry_path("Exemple", "other"))
        calls = []
        def fetch(url):
            calls.append(url)
            return PAGES[url]
        report = cultural_detail(LEAD, TITLE, 2027, DAY, fetch=fetch, registry_fetch=registry)
        self.assertEqual(report["status"], "OFFICIAL_DETAIL_PROOF_REVIEW_ONLY")
        self.assertEqual(report["proofs"], [{"official_detail_url": DETAIL, "ticket_url": TICKET,
            "start_date": "2027-06-04", "end_date": "2027-06-05", "publication_authorized": False}])
        self.assertEqual(calls, [ROOT, DETAIL])
        self.assertFalse(report["publication_authorized"])
        self.assertEqual(report["registry_requests"], 1)

    def test_wrong_city_category_or_ticket_cannot_qualify(self):
        for changed in (dict(ROW, commune="AUTRE"), dict(ROW, region="Corse"),
                        dict(ROW, domaines='["Patrimoine"]')):
            result = cultural_detail(LEAD, TITLE, 2027, DAY, fetch=lambda _: self.fail("unsafe read"),
                registry_fetch=lambda *args: {"meta": {"page": 1, "page_size": PAGE_SIZE, "total": 1},
                                              "data": [changed]})
            self.assertEqual(result["proofs"], [])
        pages = dict(PAGES, **{DETAIL: HTML.replace(TICKET, TICKET + "-autre")})
        self.assertEqual(cultural_detail(LEAD, TITLE, 2027, DAY, fetch=pages.__getitem__,
                                        registry_fetch=registry)["proofs"], [])

    def test_publisher_reconstructs_fallback_from_fresh_public_record(self):
        from national_professional_publisher_provenance import prove
        event = "https://openagenda.com/agenda/events/festival-des-rives"
        record = {"title_fr": "Festival des Rives", "canonicalurl": event,
                  "firstdate_begin": "2027-06-04", "lastdate_begin": "2027-06-05",
                  "location_countrycode": "FR", "location_city": "Exemple",
                  "location_region": "Île-de-France", "description_fr": "Festival metal et punk",
                  "registration": [{"type": "link", "value": TICKET}]}
        with patch("national_professional_publisher_provenance.discover", return_value={}), \
                patch("national_professional_publisher_provenance.examine",
                      return_value={"status": "NO_OFFICIAL_DETAIL_PROOF"}), \
                patch("national_professional_publisher_provenance.cultural_detail",
                      side_effect=lambda *args, **kw: cultural_detail(*args, **kw, registry_fetch=registry)):
            proofs = prove(event, TITLE, DAY, record_fetch=lambda _: {
                "total_count": 1, "results": [record]}, fetch=PAGES.__getitem__)
        self.assertEqual(len(proofs), 1)
        self.assertEqual(proofs[0]["official_detail_url"], DETAIL)

if __name__ == "__main__":
    unittest.main()
