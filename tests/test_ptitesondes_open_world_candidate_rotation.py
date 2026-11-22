"""Offline end-to-end: new OA agenda -> DILA -> municipal link -> source.

All outputs stay private; the mock servers are explicit, never arbitrary live
internet endpoints. No preconfigured organizer, venue, activity or domain list.
"""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from test_ptitesondes_open_world_admission_diagnostics import (
    lead, page, source_event, dila, CITY, MUNICIPAL, SOURCE, KEY,
    mint_unnumbered,
)
from ptitesondes_open_world_candidate_rotation import (
    rotate_private_open_world_lead, public_redacted_rotation_summary,
)

TODAY = date(2026, 11, 21)
HOME = "https://www.ville-les-bois.fr/"


def menu(*urls):
    return "<html><body><nav>" + "".join(
        "<a href='" + url + "'>Un lien nouveau</a>" for url in urls
    ) + "</nav></body></html>"


def cycle(item=None, previous=None, *, map_pages=None,
          page_budget=1, source_budget=1,
          event=None, directory=None, html_reader=None, location_proof=None,
          oa_source_reader=None):
    item = item or lead()
    pages = map_pages or {
        HOME: menu("agenda/sorties"),
        MUNICIPAL: page(item, True),
        SOURCE: page(item, False),
    }
    return rotate_private_open_world_lead(
        item, KEY, TODAY, previous,
        pages_per_cycle=page_budget,
        sources_per_cycle=source_budget,
        directory_reader=(lambda city: directory if directory is not None
                          else dila()),
        html_reader=html_reader or (lambda url: pages[url]),
        oa_agenda_reader=lambda uid, key: {
            "uid": item["agenda_uid"], "slug": item["agenda_slug"]},
        oa_event_reader=lambda uid, eid, key: (
            event if event is not None else source_event(item)),
        location_proof=location_proof,
        **({"oa_source_reader": oa_source_reader}
           if oa_source_reader is not None else {}))


