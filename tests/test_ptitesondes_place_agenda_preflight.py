"""Offline second-pass rechecks: no public promotion on self-confirmed schedules."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ptitesondes_place_agenda_preflight import review, SCHEMA_PREFLIGHT


def fixtures():
    sources = json.loads((ROOT / "scripts/ptitesondes_place_agenda_sources.json").read_text(encoding="utf-8"))
    places = json.loads((ROOT / "docs/ptitesondes/lieux.json").read_text(encoding="utf-8"))
    outings = json.loads((ROOT / "docs/ptitesondes/sorties.json").read_text(encoding="utf-8"))
    source = next(s for s in sources["sources"] if s["id"] == "toulouse-pourquoi-pas-bebes-explorateurs")
    lead = {
        "place_id": source["place_id"],
        "name": "Les bébés explorateurs : formes et matières",
        "start": "2026-11-21T10:30+01:00",
        "end": None,
        "source_url": source["url"],
        "status": "requires_independent_session_proof",
        "age_evidence": "0 à 3 ans selon l'organisateur",
        "extraction": "curated_official_schedule_v1",
    }
    report = {"schema": "ptitesondes.place_agenda_watch_report.v1",
              "policy": "no_automatic_publication", "event_candidates": [lead]}
    html = """<html><body>
<h1>Les bébés explorateurs : formes et matières</h1>
<p>7 → 21 novembre 2026. Gratuit sur inscription.</p>
<p>novembre 2026 samedi 7 10:30 - 11:00 samedi 21 10:30 - 11:00</p>
<p>Lecture et découverte des matières à la médiathèque jeunesse "Pourquoi Pas ?"</p>
<p>samedis 7 et 21 novembre de 10h30 à 11h</p>
<p>De 0 à 3 ans, gratuit</p>
</body></html>"""
    return sources, places, outings, report, html


class VenueAgendaPreflightTests(unittest.TestCase):
    def test_real_format_requires_secondary_evidence_before_publication(self):
        sources, places, outings, report, html = fixtures()
        result = review(report, sources, places, outings, date(2026, 11, 9),
                        getter=lambda _: html)
        self.assertEqual(result["schema"], SCHEMA_PREFLIGHT)
        self.assertFalse(result["safe_to_publish"])
        self.assertFalse(result["publish_authorized"])
        self.assertEqual(result["source_pages_read"], 1)
        self.assertEqual(result["records"][0]["state"], "source_reconfirmed_private_only")
        self.assertIn("secondary_evidence", result["records"][0]["reason"])
        self.assertNotIn("additions", result)

    def test_altered_time_or_detail_not_reconfirmed(self):
        sources, places, outings, report, html = fixtures()
        for altered in (
            html.replace("samedi 21 10:30", "samedi 21 11:30"),
            html.replace("samedis 7 et 21 novembre", "samedis 7 et 22 novembre"),
            html.replace("de 0 à 3 ans", "adultes uniquement"),
            html.replace("Pourquoi Pas ?", "un autre établissement"),
        ):
            with self.subTest(html=altered[-120:]):
                result = review(report, sources, places, outings,
                                date(2026, 11, 9), getter=lambda _: altered)
                self.assertEqual(result["records"][0]["state"], "deferred")

    def test_unknown_domain_and_unsupported_extractor_no_network(self):
        sources, places, outings, report, html = fixtures()
        for transformation in (
            lambda r: r["event_candidates"][0].update(
                source_url="https://example.org/events/malicious"),
            lambda r: r["event_candidates"][0].update(
                extraction="unapproved-html-leads"),
            lambda r: r["event_candidates"][0].update(
                place_id="fictitious-place"),
        ):
            modified = deepcopy(report)
            transformation(modified)
            def forbidden(_):
                raise AssertionError("No unapproved network fetch")
            result = review(modified, sources, places, outings, date(2026, 11, 9),
                            getter=forbidden)
            self.assertEqual(result["records"][0]["state"], "deferred")
            self.assertFalse(result["safe_to_publish"])

    def test_wrong_offset_and_past_session_rejected(self):
        sources, places, outings, report, html = fixtures()
        for start in ("2026-11-21T10:30+00:00",
                      "2026-11-21T10:30",
                      "2026-11-01T10:30+01:00",
                      "2027-11-21T10:30+01:00"):
            modified = deepcopy(report)
            modified["event_candidates"][0]["start"] = start
            with self.subTest(start=start):
                result = review(modified, sources, places, outings,
                                date(2026, 11, 9), getter=lambda _: html)
                self.assertEqual(result["records"][0]["reason"], "invalid_candidate")

    def test_already_published_venue_date_title_does_not_readd(self):
        sources, places, outings, report, html = fixtures()
        point = next(p for p in places["places"]
                     if p["id"] == report["event_candidates"][0]["place_id"])
        outings["events"].append({
            "title": report["event_candidates"][0]["name"],
            "city": point["city"], "venue": point["name"],
            "date_start": "2026-11-21", "date_end": "2026-11-21",
            "lat": point["lat"], "lng": point["lng"],
        })
        def forbidden(_):
            raise AssertionError("Duplicate must not fetch")
        result = review(report, sources, places, outings, date(2026, 11, 9),
                        getter=forbidden)
        self.assertEqual(result["records"][0]["reason"], "already_in_public_catalogue")

    def test_repeated_candidate_cannot_replay_into_publication(self):
        sources, places, outings, report, html = fixtures()
        report["event_candidates"].append(deepcopy(report["event_candidates"][0]))
        result = review(report, sources, places, outings, date(2026, 11, 9),
                        getter=lambda _: html)
        self.assertEqual(result["checked"], 2)
        self.assertEqual(result["source_pages_read"], 1)
        self.assertEqual([r["reason"] for r in result["records"]].count(
            "duplicate_candidate"), 1)

    def test_fetch_failure_stays_private_and_no_error_leaks(self):
        sources, places, outings, report, html = fixtures()
        def no(_):
            raise OSError("PRIVATE_TOKEN_MUST_NEVER_BE_LOGGED")
        result = review(report, sources, places, outings, date(2026, 11, 9), getter=no)
        self.assertEqual(result["records"][0]["reason"], "source_unavailable")
        self.assertNotIn("PRIVATE_TOKEN", json.dumps(result))
        self.assertFalse(result["publish_authorized"])

    def test_fail_closed_invalid_private_report(self):
        sources, places, outings, report, html = fixtures()
        report["policy"] = "publish_all"
        with self.assertRaisesRegex(ValueError, "Rapport"):
            review(report, sources, places, outings, date(2026, 11, 9),
                   getter=lambda _: html)


if __name__ == "__main__":
    unittest.main()
