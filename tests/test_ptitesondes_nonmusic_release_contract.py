"""Read-only non-music release planning: never approves or generates additions."""
from copy import deepcopy
from datetime import date
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_nonmusic_release_contract import (
    SCHEMA, TYPES, audit, explicit_age_matches, matching_category,
)

TODAY = date(2026, 11, 16)
URL = "https://www.villedugosier.fr/evenement/les-mercredis-timoun-3067"
IDENT = "municipal-gosier-3067-2026-11-25"
TITLE = "Mon doudou raconte : heure du conte pour les tout-petits"


def proposal():
    return {
        "review_id": IDENT, "source_event_id": "3067",
        "title": TITLE, "category_proposal": "lecture-jeunesse",
        "category_label_proposal": "Lecture jeunesse",
        "date_start": "2026-11-25", "date_end": "2026-11-25",
        "start_local": "09:00", "end_local": "09:30",
        "timezone": "America/Guadeloupe",
        "city": "Le Gosier", "department_proposal": "Guadeloupe (971)",
        "region_proposal": "Guadeloupe", "venue": "Médiathèque Raoul Georges Nicolo",
        "lat": 16.20547, "lng": -61.48950,
        "audience_evidence": "jusqua_3_ans",
        "age_label_proposal": "Jusqu’à 3 ans",
        "age_min_proposal": None, "age_max_proposal": 3,
        "official_event_url": URL, "source_label_proposal": "Ville du Gosier",
        "price": None, "access_conditions": "requires_individual_review",
        "review_status": "category_and_access_pending",
        "safe_to_publish": False, "approved": False, "published": False,
    }


def private_review(*rows):
    return {"schema": "ptitesondes.gosier_private_review_candidates.v1",
            "mode": "private_review_only_no_patch_no_publication",
            "candidates": list(rows), "approved": 0, "published": 0}


def access(review_id=IDENT, event_url=URL, status="clarification_required"):
    return {
        "review_id": review_id, "official_event_url": event_url,
        "date_start": "2026-11-25", "access_status": status,
        "price": None, "registration": "unknown",
        "price_evidence": "not_stated",
        "registration_evidence": "not_stated",
        "review_required": True,
        "safe_to_publish": False, "approved": False, "published": False,
    }


def private_access(*rows):
    return {"schema": "ptitesondes.gosier_access_review.v1",
            "mode": "private_access_review_only_no_patch",
            "reviewed": list(rows), "approved": 0, "published": 0}


def public_catalogue(extra=()):
    return {"version": 3, "updated_at": "2026-11-15T19:49:22+01:00",
            "events": [
                {"id": "old-" + str(n), "title": "Ancien concert " + str(n),
                 "category": "concert", "date_start": "2026-10-01",
                 "date_end": "2026-10-01",
                 "city": "Toulouse", "venue": "Salle"}
                for n in range(100)
            ] + list(extra)}


def run(candidate=None, condition=None, catalog=None):
    return audit(private_review(candidate or proposal()),
                 private_access(condition or access()),
                 catalog or public_catalogue(), TODAY)


