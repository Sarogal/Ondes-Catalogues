"""Synthetic adversarial sessions; never production, no new publisher."""
from copy import deepcopy
import unittest

from test_ptitesondes_family_national_source_preflight import (
    fixture, historical, run,
)

def synthetic_programme(title, items):
    entries = "".join(
        f"<li><time>{day} novembre 2026 à {clock}</time></li>"
        for day, clock in items
    )
    return ("<!doctype html><html><body><main><h1>" + title + "</h1>"
            "<p>Ajaccio, Maison des enfants</p><ul>" + entries + "</ul>"
            "<p>Pour les enfants de 5 ans à 12 ans.</p>"
            "</main></body></html>")


def start_on(bundle, day, clock):
    row = deepcopy(bundle)
    row["scope"]["date_start"] = row["scope"]["date_end"] = f"2026-11-{day}"
    row["source"]["start_local"] = clock
    return row


class MultiSessionPreflightTests(unittest.TestCase):
    def test_distinct_days_same_official_url_both_pass(self):
        first, _ = fixture()
        second = start_on(first, "19", "16:00")
        html = synthetic_programme(first["scope"]["title"], [
            ("18", "14h00"), ("19", "16h00"),
        ])
        result = run(docs=[first, second],
                     pages={first["source"]["official_url"]: html})
        self.assertEqual(result["official_source_cues_passed"], 2)
        self.assertEqual(result["blocked_reason_counts"], {})
        self.assertEqual(result["public_writes"], 0)
        self.assertFalse(result["publication_ready"])

    def test_two_explicit_same_day_times_both_pass(self):
        first, _ = fixture()
        second = start_on(first, "18", "16:00")
        html = synthetic_programme(first["scope"]["title"], [
            ("18", "14h00"), ("18", "16h00"),
        ])
        result = run(docs=[first, second],
                     pages={first["source"]["official_url"]: html})
        self.assertEqual(result["official_source_cues_passed"], 2)
        self.assertNotIn("duplicate_within_candidate_batch",
                         result["blocked_reason_counts"])

    def test_exact_duplicate_still_rejected(self):
        first, _ = fixture()
        html = synthetic_programme(first["scope"]["title"], [
            ("18", "14h00"),
        ])
        result = run(docs=[first, deepcopy(first)],
                     pages={first["source"]["official_url"]: html})
        self.assertEqual(result["official_source_cues_passed"], 1)
        self.assertIn("duplicate_within_candidate_batch",
                      result["blocked_reason_counts"])

    def test_page_mixes_date_and_time_from_different_items_rejected(self):
        first, _ = fixture()
        wrong = start_on(first, "18", "16:00")
        html = synthetic_programme(first["scope"]["title"], [
            ("18", "14h00"), ("19", "16h00"),
        ])
        result = run(docs=[first, wrong],
                     pages={first["source"]["official_url"]: html})
        self.assertEqual(result["official_source_cues_passed"], 1)
        self.assertIn("shared_page_exact_session_pair_unverified",
                      result["blocked_reason_counts"])

    def test_matching_session_from_two_sources_is_always_duplicate(self):
        first, page = fixture()
        second = deepcopy(first)
        second["scope"]["source_url"] = "https://agenda.commune.test/animations/copy"
        second["source"]["official_url"] = second["scope"]["source_url"]
        out = run(docs=[first, second], pages={
            first["source"]["official_url"]: page,
            second["source"]["official_url"]: page,
        })
        self.assertEqual(out["official_source_cues_passed"], 1)
        self.assertIn("duplicate_within_candidate_batch",
                      out["blocked_reason_counts"])

    def test_historical_other_day_same_source_is_not_duplicate(self):
        first, _ = fixture()
        newer = start_on(first, "19", "16:00")
        catalogue = historical()
        catalogue["events"].append({
            "id": "synthetic-already-present",
            "title": first["scope"]["title"],
            "city": first["scope"]["city"],
            "venue": first["scope"]["venue"],
            "category": "concert", "date_start": "2026-11-18",
            "date_end": "2026-11-18", "time": "14:00",
            "source_url": first["source"]["official_url"],
        })
        html = synthetic_programme(first["scope"]["title"], [
            ("18", "14h00"), ("19", "16h00"),
        ])
        out = run(catalog=catalogue, docs=[newer],
                  pages={first["source"]["official_url"]: html})
        self.assertEqual(out["official_source_cues_passed"], 1)
        self.assertEqual(out["public_writes"], 0)

    def test_historical_other_clock_requires_exact_pair(self):
        first, _ = fixture()
        newer = start_on(first, "18", "16:00")
        catalogue = historical()
        catalogue["events"].append({
            "id": "synthetic-prior-session",
            "title": first["scope"]["title"],
            "city": first["scope"]["city"],
            "venue": first["scope"]["venue"],
            "category": "concert", "date_start": "2026-11-18",
            "date_end": "2026-11-18", "time": "14:00",
            "source_url": first["source"]["official_url"],
        })
        html = synthetic_programme(first["scope"]["title"], [
            ("18", "14h00"), ("18", "16h00"),
        ])
        out = run(catalog=catalogue, docs=[newer],
                  pages={first["source"]["official_url"]: html})
        self.assertEqual(out["official_source_cues_passed"], 1)

    def test_historical_same_clock_still_blocked(self):
        first, _ = fixture()
        catalogue = historical()
        catalogue["events"].append({
            "id": "synthetic-same-clock", "title": first["scope"]["title"],
            "city": first["scope"]["city"],
            "venue": first["scope"]["venue"],
            "date_start": "2026-11-18", "date_end": "2026-11-18",
            "time": "14:00", "source_url": "https://another.test/session",
        })
        out = run(catalog=catalogue)
        self.assertIn("already_published_from_any_source",
                      out["blocked_reason_counts"])

    def test_historical_unclear_clock_fails_closed(self):
        first, _ = fixture()
        catalogue = historical()
        catalogue["events"].append({
            "id": "synthetic-unclear-clock", "title": first["scope"]["title"],
            "city": first["scope"]["city"],
            "venue": first["scope"]["venue"],
            "date_start": "2026-11-18", "date_end": "2026-11-18",
            "time": "14:00 et 16:00",
            "source_url": "https://another.test/session",
        })
        out = run(catalog=catalogue)
        self.assertIn("already_published_from_any_source",
                      out["blocked_reason_counts"])

    def test_shared_source_conflicting_identity_holds(self):
        first, _ = fixture()
        catalogue = historical()
        catalogue["events"].append({
            "id": "synthetic-different-title",
            "title": "Un spectacle différent", "city": "Ajaccio",
            "venue": "Maison des enfants", "date_start": "2026-11-18",
            "date_end": "2026-11-18", "time": "14:00",
            "source_url": first["source"]["official_url"],
        })
        out = run(catalog=catalogue)
        self.assertIn("shared_page_event_identity_ambiguous",
                      out["blocked_reason_counts"])


if __name__ == "__main__":
    unittest.main()
