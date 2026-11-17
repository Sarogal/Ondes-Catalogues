"""Offline adversarial municipal listing discovery. Test sessions are fictitious."""
from datetime import date
from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_mpt_listing_discovery import (
    LISTING_URL, MAX_LINKS, extract_detail_links,
    discover_listing, trusted_detail,
)
from ptitesondes_real_family_source_adapters import (
    parse_montpellier_mpt_detail,
)

TODAY = date(2026, 11, 17)
GOOD = "https://mpt.montpellier.fr/evenement/atelier-dessin-enfants"
OTHER = "https://mpt.montpellier.fr/evenement/cinema-jeunesse"
ADULT = "https://mpt.montpellier.fr/evenement/activite-adultes"
PAGE = """<html><head><title>Maison pour tous</title></head><body>
<h1>Événements</h1><div><a href="/evenement/atelier-dessin-enfants">Atelier</a>
<a href="/evenement/cinema-jeunesse">Film</a>
<a href="/evenement/atelier-dessin-enfants">Duplicate</a>
<a href="/evenement/activite-adultes">Adultes</a>
</div></body></html>"""
FAMILY_DETAIL = """<html><h1>Atelier dessin enfants</h1>
<p>Atelier pour les enfants en famille</p>
<p>Lieu : Maison pour tous Albert Camus</p>
<ul><li>18 novembre 2026 - 10:00 > 11:00</li>
<li>25 novembre 2026 - 10:00 > 11:00</li></ul>
<p>Sur inscription | Gratuit</p></html>"""
CINEMA_DETAIL = """<html><h1>Cinéma jeunesse</h1>
<p>Séance réservée aux familles et aux enfants</p>
<p>Lieu : Maison pour tous Frida Kahlo</p>
<li>18 novembre 2026 - 15:00 > 16:30</li></html>"""
ADULT_DETAIL = """<html><h1>Peinture pour les adultes</h1>
<p>Activité adultes uniquement.</p><p>Lieu : Maison pour tous Albert Camus</p>
<li>19 novembre 2026 - 10:00 > 11:00</li></html>"""


ADDRESS_DETAIL = """<html><h1>Méli'Pitchouns : atelier d'éveil et de lecture</h1>
<article><p>Tout-petits, Enfants</p>
<p>Session de lecture des contes pour les enfants, jusqu'à 5 ans</p>
<li>18 novembre 2026 - 10:00 > 11:00</li>
<p>Maison pour tous Mélina Mercouri<br/>
842 Rue de la Vieille Poste<br/>34000 Montpellier</p>
<p>Sur inscription | Gratuit<br/>Carte MPT obligatoire</p></article>
<h2>Autres événements</h2>
<h3>Atelier pour adultes</h3><li>19 novembre 2026 - 16:00 > 17:00</li>
</html>"""
ADDRESS_LINK = "https://mpt.montpellier.fr/evenement/melipitchouns-atelier-deveil-et-de-lecture"


