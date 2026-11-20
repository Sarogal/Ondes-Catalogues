"""Offline regression tests for the national, publication-disabled dossier queue."""
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import unittest

from national_discovery_queue import build_queue, SCHEMA

TODAY = "2026-11-06"
OCC = "https://agenda.montpellier.fr/"
BRE = "https://www.tourismebretagne.com/preparer-mon-sejour/agenda/"
BRE2 = "https://www.tourismebretagne.com/preparer-mon-sejour/agenda/festivals-bretagne/"
JDS = ("https://www.jds.fr/marseille/aix-en-provence-9088_V/agenda/"
       "manifestations-fetes-festivals-137_B")


class NationalDiscoveryTests(unittest.TestCase):
    def state(self):
        return {"schema": "grossesondes.source-watch.v1",
                "regional_festival_candidates_review_only": {},
                "institutional_agenda_candidate_pages": {},
                "secondary_source_candidates_private": {}}

    def report(self):
        return {"schema": "grossesondes.source-watch-report.v1",
                "date": TODAY, "source_reference_leads_review_only": []}

    def insert(self, state, title, url, origin=OCC, region="Occitanie",
               last=TODAY, first=TODAY, status="UNVERIFIED_THEME_LINK",
               public=False):
        state["regional_festival_candidates_review_only"][url] = {
            "candidate_url": url, "title": title, "source_index": origin,
            "region": region, "firstSeen": first, "lastSeen": last,
            "status": status, "discovery_signal": "THEMATIC_NAME_ONLY",
            "historical_name_slug": None, "publication_authorized": public,
        }

    def test_public_openagenda_research_creates_only_an_untrusted_dossier(self):
        from national_openagenda_research import scan as openagenda_scan
        from national_generic_primary_domain_preflight import _eligible as primary_eligible
        today = TODAY
        event = {
            "title_fr": "Festival Metal des Vignes 2027",
            "canonicalurl": "https://openagenda.com/agenda-metal/events/festival-des-vignes-2027",
            "description_fr": "Un festival de metal.",
            "keywords_fr": ["metal"], "location_countrycode": "FR",
            "location_region": "Occitanie",
            "firstdate_begin": "2027-05-07T19:00:00+02:00",
            "lastdate_begin": "2027-05-08T23:00:00+02:00",
        }
        s = self.state()
        openagenda_scan(s, today, fetch=lambda _:
                        {"total_count": 1, "results": [event]})
        queue = build_queue(s, self.report(), [], today)
        self.assertEqual(queue["candidate_dossiers_count"], 1)
        self.assertEqual(queue["publications"], 0)
        row = queue["dossiers"][0]
        self.assertFalse(row["festival_verified"])
        self.assertFalse(row["edition_dates_verified"])
        self.assertFalse(row["safe_to_publish"])
        self.assertFalse(row["publication_authorized"])
        self.assertEqual(row["date_hints"], [])
        self.assertEqual(row["sources"][0]["kind"],
                         "OPENAGENDA_PUBLIC_RESEARCH_ONLY")
        self.assertEqual(row["sources"][0]["discovered_via"],
                         "https://public.opendatasoft.com/api/explore/v2.1/"
                         "catalog/datasets/evenements-publics-openagenda/records")
        pub = {"schema": 1, "festivals": []}
        self.assertEqual(primary_eligible(queue, pub, today), [])

    def test_poisoned_openagenda_lead_never_enters_national_queue(self):
        from national_openagenda_research import scan as openagenda_scan
        from copy import deepcopy
        event = {
            "title_fr": "Festival Rock des Vignes 2027",
            "canonicalurl": "https://openagenda.com/agenda-rock/events/festival-vignes-2027",
            "description_fr": "Festival de rock.",
            "keywords_fr": ["rock"], "location_countrycode": "FR",
            "location_region": "Occitanie",
            "firstdate_begin": "2027-05-07T19:00:00+02:00",
            "lastdate_begin": "2027-05-08T23:00:00+02:00",
        }
        s = self.state()
        openagenda_scan(s, TODAY, fetch=lambda _:
                        {"total_count": 1, "results": [event]})
        initial = deepcopy(s)
        for field, value in (
            ("publication_authorized", True),
            ("edition_dates_verified", True),
            ("official_site_verified", True),
            ("source_url", "https://evil.example/private"),
            ("id", "oa-forged"),
        ):
            with self.subTest(field=field):
                poisoned = deepcopy(initial)
                poisoned["national_openagenda_research_private"][
                    "leads"][0][field] = value
                q = build_queue(poisoned, self.report(), [], TODAY)
                self.assertEqual(q["candidate_dossiers_count"], 0)
                self.assertEqual(q["publications"], 0)

    def test_visible_article_clue_stays_separate_from_visitable_dossiers(self):
        from regional_visible_article_clues import (
            visible_article_clues, update_private_articles)
        html = ("<article><h2>Metal Fest des Garrigues 2027</h2>"
                "<p>Festival metal</p></article>")
        items, _ = visible_article_clues(html, TODAY)
        state = self.state()
        created, _ = update_private_articles(
            state, OCC, "Occitanie", items, TODAY,
            __import__("regional_festival_discovery").APPROVED)
        self.assertEqual(len(created), 1)
        doc = build_queue(state, self.report(), [], TODAY)
        self.assertEqual(doc["candidate_dossiers_count"], 0)
        self.assertEqual(doc["network_requests"], 0)
        self.assertEqual(doc["unlinked_visible_article_clues_count"], 1)
        item = doc["unlinked_visible_article_clues_review_only"][0]
        self.assertFalse(item["fetch_eligible"])
        self.assertFalse(item["publication_authorized"])
        self.assertFalse(item["festival_verified"])
        self.assertNotIn("candidate_url", item)
        self.assertEqual(doc["publications"], 0)

    def test_zero_seed_dependency_discovery_of_unknown_festival(self):
        state = self.state()
        self.insert(state, "Festival Heavy Metal des Garrigues 2027",
                    "https://agenda.montpellier.fr/event/metal-garrigues-2027")
        doc = build_queue(state, self.report(), [], TODAY)
        self.assertEqual(doc["schema"], SCHEMA)
        self.assertEqual(doc["candidate_dossiers_count"], 1)
        self.assertEqual(doc["candidate_sources_count"], 1)
        entry = doc["dossiers"][0]
        self.assertEqual(entry["edition_year_hint"], 2027)
        self.assertEqual(entry["region_hint"], "Occitanie")
        self.assertFalse(entry["festival_verified"])
        self.assertFalse(entry["publication_authorized"])
        self.assertEqual(doc["qualified_sources_count"], 0)
        self.assertEqual(doc["publications"], 0)
        self.assertEqual(doc["network_requests"], 0)

    def test_same_edition_across_two_approved_sources_is_one_unverified_dossier(self):
        state = self.state()
        self.insert(state, "Armor Rock Festival 2027",
                    "https://www.tourismebretagne.com/agenda/armor2027",
                    BRE, "Bretagne")
        self.insert(state, "Armor Rock Festival 2027",
                    "https://www.tourismebretagne.com/festival/armor2027",
                    BRE2, "Bretagne")
        doc = build_queue(state, self.report(), [], TODAY)
        self.assertEqual(doc["candidate_dossiers_count"], 1)
        self.assertEqual(doc["candidate_sources_count"], 2)
        self.assertFalse(doc["dossiers"][0]["source_independence_verified"])
        self.assertIn("publisher_independence", doc["dossiers"][0]["missing_checks"])

    def test_years_and_regions_do_not_collide(self):
        state = self.state()
        self.insert(state, "Armor Rock Festival 2026",
                    "https://www.tourismebretagne.com/a/rock2026",
                    BRE, "Bretagne")
        self.insert(state, "Armor Rock Festival 2027",
                    "https://www.tourismebretagne.com/a/rock2027",
                    BRE, "Bretagne")
        self.insert(state, "Armor Rock Festival 2027",
                    "https://agenda.montpellier.fr/event/armor2027",
                    OCC, "Occitanie")
        doc = build_queue(state, self.report(), [], TODAY)
        self.assertEqual(doc["candidate_dossiers_count"], 3)
        self.assertEqual(len({x["id"] for x in doc["dossiers"]}), 3)

    def test_year_without_explicit_edition_remains_unknown(self):
        state = self.state()
        self.insert(state, "Le Festival Rock des Garrigues",
                    "https://agenda.montpellier.fr/event/garrigues")
        doc = build_queue(state, self.report(), [], TODAY)
        self.assertIsNone(doc["dossiers"][0]["edition_year_hint"])
        self.assertFalse(doc["dossiers"][0]["edition_dates_verified"])

    def test_invalid_status_and_publication_flag_never_enter_queue(self):
        state = self.state()
        self.insert(state, "Heavy Rock Fest 2027",
                    "https://agenda.montpellier.fr/event/rock2027", public=True)
        self.insert(state, "Heavy Rock Fest 2027",
                    "https://agenda.montpellier.fr/event/rockold", status="APPROVED")
        doc = build_queue(state, self.report(), [], TODAY)
        self.assertEqual(doc["candidate_dossiers_count"], 0)
        self.assertEqual(doc["discarded_input_rows"], 2)

    def test_poisoned_external_and_special_url_rejected(self):
        state = self.state()
        self.insert(state, "Punk Metal Fest 2027",
                    "https://evil.example/event/punk2027")
        self.insert(state, "Punk Metal Fest 2027",
                    "https://agenda.montpellier.fr.evil.example/event/punk2027")
        self.insert(state, "Punk Metal Fest 2027",
                    "https://agenda.montpellier.fr/event/punk2027#tracking")
        self.insert(state, "<script>alert(1)</script> Rock Fest 2027",
                    "https://agenda.montpellier.fr/event/xss2027")
        doc = build_queue(state, self.report(), [], TODAY)
        self.assertEqual(doc["candidate_dossiers_count"], 0)
        self.assertEqual(doc["publications"], 0)

    def test_stale_or_future_observations_are_ignored(self):
        state = self.state()
        self.insert(state, "Punk Rock Festival 2027",
                    "https://agenda.montpellier.fr/event/stale",
                    last="2026-08-01", first="2026-07-01")
        self.insert(state, "Punk Rock Festival 2027",
                    "https://agenda.montpellier.fr/event/future",
                    last="2026-11-07", first=TODAY)
        doc = build_queue(state, self.report(), [], TODAY)
        self.assertEqual(doc["candidate_dossiers_count"], 0)

    def test_secondary_jds_hint_joins_curated_without_qualifying_source(self):
        lead = {
            "id": "la-sainte-rock-festival-2027",
            "name": "La Sainte Rock Festival",
            "source_url": "https://lasainterockfestival.fr/",
            "start_date": "2027-04-23",
            "end_date": "2027-04-24",
            "region_hint": "Provence-Alpes-Côte d'Azur",
            "city_hint": "Aix-en-Provence",
        }
        state = self.state()
        state["secondary_source_candidates_private"][lead["id"]] = [{
            "lead_id": lead["id"], "candidate_url":
            "https://www.jds.fr/marseille/manifestations/festival/la-sainte-rock-festival-2027-1799241_A",
            "index_url": JDS, "region": lead["region_hint"],
            "firstSeen": TODAY, "lastSeen": TODAY,
            "status": "UNVERIFIED_INSTITUTIONAL_INDEX_CANDIDATE",
            "publication_authorized": False, "independence_verified": False,
        }]
        doc = build_queue(state, self.report(), [lead], TODAY)
        self.assertEqual(doc["candidate_dossiers_count"], 1)
        self.assertEqual(doc["candidate_sources_count"], 2)
        self.assertEqual(doc["qualified_sources_count"], 0)
        self.assertEqual(doc["dossiers"][0]["date_hints"][0]["verified"], False)
        self.assertFalse(doc["dossiers"][0]["source_independence_verified"])

    def test_poisoned_types_and_downloads_are_not_scheduled(self):
        state = self.state()
        self.insert(state, "Metal Rock Festival 2027",
                    "https://agenda.montpellier.fr/agenda/piece.pdf")
        self.insert(state, "Metal Rock Festival 2027",
                    "https://agenda.montpellier.fr/event/correct")
        state["regional_festival_candidates_review_only"][
            "https://agenda.montpellier.fr/event/correct"]["source_index"] = []
        self.insert(state, "Metal Rock Festival 2027",
                    "https://agenda.montpellier.fr/event/correct2")
        state["regional_festival_candidates_review_only"][
            "https://agenda.montpellier.fr/event/correct2"]["region"] = []
        doc = build_queue(state, self.report(), [], TODAY)
        self.assertEqual(doc["candidate_dossiers_count"], 0)
        self.assertEqual(doc["discarded_input_rows"], 3)

    def test_new_source_counters_exclude_curated_seeds(self):
        state = self.state()
        self.insert(state, "Festival Rock des Pins 2027",
                    "https://agenda.montpellier.fr/event/pins2027",
                    first="2026-11-04")
        self.insert(state, "Festival Metal des Vignes 2027",
                    "https://agenda.montpellier.fr/event/vignes2027")
        doc = build_queue(state, self.report(), [], TODAY)
        self.assertEqual(doc["newly_discovered_sources_count"], 1)
        self.assertEqual(doc["non_curated_dossiers_count"], 2)

    def test_malformed_state_fails_closed(self):
        state = self.state()
        state["regional_festival_candidates_review_only"] = []
        with self.assertRaises(ValueError):
            build_queue(state, self.report(), [], TODAY)

    def test_deterministic_ids_and_order(self):
        state = self.state()
        self.insert(state, "Metal Nord Festival 2027",
                    "https://agenda.montpellier.fr/event/nord")
        first = build_queue(state, self.report(), [], TODAY)
        second = build_queue(deepcopy(state), deepcopy(self.report()), [], TODAY)
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
