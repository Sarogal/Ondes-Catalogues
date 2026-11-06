"""Fail-closed, review-only festival ticket and sensitive status tests."""
import json
from datetime import date
import tempfile
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from ticket_status_watch import (
    inspect_ticket_status, stable_ticket_status_observation, STATE_KEY,
)
from watch_summary import render
from official_watch import choose_sources, choose_pending_rechecks, run

URL = "https://festival.example.org/"
ROW = {"slug": "metal-fest-2027", "name": "Metal Fest 2027",
       "startDate": "2027-08-12", "endDate": "2027-08-13"}


def html(**changes):
    event = {"@type": "MusicFestival", "name": ROW["name"],
             "startDate": ROW["startDate"], "endDate": ROW["endDate"],
             "offers": [
                 {"@type": "Offer", "name": "Pass samedi",
                  "availability": "https://schema.org/SoldOut"},
                 {"@type": "Offer", "name": "Pass dimanche",
                  "availability": "https://schema.org/InStock"},
             ]}
    event.update(changes)
    return '<main>' + ('Metal Fest official event. ' * 8) + '</main>' + (
        '<script type="application/ld+json">' + json.dumps(event) + '</script>')


def inspect(source=None, **changes):
    return inspect_ticket_status(
        source if source is not None else html(**changes),
        ROW, URL, "2026-11-04")