class OpenWorldRotationTests(unittest.TestCase):
    def test_unknown_agenda_discovers_unlisted_source_and_checks_real_sessions(self):
        item = lead()
        first = cycle(item)
        self.assertEqual(first["source_candidates_examined"], 0)
        self.assertEqual(first["municipal_page_batches_checked"], 1)
        self.assertEqual(first["source_candidates_pending"], 0)
        second = cycle(item, first["private_checkpoint"],
                       location_proof=mint_unnumbered())
        self.assertEqual(second["source_candidates_discovered"], 1)
        self.assertEqual(second["source_candidates_examined"], 1)
        self.assertEqual(second["status"],
                         "private_daily_discovery_pass_exhausted")
        self.assertEqual(len(second["private_research_reviews"]), 1)
        row = second["private_research_reviews"][0]
        self.assertEqual(row["municipal_url"], MUNICIPAL)
        self.assertEqual(row["source_url"], SOURCE)
        review = row["diagnostic"]
        self.assertEqual(review["geography_status"],
                         "independent_named_location_correlated")
        self.assertEqual(len(review["private_session_diagnostics"]), 2)
        self.assertTrue(all(x["three_source_exact_claims"] for x
                            in review["private_session_diagnostics"]))
        self.assertFalse(review["source_reuse_rights_verified"])
        self.assertFalse(second["publication_ready"])
        self.assertFalse(second["publisher_connected"])
        self.assertEqual(second["public_writes"], 0)
        again = cycle(item, second["private_checkpoint"])
        self.assertEqual(again["source_candidates_examined"], 0)

    def test_source_queue_is_processed_across_runs_without_preselected_hosts(self):
        item = lead()
        external = [
            f"https://unlisted-organizer-{i}.fr/events"
            for i in range(3)]
        pages = {
            HOME: menu("agenda/sorties"),
            MUNICIPAL: menu(*external),
        }
        for url in external:
            pages[url] = "<html><body><p>Sans séance</p></body></html>"
        result = cycle(item, map_pages=pages)
        result = cycle(item, result["private_checkpoint"], map_pages=pages,
                       source_budget=1)
        self.assertEqual(result["source_candidates_discovered"], 3)
        self.assertEqual(result["source_candidates_examined"], 1)
        self.assertEqual(result["source_candidates_pending"], 2)
        self.assertEqual(result["private_research_reviews"][0]["source_url"],
                         external[0])
        follow = cycle(item, result["private_checkpoint"], map_pages=pages)
        self.assertEqual(follow["source_candidates_examined"], 1)
        self.assertEqual(follow["source_candidates_pending"], 1)
        end = cycle(item, follow["private_checkpoint"], map_pages=pages)
        self.assertEqual(end["source_candidates_examined"], 1)
        self.assertEqual(end["source_candidates_pending"], 0)
        self.assertEqual(end["status"],
                         "private_daily_discovery_pass_exhausted")
        self.assertEqual(end["private_research_reviews"][0]["source_url"],
                         external[2])
        self.assertFalse(end["organizer_identity_verified"])

    def test_page_with_more_than_forty_external_links_preserves_tail(self):
        item = lead()
        external = [f"https://source-{i}.fr/voir" for i in range(43)]
        pages = {
            HOME: menu("agenda/sorties"),
            MUNICIPAL: menu(*external),
        }
        pages.update({
            url: "<html><body>Aucun programme</body></html>"
            for url in external
        })
        state = None
        reviewed = []
        discovered = 0
        for _ in range(50):
            res = cycle(item, state, map_pages=pages, source_budget=1)
            state = res["private_checkpoint"]
            discovered += res["source_candidates_discovered"]
            reviewed.extend(
                x["source_url"] for x in res["private_research_reviews"])
            if res["status"] == "private_daily_discovery_pass_exhausted":
                break
        else:
            self.fail("must process all 43 sources without losing HTML tail")
        self.assertEqual(discovered, 43)
        self.assertEqual(reviewed, external)
        self.assertEqual(len(state["seen_source_sha256"]), 43)

    def test_checkpoint_cannot_be_reused_for_another_event(self):
        item = lead()
        first = cycle(item)
        altered = deepcopy(item)
        altered["event_uid"] += 1
        reader = Mock(side_effect=AssertionError("never access unknown URL"))
        out = cycle(altered, first["private_checkpoint"],
                    html_reader=reader)
        self.assertEqual(out["status"], "stale_or_invalid_private_checkpoint")
        reader.assert_not_called()

    def test_tampered_pending_queue_rejected_before_network(self):
        item = lead()
        first = cycle(item)
        state = deepcopy(first["private_checkpoint"])
        state["pending_source_pairs"] = [{
            "municipal_url": "https://127.0.0.1/private",
            "source_url": SOURCE,
        }]
        reader = Mock(side_effect=AssertionError("must not fetch"))
        out = cycle(item, state, html_reader=reader)
        self.assertEqual(out["status"], "stale_or_invalid_private_checkpoint")
        reader.assert_not_called()

    def test_changed_oa_schedule_pauses_rotation_without_dropping_cursor(self):
        item = lead()
        first = cycle(item)
        changed = source_event(item)
        changed["timings"] = []
        stopped = cycle(item, first["private_checkpoint"], event=changed)
        self.assertEqual(stopped["status"],
                         "live_source_bootstrap_not_confirmed")
        self.assertEqual(stopped["bootstrap_reason_code"],
                         "live_oa_explicit_session_changed")
        self.assertEqual(stopped["private_checkpoint"],
                         first["private_checkpoint"])
        self.assertEqual(stopped["source_candidates_examined"], 0)

    def test_no_dila_is_a_research_hold_not_permission_to_publish(self):
        result = cycle(directory={"total_count": 0, "results": []})
        self.assertEqual(result["status"],
                         "live_source_bootstrap_not_confirmed")
        self.assertEqual(result["bootstrap_reason_code"],
                         "dila_municipal_domain_not_verified")
        self.assertFalse(result["organizer_identity_verified"])

    def test_private_bootstrap_diagnostic_does_not_expose_source_metadata(self):
        item = lead()
        found = cycle(item, directory={"total_count": 0, "results": []})
        self.assertIn(found["bootstrap_reason_code"],
                      {"dila_municipal_domain_not_verified",
                       "dila_municipal_directory_unavailable"})
        public = public_redacted_rotation_summary(found)
        self.assertNotIn("bootstrap_reason_code", public)
        self.assertNotIn("source_url", json.dumps(public))
        self.assertEqual(public["public_writes"], 0)

    def test_no_dila_keeps_private_oa_leads_without_approving_source(self):
        item = lead()
        oa = source_event(item)
        oa["canonicalUrl"] = "https://nouvel-organisateur.fr/spectacle"
        oa["registration"] = [{"type": "link",
                              "value": "https://nouveau-billet.fr/place"}]
        result = cycle(item, event=oa,
                       directory={"total_count": 0, "results": []})
        self.assertEqual(result["status"],
                         "live_source_bootstrap_not_confirmed")
        self.assertEqual(result["bootstrap_reason_code"],
                         "dila_municipal_domain_not_verified")
        self.assertEqual(result["oa_source_web_leads_found"], 2)
        self.assertEqual(len(result["private_unverified_oa_web_leads"]), 2)
        self.assertTrue(all(x["candidate_only"] for x in
                            result["private_unverified_oa_web_leads"]))
        self.assertEqual(result["source_candidates_examined"], 0)
        self.assertFalse(result["organizer_identity_verified"])
        self.assertFalse(result["publication_ready"])
        public = public_redacted_rotation_summary(result)
        self.assertNotIn("nouvel-organisateur", json.dumps(public))
        self.assertNotIn("bootstrap_reason_code", public)
        self.assertEqual(public["public_writes"], 0)

    def test_oa_unknown_links_can_expose_exact_sessions_without_dila(self):
        item = lead(9, 10, 11, 14, 15, 17)
        oa = source_event(item)
        first_url = "https://unlisted-a.fr/spectacle"
        second_url = "https://unlisted-b.fr/spectacle"
        third_url = "https://unlisted-c.fr/spectacle"
        oa["canonicalUrl"] = first_url
        oa["registration"] = [
            {"type": "link", "value": second_url},
            {"type": "link", "value": third_url},
        ]
        html = "<html><script type='application/ld+json'>" + json.dumps({
            "@graph": [{
                "@type": "ChildrensEvent", "name": item["title"],
                "startDate": slot["begin"], "endDate": slot["end"],
                "location": {
                    "name": item["venue_unverified"],
                    "address": {"addressLocality":
                                item["city_unverified"]}},
            } for slot in item["explicit_source_session_intervals"]]
        }, ensure_ascii=False) + "</script></html>"
        checked = []
        def read(url):
            checked.append(url)
            return html

        absent = {"total_count": 0, "results": []}
        first = cycle(item, event=oa, directory=absent, oa_source_reader=read)
        self.assertEqual(first["bootstrap_reason_code"],
                         "dila_municipal_domain_not_verified")
        self.assertEqual(first["oa_urls_rechecked"], 2)
        self.assertEqual(first["oa_exact_session_claims_unverified"], 12)
        self.assertEqual([x["status"]
                          for x in first["private_oa_url_reviews"]],
                         ["all_exact_sessions_visible_unverified"] * 2)
        self.assertTrue(all(x["origin_independently_attested"] is False
                            and x["organizer_verified"] is False
                            and x["rights_reviewed"] is False
                            and x["publication_ready"] is False
                            for x in first["private_oa_url_reviews"]))
        second = cycle(item, first["private_checkpoint"],
                       event=oa, directory=absent, oa_source_reader=read)
        self.assertEqual(second["oa_urls_rechecked"], 1)
        self.assertEqual(second["oa_exact_session_claims_unverified"], 6)
        third = cycle(item, second["private_checkpoint"],
                      event=oa, directory=absent, oa_source_reader=read)
        self.assertEqual(third["oa_urls_rechecked"], 0)
        self.assertEqual(checked, [first_url, second_url, third_url])
        summary = public_redacted_rotation_summary(first)
        self.assertNotIn(first_url, json.dumps(summary))
        self.assertEqual(summary["public_writes"], 0)

    def test_failed_oa_url_is_held_and_does_not_starve_other_unknown_urls(self):
        item = lead()
        oa = source_event(item)
        url_bad = "https://unlisted-failed.fr/show"
        url_good = "https://unlisted-good.fr/show"
        url_next = "https://unlisted-next.fr/show"
        oa["canonicalUrl"] = url_bad
        oa["registration"] = [{"type": "link", "value": url_good},
                              {"type": "link", "value": url_next}]
        called = []
        def read(url):
            called.append(url)
            if url == url_bad:
                raise ValueError("private error?secret=test")
            return "<html><body>Non structured source</body></html>"
        dila_empty = {"total_count": 0, "results": []}
        first = cycle(item, event=oa, directory=dila_empty,
                      oa_source_reader=read)
        self.assertEqual(first["oa_urls_rechecked"], 2)
        self.assertEqual([x["status"] for x in
                          first["private_oa_url_reviews"]],
                         ["oa_url_unavailable",
                          "no_exact_structured_session_match"])
        second = cycle(item, first["private_checkpoint"], event=oa,
                       directory=dila_empty, oa_source_reader=read)
        self.assertEqual(second["oa_urls_rechecked"], 1)
        self.assertEqual(called, [url_bad, url_good, url_next])
        self.assertNotIn("secret", json.dumps(second))
        self.assertEqual(second["public_writes"], 0)

    def test_original_event_vocabulary_never_filters_source_discovery(self):
        item = lead(title="Création sonore hors catégories")
        unknown_format = source_event(
            item, description={"fr":
                "Une expérience inédite pour enfants et familles."})
        a = cycle(item, event=unknown_format)
        b = cycle(item, a["private_checkpoint"],
                  event=unknown_format)
        self.assertEqual(b["source_candidates_examined"], 1)
        self.assertEqual(
            b["private_research_reviews"][0]["diagnostic"]["editorial_status"],
            "new_activity_needs_editorial_research")
        self.assertFalse(b["publication_ready"])

    def test_redacted_summary_contains_no_private_host_or_local_date(self):
        item = lead()
        first = cycle(item)
        second = cycle(item, first["private_checkpoint"])
        output = public_redacted_rotation_summary(second)
        text = json.dumps(output)
        for private in (SOURCE, MUNICIPAL, CITY, "2026-12-05"):
            self.assertNotIn(private, text)
        self.assertEqual(output["sources_examined"], 1)
        with self.assertRaises(ValueError):
            public_redacted_rotation_summary(
                dict(second, publication_ready=True))
        with self.assertRaises(ValueError):
            public_redacted_rotation_summary(
                dict(second, source_rights_reviewed=True))

    def test_daily_checkpoint_is_never_a_permanent_domain_allowlist(self):
        item = lead()
        first = cycle(item)
        stale = deepcopy(first["private_checkpoint"])
        stale["scan_day"] = "2026-11-20"
        rejected = cycle(item, stale)
        self.assertEqual(rejected["status"],
                         "stale_or_invalid_private_checkpoint")
        new = cycle(item)
        self.assertEqual(new["municipal_page_batches_checked"], 1)


if __name__ == "__main__":
    unittest.main()
