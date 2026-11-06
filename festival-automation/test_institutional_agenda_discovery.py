"""Index-to-edition discovery must be exact, bounded and private."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).parent))

from institutional_agenda_discovery import (
    load_seeds, matching_index_links, eligible_seed_rows, scan_indexes,
    accepted_index_leads, SCHEMA,
)
from source_qualification import Anchors, clean_url, classify, normalized, qualify

INDEX = "https://www.phalempin.fr/mes-loisirs/evenements-manifestations/"
TARGET = "https://www.phalempin.fr/2026/10/09/dawn-metal-festival-14-nov/"
BASE = "https://www.phalempin.fr/2026/10/09/dawn-metal-festival-le-refuge-59/"
LEAD = {
    "slug": "dawn-metal-festival-2026",
    "name": "Dawn Metal Festival",
    "start_date": "2026-11-14",
    "end_date": "2026-11-14",
    "candidate_urls": [BASE],
    "official_status": "NOT_VERIFIED",
    "allowed_to_publish": False,
}
SEEDS = [{"slug": LEAD["slug"], "index_url": INDEX}]


def mk(label="Dawn metal festival / 14 nov.", target=TARGET):
    return ('<h2>Les rendez-vous associatifs</h2>'
            '<div class="item"><a href="' + target + '">' +
            label + '</a></div>')


def match(raw, lead=LEAD):
    return matching_index_links(raw, INDEX, lead, clean_url,
                                normalized, Anchors)


def report(day="2026-11-05"):
    return {
        "schema": "grossesondes.source-watch-report.v1",
        "date": day,
        "source_reference_leads_review_only": [LEAD],
    }


class InstitutionalAgendaTests(unittest.TestCase):
    def test_known_index_delivers_new_primary_detail_page(self):
        self.assertEqual(match(mk()), [TARGET])
        self.assertEqual(match(mk(target="/2026/10/09/dawn-metal-festival-14-nov/")),
                         [TARGET])
        self.assertEqual(match(mk(label="Dawn metal festival / 14 novembre")), [TARGET])
        self.assertEqual(match(mk(label="Dawn metal festival / 14 nov. 2026")), [TARGET])

    def test_nearby_but_different_events_never_match(self):
        for label in (
            "Dawn Metal Festival 2025 / 14 nov",
            "Dawn Metal Festival 2027 / 14 nov",
            "Dawn Metal Festival II / 15 nov",
            "Dawn Metal Festival 14 dec",
            "Dawn Metal Festival #2 / 14 nov 2025",
            "Dawn Metal Festival 14 nov. 2026 et 2027",
            "Dawn Metal Festival 2026",  # no full day/month proof
            "Another Dawn Metal Festival / 14 nov.",
            "Dawn Metal Festival 60 / 14 nov.",  # sibling edition
        ):
            with self.subTest(label=label):
                self.assertEqual(match(mk(label)), [])

    def test_wrong_hosts_year_paths_unsafe_and_hidden_never_match(self):
        bads = (
            "https://www.phalempin.fr.evil.fr/2026/10/09/event/",
            "https://evil.fr/2026/10/09/event/",
            "https://127.0.0.1/2026/10/09/event/",
            "http://www.phalempin.fr/2026/10/09/event/",
            "https://www.phalempin.fr/2025/10/09/event/",
            "https://www.phalempin.fr/2027/10/09/event/",
            "https://www.phalempin.fr/wp-content/uploads/2026/affiche.jpg",
            "https://www.phalempin.fr/agenda/sans-annee",
        )
        for url in bads:
            with self.subTest(url=url):
                self.assertEqual(match(mk(target=url)), [])
        for elem in (
            "<div hidden>", '<div aria-hidden="true">',
            '<div style="display:none">', "<noscript>", "<template>"
        ):
            page = elem + mk() + ("</div>" if elem.startswith("<div") else
                                   "</noscript>" if elem.startswith("<noscript") else "</template>")
            self.assertEqual(match(page), [])

    def test_load_only_small_allowlisted_institutional_seeds(self):
        config = {"schema": SCHEMA, "seeds": SEEDS}
        self.assertEqual(load_seeds(config, clean_url, classify), SEEDS)
        for data in (
            {"schema": "other", "seeds": SEEDS},
            {"schema": SCHEMA, "seeds": SEEDS*25},
            {"schema": SCHEMA, "seeds": SEEDS*2},
            {"schema": SCHEMA, "seeds": [{"slug": LEAD["slug"], "index_url": "http://www.phalempin.fr"}]},
            {"schema": SCHEMA, "seeds": [{"slug": LEAD["slug"], "index_url": "https://127.0.0.1"}]},
            {"schema": SCHEMA, "seeds": [{"slug": LEAD["slug"], "index_url": "https://www.facebook.com/agenda"}]},
        ):
            with self.subTest(data=str(data)[:100]), self.assertRaises(ValueError):
                load_seeds(data, clean_url, classify)

    def test_scan_reads_only_trusted_known_origin_and_persists_without_publication(self):
        state, visits, r = {}, [], report()
        def fetch(url):
            visits.append(url)
            self.assertEqual(url, INDEX)
            return mk()
        new = scan_indexes(r, state, SEEDS, r["date"], fetch,
                           clean_url, classify, normalized, Anchors)
        self.assertEqual(visits, [INDEX])
        self.assertEqual(len(new), 1)
        self.assertTrue(new[0]["new_this_pass"])
        self.assertEqual(new[0]["candidate_url"], TARGET)
        self.assertFalse(new[0]["publication_authorized"])
        self.assertEqual(r["institutional_agenda_new_urls_review_only"], 1)
        self.assertEqual(r["institutional_agenda_pending_urls_review_only"], 1)
        self.assertNotIn(TARGET, LEAD["candidate_urls"])
        # An evening recheck does not spend a second request.
        again = scan_indexes(r, state, SEEDS, r["date"], fetch,
                             clean_url, classify, normalized, Anchors)
        self.assertEqual(again, [])
        self.assertEqual(visits, [INDEX])
        self.assertEqual(r["institutional_agenda_new_urls_review_only"], 0)
        self.assertEqual(r["institutional_agenda_pending_urls_review_only"], 1)

    def test_out_of_scope_or_ended_editions_do_not_fetch_indexes(self):
        for lead in (
            dict(LEAD, candidate_urls=["https://www.other-town.fr/2026/festival"]),
            dict(LEAD, end_date="2026-11-04"),
            dict(LEAD, official_status="VERIFIED"),
            dict(LEAD, allowed_to_publish=True),
        ):
            self.assertEqual(eligible_seed_rows([lead], SEEDS, {}, "2026-11-05",
                                                clean_url, classify), [])

    def test_error_is_unknown_never_cancellation_or_publishable(self):
        r, state = report(), {}
        def unavailable(_):
            raise OSError("403")
        self.assertEqual(scan_indexes(r, state, SEEDS, r["date"], unavailable,
                                     clean_url, classify, normalized, Anchors), [])
        self.assertEqual(r["institutional_agenda_index_checks_review_only"][0]
                         ["status"], "INACCESSIBLE")
        self.assertFalse(r["institutional_agenda_index_checks_review_only"][0]
                         ["publication_authorized"])
        self.assertEqual(r["institutional_agenda_new_urls_review_only"], 0)

    def test_next_pass_can_review_discovery_but_never_publish(self):
        r, state = report(), {}
        scan_indexes(r, state, SEEDS, r["date"], lambda _: mk(),
                     clean_url, classify, normalized, Anchors)
        rows = accepted_index_leads([LEAD], state, SEEDS, "2026-11-06",
                                    clean_url, classify)
        self.assertEqual(rows[0]["candidate_urls"], [BASE, TARGET])
        self.assertFalse(rows[0]["allowed_to_publish"])
        # Use the URL on the next day, not the day it was found.
        state["source_qualification_last_checked"] = {
            LEAD["slug"]: {BASE: {"lastChecked": "2026-11-05",
                                  "status": "NOT_VERIFIED",
                                  "reason": "NO_VISIBLE_EVIDENCE"}}
        }
        next_report = report("2026-11-06")
        seen = []
        def fetch(url):
            seen.append(url)
            self.assertEqual(url, TARGET)
            return "<h1>Dawn Metal Festival</h1><p>14 novembre 2026</p>"
        qualify(next_report, state, fetch=fetch, limit=1, index_seeds=SEEDS)
        self.assertEqual(seen, [TARGET])
        self.assertEqual(next_report["source_qualification_checked"], 1)
        self.assertFalse(next_report["source_qualification_review_only"][0]
                         ["publication_authorized"])
        self.assertNotIn("officialSite", next_report["source_qualification_review_only"][0])

    def test_expired_injected_or_untrusted_pages_cannot_enter_schedule(self):
        future = dict(LEAD, end_date="2026-12-20")
        state = {"institutional_agenda_candidate_pages": {
            LEAD["slug"]: [{
                "source": INDEX, "candidate_url": TARGET,
                "status": "UNVERIFIED_INDEX_LINK",
                "lastSeen": "2026-11-05",
                "publication_authorized": False,
            }]}}
        self.assertEqual(len(accepted_index_leads([future], state, SEEDS, "2026-11-19",
                                                 clean_url, classify)[0]["candidate_urls"]), 2)
        self.assertEqual(len(accepted_index_leads([future], state, SEEDS, "2026-11-20",
                                                 clean_url, classify)[0]["candidate_urls"]), 1)
        record = state["institutional_agenda_candidate_pages"][LEAD["slug"]][0]
        for change in (
            {"source": "https://evil.fr/agenda"},
            {"candidate_url": "https://evil.fr/2026/10/09/foo/"},
            {"candidate_url": "http://www.phalempin.fr/2026/10/09/foo/"},
            {"candidate_url": "https://www.phalempin.fr/2025/10/09/foo/"},
            {"status": "VERIFIED"}, {"publication_authorized": True},
            {"lastSeen": "2026-11-21"},
        ):
            with self.subTest(change=change):
                bad = dict(record, **change)
                injected = {"institutional_agenda_candidate_pages": {
                    LEAD["slug"]: [bad]}}
                self.assertEqual(
                    accepted_index_leads([LEAD], injected, SEEDS, "2026-11-06",
                                         clean_url, classify)[0]["candidate_urls"],
                    [BASE])


if __name__ == "__main__":
    unittest.main()
