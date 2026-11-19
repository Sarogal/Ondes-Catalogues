"""Adversarial end-to-end diagnostic: official index -> detail -> child scope."""
import json
from datetime import date, datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ptitesondes_html_index_detail_funnel import (
    SCHEMA, diagnose_html_index_detail_funnel, redact_detail_funnel_report,
)
from test_ptitesondes_real_family_source_adapters import MPT_HTML
from ptitesondes_real_family_source_adapters import parse_montpellier_mpt_detail

PIN = {
    "approved_host": "mpt.montpellier.fr",
    "exact_index_url": "https://mpt.montpellier.fr/evenements",
}
ONE = "https://mpt.montpellier.fr/evenement/parcours-motricite"
TWO = "https://mpt.montpellier.fr/evenement/atelier-dessin"
TODAY = date(2026, 11, 19)


def html_index(*links):
    return "<html><body><main><h1>Programme</h1>" + "".join(
        '<a href="' + url + '">Voir le détail des animations</a>'
        for url in links
    ) + "</main></body></html>"


class _Reply:
    def __init__(self, req, data, status=200, redirected=False, mime="text/html"):
        self.url = req.full_url
        self.body = data
        self.status = status
        self.redirected = redirected
        self.headers = {"Content-Type": mime}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self):
        return self.url + "/redirect" if self.redirected else self.url

    def read(self, size):
        return self.body.encode("utf-8")


class MemoryWeb:
    def __init__(self, content, bad=None):
        self.content = content
        self.bad = bad or {}
        self.seen = []

    def __call__(self, request, timeout):
        url = request.full_url
        self.seen.append((url, request.get_method(), timeout))
        if url not in self.content:
            raise OSError("offline page not available")
        return _Reply(request, self.content[url], **self.bad.get(url, {}))


def probe(index_links=None, details=None, limit=12, adapter="montpellier_mpt",
          pin=None, today=TODAY, independent_context=None):
    if index_links is None:
        index_links = (ONE,)
    if details is None:
        details = {ONE: MPT_HTML}
    if pin is None:
        pin = PIN
    index = MemoryWeb({PIN["exact_index_url"]: html_index(*index_links)})
    pages = MemoryWeb(details)
    report = diagnose_html_index_detail_funnel(
        pin, adapter, today, max_details=limit,
        index_opener=index, detail_opener=pages,
        independent_context=independent_context)
    return report, index, pages


