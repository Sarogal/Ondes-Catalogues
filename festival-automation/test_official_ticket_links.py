"""No ticket link is ever evidence of ticket availability or permission."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, str(Path(__file__).parent))
from official_ticket_links import provider_for_host, ticket_link_leads
from official_watch import PAGES, GIT, ORIGIN, choose_sources, permitted_url, run


class TicketLinkLeadTests(unittest.TestCase):
    def test_only_known_provider_hosts_are_selected(self):
        html = ('<a href="https://www.helloasso.com/associations/metal/evenements/fest">Billets</a>'
                '<a href="https://www.billetweb.fr/metal2027?token=SECRET#top">Vente</a>'
                '<a href="https://shotgun.live/events/fest2027">Shotgun</a>'
                '<a href="https://helloasso.com.evil.org/associations/fake">Faux</a>'
                '<a href="javascript:alert(1)">Script</a>'
                '<a href="http://billetweb.fr/fest">Non sécurisé</a>')
        found = ticket_link_leads(html, "https://festival.fr/", permitted_url)
        self.assertEqual([r["provider"] for r in found],
                         ["HelloAsso", "Billetweb", "Shotgun"])
        self.assertEqual(found[1]["ticket_url"], "https://www.billetweb.fr/metal2027")
        self.assertTrue(all(r["publication_authorized"] is False for r in found))

    def test_weezevent_and_other_referenced_official_vendors_are_review_only(self):
        """Only explicit HTTPS organizer links count, no stock inferred."""
        urls = [
            ("https://my.weezevent.com/festival-x", "Weezevent"),
            ("https://www.weezevent.com/festival-y", "Weezevent"),
            ("https://billetterie.festik.net/festival-z", "Festik"),
            ("https://www.fnacspectacles.com/event/festival-metal", "Fnac Spectacles"),
            ("https://lempreinte.mapado.com/en/event/724833-charitable-metal-fest-ashen-guests", "Mapado"),
        ]
        html = "".join('<a href="' + url + '?utm_campaign=demo">' + name + '</a>'
                       for url, name in urls)
        found = ticket_link_leads(html, "https://festival.fr/", permitted_url)
        self.assertEqual([(row["ticket_url"], row["provider"]) for row in found], urls)
        self.assertTrue(all(row["publication_authorized"] is False
                            and row["verification_status"] == "LINK_ONLY"
                            for row in found))

    def test_provider_domains_are_not_substring_matched(self):
        self.assertIsNone(provider_for_host("fake-weezevent.com"))
        self.assertIsNone(provider_for_host("weezevent.com.evil.example"))
        self.assertIsNone(provider_for_host("fnacspectacles.com.evil.example"))
        self.assertIsNone(provider_for_host("fakefestik.net"))
        self.assertIsNone(provider_for_host("lempreinte.mapado.com.evil.fr"))
        self.assertEqual(provider_for_host("lempreinte.mapado.com"), "Mapado")
        self.assertIsNone(provider_for_host("weezevent.com:8080"))
        self.assertEqual(provider_for_host("my.weezevent.com"), "Weezevent")

    def test_duplicate_and_homepage_are_rejected(self):
        html = ('<a href="https://billetweb.fr/">Accueil</a>'
                '<a href="https://billetweb.fr/fest?utm_source=test">Acheter</a>'
                '<a href="https://billetweb.fr/fest?code=abc">Acheter</a>')
        found = ticket_link_leads(html, "https://fest.fr/", permitted_url)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["ticket_url"], "https://billetweb.fr/fest")

    def test_host_prefix_is_not_trusted(self):
        self.assertIsNone(provider_for_host("billetweb.fr.attacker.net"))
        self.assertIsNone(provider_for_host("myhelloasso.com"))
        self.assertEqual(provider_for_host("www.helloasso.com"), "HelloAsso")
        self.assertEqual(ticket_link_leads(
            '<a href="https://127.0.0.1/steal">Click</a>',
            "https://fest.fr/", permitted_url), [])

    def test_bad_source_or_volume_cannot_produce_leads(self):
        html = '<a href="https://shotgun.live/events/fest">Billets</a>'
        self.assertEqual(ticket_link_leads(html, "http://fest.fr", permitted_url), [])
        self.assertEqual(ticket_link_leads("a" * 650001 + html,
                                            "https://fest.fr", permitted_url), [])

    def test_live_watch_records_review_leads_without_publish_or_patch(self):
        doc = {"schema": 1, "generatedAt": "2026-11-04", "festivals": [
            {"slug": "test-" + str(i), "name": "Festival test",
             "startDate": "2027-06-10", "endDate": "2027-06-11",
             "officialSite": "https://fest" + str(i) + ".fr/"}
            for i in range(90)
        ]}
        slug, site = choose_sources(doc, date(2026, 11, 4), limit=1)[0]
        html = ("<p>" + "Le vrai programme du festival. " * 8 + "</p>"
                '<a href="https://www.billetweb.fr/festival-demo">Billetterie</a>')
        with tempfile.TemporaryDirectory() as tmp:
            report = run(Path(tmp), "2026-11-04", limit=1,
                         download_json=lambda u: doc,
                         download_page=lambda u: html)
            leads = report["ticket_link_leads_review_only"]
            self.assertEqual(len(leads), 1)
            self.assertEqual(leads[0]["slug"], slug)
            self.assertEqual(leads[0]["source_url"], site)
            self.assertEqual(leads[0]["verification_status"], "LINK_ONLY")
            self.assertEqual(report["ticketProposalCount"], 0)
            self.assertEqual(report["publishedChanges"], 0)
            self.assertFalse((Path(tmp) / "patch-2026-11-04.json").exists())


if __name__ == "__main__":
    unittest.main()
