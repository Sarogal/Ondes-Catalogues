"""No provider page can directly authorize public ticketAvailability."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).parent))
from official_watch import run
from ticket_provider_probe import (provider_snapshot, select_provider_checks,
                                   provider_conflict_reason)
from ticket_candidates import withdraw_contradicted_ticket_proposals


def edition(slug="unfest-3-2026", official="https://mjcdouai.fr/unfest/"):
    return {"slug": slug, "name": "UNFEST #3", "startDate": "2026-11-06",
            "endDate": "2026-11-07", "officialSite": official}


def event_html(title="UNFEST#3", start="2026-11-06", end="2026-11-07",
               status=None, availability="https://schema.org/SoldOut"):
    event = {"@type": "MusicEvent", "name": title, "startDate": start,
             "endDate": end, "offers": [
                 {"name": "Pass samedi", "availability": availability}]}
    if status:
        event["eventStatus"] = status
    return ('<main>Official tickets</main><script type="application/ld+json">' +
            json.dumps(event) + "</script>")


class ProviderReviewTests(unittest.TestCase):
    def test_exact_edition_is_only_review(self):
        found = provider_snapshot(event_html(), edition())
        self.assertEqual(found["result"], "EXPLICIT_CATEGORY_HINTS")
        self.assertEqual(found["categories_review_only"], [
            {"category": "Pass samedi", "availability": "sold_out"}])
        self.assertNotIn("ticketAvailability", found)
        self.assertNotIn("publication_authorized", found)

    def test_wrong_title_date_or_unstructured_sold_out_is_not_a_hint(self):
        for raw in (event_html(title="UNFEST #4"),
                    event_html(start="2025-11-06"),
                    "<p>Pass samedi: complet</p>"):
            self.assertEqual(provider_snapshot(raw, edition())["result"], "UNVERIFIED")

    def test_cancelled_and_conflicting_sources_do_not_claim_stock(self):
        result = provider_snapshot(event_html(
            status="https://schema.org/EventCancelled"), edition())
        self.assertEqual(result["result"], "SENSITIVE_REVIEW")
        self.assertEqual(result["categories_review_only"], [])
        result = provider_snapshot(event_html() +
             event_html(availability="https://schema.org/InStock"), edition())
        self.assertEqual(result["result"], "CONFLICT")
        self.assertEqual(result["categories_review_only"], [])

    def test_selector_excludes_archives_unknown_hosts_and_injected_links(self):
        current = edition()
        archived = {**edition("old", "https://creeps.fr/"),
                    "startDate": "2026-10-31", "endDate": "2026-10-31"}
        future = {**edition("future", "https://fest.fr/"),
                  "startDate": "2027-07-08", "endDate": "2027-07-09"}
        editions = {r["slug"]: r for r in (current, archived, future)}
        def lead(row, url):
            return {"slug": row["slug"], "source_url": row["officialSite"],
                    "ticket_url": url, "provider": "HelloAsso",
                    "verification_status": "LINK_ONLY",
                    "publication_authorized": False}
        x = lead(current, "https://www.helloasso.com/associations/x/evenements/unfest")
        rows = [
            lead(archived, "https://helloasso.com/associations/x/evenements/old"),
            lead(future, "https://helloasso.com/associations/x/evenements/next"),
            x, x,
            {**x, "source_url": "https://attacker.fr"},
            {**x, "ticket_url": "https://www.helloasso.com.evil.fr/bad"}
        ]
        selected = select_provider_checks(rows, editions, "2026-11-04")
        self.assertEqual([row["slug"] for row, _ in selected], ["unfest-3-2026", "future"])
        self.assertEqual(select_provider_checks(rows, editions, "2027-11-10"), [])

    def test_probe_budget_covers_distinct_festivals_and_prefers_exact_offers(self):
        first = edition()
        second = {**edition("next-festival", "https://festival-two.fr/"),
                  "name": "Next Festival"}
        third = {**edition("third-festival", "https://festival-three.fr/"),
                 "name": "Third Festival"}
        all_editions = {r["slug"]: r for r in (first, second, third)}

        def lead(row, suffix, structured=False):
            item = {"slug": row["slug"], "source_url": row["officialSite"],
                    "ticket_url": "https://my.weezevent.com/" + suffix,
                    "provider": "Weezevent", "verification_status": "LINK_ONLY",
                    "publication_authorized": False}
            if structured:
                item["link_origin"] = "schema_org_offer_url"
            return item

        links = [
            lead(first, "aaa-generic"),
            lead(first, "zzz-precise", structured=True),
            lead(first, "bbb-generic"),
            lead(second, "next"),
            lead(third, "third"),
        ]
        selected = select_provider_checks(links, all_editions, "2026-11-04", limit=3)
        self.assertEqual({item["slug"] for item, _ in selected},
                         {"unfest-3-2026", "next-festival", "third-festival"})
        first_checked = next(item for item, _ in selected
                             if item["slug"] == "unfest-3-2026")
        self.assertEqual(first_checked["ticket_url"],
                         "https://my.weezevent.com/zzz-precise")
        self.assertEqual(len(set(item["slug"] for item, _ in selected)), 3)

    def test_watch_never_publishes_or_creates_patch_from_provider_html(self):
        festivals = []
        for i in range(90):
            f = edition("festival-" + str(i), "https://festival" + str(i) + ".fr/")
            if i % 2:
                f.update(startDate="2026-10-20", endDate="2026-10-21")
            festivals.append(f)
        doc = {"schema": 1, "generatedAt": "2026-11-04", "festivals": festivals}
        fetched = []
        def download_page(url):
            if "helloasso" in url:
                fetched.append(url)
                return event_html()
            return ("<p>" + "Festival officiel de musique. " * 10 + "</p>" +
                '<a href="https://www.helloasso.com/associations/x/evenements/unfest">Billets</a>')
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            report = run(folder, "2026-11-04", limit=8,
                         download_json=lambda u: doc, download_page=download_page)
            self.assertGreater(len(report["ticket_link_leads_review_only"]), 0)
            self.assertLessEqual(len(report["ticket_provider_checks_review_only"]), 3)
            self.assertLessEqual(len(fetched), 3)
            self.assertEqual(report["ticketProposalCount"], 0)
            self.assertEqual(report["publishedChanges"], 0)
            self.assertFalse((folder / "patch-2026-11-04.json").exists())


    def test_provider_disagreement_is_veto_not_an_availability_claim(self):
        official = {"ticket_categories": [
            {"category": "Pass Samedi", "availability": "in_stock"},
            {"category": "Pass Week-end", "availability": "sold_out"},
        ]}
        vendor = {"result": "EXPLICIT_CATEGORY_HINTS", "categories_review_only": [
            {"category": "pass samedi", "availability": "sold_out"}]}
        self.assertEqual(provider_conflict_reason(vendor, official),
                         "CATEGORY_DISAGREEMENT")
        self.assertIsNone(provider_conflict_reason(
            {"result": "INACCESSIBLE", "categories_review_only": []}, official))
        self.assertIsNone(provider_conflict_reason(
            {"result": "UNVERIFIED", "categories_review_only": []}, official))
        self.assertIsNone(provider_conflict_reason(
            {"result": "MATCHED_NO_STOCK", "categories_review_only": []}, official))
        self.assertIsNone(provider_conflict_reason(
            {"result": "EXPLICIT_CATEGORY_HINTS", "categories_review_only": [
                {"category": "Pass Week-end", "availability": "sold_out"}]}, official))
        self.assertIsNone(provider_conflict_reason(vendor, None))
        self.assertEqual(provider_conflict_reason(
            {"result": "CONFLICT", "categories_review_only": []}, None),
            "VENDOR_STRUCTURED_CONFLICT")
        self.assertEqual(provider_conflict_reason(
            {"result": "SENSITIVE_REVIEW", "categories_review_only": []}, None),
            "VENDOR_SENSITIVE_REVIEW")

    def test_withdraw_only_automated_ticket_candidate(self):
        ticket = {"slug": "one", "proofMode": "structured-tickets.v1",
                  "changes": [{"field": "ticketAvailability", "before": None,
                               "after": {"categories": []}}]}
        roster = {"slug": "one", "proofMode": "structured-roster.v1",
                  "changes": [{"field": "lineup"}]}
        manual = {"slug": "one", "changes": [{"field": "ticketAvailability"}]}
        another = {**ticket, "slug": "two"}
        patch = {"schema": "grossesondes.patch.v1",
                 "safe_to_publish": False,
                 "updates": [ticket, roster, manual, another]}
        self.assertEqual(withdraw_contradicted_ticket_proposals(patch, {"one"}), 1)
        self.assertEqual(patch["updates"], [roster, manual, another])

    def test_vendor_contradiction_retracts_candidate_in_private_intake(self):
        festivals = []
        for index in range(90):
            row = edition("festival-" + str(index))
            if index:
                row["name"] = "Unrelated Festival " + str(index)
            festivals.append(row)
        document = {"schema": 1, "generatedAt": "2026-11-04",
                    "festivals": festivals}
        previous = {
            "schema": "grossesondes.patch.v1", "safe_to_publish": False,
            "generated_at": "2026-11-03",
            "source": {"festivals": {
                "url": "https://grosses-ondes.fr/data/festivals.json",
                "generatedAt": document["generatedAt"],
                "count": len(festivals)}},
            "additions": [], "updates": [{
                "slug": "festival-0", "proofMode": "structured-tickets.v1",
                "changes": [{"field": "ticketAvailability", "before": None,
                             "after": {"categories": []}}]
            }],
            "history_additions": [], "history_updates": [], "deferred": [],
        }
        organizer_page = ("<main>" + ("Official festival information. " * 8)
                          + "</main>" + event_html(title="UNFEST #3 2026")
                          + '<a href="https://my.weezevent.com/unfest-3">Tickets</a>')
        vendor_page = event_html(title="UNFEST #3 2026",
                                 availability="https://schema.org/InStock")
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "patch-2026-11-03.json").write_text(
                json.dumps(previous), encoding="utf-8")
            report = run(folder, "2026-11-04", limit=3,
                         download_json=lambda _url: document,
                         download_page=lambda _url: organizer_page,
                         download_vendor=lambda _url: vendor_page)
            self.assertEqual(report["ticketProposalCount"], 0)
            self.assertEqual(report["ticketProposalWithdrawnCount"], 1)
            self.assertEqual(report["publishedChanges"], 0)
            self.assertEqual(len(report["ticket_provider_conflicts_review_only"]), 1)
            self.assertEqual(report["ticket_provider_conflicts_review_only"][0]["reason"],
                             "CATEGORY_DISAGREEMENT")
            patched = json.loads((folder / "patch-2026-11-04.json").read_text())
            self.assertFalse(any(row.get("slug") == "festival-0"
                                 for row in patched["updates"]))


    def test_rotation_favors_new_editions_and_changed_provider_links(self):
        editions = {}
        leads = []
        for i in range(5):
            row = {**edition("festival-" + str(i)),
                   "officialSite": "https://festival" + str(i) + ".fr/"}
            editions[row["slug"]] = row
            leads.append({
                "slug": row["slug"], "source_url": row["officialSite"],
                "ticket_url": "https://my.weezevent.com/ticket-" + str(i),
                "provider": "Weezevent", "verification_status": "LINK_ONLY",
                "publication_authorized": False,
            })
        first = select_provider_checks(leads, editions, "2026-11-04", limit=3)
        self.assertEqual(len(first), 3)
        history = {
            lead["slug"]: {"ticket_url": lead["ticket_url"],
                           "lastChecked": "2026-11-04"}
            for lead, _ in first
        }
        second = select_provider_checks(
            leads, editions, "2026-11-04", limit=3, last_checked=history)
        new_slugs = {lead["slug"] for lead, _ in second}
        self.assertEqual(len(new_slugs), 3)
        self.assertEqual(len(new_slugs - set(history)), 2)
        # Same edition, newly discovered official link: review again.
        updated = [{**lead, "ticket_url": "https://my.weezevent.com/new-link"}
                   if lead["slug"] == first[0][0]["slug"] else lead
                   for lead in leads]
        changed = select_provider_checks(
            updated, editions, "2026-11-04", limit=3, last_checked=history)
        self.assertIn(first[0][0]["slug"], {lead["slug"] for lead, _ in changed})
        # Impossible future history must not starve a festival.
        future_history = {slug: {**entry, "lastChecked": "2099-01-01"}
                          for slug, entry in history.items()}
        again = select_provider_checks(
            leads, editions, "2026-11-04", limit=5,
            last_checked=future_history)
        self.assertEqual(len(again), 5)

    def test_two_private_runs_rotate_even_after_inaccessible_pages(self):
        festivals = []
        for i in range(90):
            row = edition("festival-" + str(i),
                          "https://festival" + str(i) + ".fr/")
            festivals.append(row)
        doc = {"schema": 1, "generatedAt": "2026-11-04",
               "festivals": festivals}

        def official_page(url):
            host = urlsplit(url).hostname
            return ("<main>" + "Site officiel musique festival. " * 8 +
                    "</main><a href='https://my.weezevent.com/" +
                    host.split(".")[0] + "'>Billetterie</a>")

        def vendor_unavailable(url):
            raise ValueError("page inaccessible")

        with tempfile.TemporaryDirectory() as tmp:
            first = run(tmp, "2026-11-04", limit=12,
                        download_json=lambda _url: doc,
                        download_page=official_page,
                        download_vendor=vendor_unavailable)
            second = run(tmp, "2026-11-04", limit=12,
                         download_json=lambda _url: doc,
                         download_page=official_page,
                         download_vendor=vendor_unavailable)
            a = {x["slug"] for x in first["ticket_provider_checks_review_only"]}
            b = {x["slug"] for x in second["ticket_provider_checks_review_only"]}
            self.assertEqual(len(a), 3)
            self.assertEqual(len(b), 3)
            self.assertTrue(a.isdisjoint(b))
            self.assertEqual(first["ticket_provider_first_checks_review_only"], 3)
            self.assertEqual(second["ticket_provider_first_checks_review_only"], 3)
            self.assertTrue(all(x["result"] == "INACCESSIBLE"
                                for x in second["ticket_provider_checks_review_only"]))
            self.assertEqual(second["publishedChanges"], 0)
            state = json.loads((Path(tmp) / "source-watch-state.json").read_text())
            self.assertEqual(len(state["ticket_provider_last_checked"]), 6)



    def test_rotates_three_links_for_one_festival_without_repeat(self):
        row = edition()
        editions = {row["slug"]: row}
        def link(suffix, structured=False):
            lead = {"slug": row["slug"], "source_url": row["officialSite"],
                    "ticket_url": "https://my.weezevent.com/" + suffix,
                    "provider": "Weezevent", "verification_status": "LINK_ONLY",
                    "publication_authorized": False}
            if structured:
                lead["link_origin"] = "schema_org_offer_url"
            return lead
        leads = [link("generic-a"), link("offer-exact", True), link("generic-b")]
        history = {}
        order = []
        for n in range(3):
            selected = select_provider_checks(
                leads, editions, "2026-11-04", limit=3,
                last_checked=history)
            self.assertEqual(len(selected), 1)
            chosen = selected[0][0]
            order.append(chosen["ticket_url"])
            previous = history.get(row["slug"], {"urls": {}})
            dates = dict(previous.get("urls", {}))
            dates[chosen["ticket_url"]] = "2026-11-04"
            history[row["slug"]] = {
                "ticket_url": chosen["ticket_url"], "lastChecked": "2026-11-04",
                "urls": dates}
        self.assertEqual(len(set(order)), 3)
        self.assertEqual(order[0], "https://my.weezevent.com/offer-exact")
        # Once every link was examined, the exact organizer offer wins ties.
        selected = select_provider_checks(
            leads, editions, "2026-11-04", last_checked=history)
        self.assertEqual(selected[0][0]["ticket_url"], order[0])

    def test_legacy_vendor_history_prioritizes_other_link(self):
        row = edition()
        leads = []
        for suffix in ("old", "alternative"):
            leads.append({"slug": row["slug"], "source_url": row["officialSite"],
                          "ticket_url": "https://my.weezevent.com/" + suffix,
                          "provider": "Weezevent", "verification_status": "LINK_ONLY",
                          "publication_authorized": False})
        history = {row["slug"]: {
            "ticket_url": "https://my.weezevent.com/alternative",
            "lastChecked": "2026-11-03"}}
        selected = select_provider_checks(
            leads, {row["slug"]: row}, "2026-11-04", last_checked=history)
        self.assertEqual(selected[0][0]["ticket_url"],
                         "https://my.weezevent.com/old")

    def test_cloud_intake_alternates_seller_urls_without_publishing(self):
        rows = [edition("festival-0")]
        for index in range(1, 90):
            old = edition("archive-" + str(index))
            old.update(name="Archive " + str(index),
                       startDate="2026-10-01", endDate="2026-10-01")
            rows.append(old)
        document = {"schema": 1, "generatedAt": "2026-11-04", "festivals": rows}
        page = ("<main>" + "Site officiel du festival et billetterie. " * 8 +
                "</main>" + "".join(
                    '<a href="https://my.weezevent.com/vendor-%s">Billets</a>' % suffix
                    for suffix in ("a", "b", "c")))
        def inaccessible(_url):
            raise ValueError("HTTP 403")
        attempts = []
        with tempfile.TemporaryDirectory() as temp:
            for i in range(3):
                report = run(temp, "2026-11-04", limit=2,
                             download_json=lambda _url: document,
                             download_page=lambda _url: page,
                             download_vendor=inaccessible)
                checks = report["ticket_provider_checks_review_only"]
                self.assertEqual(len(checks), 1)
                attempts.append(checks[0]["ticket_url"])
                self.assertEqual(checks[0]["result"], "INACCESSIBLE")
                self.assertEqual(report["ticket_provider_first_checks_review_only"], 1)
                self.assertEqual(report["ticketProposalCount"], 0)
                self.assertEqual(report["publishedChanges"], 0)
            self.assertEqual(len(set(attempts)), 3)
            state = json.loads((Path(temp) / "source-watch-state.json").read_text())
            record = state["ticket_provider_last_checked"]["festival-0"]
            self.assertEqual(set(record["urls"]), set(attempts))
            self.assertEqual(record["ticket_url"], attempts[-1])


if __name__ == "__main__":
    unittest.main()