class OfficialAddressPatternTests(unittest.TestCase):
    def test_exact_mpt_street_address_recognized_without_lieu_label(self):
        rows = parse_montpellier_mpt_detail(ADDRESS_DETAIL, ADDRESS_LINK, TODAY)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["venue"], "Maison pour tous Mélina Mercouri")
        self.assertEqual(rows[0]["city"], "Montpellier")
        self.assertEqual(rows[0]["date_start"], "2026-11-18")
        self.assertEqual(rows[0]["start_local"], "10:00")
        self.assertEqual(rows[0]["price_evidence"], "ambiguous")
        self.assertEqual(rows[0]["category"], "lecture-jeunesse")
        self.assertEqual(rows[0]["verification"],
                         "discovery_only_needs_official_and_independent_proof")

    def test_sidebar_future_occurrences_cannot_supply_main_event_dates(self):
        rows = parse_montpellier_mpt_detail(ADDRESS_DETAIL, ADDRESS_LINK, TODAY)
        self.assertEqual([x["date_start"] for x in rows], ["2026-11-18"])

    def test_no_street_or_wrong_city_keeps_venue_unverified(self):
        for change in (
            "842 Rue de la Vieille Poste",
            "34000 Montpellier",
        ):
            html = ADDRESS_DETAIL.replace(change, "unverified")
            self.assertEqual(parse_montpellier_mpt_detail(
                html, ADDRESS_LINK, TODAY), [])

    def test_multiple_conflicting_address_blocks_held(self):
        conflicting = ADDRESS_DETAIL.replace(
            "</article>",
            '<p>Maison pour tous Autre bâtiment<br/>'
            '4 Rue des Peupliers<br/>34000 Montpellier</p></article>')
        self.assertEqual(parse_montpellier_mpt_detail(
            conflicting, ADDRESS_LINK, TODAY), [])

    def test_hidden_or_related_address_does_not_certify_venue(self):
        hidden = ADDRESS_DETAIL.replace(
            '<p>Maison pour tous Mélina Mercouri<br/>',
            '<p hidden>Maison pour tous Mélina Mercouri<br/>')
        self.assertEqual(parse_montpellier_mpt_detail(
            hidden, ADDRESS_LINK, TODAY), [])
        related = ADDRESS_DETAIL.replace(
            "842 Rue de la Vieille Poste<br/>34000 Montpellier",
            "lieu non précisé").replace(
            "<h3>Atelier pour adultes</h3>",
            '<h3>Atelier pour adultes</h3><p>Maison pour tous Mélina Mercouri<br/>'
            '842 Rue de la Vieille Poste<br/>34000 Montpellier</p>')
        self.assertEqual(parse_montpellier_mpt_detail(
            related, ADDRESS_LINK, TODAY), [])

    def test_reserved_to_creches_is_not_open_family_outing(self):
        page = ADDRESS_DETAIL.replace(
            "Session de lecture des contes pour les enfants",
            "Animation réservée aux crèches Thérèse Sentis et Oustal")
        self.assertEqual(parse_montpellier_mpt_detail(
            page, ADDRESS_LINK, TODAY), [])

