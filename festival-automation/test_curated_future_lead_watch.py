"""Never publish inferred 2027 festivals; only fixed, visible primary claims."""
import copy
from datetime import date
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from curated_future_lead_watch import (
    load_leads, published_duplicate, select_leads, inspect_primary, scan,
    SCHEMA, ALLOWED,
)

DAY = "2026-11-05"
DATA = json.loads(Path(__file__).with_name(
    "curated_future_leads.json").read_text(encoding="utf-8"))
LEADS = load_leads(DATA)
SAMPLE = LEADS[0]


def report(day=DAY):
    return {"schema": "grossesondes.source-watch-report.v1", "date": day}


def state():
    return {"schema": "grossesondes.source-watch.v1"}


def html(lead=SAMPLE, date_phrase=None):
    phrase = date_phrase if date_phrase is not None else lead["date_phrase"]
    return ("<main><h1>" + lead["name"] + "</h1>"
            "<p>Festival à venir en France. Édition confirmée sur "
            "notre site : " + phrase + ". Informations officielles "
            "sur le site de l'événement et les organisateurs.</p></main>")


class CuratedFutureLeadTests(unittest.TestCase):
    def test_configuration_fixed_primary_urls_only(self):
        self.assertEqual(len(LEADS), 5)
        self.assertEqual(set(ALLOWED), {row["id"] for row in LEADS})
        self.assertEqual(sum(x["start_date"] is None for x in LEADS), 1)
        self.assertEqual(LEADS[-1]["id"], "esqui-riot-2027")
        for lead in LEADS:
            self.assertTrue(lead["source_url"].startswith("https://"))
            self.assertIn("2027", lead["date_phrase"])

    def test_unreviewed_host_query_and_path_never_fetched(self):
        for bad in ("http://www.mozhell.fr/fr/",
                    "https://127.0.0.1/internal",
                    "https://www.mozhell.fr/fr/?redirect=https://evil.fr",
                    "https://www.mozhell.fr/fr/another-2027",
                    "https://www.mozhell.fr.evil.fr/fr/"):
            copy_data = copy.deepcopy(DATA)
            copy_data["leads"][0]["source_url"] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                load_leads(copy_data)

    def test_dates_cannot_be_synthetic_or_partial(self):
        for start, end in (("2027-07-23", None),
                           ("2027-07-23", "2027-07-22"),
                           ("2028-07-23", "2028-07-24"),
                           ("2027-01-01", "2027-01-10")):
            data = copy.deepcopy(DATA)
            data["leads"][0]["start_date"] = start
            data["leads"][0]["end_date"] = end
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                load_leads(data)

    def test_hidden_date_or_name_does_not_support_a_primary_claim(self):
        hidden_date = ("<main><h1>MozHell Open Air</h1>"
                       "<p>Festival officiel 2027 en France.</p>"
                       "<script>" + SAMPLE["date_phrase"] + "</script></main>")
        self.assertEqual(inspect_primary(SAMPLE, hidden_date)[:2], (True, False))
        hidden_name = ("<main><h1>Festival inconnu</h1>"
                       "<p>Les dates sont " + SAMPLE["date_phrase"] +
                       " et la billetterie arrive bientôt.</p>"
                       "<div hidden>MozHell Open Air</div></main>")
        self.assertEqual(inspect_primary(SAMPLE, hidden_name)[:2], (False, True))

    def test_two_different_calendar_days_still_private(self):
        s, urls = state(), []
        def fetch(url):
            urls.append(url)
            return html()
        doc = {"festivals": []}
        first = scan(report(), s, [SAMPLE], doc, DAY, fetch, limit=1)
        self.assertEqual(first[0]["status"], "FIRST_PRIMARY_OBSERVATION_PRIVATE")
        self.assertFalse(first[0]["publication_authorized"])
        self.assertTrue(first[0]["dated_edition"])
        self.assertEqual(scan(report(), s, [SAMPLE], doc, DAY, fetch, limit=1), [])
        self.assertEqual(len(urls), 1)
        tomorrow = "2026-11-06"
        second = scan(report(tomorrow), s, [SAMPLE], doc,
                      tomorrow, fetch, limit=1)
        self.assertEqual(second[0]["status"], "TWO_DAYS_PRIMARY_OBSERVATION_PRIVATE")
        self.assertEqual(len(urls), 2)
        self.assertEqual(s["curated_future_lead_observations"][SAMPLE["id"]]
                         ["publication_authorized"], False)
        self.assertEqual(report().get("curated_future_leads_publications"), None)
        self.assertTrue(all(x["publication_authorized"] is False
                            for x in first + second))

    def test_dated_public_duplicate_is_not_added_as_another_lead(self):
        published = {"festivals": [{
            "slug": "other-slug", "name": "MozHell Open Air 2027",
            "startDate": "2027-07-23", "officialSite": "https://www.mozhell.fr/fr/",
        }]}
        self.assertTrue(published_duplicate(SAMPLE, published))
        calls = []
        outcome = scan(report(), state(), [SAMPLE], published, DAY,
                       lambda url: calls.append(url), limit=1)
        self.assertEqual(calls, [])
        self.assertEqual(outcome[0]["status"], "ALREADY_PUBLISHED")
        self.assertFalse(outcome[0]["publication_authorized"])

    def test_poisoned_state_never_becomes_a_fetch_destination(self):
        s = state()
        s["curated_future_lead_last_checked"] = {"https://127.0.0.1/": DAY}
        s["curated_future_lead_observations"] = {
            "https://127.0.0.1/": {"publication_authorized": True}}
        calls = []
        scan(report(), s, [SAMPLE], {"festivals": []}, DAY,
             lambda url: (calls.append(url) or html()), limit=1)
        self.assertEqual(calls, [SAMPLE["source_url"]])
        self.assertNotIn("https://127.0.0.1/", s["curated_future_lead_last_checked"])
        self.assertNotIn("https://127.0.0.1/", s["curated_future_lead_observations"])

    def test_source_unavailable_never_confirms_a_date(self):
        s = state()
        def down(_):
            raise OSError("503")
        result = scan(report(), s, [SAMPLE], {"festivals": []}, DAY, down, limit=1)
        self.assertEqual(result[0]["status"], "SOURCE_UNAVAILABLE")
        self.assertNotIn(SAMPLE["id"], s["curated_future_lead_observations"])

    def test_visible_change_retracts_prior_positive_observation(self):
        s = state()
        scan(report(), s, [SAMPLE], {"festivals": []}, DAY,
             lambda _: html(), limit=1)
        result = scan(report("2026-11-06"), s, [SAMPLE], {"festivals": []},
                      "2026-11-06", lambda _: html(date_phrase="juin 2028"),
                      limit=1)
        self.assertEqual(result[0]["status"], "VISIBLE_EVIDENCE_INSUFFICIENT")
        self.assertNotIn(SAMPLE["id"], s["curated_future_lead_observations"])

    def test_undated_festival_cannot_be_promoted_as_dated(self):
        lead = LEADS[-1]
        out = scan(report(), state(), [lead], {"festivals": []},
                   DAY, lambda _: html(lead), limit=1)
        self.assertEqual(out[0]["status"], "FIRST_PRIMARY_OBSERVATION_PRIVATE")
        self.assertFalse(out[0]["dated_edition"])
        self.assertFalse(out[0]["publication_authorized"])

    def test_budget_and_no_same_day_second_fetch(self):
        s, calls = state(), []
        scan(report(), s, LEADS, {"festivals": []}, DAY,
             lambda url: (calls.append(url) or html()), limit=2)
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(set(calls)), 2)
        self.assertEqual(select_leads(LEADS, s["curated_future_lead_last_checked"],
                                      DAY, 2)[0]["id"],
                         sorted(x["id"] for x in LEADS if x["id"] not in
                                s["curated_future_lead_last_checked"])[0])
        with self.assertRaises(ValueError):
            scan(report(), s, LEADS, {"festivals": []}, DAY,
                 lambda url: html(), limit=3)

    def test_bad_report_and_unknown_config_rejected(self):
        s = state()
        with self.assertRaises(ValueError):
            scan(report("2026-11-06"), s, LEADS, {"festivals": []},
                 DAY, lambda _: html(), limit=1)
        data = copy.deepcopy(DATA)
        data["leads"][0]["id"] = "new-festival-unknown"
        with self.assertRaises(ValueError):
            load_leads(data)


    def test_failed_recheck_revokes_previous_primary_evidence(self):
        sample = SAMPLE
        s = state()
        live = {"festivals": []}
        first = scan(report(), s, [sample], live, DAY,
                     lambda _: html(), limit=1)
        self.assertEqual(first[0]["status"], "FIRST_PRIMARY_OBSERVATION_PRIVATE")
        self.assertIn(sample["id"], s["curated_future_lead_observations"])

        def unavailable(_):
            raise OSError("temporary failure")
        result = scan(report("2026-11-06"), s, [sample], live,
                      "2026-11-06", unavailable, limit=1)
        self.assertEqual(result[0]["status"], "SOURCE_UNAVAILABLE")
        self.assertNotIn(sample["id"], s["curated_future_lead_observations"])
        self.assertFalse(result[0]["publication_authorized"])

    def test_truncated_recheck_revokes_previous_primary_evidence(self):
        sample = SAMPLE
        s = state()
        live = {"festivals": []}
        scan(report(), s, [sample], live, DAY,
             lambda _: html(), limit=1)
        result = scan(report("2026-11-06"), s, [sample], live,
                      "2026-11-06", lambda _: "<html>oops</html>", limit=1)
        self.assertEqual(result[0]["status"], "SOURCE_UNAVAILABLE")
        self.assertNotIn(sample["id"], s["curated_future_lead_observations"])


if __name__ == "__main__":
    unittest.main()
