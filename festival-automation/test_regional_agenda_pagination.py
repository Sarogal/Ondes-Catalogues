"""Fail-closed tests for delayed, bounded index-page exploration."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).parent))

from regional_agenda_pagination import (
    canonical_page_url, discover_pagination, prune_page_queue,
    eligible_page_checks, remember_page_links, STATUS, MAX_PAGE_QUEUE)
from regional_festival_discovery import scan_regional_indexes
from source_qualification import Anchors
from official_watch import permitted_url

BASE = "https://sortir.limoges.fr/agenda"
OTHER = "https://www.angers.fr/actualites-sorties/agenda/index.html"
PAGE = BASE + "?page=1"
FEST = "https://sortir.limoges.fr/agenda/shred-fest-2027"
TODAY = "2026-11-05"
A = {"url":BASE, "id":"na-limoges", "region":"Nouvelle-Aquitaine"}
B = {"url":OTHER, "id":"pdl-angers", "region":"Pays de la Loire"}


def report(day=TODAY):
    return {"schema":"grossesondes.source-watch-report.v1","date":day}


def nav(href="?page=1", label="2"):
    return "<nav><a href='" + href + "'>" + label + "</a></nav>"


class PaginationTests(unittest.TestCase):
    def test_only_same_index_path_and_single_small_page_parameter(self):
        self.assertEqual(canonical_page_url(PAGE, BASE, permitted_url), PAGE)
        self.assertEqual(canonical_page_url(BASE+"?page=6", BASE, permitted_url), BASE+"?page=6")
        for bad in (
            "http://sortir.limoges.fr/agenda?page=1",
            "https://sortir.limoges.fr.evil.fr/agenda?page=1",
            "https://127.0.0.1/agenda?page=1",
            "https://sortir.limoges.fr/other?page=1",
            "https://sortir.limoges.fr/agenda?page=0",
            "https://sortir.limoges.fr/agenda?page=7",
            "https://sortir.limoges.fr/agenda?page=-1",
            "https://sortir.limoges.fr/agenda?page=01",
            "https://sortir.limoges.fr/agenda?page=1&token=abc",
            "https://sortir.limoges.fr/agenda?page=1&page=2",
            "https://sortir.limoges.fr/agenda?page=1#anchor",
            "https://sortir.limoges.fr/agenda?redirect=https://evil.fr&page=1",
            "https://sortir.limoges.fr/agenda?page=%31",
        ):
            with self.subTest(bad=bad):
                self.assertIsNone(canonical_page_url(bad, BASE, permitted_url))

    def test_exact_curated_query_is_preserved_across_pagination(self):
        origin = BASE + "?keys=rock"
        self.assertEqual(
            canonical_page_url(origin+"&page=2", origin, permitted_url),
            origin+"&page=2")
        for target in (BASE+"?page=2", BASE+"?keys=metal&page=2",
                       BASE+"?keys=rock&keys=punk&page=2",
                       BASE+"?page=2&keys=rock"):
            self.assertIsNone(canonical_page_url(target,origin,permitted_url))

    def test_only_visible_navigation_links_and_at_most_two_pages(self):
        html=(nav()+nav("?page=2", "3")+nav("?page=3", "suivant"))
        self.assertEqual(discover_pagination(
            html,BASE,BASE,Anchors,permitted_url),
            [PAGE,BASE+"?page=2"])
        self.assertEqual(discover_pagination(
            nav("?page=1","Festival de Metal"),BASE,BASE,Anchors,permitted_url),[])
        for wrapper in ("<script>", "<noscript>", "<div hidden>",
                        '<div aria-hidden="true">','<div style="display:none">'):
            closing="</"+wrapper.split()[0][1:].strip(">")+">"
            self.assertEqual(discover_pagination(
                wrapper+nav()+closing,BASE,BASE,Anchors,permitted_url),[])
        self.assertEqual(discover_pagination(
            nav("https://evil.fr/agenda?page=1"),BASE,BASE,Anchors,permitted_url),[])

    def test_visible_page_six_is_allowed_but_seven_is_rejected(self):
        self.assertEqual(discover_pagination(
            nav("?page=6", "6"), BASE, BASE, Anchors, permitted_url),
            [BASE+"?page=6"])
        self.assertEqual(discover_pagination(
            nav("?page=7", "7"), BASE, BASE, Anchors, permitted_url), [])

    def test_two_delayed_page_checks_keep_root_budget_and_deduplicate(self):
        today = "2026-11-06"
        state = {"regional_festival_page_queue_review_only": {}}
        for i in (1, 2):
            remember_page_links(
                state["regional_festival_page_queue_review_only"],
                [BASE+"?page="+str(i)], BASE, TODAY, permitted_url)
        visits = []
        def fetch(url):
            visits.append(url)
            if "page=" in url:
                return "<a href='" + FEST + "'>Shred Fest 2027</a>"
            return "<main>Agenda disponible</main>"
        r = report(today)
        new = scan_regional_indexes(r, state, [A, B], today, fetch, limit=4)
        self.assertEqual(len(visits), 4)
        self.assertEqual(sum("page=" in u for u in visits), 2)
        self.assertEqual(r["regional_festival_pagination_attempted_review_only"], 2)
        self.assertEqual(r["regional_festival_pagination_checked_review_only"], 2)
        self.assertEqual(r["regional_festival_regions_this_pass_review_only"], 2)
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0]["candidate_url"], FEST)
        self.assertEqual(r["regional_festival_publications"], 0)
        self.assertFalse(new[0]["publication_authorized"])

    def test_count_based_limoges_pagination_advances_across_days(self):
        origin = BASE + "?keys=rock"
        seed = {"id":"na-rock", "region":"Nouvelle-Aquitaine", "url":origin}
        root = ('<main>Affichage des événements 1 à 9 sur 90 au total</main>'
                '<nav><a href="?keys=rock&page=1">2</a>'
                '<a href="?keys=rock&page=2">3</a></nav>')
        visits = []
        def fetch(url):
            visits.append(url)
            return root if url == origin else "<main>Agenda accessible</main>"
        state = {}
        for day, expected in (("2026-11-05", 2),
                              ("2026-11-06", 4),
                              ("2026-11-07", 6)):
            r = report(day)
            scan_regional_indexes(r, state, [seed], day, fetch, limit=4)
            queue = state["regional_festival_page_queue_review_only"]
            self.assertEqual(len(queue), expected)
            self.assertEqual(r["regional_festival_pagination_pending_review_only"], expected)
            self.assertEqual(r["regional_festival_pagination_discovered_review_only"], 2)
            self.assertTrue(all(not v["publication_authorized"] for v in queue.values()))
            self.assertEqual(r["regional_festival_publications"], 0)
        self.assertTrue(any(u.endswith("&page=6") for u in queue))
        self.assertEqual(len([u for u in visits if u == origin]), 3)
        r = report("2026-11-08")
        scan_regional_indexes(r, state, [seed], "2026-11-08", fetch, limit=4)
        self.assertEqual(r["regional_festival_pagination_discovered_review_only"], 0)
        self.assertEqual(len(queue), 6)

    def test_queue_never_fetches_same_day_and_rechecks_only_after_week(self):
        pending={}
        self.assertEqual(remember_page_links(
            pending,[PAGE,PAGE],BASE,TODAY,permitted_url),1)
        self.assertEqual(eligible_page_checks(
            pending,{BASE:"Nouvelle-Aquitaine"},TODAY,permitted_url),[])
        self.assertEqual(eligible_page_checks(
            pending,{BASE:"Nouvelle-Aquitaine"},"2026-11-06",permitted_url),
            [(BASE,PAGE)])
        pending[PAGE]["lastChecked"]="2026-11-06"
        self.assertEqual(eligible_page_checks(
            pending,{BASE:"Nouvelle-Aquitaine"},"2026-11-12",permitted_url),[])
        self.assertEqual(eligible_page_checks(
            pending,{BASE:"Nouvelle-Aquitaine"},"2026-11-13",permitted_url),
            [(BASE,PAGE)])

    def test_corrupt_private_pagination_state_cannot_be_scanned(self):
        bad = {
            "https://127.0.0.1/agenda?page=1":{
                "candidate_url":"https://127.0.0.1/agenda?page=1",
                "source_index":BASE,"firstSeen":TODAY,"lastSeen":TODAY,
                "status":STATUS,"publication_authorized":False},
            PAGE:{"candidate_url":PAGE,"source_index":BASE,
                  "firstSeen":TODAY,"lastSeen":TODAY,
                  "status":STATUS,"publication_authorized":True},
            BASE+"?page=2":{"candidate_url":BASE+"?page=2",
                           "source_index":"https://evil.fr/agenda",
                           "firstSeen":TODAY,"lastSeen":TODAY,
                           "status":STATUS,"publication_authorized":False},
        }
        prune_page_queue(bad,{BASE:"Nouvelle-Aquitaine"},TODAY,permitted_url)
        self.assertEqual(bad,{})

    def test_unhashable_poisoned_source_is_pruned_safely(self):
        pending={PAGE:{"candidate_url":PAGE,"source_index":["bad"],
                       "firstSeen":TODAY,"lastSeen":TODAY,
                       "status":STATUS,"publication_authorized":False}}
        prune_page_queue(pending,{BASE:"Nouvelle-Aquitaine"},TODAY,permitted_url)
        self.assertEqual(pending,{})
        self.assertEqual(eligible_page_checks(
            {PAGE:{"source_index":["bad"],"status":STATUS,
                   "publication_authorized":False}},
            {BASE:"Nouvelle-Aquitaine"},"2026-11-06",permitted_url),[])

    def test_stale_pages_expire_and_queue_capped(self):
        pending={}
        for i in range(3):
            candidate=BASE+"?page="+str(i+1)
            remember_page_links(pending,[candidate],BASE,TODAY,permitted_url)
        self.assertEqual(len(pending),3)
        prune_page_queue(pending,{BASE:"Nouvelle-Aquitaine"},
                         "2026-12-06",permitted_url)
        self.assertEqual(pending,{})
        self.assertEqual(MAX_PAGE_QUEUE,45)

    def test_full_collection_next_day_budget_and_private_nonpublication(self):
        state={}
        visits=[]
        def fetch(url):
            visits.append(url)
            if url == BASE:
                return nav()
            if url == PAGE:
                return "<main><a href='"+FEST+"'>Shred Fest 2027</a></main>"
            return "<main>Other area agenda</main>"
        r=report()
        self.assertEqual(scan_regional_indexes(r,state,[A,B],TODAY,fetch,limit=2),[])
        self.assertEqual(visits,[BASE,OTHER])
        self.assertEqual(r["regional_festival_pagination_discovered_review_only"],1)
        self.assertEqual(r["regional_festival_pagination_checked_review_only"],0)
        self.assertEqual(r["regional_festival_pagination_pending_review_only"],1)
        self.assertEqual(r["regional_festival_publications"],0)
        self.assertEqual(state["regional_festival_page_queue_review_only"][PAGE]
                         ["firstSeen"],TODAY)
        # A second same-day run may not fetch this newly discovered URL.
        visits.clear()
        scan_regional_indexes(report(),state,[A,B],TODAY,fetch,limit=2)
        self.assertEqual(visits,[])
        # Next day: one regular root + one delayed page, still two GETs.
        visits.clear()
        r2=report("2026-11-06")
        out=scan_regional_indexes(r2,state,[A,B],"2026-11-06",fetch,limit=2)
        self.assertEqual(len(visits),2)
        self.assertIn(PAGE,visits)
        self.assertEqual(len(out),1)
        self.assertEqual(out[0]["candidate_url"],FEST)
        self.assertEqual(r2["regional_festival_pagination_checked_review_only"],1)
        self.assertEqual(r2["regional_festival_new_links_review_only"],1)
        self.assertEqual(r2["regional_festival_detail_pages_checked_review_only"],0)
        self.assertEqual(r2["regional_festival_publications"],0)
        self.assertFalse(out[0]["publication_authorized"])
        self.assertEqual(state["regional_festival_page_queue_review_only"][PAGE]
                         ["lastChecked"],"2026-11-06")

    def test_failed_pagination_is_not_verified_and_retries_later(self):
        second = BASE + "?page=2"
        queue = {}
        remember_page_links(queue, [PAGE, second], BASE, TODAY, permitted_url)
        state = {"regional_festival_page_queue_review_only": queue}
        visits = []

        def fetch(url):
            visits.append(url)
            if url == PAGE:
                raise OSError("temporary network failure")
            return "<main>Agenda vide</main>"

        first = report("2026-11-06")
        scan_regional_indexes(first, state, [A, B], "2026-11-06", fetch, limit=2)
        self.assertIn(PAGE, visits)
        self.assertEqual(first["regional_festival_pagination_attempted_review_only"], 1)
        self.assertEqual(first["regional_festival_pagination_checked_review_only"], 0)
        self.assertEqual(first["regional_festival_pagination_inaccessible_review_only"], 1)
        self.assertEqual(queue[PAGE]["lastAttempted"], "2026-11-06")
        self.assertEqual(queue[PAGE]["lastChecked"], "")
        self.assertFalse(queue[PAGE]["publication_authorized"])

        visits.clear()
        same_day = report("2026-11-06")
        scan_regional_indexes(same_day, state, [A, B], "2026-11-06", fetch, limit=2)
        self.assertNotIn(PAGE, visits)
        self.assertIn(second, visits)
        self.assertEqual(queue[second]["lastChecked"], "2026-11-06")

        visits.clear()
        next_day = report("2026-11-07")
        scan_regional_indexes(next_day, state, [A, B], "2026-11-07", fetch, limit=2)
        self.assertIn(PAGE, visits)
        self.assertEqual(queue[PAGE]["lastAttempted"], "2026-11-07")
        self.assertEqual(queue[PAGE]["lastChecked"], "")
        self.assertEqual(next_day["regional_festival_publications"], 0)

    def test_poisoned_future_attempt_is_pruned(self):
        queue = {}
        remember_page_links(queue, [PAGE], BASE, TODAY, permitted_url)
        queue[PAGE]["lastAttempted"] = "2099-01-01"
        prune_page_queue(queue, {BASE: "Nouvelle-Aquitaine"},
                         "2026-11-06", permitted_url)
        self.assertEqual(queue, {})

    def test_unavailable_index_is_not_a_verified_event(self):
        state={"regional_festival_page_queue_review_only":{
            PAGE:{"candidate_url":PAGE,"source_index":BASE,
                  "firstSeen":TODAY,"lastSeen":TODAY,"lastChecked":"",
                  "status":STATUS,"publication_authorized":False}}}
        attempted=[]
        def unreachable(url):
            attempted.append(url)
            raise OSError("403")
        r=report("2026-11-06")
        new=scan_regional_indexes(r,state,[A,B],"2026-11-06",
                                  unreachable,limit=2)
        self.assertEqual(new,[])
        self.assertIn(PAGE,attempted)
        self.assertEqual(r["regional_festival_inaccessible_this_pass_review_only"],2)
        self.assertEqual(r["regional_festival_publications"],0)


if __name__ == "__main__":
    unittest.main()
