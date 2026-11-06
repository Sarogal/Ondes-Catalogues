"""Fail-closed tests for publisher independence, edition years and privacy."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from curated_future_lead_watch import load_leads, PRIVATE_STATUS
from curated_corroboration import (
    SOURCES, SCHEMA, RECORD_STATUS, build_report, scan, inspect_source,
    choose_checks, valid_secondary, validate_sources,
)

TODAY = "2026-11-06"
LEADS = load_leads(json.loads(Path(__file__).with_name(
    "curated_future_leads.json").read_text(encoding="utf-8")))


def primary(lead):
    return {"status": PRIVATE_STATUS, "firstSeen": TODAY, "lastSeen": TODAY,
            "publication_authorized": False, "lastVisibleDigest": "a" * 64,
            "claim": [lead["name"], lead["start_date"], lead["end_date"],
                      lead["date_phrase"], lead["source_url"]]}


def state(with_primaries=True):
    return {"schema": "grossesondes.source-watch.v1",
            "curated_future_lead_observations": (
                {l["id"]: primary(l) for l in LEADS} if with_primaries else {})}


def html(lead, date_text=None):
    return ("<html><body><main><h1>" + lead["name"] + "</h1><p>"
            + (date_text if date_text is not None else lead["date_phrase"])
            + " dans la région. Festival de musiques actuelles"
            + " avec informations pratiques et accès détaillés.</p></main></body></html>")


class CorroborationTests(unittest.TestCase):
    def test_registry_has_only_bounded_https_destinations(self):
        self.assertTrue(validate_sources(SOURCES, LEADS))
        self.assertEqual(len(SOURCES), 6)
        self.assertTrue(all(not x["independence_verified"] for x in SOURCES))

    def test_a_second_domain_is_not_independent(self):
        s = state()
        src = SOURCES[0]  # helloasso is the festival operator's ticket page
        scan(s, LEADS, TODAY, fetch=lambda _: html(LEADS[0]), limit=1,
             sources=(src,))
        d = build_report(LEADS, s, {"festivals": []}, TODAY,
                         sources=(src,))
        self.assertEqual(d["schema"], SCHEMA)
        self.assertEqual(d["total"], 5)
        self.assertFalse(d["safe_to_publish"])
        self.assertEqual(d["publication_authorized_count"], 0)
        self.assertEqual(d["independently_corroborated_count"], 0)
        row = d["dossiers"][0]
        self.assertEqual(row["candidate_status"], "PRIMARY_CONFIRMED")
        self.assertEqual(row["same_publisher_date_repeats"], 1)
        self.assertEqual(row["field_provenance"]["start_date"]["status"], "PRIMARY_ONLY")
        self.assertEqual(len(row["field_provenance"]["start_date"]["sources"]), 2)
        self.assertIn("independent_date_corroboration_missing", row["missing_checks"])

    def test_trusted_distinct_editorial_publisher_is_needed_for_independence(self):
        src = dict(SOURCES[0], role="INDEPENDENT_MEDIA",
                   publisher="separate-editorial-team", independence_verified=True)
        s = state()
        scan(s, LEADS, TODAY, fetch=lambda _: html(LEADS[0]), sources=(src,))
        report = build_report(LEADS, s, {"festivals": []}, TODAY, sources=(src,))
        self.assertEqual(report["independently_corroborated_count"], 1)
        row = report["dossiers"][0]
        self.assertEqual(row["candidate_status"], "INDEPENDENTLY_CORROBORATED")
        self.assertTrue(row["independent_date_corroboration"])
        self.assertEqual(row["field_provenance"]["start_date"]["status"], "CORROBORATED")
        self.assertIn("editorial_signoff", row["missing_checks"])
        self.assertFalse(row["safe_to_publish"])
        self.assertFalse(row["publication_authorized"])

    def test_ticketing_or_coorganizer_cannot_be_flagged_independent(self):
        for role in ("ORGANIZER_TICKETING", "VENUE_COPRESENTER", "FESTIVAL_SITE"):
            source = dict(SOURCES[0], role=role, independence_verified=True,
                          publisher="another-hostname")
            with self.subTest(role=role), self.assertRaises(ValueError):
                validate_sources((source,), LEADS)
        same = dict(SOURCES[0], role="INDEPENDENT_MEDIA",
                    independence_verified=True)
        with self.assertRaises(ValueError):
            validate_sources((same,), LEADS)

    def test_2026_archive_does_not_prove_2027(self):
        lead = LEADS[2]
        source = SOURCES[4]  # 6MIC event is explicitly about the 2026 edition
        s = state()
        scan(s, LEADS, TODAY, fetch=lambda _: html(
            lead, "La Sainte Rock, samedi 25 avril 2026 au 6MIC"),
             sources=(source,))
        report = build_report(LEADS, s, {"festivals": []}, TODAY,
                              sources=(source,))
        row = report["dossiers"][2]
        self.assertEqual(row["same_publisher_date_repeats"], 0)
        self.assertEqual(row["field_provenance"]["start_date"]["status"], "PRIMARY_ONLY")

    def test_esqui_riot_undated_is_never_assigned_dates(self):
        report = build_report(LEADS, state(), {"festivals": []}, TODAY)
        row = report["dossiers"][-1]
        self.assertEqual(row["candidate_status"], "DISCOVERED")
        self.assertIsNone(row["field_provenance"]["start_date"]["value_hint"])
        self.assertEqual(row["field_provenance"]["start_date"]["sources"], [])
        self.assertIn("exact_edition_dates_missing", row["missing_checks"])

    def test_hidden_dates_and_unrelated_year_do_not_match(self):
        lead = LEADS[0]
        only_hidden = ("<html><script>" + lead["date_phrase"] + "</script>"
                       "<body><h1>" + lead["name"] + "</h1>"
                       "<p>Edition future non encore annoncée dans ce département, informations prochainement</p>"
                       "</body></html>")
        self.assertFalse(inspect_source(lead, only_hidden)["date_seen"])
        self.assertFalse(inspect_source(lead, html(
            lead, "les 23, 24, 25 juillet 2026"))["date_seen"])

    def test_cancellation_is_only_private_review_signal(self):
        s = state()
        source = SOURCES[0]
        scan(s, LEADS, TODAY, fetch=lambda _: html(
            LEADS[0], "MozHell Open Air 2027 annulé, "
            + LEADS[0]["date_phrase"]), sources=(source,))
        row = build_report(LEADS, s, {"festivals": []}, TODAY,
                           sources=(source,))["dossiers"][0]
        self.assertTrue(row["potential_cancellation"])
        self.assertEqual(row["candidate_status"], "REVIEW_REQUIRED")
        self.assertFalse(row["publication_authorized"])

    def test_unavailable_page_clears_earlier_evidence(self):
        s = state()
        source = SOURCES[0]
        scan(s, LEADS, TODAY, fetch=lambda _: html(LEADS[0]),
             sources=(source,))
        self.assertIn(source["id"], s["curated_corroboration_observations"])
        def fails(_):
            raise OSError("source inaccessible")
        scan(s, LEADS, "2026-11-07", fetch=fails, sources=(source,))
        self.assertNotIn(source["id"], s["curated_corroboration_observations"])
        self.assertEqual(s["curated_corroboration_last_attempted"][source["id"]],
                         "2026-11-07")

    def test_stale_secondary_does_not_count(self):
        s = state()
        src = SOURCES[0]
        scan(s, LEADS, TODAY, fetch=lambda _: html(LEADS[0]), sources=(src,))
        row = s["curated_corroboration_observations"][src["id"]]
        row["observed_at"] = "2026-10-25"
        self.assertFalse(valid_secondary(src, row, TODAY))
        self.assertEqual(build_report(LEADS, s, {"festivals": []}, TODAY,
                                      sources=(src,))["dossiers"][0][
                                          "same_publisher_date_repeats"], 0)

    def test_poisoned_private_state_cannot_authorize(self):
        src = SOURCES[0]
        base = state()
        scan(base, LEADS, TODAY, fetch=lambda _: html(LEADS[0]), sources=(src,))
        for mutation in (
            {"publication_authorized": True},
            {"role": "INDEPENDENT_MEDIA"},
            {"publisher": "attacker"},
            {"independence_verified": True},
            {"text_sha256": "not-a-digest"},
            {"source_id": "wrong"},
            {"date_seen": "yes"},
            {"observed_at": "2099-01-01"},
        ):
            s = deepcopy(base)
            s["curated_corroboration_observations"][src["id"]].update(mutation)
            with self.subTest(mutation=mutation):
                row = s["curated_corroboration_observations"][src["id"]]
                self.assertFalse(valid_secondary(src, row, TODAY))
                r = build_report(LEADS, s, {"festivals": []}, TODAY,
                                 sources=(src,))
                self.assertEqual(r["independently_corroborated_count"], 0)
                self.assertEqual(r["dossiers"][0]["same_publisher_date_repeats"], 0)

    def test_duplicate_in_public_catalogue_blocks_qualification(self):
        published = {"festivals": [{"slug": "x", "name": "MozHell Open Air 2027",
                                    "startDate": "2027-07-23"}]}
        report = build_report(LEADS, state(), published, TODAY)
        self.assertEqual(report["dossiers"][0]["candidate_status"], "REVIEW_REQUIRED")
        self.assertIn("already_in_public_catalogue",
                      report["dossiers"][0]["missing_checks"])

    def test_cycle_throttles_and_rotates(self):
        first = choose_checks(SOURCES, {}, TODAY, limit=2)
        self.assertEqual(len(first), 2)
        attempts = {row["id"]: TODAY for row in first}
        second = choose_checks(SOURCES, attempts, TODAY, limit=2)
        self.assertFalse(set(s["id"] for s in first) &
                         set(s["id"] for s in second))
        self.assertEqual(len(second), 2)
        self.assertEqual(choose_checks(SOURCES, attempts, TODAY, limit=0), [])
        self.assertEqual(len(choose_checks(
            SOURCES, attempts, "2026-11-07", limit=2)), 2)
        with self.assertRaises(ValueError):
            choose_checks(SOURCES, attempts, TODAY, limit=99)

    def test_state_not_a_network_destination_or_public_patch(self):
        s = state()
        s["curated_corroboration_last_attempted"] = {
            "https://attacker.test/exfil": "2026-11-01"}
        s["curated_corroboration_observations"] = {
            "https://attacker.test/exfil": {"payload": "SECRET"}}
        visited = []
        def fake(url):
            visited.append(url)
            return html(LEADS[0])
        scan(s, LEADS, TODAY, fetch=fake, limit=2)
        self.assertEqual(len(visited), 2)
        self.assertTrue(all(url in {x["url"] for x in SOURCES} for url in visited))
        self.assertNotIn("https://attacker.test/exfil", json.dumps(s))
        report = build_report(LEADS, s, {"festivals": []}, TODAY)
        self.assertNotIn("SECRET", json.dumps(report))
        self.assertFalse(report["safe_to_publish"])

    def test_primary_stale_is_not_corroborated_by_secondary_alone(self):
        s = state(with_primaries=False)
        src = dict(SOURCES[0], role="INDEPENDENT_MEDIA",
                   publisher="verified-separate-team", independence_verified=True)
        scan(s, LEADS, TODAY, fetch=lambda _: html(LEADS[0]), sources=(src,))
        report = build_report(LEADS, s, {"festivals": []}, TODAY, sources=(src,))
        self.assertEqual(report["dossiers"][0]["candidate_status"], "DISCOVERED")
        self.assertFalse(report["dossiers"][0]["independent_date_corroboration"])
        self.assertEqual(report["independently_corroborated_count"], 0)


if __name__ == "__main__":
    unittest.main()