class NonMusicReleaseReadinessTests(unittest.TestCase):
    def test_valid_private_review_is_still_not_publishable(self):
        x = run()
        self.assertEqual(x["schema"], SCHEMA)
        self.assertEqual(x["candidates_examined"], 1)
        self.assertEqual(x["blocked"], 1)
        self.assertEqual(x["publication_ready"], 0)
        self.assertEqual(x["approval_granted"], 0)
        self.assertEqual(x["public_writes"], 0)
        self.assertNotIn("additions", x)
        self.assertEqual(x["details_for_private_review_only"][0]["publication_ready"], False)
        self.assertIn("frontend_v172_category_filter_unverified", x["reason_counts"])
        self.assertIn("municipal_public_prevalidator_not_activated", x["reason_counts"])
        self.assertIn("private_manual_approval_not_present", x["reason_counts"])
        self.assertIn("category_not_accepted_by_current_public_contract", x["reason_counts"])
        self.assertIn("access_information_requires_manual_review", x["reason_counts"])

    def test_exact_child_categories_no_fallback_to_music(self):
        expected = {"lecture-jeunesse", "atelier-numerique",
                    "lecture-cinema", "jeux-famille"}
        self.assertEqual(set(TYPES), expected)
        self.assertTrue(matching_category(TITLE, "lecture-jeunesse"))
        self.assertFalse(matching_category(TITLE, "concert"))
        self.assertFalse(matching_category("Concert pour adultes", "lecture-jeunesse"))
        c = proposal()
        c["category_proposal"] = "concert"
        with self.assertRaisesRegex(ValueError, "category_unreviewed"):
            run(candidate=c)
        c["category_proposal"] = "atelier-numerique"
        c["category_label_proposal"] = "Atelier numérique"
        with self.assertRaisesRegex(ValueError, "category_unreviewed"):
            run(candidate=c)

    def test_age_label_must_derive_from_same_explicit_cue(self):
        self.assertTrue(explicit_age_matches(proposal()))
        for change in (
            {"age_min_proposal": 0},
            {"age_max_proposal": 6},
            {"age_label_proposal": "Dès 3 ans"},
            {"audience_evidence": "des_8_ans"},
            {"audience_evidence": None},
            {"age_max_proposal": True},
        ):
            with self.subTest(change=change):
                c = proposal()
                c.update(change)
                with self.assertRaises(ValueError):
                    run(candidate=c)

    def test_forged_approval_or_price_fails_closed(self):
        for change in ({"approved": True}, {"published": True},
                       {"safe_to_publish": True}, {"price": "Gratuit"},
                       {"review_status": "approved"},
                       {"access_conditions": "no_registration"}):
            with self.subTest(change=change):
                c = proposal()
                c.update(change)
                with self.assertRaisesRegex(ValueError, "candidate_identity"):
                    run(candidate=c)

    def test_exact_municipal_location_and_timezone(self):
        for change in (
            {"timezone": "Europe/Paris"},
            {"lat": 16.20620}, {"lng": -61.498},
            {"venue": "Médiathèque annexe"},
            {"region_proposal": "Occitanie"},
            {"department_proposal": "Hérault"},
        ):
            with self.subTest(change=change):
                c = proposal()
                c.update(change)
                with self.assertRaises(ValueError):
                    run(candidate=c)

    def test_official_url_venue_and_event_id_must_match(self):
        for change in (
            {"official_event_url": "https://www.villedugosier.fr.evil.example/evenement/x"},
            {"official_event_url": URL + "?signup=1"},
            {"source_event_id": "3068"},
            {"review_id": "municipal-gosier-9999-2026-11-25"},
        ):
            with self.subTest(change=change):
                c = proposal()
                c.update(change)
                with self.assertRaises(ValueError):
                    run(candidate=c)

    def test_access_report_cannot_claim_approval_or_fake_link(self):
        for change in (
            {"approved": True}, {"published": True},
            {"safe_to_publish": True}, {"review_required": False},
            {"official_event_url": "https://evil.example/event"},
            {"date_start": "2026-11-18"},
        ):
            with self.subTest(change=change):
                a = access()
                a.update(change)
                with self.assertRaises(ValueError):
                    run(condition=a)

    def test_cancellation_report_rejected_no_waiver(self):
        a = access(status="cancelled_or_unavailable")
        r = run(condition=a)
        self.assertIn("cancelled_or_unavailable", r["reason_counts"])
        self.assertEqual(r["publication_ready"], 0)

    def test_published_date_range_or_same_source_is_a_conflict(self):
        old = dict(title=TITLE, city="Le Gosier",
                   venue="Médiathèque Raoul Georges Nicolo",
                   date_start="2026-11-18", date_end="2026-11-30",
                   source_url=URL, id="existing-outing", category="concert")
        out = run(catalog=public_catalogue([old]))
        self.assertIn("already_public_semantic_or_range", out["reason_counts"])

    def test_unknown_access_cannot_be_reported_as_free(self):
        r = run()
        self.assertIn("access_information_requires_manual_review", r["reason_counts"])
        self.assertEqual(r["approval_granted"], 0)

    def test_day_must_be_current_future_and_valid_horizons(self):
        for day in ("2026-11-10", "2027-12-01"):
            c = proposal()
            c["date_start"] = day
            c["date_end"] = day
            c["review_id"] = "municipal-gosier-3067-" + day
            a = access(review_id=c["review_id"])
            a["date_start"] = day
            with self.subTest(day=day), self.assertRaises(ValueError):
                run(candidate=c, condition=a)

    def test_empty_reports_cannot_create_any_public_write(self):
        r = audit(private_review(), private_access(), public_catalogue(), TODAY)
        self.assertEqual(r["candidates_examined"], 0)
        self.assertEqual(r["public_writes"], 0)
        self.assertEqual(r["publication_ready"], 0)


if __name__ == "__main__":
    unittest.main()
