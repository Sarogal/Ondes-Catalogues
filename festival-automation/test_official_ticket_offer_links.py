"""Official schema.org ticket links are leads, never ticket availability."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, str(Path(__file__).parent))
from official_ticket_offer_links import structured_offer_links
from official_watch import choose_sources, permitted_url, run


def event_html(name="UNFEST #3 2026", start="2026-11-06",
               end="2026-11-07", offers=None, status=None):
    event = {"@type": "MusicEvent", "name": name,
             "startDate": start, "endDate": end,
             "offers": offers if offers is not None else []}
    if status is not None:
        event["eventStatus"] = status
    return ("<main>" + "Programmation officielle de cet événement. " * 5 +
            "</main><script type='application/ld+json'>" +
            json.dumps({"@graph": [event]}) + "</script>")


def edition():
    return {"slug": "unfest-3-2026", "name": "UNFEST #3",
            "startDate": "2026-11-06", "endDate": "2026-11-07",
            "officialSite": "https://mjcdouai.fr/unfest/"}


class OfficialOfferLinksTests(unittest.TestCase):
    def leads(self, html, festival=None):
        festival = edition() if festival is None else festival
        return structured_offer_links(
            html, festival["officialSite"], festival, permitted_url)

    def test_exact_event_uses_offer_url_without_transferring_inventory(self):
        offers = [
            {"name": "Pass 2 jours", "url": "https://my.weezevent.com/unfest-2026?code=PRIVATE",
             "availability": "https://schema.org/SoldOut"},
            {"name": "Vendredi", "url": "https://www.helloasso.com/associations/test/evenements/unfest"}
        ]
        result = self.leads(event_html(offers=offers))
        self.assertEqual([r["provider"] for r in result], ["Weezevent", "HelloAsso"])
        self.assertEqual(result[0]["ticket_url"], "https://my.weezevent.com/unfest-2026")
        self.assertTrue(all(r["link_origin"] == "schema_org_offer_url" for r in result))
        self.assertTrue(all(r["verification_status"] == "LINK_ONLY"
                            and r["publication_authorized"] is False for r in result))
        self.assertFalse(any("availability" in r or "categories" in r for r in result))

    def test_wrong_name_date_or_sensitive_status_blocks_lead(self):
        offer = {"url": "https://my.weezevent.com/unfest"}
        for html in (event_html(name="UNFEST #4 2026", offers=offer),
                     event_html(start="2025-11-06", offers=offer),
                     event_html(end="2026-11-08", offers=offer),
                     event_html(status="https://schema.org/EventCancelled", offers=offer),
                     event_html(status="https://schema.org/EventPostponed", offers=offer),
                     event_html(status="https://schema.org/EventRescheduled", offers=offer)):
            self.assertEqual(self.leads(html), [])

    def test_host_bypass_http_secrets_and_generic_homepage_are_excluded(self):
        offers = [
            {"url": "https://my.weezevent.com.evil.fr/steal"},
            {"url": "http://my.weezevent.com/unsafe"},
            {"url": "https://customer:password@my.weezevent.com/ticket"},
            {"url": "https://127.0.0.1/private"},
            {"url": "https://www.weezevent.com/"},
            {"url": "https://www.billetweb.fr/ok?token=SECRET#secret"},
            {"url": "https://www.billetweb.fr/ok?token=OTHER"},
        ]
        result = self.leads(event_html(offers=offers))
        self.assertEqual(result, [{
            "ticket_url": "https://www.billetweb.fr/ok",
            "provider": "Billetweb",
            "verification_status": "LINK_ONLY",
            "publication_authorized": False,
            "link_origin": "schema_org_offer_url",
        }])

    def test_shared_official_page_only_matches_corresponding_edition(self):
        a = edition()
        b = {**a, "slug": "other-festival-2026", "name": "Autre Festival",
             "startDate": "2026-12-01", "endDate": "2026-12-02"}
        html = event_html(offers={"url": "https://my.weezevent.com/unfest"})
        self.assertEqual(len(self.leads(html, a)), 1)
        self.assertEqual(self.leads(html, b), [])

    def test_full_watch_deduplicates_anchor_and_jsonld_and_never_publishes(self):
        rows = [{
            "slug": "festival-" + str(i), "name": "Festival Test",
            "startDate": "2027-06-10", "endDate": "2027-06-11",
            "officialSite": "https://festival" + str(i) + ".fr/"
        } for i in range(90)]
        doc = {"schema": 1, "generatedAt": "2026-11-04", "festivals": rows}
        html = (event_html(name="Festival Test 2027",
                           start="2027-06-10", end="2027-06-11",
                           offers={"url": "https://my.weezevent.com/test"})
                + '<a href="https://my.weezevent.com/test?token=PRIVATE">Billetterie</a>')
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            report = run(folder, "2026-11-04", limit=1,
                         download_json=lambda u: doc,
                         download_page=lambda u: html)
            links = report["ticket_link_leads_review_only"]
            self.assertEqual(len(links), 1)
            self.assertEqual(links[0]["link_origin"], "schema_org_offer_url")
            self.assertEqual(links[0]["ticket_url"], "https://my.weezevent.com/test")
            self.assertEqual(report["ticketProposalCount"], 0)
            self.assertEqual(report["publishedChanges"], 0)
            self.assertFalse((folder / "patch-2026-11-04.json").exists())


if __name__ == "__main__":
    unittest.main()