class MptListingDiscoveryTests(unittest.TestCase):
    def test_read_only_listing_extracts_distinct_detail_links(self):
        self.assertEqual(extract_detail_links(PAGE), [GOOD, OTHER, ADULT])

    def test_unsafe_links_and_forged_domains_not_visited(self):
        untrusted = (
            "<html><h1>Événements</h1>" +
            "".join('<a href="' + x + '">Fake</a>' for x in (
                "https://evil.test/evenement/atelier",
                "//evil.test/evenement/atelier",
                "https://mpt.montpellier.fr.evil.test/evenement/atelier",
                "http://mpt.montpellier.fr/evenement/atelier",
                "https://mpt.montpellier.fr@evil.test/evenement/atelier",
                "/evenements?next=/evenement/atelier",
                "/evenement/foo?admin=1", "/evenement/foo#session",
                "/evenement/",
            )) + "</html>"
        )
        self.assertEqual(extract_detail_links(untrusted), [])
        for bad in ("https://other.test/evenement/x",
                    "https://mpt.montpellier.fr.evil.test/evenement/x",
                    "https://mpt.montpellier.fr/evenements",
                    "https://mpt.montpellier.fr/evenement/x?edit=1"):
            self.assertFalse(trusted_detail(bad))

    def test_hidden_links_not_collected(self):
        html = """<html><h1>Événements</h1>
        <a hidden href="/evenement/hidden">Hidden</a>
        <a aria-hidden="true" href="/evenement/hidden2">Hidden</a>
        <a style="display:none" href="/evenement/hidden3">Hidden</a>
        <script><a href="/evenement/in-script">Not visible</a></script>
        <a href="/evenement/atelier-dessin-enfants">Visible</a></html>"""
        self.assertEqual(extract_detail_links(html), [GOOD])

    def test_actual_detail_page_rechecked_and_occurrences_distinct(self):
        pages = {GOOD: FAMILY_DETAIL, OTHER: CINEMA_DETAIL,
                 ADULT: ADULT_DETAIL}
        seen = []
        def getter(url):
            self.assertIn(url, pages)
            seen.append(url)
            return pages[url]
        leads, report = discover_listing(
            PAGE, today=TODAY, detail_get=getter)
        self.assertEqual(seen, [GOOD, OTHER, ADULT])
        self.assertEqual(len(leads), 3)
        self.assertEqual(report["listed_unique_detail_urls"], 3)
        self.assertEqual(report["explicit_dated_occurrences"], 3)
        self.assertEqual(report["structurally_plausible_for_independent_review"], 3)
        self.assertEqual(report["details_without_explicit_family_session"], 1)
        self.assertEqual({x["date_start"] for x in leads},
                         {"2026-11-18", "2026-11-25"})
        self.assertEqual(sorted(x["category"] for x in leads),
                         ["atelier-creatif", "atelier-creatif", "cinema-jeunesse"])

    def test_bounded_sampling_does_not_infer_remaining_sessions(self):
        seen = []
        leads, report = discover_listing(
            PAGE, today=TODAY, page_limit=1,
            detail_get=lambda url: seen.append(url) or FAMILY_DETAIL)
        self.assertEqual(seen, [GOOD])
        self.assertEqual(len(leads), 2)
        self.assertTrue(report["selected_details_are_sample_only"])
        self.assertEqual(report["selected_detail_pages"], 1)

    def test_fetch_error_deferred_and_not_treated_as_empty_page(self):
        def getter(url):
            if url == OTHER:
                raise OSError("unavailable")
            return FAMILY_DETAIL if url == GOOD else ADULT_DETAIL
        leads, report = discover_listing(
            PAGE, today=TODAY, detail_get=getter)
        self.assertEqual(len(leads), 2)
        self.assertEqual(report["held_unreadable_details"], 1)
        self.assertEqual(report["readable_detail_pages"], 2)
        self.assertFalse(report["publication_ready"])

    def test_report_never_contains_candidate_personal_or_location_details(self):
        leads, report = discover_listing(
            PAGE, today=TODAY, detail_get=lambda url: FAMILY_DETAIL)
        out = json.dumps(report, ensure_ascii=False)
        for forbidden in ("source_url", "Maison pour tous",
                          "Atelier dessin", GOOD, OTHER,
                          '"additions"', '"patch"'):
            self.assertNotIn(forbidden, out)
        for forbidden_key in ("events", "title", "candidates",
                              "source_url", "additions", "patch"):
            self.assertNotIn(forbidden_key, report)
        self.assertEqual(report["public_writes"], 0)
        self.assertEqual(report["private_approvals"], 0)
        self.assertFalse(report["approval_granted_to_publisher"])
        self.assertFalse(report["publisher_connected"])

    def test_refuse_unbounded_and_malformed_requests(self):
        with self.assertRaises(ValueError):
            discover_listing(PAGE, today=TODAY,
                             detail_get=lambda x: FAMILY_DETAIL, page_limit=999)
        with self.assertRaises(ValueError):
            discover_listing(PAGE, today=TODAY,
                             detail_get=None)
        with self.assertRaises(ValueError):
            extract_detail_links("incomplete")
        with self.assertRaises(ValueError):
            extract_detail_links(PAGE, listing_url="https://evil.test/evenements")

    def test_full_twenty_four_page_bound_uses_only_distinct_links(self):
        urls = [
            "https://mpt.montpellier.fr/evenement/session-" + str(n)
            for n in range(24)
        ]
        html = "<html><h1>Événements</h1>" + "".join(
            '<a href="' + url + '">Détail</a>' for url in urls
        ) + "</html>"
        visited = []
        _, report = discover_listing(
            html, today=TODAY, page_limit=24,
            detail_get=lambda url: visited.append(url) or ADULT_DETAIL)
        self.assertEqual(visited, urls)
        self.assertEqual(report["selected_detail_pages"], 24)
        self.assertEqual(report["readable_detail_pages"], 24)
        self.assertEqual(report["explicit_dated_occurrences"], 0)
        self.assertEqual(report["public_writes"], 0)

    def test_no_synthetic_ages_or_geolocation_on_leads(self):
        leads, report = discover_listing(
            PAGE, today=TODAY, page_limit=1,
            detail_get=lambda x: FAMILY_DETAIL)
        for item in leads:
            self.assertNotIn("lat", item)
            self.assertNotIn("lng", item)
            self.assertNotIn("age_min", item)
            self.assertNotIn("age_max", item)
        self.assertEqual(report["independent_geo_verified"], 0)
        self.assertEqual(report["trusted_organisers_authenticated"], 0)


if __name__ == "__main__":
    unittest.main()