class OfficialIndexToScopeTests(unittest.TestCase):
    def test_full_offline_source_to_session_scope_never_publishes(self):
        result, index, pages = probe()
        self.assertEqual(result["schema"], SCHEMA)
        self.assertEqual(result["stage"], "sampled_child_sessions_unverified")
        self.assertEqual(result["child_pages_matching_contract"], 1)
        self.assertEqual(result["child_pages_read"], 1)
        self.assertEqual(result["future_child_occurrences"], 1)
        self.assertEqual(result["structurally_plausible_for_independent_review"], 1)
        self.assertEqual(index.seen, [(PIN["exact_index_url"], "GET", 12)])
        self.assertEqual(pages.seen, [(ONE, "GET", 12)])
        for item in ("independent_institution_owner_attested",
                     "independent_venue_verified",
                     "independent_age_access_rights_verified",
                     "independent_event_session_verified",
                     "publication_ready", "approval_granted",
                     "publisher_connected"):
            self.assertFalse(result[item])
        self.assertEqual(result["public_writes"], 0)

    def test_one_index_finds_multiple_distinct_children_and_sessions(self):
        second = MPT_HTML.replace("Parcours motricité", "Atelier dessin jeunesse")
        result, _, pages = probe(
            index_links=(ONE, TWO),
            details={ONE: MPT_HTML, TWO: second})
        self.assertEqual(result["child_pages_read"], 2)
        self.assertEqual(result["future_child_occurrences"], 2)
        self.assertEqual(result["structurally_plausible_for_independent_review"], 2)
        self.assertEqual(len(pages.seen), 2)

    def test_multi_session_detail_preserves_occurrences_not_date_range(self):
        result, _, _ = probe(today=date(2026, 11, 16))
        self.assertEqual(result["future_child_occurrences"], 3)
        self.assertEqual(result["structurally_plausible_for_independent_review"], 3)

    def test_cancelled_or_adult_only_pages_never_create_session(self):
        bad = MPT_HTML.replace("Carte MPT obligatoire", "Événement annulé")
        result, _, _ = probe(details={ONE: bad})
        self.assertEqual(result["child_pages_without_future_child_session"], 1)
        self.assertEqual(result["future_child_occurrences"], 0)
        adult = MPT_HTML.replace("Tout-petits, Enfants", "Adultes").replace(
            "Tout-petits, enfants de 18 mois à 6 ans", "Adultes")
        result, _, _ = probe(details={ONE: adult})
        self.assertEqual(result["future_child_occurrences"], 0)

    def test_wrong_date_or_missing_venue_never_passes(self):
        old = MPT_HTML.replace("20 janvier 2027", "20 janvier 2025")
        result, _, _ = probe(details={ONE: old})
        self.assertEqual(result["future_child_occurrences"], 0)
        no_venue = MPT_HTML.replace("Lieu :", "Information :")
        result, _, _ = probe(details={ONE: no_venue})
        self.assertEqual(result["future_child_occurrences"], 0)

    def test_missing_child_response_is_held_no_false_success(self):
        result, _, pages = probe(details={})
        self.assertEqual(result["child_pages_held"], 1)
        self.assertEqual(result["child_pages_read"], 0)
        self.assertEqual(result["future_child_occurrences"], 0)
        self.assertEqual(len(pages.seen), 1)

    def test_wrong_adapters_and_wrong_pin_fail_without_any_fetch(self):
        bad = dict(PIN, approved_host="attacker.example")
        result, idx, pages = probe(pin=bad)
        self.assertEqual(result["stage"], "invalid_trusted_pilot_configuration")
        self.assertEqual(idx.seen, [])
        self.assertEqual(pages.seen, [])
        result, idx, pages = probe(adapter="attacker_adaptor")
        self.assertEqual(result["stage"], "invalid_trusted_pilot_configuration")
        self.assertEqual(idx.seen, [])
        self.assertEqual(pages.seen, [])

    def test_unrelated_and_external_index_links_never_reach_child_reader(self):
        result, _, pages = probe(
            index_links=("/accueil", "https://evil.example/evenement/abc",
                         "https://mpt.montpellier.fr.evil.example/evenement/abc",
                         ONE),
            details={ONE: MPT_HTML})
        self.assertEqual(result["child_pages_matching_contract"], 1)
        self.assertEqual(len(pages.seen), 1)

    def test_bounded_sample_is_explicit_and_deterministic(self):
        more = [f"https://mpt.montpellier.fr/evenement/test-{n:02d}"
                for n in range(5)]
        result, _, pages = probe(
            index_links=tuple(more),
            details={url: MPT_HTML for url in more},
            limit=2)
        self.assertEqual(result["child_pages_matching_contract"], 5)
        self.assertEqual(result["child_pages_selected"], 2)
        self.assertEqual(result["child_pages_skipped_by_limit"], 3)
        self.assertEqual(len(pages.seen), 2)
        self.assertEqual(pages.seen[0][0], more[0])

    def test_full_bounded_coverage_reads_thirty_pages_without_publication(self):
        links = [
            f"https://mpt.montpellier.fr/evenement/page-test-{n:02d}"
            for n in range(35)
        ]
        report, _, pages = probe(
            index_links=tuple(links),
            details={url: MPT_HTML for url in links},
            limit=30,
        )
        self.assertEqual(report["child_pages_matching_contract"], 35)
        self.assertEqual(report["child_pages_selected"], 30)
        self.assertEqual(report["child_pages_skipped_by_limit"], 5)
        self.assertEqual(report["child_pages_read"], 30)
        self.assertEqual(len(pages.seen), 30)
        self.assertEqual(report["duplicate_child_sessions_held"], 29)
        public = redact_detail_funnel_report(report)
        self.assertEqual(public["child_pages_read"], 30)
        self.assertFalse(public["approval_granted"])
        self.assertFalse(public["publisher_connected"])
        self.assertEqual(public["public_writes"], 0)
        self.assertNotIn("/evenement/page-test-", json.dumps(public))

    def test_public_aggregate_report_never_exposes_dynamic_private_keys(self):
        report, _, _ = probe()
        report["secret_url"] = ONE
        report["scope_blocked_reason_counts"] = {
            "unknown_record_kind": 2,
            "https://private.example/secret": 8,
            "blocked_harmless": -5,
        }
        public = redact_detail_funnel_report(report)
        serialized = json.dumps(public, ensure_ascii=False)
        self.assertNotIn(ONE, serialized)
        self.assertNotIn("private.example", serialized)
        self.assertEqual(public["scope_blocked_reason_counts"],
                         {"unknown_record_kind": 2})
        self.assertFalse(public["approval_granted"])
        self.assertFalse(public["publisher_connected"])
        self.assertEqual(public["public_writes"], 0)

    def test_public_report_refuses_forged_counts_and_unknown_structure(self):
        forged = {"schema": SCHEMA, "public_writes": 1,
                  "child_pages_read": True,
                  "future_child_occurrences": -5,
                  "source_url": ONE}
        sanitized = redact_detail_funnel_report(forged)
        self.assertEqual(sanitized["public_writes"], 0)
        self.assertEqual(sanitized["child_pages_read"], 0)
        self.assertEqual(sanitized["future_child_occurrences"], 0)
        self.assertNotIn(ONE, json.dumps(sanitized))
        self.assertEqual(redact_detail_funnel_report({})["child_pages_read"], 0)