class TicketStatusTests(unittest.TestCase):
    def test_category_sold_out_is_not_whole_festival_sold_out(self):
        records = inspect()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["ticket_categories"], [
            {"category": "Pass dimanche", "availability": "in_stock"},
            {"category": "Pass samedi", "availability": "sold_out"},
        ])
        self.assertIs(records[0]["publication_authorized"], False)
        self.assertIsNone(records[0]["sensitive_event_status"])

    def test_generic_schema_event_uses_same_exact_edition_guards(self):
        # Some official ticket pages use the generic schema.org/Event type.
        self.assertEqual(len(inspect(**{"@type": "Event"})), 1)
        self.assertEqual(inspect(**{"@type": "Event", "name": "Metal Fest"}), [])
        self.assertEqual(inspect(**{"@type": "Event", "startDate": "2027-08-14"}), [])
        self.assertEqual(inspect(**{"@type": "OtherEvent"}), [])

    def test_missing_or_unlabelled_availability_not_assumed(self):
        self.assertEqual(inspect(offers=[{"@type": "Offer",
            "availability": "https://schema.org/SoldOut"}]), [])
        self.assertEqual(inspect(offers=[{"name": "Pass samedi"}]), [])
        self.assertEqual(inspect(source="<main>Festival complet, sold out! </main>"), [])
        self.assertEqual(inspect(offers=[{"name": "Pass samedi",
            "availability": "https://evil.example/SoldOut"}]), [])

    def test_conflicting_offer_categories_fail_closed(self):
        self.assertEqual(inspect(offers=[
            {"name": "Pass samedi", "availability": "SoldOut"},
            {"name": "Pass samedi", "availability": "InStock"}]), [])

    def test_unique_edition_and_same_dates_required_for_ticket(self):
        self.assertEqual(inspect(name="Metal Fest 2028"), [])
        self.assertEqual(inspect(name="Metal Fest"), [])
        self.assertEqual(inspect(name="Other Fest 2027"), [])
        self.assertEqual(inspect(startDate="2027-08-14"), [])
        self.assertEqual(inspect(eventStatus="EventScheduled", offers=[]), [])
        duplicate = json.loads(html().split('application/ld+json">', 1)[1].split("</script>")[0])
        variant = dict(duplicate)
        variant["offers"] = [{"name":"Pass dimanche", "availability":"SoldOut"}]
        self.assertEqual(inspect(source='<script type="application/ld+json">' +
            json.dumps({"@graph":[duplicate, variant]}) + '</script>'), [])

    def test_cancellation_and_postponement_remain_review_only(self):
        for status, expected in [
            ("https://schema.org/EventCancelled", "cancelled"),
            ("EventPostponed", "postponed"),
            ("EventRescheduled", "rescheduled"),
        ]:
            clues = inspect(eventStatus=status, offers=[], startDate="2027-08-14", endDate="2027-08-15")
            self.assertEqual(clues[0]["sensitive_event_status"], expected)
            self.assertEqual(clues[0]["ticket_categories"], [])
            self.assertIs(clues[0]["publication_authorized"], False)

    def test_two_calendar_days_required_even_if_same_day_repeated(self):
        state = {}
        first = inspect()
        self.assertIsNone(stable_ticket_status_observation(
            state, ROW["slug"], URL, first, "2026-11-04"))
        self.assertIsNone(stable_ticket_status_observation(
            state, ROW["slug"], URL, first, "2026-11-04"))
        confirmed = stable_ticket_status_observation(
            state, ROW["slug"], URL, first, "2026-11-05")
        self.assertEqual(len(confirmed), 64)
        self.assertEqual(stable_ticket_status_observation(
            state, ROW["slug"], URL, first, "2026-11-05"), confirmed)
        self.assertEqual(state[STATE_KEY][ROW["slug"]]["firstSeen"], "2026-11-04")

    def test_availability_change_or_date_gap_restarts_confirmation(self):
        state = {}
        a = inspect()
        b = inspect(offers=[{"name": "Pass samedi", "availability": "InStock"}])
        self.assertIsNone(stable_ticket_status_observation(
            state, ROW["slug"], URL, a, "2026-11-04"))
        self.assertIsNone(stable_ticket_status_observation(
            state, ROW["slug"], URL, b, "2026-11-05"))
        self.assertIsNotNone(stable_ticket_status_observation(
            state, ROW["slug"], URL, b, "2026-11-06"))
        state = {}
        self.assertIsNone(stable_ticket_status_observation(
            state, ROW["slug"], URL, a, "2026-11-04"))
        self.assertIsNone(stable_ticket_status_observation(
            state, ROW["slug"], URL, a, "2026-11-06"))

    def test_bad_proofs_clear_state_and_never_become_updates(self):
        state = {}
        a = inspect()
        stable_ticket_status_observation(state, ROW["slug"], URL, a, "2026-11-04")
        a[0]["publication_authorized"] = True
        self.assertIsNone(stable_ticket_status_observation(
            state, ROW["slug"], URL, a, "2026-11-05"))
        self.assertNotIn(ROW["slug"], state[STATE_KEY])
        with self.assertRaises(ValueError):
            stable_ticket_status_observation({STATE_KEY: []},
                                             ROW["slug"], URL, [], "2026-11-05")

    def test_summary_reports_review_without_publication(self):
        report = {
            "schema": "grossesondes.source-watch-report.v1",
            "date": "2026-11-05", "scanned": [], "unavailable": [],
            "ticketStatusReviewCount": 2, "candidateUpdateCount": 0,
            "candidateEditionCount": 0, "deferredAdded": 2,
        }
        text = render(report)
        self.assertIn("**2** signaux revus", text)
        self.assertIn("catégories uniquement", text)
        self.assertIn("publiées par cette veille : **0**", text)
        report["ticketStatusReviewCount"] = -1
        with self.assertRaises(ValueError):
            render(report)



    def test_next_day_ticket_recheck_is_prioritized_without_starving_rotation(self):
        doc = {"schema": 1, "festivals": [
            {"slug": "festival-" + str(i),
             "officialSite": "https://festival" + str(i) + ".example.org/",
             "startDate": "2027-08-12"} for i in range(100)]}
        today = date(2026, 11, 5)
        normal = choose_sources(doc, today, "primary", 12)
        earlier = choose_sources(doc, date(2026, 11, 4), "primary", 12)
        target = next(url for _, url in earlier if url not in {u for _, u in normal})
        state = {STATE_KEY: {"festival-1": {
            "source": target, "lastSeen": "2026-11-04",
            "digest": "candidate"}}}
        selected = choose_pending_rechecks(doc, today, "primary", 12, state)
        self.assertIn(target, [url for _, url in selected])
        self.assertGreaterEqual(
            len({url for _, url in selected} & {url for _, url in normal}), 11)
        state[STATE_KEY]["festival-1"]["source"] = "https://unregistered.example.org/"
        self.assertEqual(
            choose_pending_rechecks(doc, today, "primary", 12, state), normal)

    def test_real_watch_pipeline_only_appends_review_to_private_patch(self):
        doc = {"schema": 1, "generatedAt": "2026-11-03",
               "festivals": [
                   {"slug": "festival-" + str(i),
                    "name": "Festival Metal " + str(i) + " 2027",
                    "startDate": "2027-08-12", "endDate": "2027-08-13",
                    "officialSite": "https://festival" + str(i) + ".example.org/",
                    "lineup": [], "bands": 0, "lastVerified": "2026-10-01"}
                   for i in range(100)]}
        target_slug, target_url = choose_sources(
            doc, date(2026, 11, 4), "primary", 12)[0]
        name = next(row["name"] for row in doc["festivals"] if row["slug"] == target_slug)
        event = {"@type": "MusicFestival", "name": name,
                 "startDate": "2027-08-12", "endDate": "2027-08-13",
                 "offers": [{"name": "Pass samedi", "availability": "SoldOut"}]}
        official_page = ('<main>' + "Official metal festival ticket page. " * 8
                         + '</main><script type="application/ld+json">'
                         + json.dumps(event) + '</script>')
        baseline_page = "<main>" + "Ordinary official metal festival website. " * 8 + "</main>"
        patch = {"schema": "grossesondes.patch.v1", "generated_at": "2026-11-03",
                 "safe_to_publish": False,
                 "source": {"festivals": {"count": 100, "generatedAt": "2026-11-03",
                                          "url": "https://grosses-ondes.fr/data/festivals.json"}},
                 "additions": [], "updates": [], "history_additions": [],
                 "history_updates": [], "deferred": []}
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "patch-2026-11-03.json").write_text(json.dumps(patch))
            kwargs = {"limit": 12, "download_json": lambda _: doc,
                      "download_page": lambda url: official_page if url == target_url
                          else baseline_page}
            day1 = run(folder, "2026-11-04", **kwargs)
            day2 = run(folder, "2026-11-05", **kwargs)
            self.assertEqual(day1["ticketStatusReviewCount"], 0)
            self.assertEqual(day2["ticketStatusReviewCount"], 1)
            self.assertEqual(day2["ticket_status_review"][0]["slug"], target_slug)
            self.assertEqual(day2["candidateUpdateCount"], 0)
            self.assertEqual(day2["ticketProposalCount"], 1)
            self.assertEqual(day2["publishedChanges"], 0)
            proposed = json.loads((folder / "patch-2026-11-05.json").read_text())
            self.assertIs(proposed["safe_to_publish"], False)
            self.assertEqual(len(proposed["updates"]), 1)
            self.assertEqual(proposed["updates"][0]["proofMode"], "structured-tickets.v1")
            self.assertEqual(proposed["updates"][0]["changes"][0]["field"],
                             "ticketAvailability")
            self.assertEqual(proposed["additions"], [])
            self.assertEqual(len(proposed["deferred"]), 1)
            self.assertEqual(proposed["deferred"][0]["evidence_kind"],
                             "schema.org-ticket-status-two-day")

if __name__ == "__main__":
    unittest.main()
