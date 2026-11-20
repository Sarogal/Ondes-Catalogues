"""Offline security and provenance tests for nationwide OpenAgenda public research."""
from copy import deepcopy
import unittest

from national_openagenda_research import (
    SCHEMA, STATE_KEY, QUERIES, SOURCE, MAX_LEADS, FESTIVAL_PAGE_OFFSETS,
    candidate, fixed_query_urls, fetch_json, validated_leads, scan,
)

DAY = "2026-11-20"
EVENT = {
    "title_fr": "Festival Metal des Garrigues 2027",
    "canonicalurl": "https://openagenda.com/agenda-rock/events/festival-metal-garrigues-2027",
    "firstdate_begin": "2027-04-23T18:00:00+02:00",
    "lastdate_begin": "2027-04-24T20:00:00+02:00",
    "description_fr": "Festival métal et rock avec concerts.",
    "keywords_fr": ["metal", "rock"],
    "location_region": "Occitanie", "location_countrycode": "FR",
    "status": "Programmée",
}


def state():
    return {"schema": "grossesondes.source-watch.v1"}


def payload(records):
    return {"total_count": len(records), "results": records}


class NationalOpenAgendaResearchTests(unittest.TestCase):
    def test_public_workflow_preserves_private_runner_boundaries(self):
        from pathlib import Path
        workflow = (Path(__file__).resolve().parents[1] / ".github" /
                    "workflows" /
                    "grossesondes-festivals-private-intake-on-public-runners.yml"
                    ).read_text(encoding="utf-8")
        self.assertIn("runs-on: ubuntu-24.04", workflow)
        self.assertIn("branches: [main]", workflow)
        self.assertNotIn("pull_request_target:", workflow)
        self.assertIn("national_openagenda_research.py", workflow)
        self.assertIn("national-openagenda-research-review.json", workflow)
        self.assertIn("--catalog application/docs/grossesondes/festivals.json",
                      workflow)
        self.assertLess(workflow.index("run_private openagenda_public_research"),
                        workflow.index("run_private queue"))
        self.assertIn("intake/automation-intake/grossesondes", workflow)

    def test_all_queries_are_fixed_bounded_and_no_user_url(self):
        urls = fixed_query_urls()
        self.assertEqual(len(urls), len(QUERIES) + len(FESTIVAL_PAGE_OFFSETS) - 1)
        self.assertEqual(urls, fixed_query_urls(DAY))
        self.assertEqual(list(FESTIVAL_PAGE_OFFSETS), list(range(0, 200, 25)))
        self.assertTrue(all("offset=" in x for x in urls))
        self.assertTrue(any("offset=175" in x for x in urls))
        self.assertTrue(any("offset=0" in x for x in urls))
        self.assertEqual(len(urls), len(set(urls)))
        self.assertTrue(all(x.startswith(SOURCE + "?") for x in urls))
        self.assertTrue(all("limit=25" in x for x in urls))
        self.assertTrue(all("select=" in x and "where=" in x for x in urls))
        self.assertTrue(all("lastdate_begin" in x and "firstdate_begin" in x
                            for x in urls))
        self.assertTrue(all("2026-11-20" in x and "2029-01-01" in x
                            for x in urls))
        self.assertNotEqual(urls, fixed_query_urls("2026-11-21"))
        with self.assertRaises(ValueError):
            fixed_query_urls("2026-11-20' OR 1=1")
        for invalid in (
            "https://evil.example/api",
            "http://public.opendatasoft.com/api",
            SOURCE + "?limit=100000",
            SOURCE + "?where=http%3A%2F%2F127.0.0.1",
        ):
            with self.subTest(url=invalid), self.assertRaises(ValueError):
                fetch_json(invalid)

    def test_strong_identity_future_dates_musical_theme_private_only(self):
        row = candidate(EVENT, DAY)
        self.assertIsNotNone(row)
        self.assertEqual(row["edition_year_hint"], 2027)
        self.assertEqual(row["region_hint"], "Occitanie")
        self.assertEqual(row["year_source_review_only"], "TITLE")
        self.assertEqual(row["kind"], "OPENAGENDA_PUBLIC_RESEARCH_ONLY")
        self.assertEqual(row["source_url"], EVENT["canonicalurl"])
        self.assertFalse(row["publication_authorized"])
        self.assertFalse(row["official_site_verified"])
        self.assertFalse(row["edition_dates_verified"])
        self.assertFalse(row["festival_verified"])
        self.assertNotIn("startDate", row)
        self.assertNotIn("lat", row)
        self.assertNotIn("artists", row)
        self.assertNotIn("date_hints", row)

    def test_yearless_edition_year_from_provider_is_unverified_research_hint(self):
        item = dict(EVENT, title_fr="Kreiz Y Fest #5")
        research = candidate(item, DAY)
        self.assertIsNotNone(research)
        self.assertEqual(research["edition_year_hint"], 2027)
        self.assertEqual(research["year_source_review_only"],
                         "UNVERIFIED_PROVIDER_START_DATE")
        self.assertFalse(research["edition_dates_verified"])
        self.assertFalse(research["official_site_verified"])
        self.assertFalse(research["publication_authorized"])
        s = state()
        report = scan(s, DAY, fetch=lambda _: payload([item]))
        self.assertEqual(report["leads_count"], 1)
        self.assertEqual(validated_leads(s, DAY), report["leads"])
        forged = deepcopy(s)
        forged[STATE_KEY]["leads"][0]["year_source_review_only"] = "TITLE"
        self.assertEqual(validated_leads(forged, DAY), [])
        mismatched = dict(item, firstdate_begin="2028-05-23T18:00:00+02:00")
        self.assertIsNone(candidate(mismatched, DAY))
        both_2028 = dict(mismatched, lastdate_begin="2028-05-24T20:00:00+02:00")
        self.assertEqual(candidate(both_2028, DAY)["edition_year_hint"], 2028)

    def test_single_concert_advertised_inside_a_festival_is_not_festival(self):
        """Generic exclusion, not a rule tailored to a named event."""
        cases = [
            "Concert gratuit de Léopard Café (Festival Culture Bar-Bars)",
            "Spectacle rock au Festival des Rives 2027",
            "Atelier metal pendant le Festival des Plaines 2027",
            "Soirée punk au Festival des Rives 2027",
        ]
        for label in cases:
            with self.subTest(label=label):
                event = dict(EVENT, title_fr=label,
                             description_fr="Festival punk rock")
                self.assertIsNone(candidate(event, DAY))
        # A genuine festival must not be rejected merely for hosting gigs.
        self.assertIsNotNone(candidate(
            dict(EVENT, title_fr="Festival Rock des Plaines 2027",
                 description_fr="Concerts et ateliers rock"), DAY))

    def test_known_edition_exact_name_year_region_is_not_queued_again(self):
        from national_openagenda_research import known_published_editions
        row = dict(EVENT, title_fr="KREIZ Y FEST #5",
                   canonicalurl="https://openagenda.com/shotgun/events/kreiz-y-fest-5",
                   description_fr="Festival metal et rock",
                   location_region="Bretagne")
        catalog = {"schema": 1, "festivals": [{
            "name": "Kreiz Y Fest", "startDate": "2027-07-09",
            "region": "Bretagne",
        }]}
        self.assertIn(("kreiz y fest", 2027, "Bretagne"),
                      known_published_editions(catalog))
        current = state()
        removed = scan(current, DAY, fetch=lambda _: payload([row]),
                       catalog=catalog)
        self.assertEqual(removed["leads_count"], 0)
        self.assertEqual(removed["already_published_leads_count"], 1)
        self.assertFalse(removed["publication_authorized"])
        self.assertEqual(validated_leads(current, DAY), [])
        # New trusted catalog digest triggers a fresh same-day review.
        not_published = {"schema": 1, "festivals": [{
            "name": "Kreiz Y Fest", "startDate": "2028-07-09",
            "region": "Bretagne",
        }]}
        seen = []
        available = scan(current, DAY, fetch=lambda u: (
            seen.append(u), payload([row]))[1], catalog=not_published)
        self.assertEqual(len(seen), len(fixed_query_urls(DAY)))
        self.assertEqual(available["leads_count"], 1)
        self.assertEqual(available["already_published_leads_count"], 0)
        # Different geographical festival also stays a research lead.
        wrong_region = {"schema": 1, "festivals": [{
            "name": "Kreiz Y Fest", "startDate": "2027-07-09",
            "region": "Occitanie",
        }]}
        other = scan(state(), DAY, fetch=lambda _: payload([row]),
                     catalog=wrong_region)
        self.assertEqual(other["leads_count"], 1)
        self.assertEqual(other["publications"], 0)

    def test_private_cache_invalidates_legacy_ruleset_and_forged_metadata(self):
        current = state()
        report = scan(current, DAY, fetch=lambda _: payload([EVENT]))
        stale = deepcopy(current)
        stale[STATE_KEY].pop("research_ruleset")
        self.assertEqual(validated_leads(stale, DAY), [])
        calls = []
        refreshed = scan(stale, DAY, fetch=lambda u: (
            calls.append(u), payload([EVENT]))[1])
        self.assertIsNot(refreshed, report)
        self.assertEqual(len(calls), len(fixed_query_urls(DAY)))
        self.assertEqual(refreshed["leads_count"], 1)
        for broken in (
            {"schema": 2, "festivals": []},
            {"schema": 1, "festivals": "unsafe"},
            {"schema": 1, "festivals": [None] * 5001},
        ):
            with self.subTest(broken=str(broken)[:50]):
                with self.assertRaises(ValueError):
                    scan(state(), DAY, fetch=lambda _: self.fail(
                        "Invalid trusted catalog cannot initiate requests"),
                        catalog=broken)

    def test_overseas_eligible_as_research_not_geographic_proof(self):
        for country, region in [
            ("RE", "La Réunion"), ("GP", "Guadeloupe"),
            ("MQ", "Martinique"), ("GF", "Guyane"),
            ("YT", "Mayotte"), ("NC", "Nouvelle-Calédonie"),
            ("PF", "Polynésie française"),
        ]:
            with self.subTest(country=country):
                item = dict(EVENT, location_countrycode=country, location_region=None)
                self.assertEqual(candidate(item, DAY)["region_hint"], region)

    def test_wrong_year_missing_year_non_festival_unsafe_url_and_false_country_rejected(self):
        cases = [
            dict(EVENT, title_fr="Festival Metal des Garrigues 2028"),
             dict(EVENT, title_fr="Festival Metal des Garrigues 2026"),
            dict(EVENT, title_fr="Festival Metal des Garrigues 2027 / 2028"),
            dict(EVENT, title_fr="<script>Festival Metal 2027</script>"),
            dict(EVENT, title_fr="Concert Metal des Garrigues 2027"),
            dict(EVENT, title_fr="Festival du Cinéma 2027",
                 description_fr="Cinéma", keywords_fr=[]),
            dict(EVENT, canonicalurl="https://evil.example/malice"),
            dict(EVENT, canonicalurl="http://openagenda.com/user/events/fest-2027"),
            dict(EVENT, canonicalurl="https://openagenda.com.evil.example/user/events/fest-2027"),
            dict(EVENT, canonicalurl=EVENT["canonicalurl"] + "#part"),
            dict(EVENT, canonicalurl=EVENT["canonicalurl"] + "?tracking=1"),
            dict(EVENT, location_countrycode="US"),
            dict(EVENT, location_region="FRANCE", location_countrycode="FR"),
            dict(EVENT, firstdate_begin="2026-04-23T18:00:00+02:00"),
            dict(EVENT, lastdate_begin="2026-04-23T18:00:00+02:00"),
            dict(EVENT, lastdate_begin="2027-04-20T18:00:00+02:00"),
            dict(EVENT, status="Événement annulé"),
        ]
        for item in cases:
            with self.subTest(item=item):
                self.assertIsNone(candidate(item, DAY))

    def test_bounded_pagination_reaches_late_festival_pages_without_approving(self):
        urls = fixed_query_urls(DAY)
        visits = []
        first_page = urls[0]
        late_page = next(u for u in urls if "offset=175" in u)
        unique = dict(EVENT, title_fr="Magnezik Fest #2",
                      canonicalurl="https://openagenda.com/shotgun/events/magnezik-festival-2")
        def fetch(url):
            visits.append(url)
            return payload([unique] if url == late_page else [])
        s = state()
        result = scan(s, DAY, fetch=fetch)
        self.assertEqual(result["leads_count"], 1)
        self.assertEqual(result["publications"], 0)
        self.assertFalse(result["publication_authorized"])
        self.assertEqual(result["requests_attempted"], len(urls))
        self.assertIn(first_page, visits)
        self.assertIn(late_page, visits)
        self.assertEqual(len(visits), len(set(visits)))
        self.assertEqual(result["leads"][0]["year_source_review_only"],
                         "UNVERIFIED_PROVIDER_START_DATE")

    def test_scan_deduplicates_5_queries_without_publication(self):
        visited = []
        def fetch(url):
            visited.append(url)
            return payload([deepcopy(EVENT)])
        current = state()
        report = scan(current, DAY, fetch=fetch)
        self.assertEqual(visited, list(fixed_query_urls(DAY)))
        self.assertEqual(report["schema"], SCHEMA)
        self.assertEqual(report["status"], "SCANNED")
        self.assertEqual(report["leads_count"], 1)
        self.assertEqual(report["requests_failed"], 0)
        self.assertEqual(report["publications"], 0)
        self.assertFalse(report["publication_authorized"])
        self.assertEqual(validated_leads(current, DAY), report["leads"])
        self.assertIs(current[STATE_KEY], report)
        # Second public run today cannot incur an unnecessary OpenData request.
        again = scan(current, DAY, fetch=lambda _: self.fail("No second fetch"))
        self.assertIs(again, report)

    def test_same_day_old_query_budget_rechecks_new_pages(self):
        current = state()
        first = scan(current, DAY, fetch=lambda _: payload([EVENT]))
        self.assertEqual(first["requests_attempted"], len(fixed_query_urls(DAY)))
        current[STATE_KEY]["requests_attempted"] = 6  # Older six-view engine.
        visited = []
        def fetch(url):
            visited.append(url)
            return payload([EVENT])
        refreshed = scan(current, DAY, fetch=fetch)
        self.assertIsNot(refreshed, first)
        self.assertEqual(visited, list(fixed_query_urls(DAY)))
        self.assertEqual(refreshed["requests_attempted"],
                         len(fixed_query_urls(DAY)))
        self.assertEqual(refreshed["leads_count"], 1)
        self.assertFalse(refreshed["publication_authorized"])

    def test_partial_outage_never_authorizes_and_can_retry_next_slot(self):
        urls = fixed_query_urls()
        attempts = []
        def flaky(url):
            attempts.append(url)
            if url == urls[0]:
                return payload([EVENT])
            raise OSError("external OpenData unavailable")
        current = state()
        partial = scan(current, DAY, fetch=flaky)
        self.assertEqual(partial["status"], "PARTIAL")
        self.assertEqual(partial["requests_failed"], len(urls) - 1)
        self.assertEqual(partial["leads_count"], 1)
        self.assertFalse(partial["publication_authorized"])
        complete = scan(current, DAY,
                        fetch=lambda _: payload([EVENT]))
        self.assertEqual(complete["status"], "SCANNED")
        self.assertEqual(complete["requests_failed"], 0)
        self.assertEqual(complete["publications"], 0)

    def test_total_source_outage_is_not_confused_with_empty_success(self):
        s = state()
        result = scan(s, DAY, fetch=lambda _: (_ for _ in ()).throw(
            OSError("offline")))
        self.assertEqual(result["status"], "UNAVAILABLE")
        self.assertEqual(result["leads_count"], 0)
        self.assertEqual(result["requests_failed"], len(fixed_query_urls(DAY)))
        self.assertEqual(validated_leads(s, DAY), [])

    def test_bogus_favorable_state_never_forges_a_publisher_lead(self):
        s = state()
        good = scan(s, DAY, fetch=lambda _: payload([EVENT]))
        cases = [
            ("publication_authorized", True),
            ("safe_to_publish", True),
            ("review_only", False),
            ("as_of", "2026-11-19"),
        ]
        for key, val in cases:
            with self.subTest(key=key):
                fake = deepcopy(s)
                fake[STATE_KEY][key] = val
                self.assertEqual(validated_leads(fake, DAY), [])
        bad = deepcopy(s)
        bad[STATE_KEY]["leads"][0]["source_url"] = "https://evil.example/"
        self.assertEqual(validated_leads(bad, DAY), [])
        bad = deepcopy(s)
        bad[STATE_KEY]["leads"][0]["official_site_verified"] = True
        self.assertEqual(validated_leads(bad, DAY), [])
        bad = deepcopy(s)
        bad[STATE_KEY]["leads"][0]["id"] = "oa-fake-id"
        self.assertEqual(validated_leads(bad, DAY), [])
        self.assertEqual(good["publications"], 0)

    def test_unexpected_large_or_malformed_json_fails_without_candidate(self):
        for malformed in (
            [], None, {"total_count": "1", "results": [EVENT]},
            {"total_count": 1, "results": "bad"},
            {"total_count": 5000, "results": [EVENT] * 30},
        ):
            with self.subTest(response=str(malformed)[:40]):
                current = state()
                result = scan(current, DAY, fetch=lambda _: malformed)
                self.assertEqual(result["status"], "UNAVAILABLE")
                self.assertEqual(result["leads_count"], 0)
                self.assertEqual(result["publications"], 0)

    def test_source_never_allows_external_approved_network_destinations(self):
        s = state()
        report = scan(s, DAY, fetch=lambda _: payload([EVENT]))
        lead = report["leads"][0]
        self.assertNotIn("officialSite", lead)
        self.assertNotIn("organizer", lead)
        self.assertNotIn("venue", lead)
        self.assertNotIn("price", lead)
        self.assertNotIn("lineup", lead)
        self.assertNotIn("geo", lead)