# The actual MPT website observed on 19 November labels its location as
# "Maison pour tous <name>" and separately "Organisé par la maison <name>".
# This deliberately synthetic HTML models the GENERIC template, not an
# archived verbatim copy of a third party's site.
MPT_TEMPLATE = """<html><body><main>
<h1>Atelier snoezelen</h1>
<p>Atelier/Stage | Culture</p><p>Familles</p>
<p>Partagez ce moment de découverte avec votre bébé et votre famille.</p>
<ul><li>21 novembre 2026 - 09:15 > 10:15</li>
<li>21 novembre 2026 - 10:30 > 11:30</li></ul>
<p>Maison pour tous Albert Camus</p>
<p>Allée Maurice Bonafos</p><p>34070 Montpellier</p>
<p>Organisé par la maison</p><p>Albert Camus</p>
<p>Sur inscription | Gratuit</p><p>Carte MPT obligatoire</p>
<h2>Autres événements</h2>
<p>Atelier pour enfants 23 novembre 2026 - 11:00 > 12:00</p>
</main></body></html>"""


class OfficialMptCurrentTemplateTests(unittest.TestCase):
    def test_source_named_venue_and_matching_organizer_yield_two_real_sessions(self):
        rows = parse_montpellier_mpt_detail(MPT_TEMPLATE, ONE, TODAY)
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["start_local"] for r in rows], ["09:15", "10:30"])
        self.assertTrue(all(r["venue"] == "Maison pour tous Albert Camus"
                            for r in rows))
        self.assertTrue(all(r["price_evidence"] == "ambiguous" for r in rows))
        self.assertTrue(all(r["category"] == "atelier-sensoriel" for r in rows))
        self.assertNotIn("2026-11-23", [r["date_start"] for r in rows])

    def test_wrong_house_organizer_held_without_untrusted_place_alias(self):
        changed = MPT_TEMPLATE.replace(
            "<p>Albert Camus</p>", "<p>Autre association</p>")
        self.assertEqual(parse_montpellier_mpt_detail(changed, ONE, TODAY), [])

    def test_adult_only_session_with_child_in_description_is_excluded(self):
        changed = MPT_TEMPLATE.replace(
            "<p>Familles</p>", "<p>Adultes</p>")
        # The description still says 'bébé' and 'famille'. The visible
        # explicit adult-only audience label must win.
        self.assertEqual(parse_montpellier_mpt_detail(changed, ONE, TODAY), [])

    def test_mixed_children_and_adults_are_not_incorrectly_rejected(self):
        changed = MPT_TEMPLATE.replace(
            "<p>Familles</p>", "<p>Enfants, Adultes</p>")
        self.assertEqual(len(parse_montpellier_mpt_detail(
            changed, ONE, TODAY)), 2)

    def test_musical_and_unknown_topics_are_counted_separately(self):
        music = MPT_TEMPLATE.replace("Atelier snoezelen", "Atelier d'éveil musical")
        report, _, _ = probe(details={ONE: music})
        self.assertEqual(report["future_child_occurrences"], 2)
        self.assertEqual(report["unclassified_occurrences_held"], 2)
        self.assertEqual(report["explicit_musical_occurrences_held"], 2)
        self.assertEqual(report["unclassified_nonmusical_occurrences_held"], 0)
        self.assertEqual(report["structurally_plausible_for_independent_review"], 0)
        unknown = MPT_TEMPLATE.replace("Atelier snoezelen", "Atelier détente bébé")
        report, _, _ = probe(details={ONE: unknown})
        self.assertEqual(report["unclassified_occurrences_held"], 2)
        self.assertEqual(report["explicit_musical_occurrences_held"], 0)
        self.assertEqual(report["unclassified_nonmusical_occurrences_held"], 2)
        public = redact_detail_funnel_report(report)
        self.assertEqual(public["unclassified_nonmusical_occurrences_held"], 2)
        self.assertNotIn("détente bébé", json.dumps(public, ensure_ascii=False))
        self.assertFalse(public["publisher_connected"])
        self.assertEqual(public["public_writes"], 0)

    def test_sensory_registry_and_history_are_only_readonly_counts(self):
        independently_reviewed = {
            "city": "Montpellier",
            "aliases": ["Maison pour tous Albert Camus"],
            "lat": 43.60, "lng": 3.85,
            "official": "https://mpt.montpellier.fr/maisons/albert-camus",
            "geo_source": "https://www.openstreetmap.org/way/12345",
        }
        context = {
            "legacy_venues": [independently_reviewed],
            "public_places": [],
            "historical_catalogue": {
                "updated_at": "2026-11-19T09:00:00+01:00",
                "events": [],
            },
        }
        report, _, _ = probe(details={ONE: MPT_TEMPLATE},
                             independent_context=context)
        self.assertEqual(report["future_child_occurrences"], 2)
        self.assertEqual(report["registry_location_exact_matches"], 2)
        self.assertEqual(report["historical_no_collision_found"], 2)
        self.assertEqual(report["historical_exact_duplicates_held"], 0)
        self.assertFalse(report["independent_venue_verified"])
        self.assertFalse(report["independent_gps_refetched"])
        self.assertFalse(report["publisher_connected"])
        self.assertEqual(report["public_writes"], 0)
        public = redact_detail_funnel_report(report)
        self.assertEqual(public["registry_location_exact_matches"], 2)
        self.assertNotIn("Albert Camus", json.dumps(public, ensure_ascii=False))
        unpinned, _, _ = probe(details={ONE: MPT_TEMPLATE})
        self.assertEqual(unpinned["registry_location_not_checked"], 2)
        self.assertEqual(unpinned["historical_not_checked"], 2)

    def test_sensory_sessions_are_only_structurally_plausible(self):
        result, _, _ = probe(details={ONE: MPT_TEMPLATE})
        self.assertEqual(result["child_pages_read"], 1)
        self.assertEqual(result["future_child_occurrences"], 2)
        self.assertEqual(result["unclassified_occurrences_held"], 0)
        self.assertEqual(result["structurally_plausible_for_independent_review"], 2)
        self.assertEqual(result["public_writes"], 0)
        self.assertFalse(result["approval_granted"])



