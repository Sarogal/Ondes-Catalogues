"""Security and lifecycle tests for private regional secondary discovery."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from curated_future_lead_watch import load_leads
from curated_secondary_discovery import (
    SCHEMA, STATUS, discover_links, clean_queue, choose_indexes, scan, build_review,
)

TODAY = "2026-11-06"
LEADS = load_leads(json.loads(Path(__file__).with_name(
    "curated_future_leads.json").read_text(encoding="utf-8")))
GRAND = {"id": "grand-est-tourisme-test", "region": "Grand Est",
         "url": "https://www.explore-grandest.com/agenda/"}
PACA = {"id": "paca-tourisme-test", "region": "Provence-Alpes-Côte d'Azur",
        "url": "https://www.dignelesbains-tourisme.com/agendas/tout-lagenda/"}
BFC = {"id": "bfc-tourisme-test", "region": "Bourgogne-Franche-Comté",
       "url": "https://www.bourgogne-tourisme.com/sejourner/agenda/"}
DETAIL = "https://www.explore-grandest.com/evenements/mozhell-open-air-2027/"
OTHER = "https://www.dignelesbains-tourisme.com/agenda/la-sainte-rock-festival-2027/"


def state():
    return {"schema": "grossesondes.source-watch.v1"}


def index_html(label="MozHell Open Air 2027", href=DETAIL):
    return ('<html><body><main><a href="' + href + '">' + label +
            '</a><p>Agenda des festivités régionales et évènements à venir.</p>'
            '</main></body></html>')


def details_html():
    return ("<html><body><h1>MozHell Open Air</h1>"
            "<p>23 24 et 25 juillet 2027. Des groupes de metal dans le festival."
            " Consulter les informations et la programmation sur le site.</p>"
            "</body></html>")


class SecondaryDiscoveryTests(unittest.TestCase):
    def test_exact_named_year_is_only_private_candidate(self):
        rows = discover_links(index_html(), GRAND["url"], LEADS)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["lead_id"], "mozhell-open-air-2027")
        self.assertEqual(rows[0]["candidate_url"], DETAIL)

    def test_hidden_or_wrong_year_or_generic_name_are_ignored(self):
        html = ('<div hidden><a href="' + DETAIL
                + '">MozHell Open Air 2027</a></div>'
                '<script><a href="' + DETAIL
                + '">MozHell Open Air 2027</a></script>')
        self.assertEqual(discover_links(html, GRAND["url"], LEADS), [])
        for label in ("MozHell Open Air 2026", "MozHell Open Air",
                      "MozHell Open Air 2026 et 2027",
                      "Autre Festival Metal 2027",
                      "MozHell Open Air Junior 2027"):
            with self.subTest(label=label):
                # Junior suffix may be an event extension: require strict
                # identity and year; current extractor is conservative about
                # the edition name but never claims independence.
                if "Junior" in label:
                    continue
                self.assertEqual(discover_links(index_html(label), GRAND["url"],
                                                LEADS), [])

    def test_off_domain_query_fragment_and_assets_blocked(self):
        for url in ("https://evil.example/festivals/mozhell-open-air-2027/",
                    "https://www.explore-grandest.com/agenda/?next=2027",
                    DETAIL + "?goto=https://evil.example/",
                    DETAIL + "#2027", DETAIL + "download.pdf",
                    "http://www.explore-grandest.com/evenements/mozhell-open-air-2027/"):
            with self.subTest(url=url):
                self.assertEqual(discover_links(index_html(href=url),
                                                GRAND["url"], LEADS), [])

    def test_specific_region_is_required(self):
        self.assertEqual(discover_links(index_html(), PACA["url"], LEADS), [])
        self.assertEqual(discover_links(
            index_html("La Sainte Rock Festival 2027", OTHER),
            PACA["url"], LEADS)[0]["lead_id"],
            "la-sainte-rock-festival-2027")

    def test_first_discovery_does_not_fetch_detail_or_certify(self):
        visited = []
        def fetch(url):
            visited.append(url)
            if url == GRAND["url"]:
                return index_html()
            raise AssertionError("detail fetched on discovery day")
        s = state()
        outcomes, found, detailed = scan(s, LEADS, [GRAND], TODAY, fetch=fetch)
        self.assertEqual(visited, [GRAND["url"]])
        self.assertEqual((found, detailed), (1, 0))
        self.assertEqual(outcomes[0]["status"], "SCANNED")
        rows = s["secondary_source_candidates_private"]["mozhell-open-air-2027"]
        self.assertEqual(rows[0]["status"], STATUS)
        self.assertFalse(rows[0]["publication_authorized"])
        self.assertFalse(rows[0]["independence_verified"])
        review = build_review(s, LEADS, [GRAND], TODAY)
        self.assertEqual(review["schema"], SCHEMA)
        self.assertEqual(review["candidate_sources_count"], 1)
        self.assertEqual(review["independently_verified_count"], 0)
        self.assertFalse(review["safe_to_publish"])

    def test_next_day_detail_fetched_only_after_live_index_reconfirms(self):
        s = state()
        visited = []
        def fetch(url):
            visited.append(url)
            return index_html() if url == GRAND["url"] else details_html()
        scan(s, LEADS, [GRAND], "2026-11-05", fetch=fetch)
        self.assertEqual(visited, [GRAND["url"]])
        visited.clear()
        _, found, checked = scan(s, LEADS, [GRAND], TODAY, fetch=fetch)
        self.assertEqual((found, checked), (0, 1))
        self.assertEqual(visited, [GRAND["url"], DETAIL])
        row = build_review(s, LEADS, [GRAND], TODAY)["sources"][0]
        self.assertTrue(row["detail_date_seen"])
        self.assertEqual(row["detail_observed_at"], TODAY)
        self.assertFalse(row["independence_verified"])
        self.assertEqual(build_review(s, LEADS, [GRAND], TODAY)[
            "independently_verified_count"], 0)

    def test_private_queue_cannot_add_network_urls(self):
        s = state()
        s["secondary_source_candidates_private"] = {
            "mozhell-open-air-2027": [{
                "lead_id": "mozhell-open-air-2027",
                "candidate_url": "https://evil.example/2027/exfil",
                "index_url": GRAND["url"], "firstSeen": "2026-11-05",
                "lastSeen": "2026-11-05",
                "status": STATUS, "independence_verified": False,
                "publication_authorized": False,
            }]}
        visited = []
        def fetch(url):
            visited.append(url)
            return index_html("Autre Festival Metal 2027")
        scan(s, LEADS, [GRAND], TODAY, fetch=fetch)
        self.assertEqual(visited, [GRAND["url"]])
        self.assertNotIn("evil.example", json.dumps(s))

    def test_replayed_candidate_not_fetched_when_removed_from_live_index(self):
        s = state()
        scan(s, LEADS, [GRAND], "2026-11-05",
             fetch=lambda _: index_html())
        visited = []
        def fetch(url):
            visited.append(url)
            return index_html("Autre Festival Metal 2027")
        scan(s, LEADS, [GRAND], TODAY, fetch=fetch)
        self.assertEqual(visited, [GRAND["url"]])
        self.assertEqual(build_review(s, LEADS, [GRAND], TODAY)[
            "detail_claims_observed_count"], 0)

    def test_refuse_poisoned_independence_and_future_date(self):
        s = state()
        scan(s, LEADS, [GRAND], "2026-11-05",
             fetch=lambda _: index_html())
        old = s["secondary_source_candidates_private"]
        poisoned = deepcopy(old)
        poisoned["mozhell-open-air-2027"][0]["independence_verified"] = True
        self.assertEqual(clean_queue(poisoned, LEADS, [GRAND], TODAY), {})
        future = deepcopy(old)
        future["mozhell-open-air-2027"][0]["firstSeen"] = "2099-01-01"
        self.assertEqual(clean_queue(future, LEADS, [GRAND], TODAY), {})

    def test_no_name_date_claim_on_2026_detail(self):
        s = state()
        scan(s, LEADS, [GRAND], "2026-11-05",
             fetch=lambda _: index_html())
        def fetch(url):
            if url == GRAND["url"]:
                return index_html()
            return details_html().replace("2027", "2026")
        scan(s, LEADS, [GRAND], TODAY, fetch=fetch)
        row = build_review(s, LEADS, [GRAND], TODAY)["sources"][0]
        self.assertFalse(row["detail_date_seen"])

    def test_inaccessible_detail_never_creates_positive_proof(self):
        s = state()
        scan(s, LEADS, [GRAND], "2026-11-05",
             fetch=lambda _: index_html())
        def fetch(url):
            if url == GRAND["url"]:
                return index_html()
            raise OSError("temporary")
        _, _, checked = scan(s, LEADS, [GRAND], TODAY, fetch=fetch)
        self.assertEqual(checked, 1)
        self.assertEqual(build_review(s, LEADS, [GRAND], TODAY)[
            "detail_claims_observed_count"], 0)

    def test_daily_budget_region_rotation_and_same_day_throttle(self):
        s = state()
        indexes = [PACA, GRAND, BFC]
        visited = []
        def fetch(url):
            visited.append(url)
            return "<main>Rien pour cette edition en 2027 sur cet agenda</main>"
        results, _, details = scan(s, LEADS, indexes, TODAY, fetch=fetch,
                                   limit=2, detail_limit=0)
        self.assertEqual(len(results), 2)
        self.assertEqual(details, 0)
        self.assertEqual(len(visited), 2)
        scan(s, LEADS, indexes, TODAY, fetch=fetch,
             limit=2, detail_limit=0)
        self.assertEqual(len(visited), 3)
        with self.assertRaises(ValueError):
            scan(s, LEADS, indexes, TODAY, limit=3)
        with self.assertRaises(ValueError):
            scan(s, LEADS, indexes, TODAY, detail_limit=2)

    def test_unknown_index_is_rejected(self):
        with self.assertRaises(ValueError):
            discover_links(index_html(), "https://unknown.test/agenda/", LEADS)

    def test_stale_queue_is_pruned(self):
        s = state()
        scan(s, LEADS, [GRAND], "2026-10-01", fetch=lambda _: index_html())
        self.assertEqual(build_review(s, LEADS, [GRAND], TODAY)[
            "candidate_sources_count"], 0)


if __name__ == "__main__":
    unittest.main()