class RepresentativeSamplingAndDedupTests(unittest.TestCase):
    def test_sampling_prefers_supported_topics_but_never_claims_event_proof(self):
        relevant = "https://mpt.montpellier.fr/evenement/zzz-atelier-motricite"
        nonspecific = "https://mpt.montpellier.fr/evenement/aaa-information"
        result, _, pages = probe(
            index_links=(nonspecific, relevant),
            details={nonspecific: MPT_HTML, relevant: MPT_HTML},
            limit=1,
        )
        self.assertEqual(pages.seen[0][0], relevant)
        self.assertEqual(result["child_pages_skipped_by_limit"], 1)
        self.assertFalse(result["independent_event_session_verified"])
        self.assertFalse(result["approval_granted"])

    def test_duplicate_official_urls_for_same_session_not_counted_twice(self):
        other = "https://mpt.montpellier.fr/evenement/autre-parcours-motricite"
        result, _, _ = probe(
            index_links=(ONE, other),
            details={ONE: MPT_HTML, other: MPT_HTML},
        )
        self.assertEqual(result["child_pages_read"], 2)
        self.assertEqual(result["future_child_occurrences"], 1)
        self.assertEqual(result["duplicate_child_sessions_held"], 1)
        self.assertEqual(result["structurally_plausible_for_independent_review"], 1)

    def test_different_exact_session_times_never_deduplicate(self):
        other = "https://mpt.montpellier.fr/evenement/second-parcours-motricite"
        second = MPT_HTML.replace("10:00 > 11:00", "15:00 > 16:00")
        result, _, _ = probe(
            index_links=(ONE, other),
            details={ONE: MPT_HTML, other: second},
        )
        self.assertEqual(result["future_child_occurrences"], 2)
        self.assertEqual(result["duplicate_child_sessions_held"], 0)

    def test_numeric_url_variants_still_available_when_sampling_limit_grows(self):
        stems = [
            "https://mpt.montpellier.fr/evenement/attention-cirque",
            "https://mpt.montpellier.fr/evenement/attention-cirque-0",
            "https://mpt.montpellier.fr/evenement/parcours-motricite",
        ]
        result, _, pages = probe(
            index_links=tuple(stems),
            details={url: MPT_HTML for url in stems},
            limit=2,
        )
        self.assertEqual(result["child_pages_matching_contract"], 3)
        self.assertEqual(result["child_pages_selected"], 2)
        self.assertEqual(result["child_pages_skipped_by_limit"], 1)
        self.assertEqual({url for url, _, _ in pages.seen},
                         {stems[0], stems[2]})
        self.assertFalse(result["publisher_connected"])



class ExactLocalClockTests(unittest.TestCase):
    def test_live_clock_holds_started_morning_slot_but_keeps_later_slot(self):
        zone = ZoneInfo("Europe/Paris")
        now = datetime(2026, 11, 21, 10, 0, tzinfo=zone)
        index = MemoryWeb({PIN["exact_index_url"]: html_index(ONE)})
        pages = MemoryWeb({ONE: MPT_TEMPLATE})
        report = diagnose_html_index_detail_funnel(
            PIN, "montpellier_mpt", now.date(), as_of=now,
            index_opener=index, detail_opener=pages,
        )
        self.assertTrue(report["exact_local_clock_cutoff_applied"])
        self.assertEqual(report["already_started_sessions_held"], 1)
        self.assertEqual(report["future_child_occurrences"], 1)
        self.assertEqual(report["unclassified_occurrences_held"], 0)
        self.assertEqual(report["structurally_plausible_for_independent_review"], 1)
        self.assertEqual(
            redact_detail_funnel_report(report)["already_started_sessions_held"], 1)

    def test_naive_or_wrong_local_clock_fails_before_network(self):
        for moment in (
            datetime(2026, 11, 21, 10, 0),
            datetime(2026, 11, 20, 10, 0, tzinfo=ZoneInfo("Europe/Paris")),
            "2026-11-21",
        ):
            index = MemoryWeb({PIN["exact_index_url"]: html_index(ONE)})
            pages = MemoryWeb({ONE: MPT_TEMPLATE})
            out = diagnose_html_index_detail_funnel(
                PIN, "montpellier_mpt", date(2026, 11, 21),
                as_of=moment, index_opener=index, detail_opener=pages,
            )
            self.assertIn(out["stage"], (
                "invalid_trusted_local_clock",
                "trusted_local_clock_day_mismatch",
            ))
            self.assertEqual(index.seen, [])
            self.assertEqual(pages.seen, [])

    def test_ambiguous_spring_or_fall_dst_clock_is_never_inferred(self):
        zone = ZoneInfo("Europe/Paris")
        for day, raw_date, year in (
            (date(2026, 3, 29), "29 mars 2026", 2026),
            (date(2026, 10, 25), "25 octobre 2026", 2026),
        ):
            with self.subTest(day=day):
                source = MPT_TEMPLATE.replace(
                    "21 novembre 2026", raw_date).replace(
                        "09:15 > 10:15", "02:15 > 03:15").replace(
                            "10:30 > 11:30", "02:30 > 03:30")
                # At 00:00 both 02:15 and 02:30 are either nonexistent or
                # ambiguous, and must not be treated as verified sessions.
                now = datetime(year, day.month, day.day, 0, 0, tzinfo=zone)
                index = MemoryWeb({PIN["exact_index_url"]: html_index(ONE)})
                pages = MemoryWeb({ONE: source})
                out = diagnose_html_index_detail_funnel(
                    PIN, "montpellier_mpt", day, as_of=now,
                    index_opener=index, detail_opener=pages,
                )
                self.assertEqual(out["future_child_occurrences"], 0)
                self.assertEqual(out["already_started_sessions_held"], 2)
                self.assertEqual(out["public_writes"], 0)


if __name__ == "__main__":
    unittest.main()
