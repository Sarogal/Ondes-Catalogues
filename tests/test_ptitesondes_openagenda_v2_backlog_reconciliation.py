"""Offline UID-first backlog audit: strict duplicate and publication safeguards."""
from datetime import date
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_openagenda_v2_backlog_reconciliation import reconcile_backlog

TODAY = date(2026, 11, 18)


def lead(uid, when="2026-12-05", *, title="Lecture jeunesse",
         city="Villeurbanne", venue="Bibliothèque",
         slug="ville-test", collector="openagenda-v2", eligible=True):
    return {
        "external_id": str(uid), "date_start": when, "date_end": when,
        "source_url": (
            "https://openagenda.com/fr/" + slug + "/events/" +
            str(uid) + "_lecture-jeunesse"
        ),
        "title": title, "venue": venue, "city": city,
        "collector": collector, "eligible": eligible,
    }


def catalog(*events):
    # Keep the REAL public merge policy's version=3 and >=100 historical
    # events contract. Do not weaken byid() to make miniature tests pass.
    baseline = [{
        "id": "test-history-" + str(i),
        "title": "Autre activité", "city": "Autreville",
        "venue": "Maison des autres",
        "date_start": "2026-12-11", "date_end": "2026-12-11",
        "source_url": "https://autreville.test/agenda",
    } for i in range(100)]
    return {
        "version": 3,
        "updated_at": "2026-11-17T08:49:57+01:00",
        "events": baseline + list(events),
    }


def audited(leads, published=None):
    return reconcile_backlog(
        leads, published if published is not None else catalog(), TODAY,
        eligible_fn=lambda x, today: bool(x.get("eligible")),
        reason_fn=lambda x, today: (
            "eligible" if x.get("eligible")
            else "venue_gps_unverified"
        ),
    )


class BacklogReconciliationContract(unittest.TestCase):
    def test_dedup_collectors_uid_days_and_multi_day_hold(self):
        rows = [
            lead(123, collector="openagenda-v2"),
            lead(123, collector="opendatasoft-index"),
            lead(456, "2026-12-06"),
            lead(456, "2026-12-07"),
            lead(789, "2026-12-08"),
        ]
        r = audited(rows)
        c = r["counts"]
        self.assertEqual(c["future_leads"], 5)
        self.assertEqual(c["future_distinct_uids"], 3)
        self.assertEqual(c["future_valid_url_uid_day_groups"], 4)
        self.assertEqual(c["future_multi_day_uid_groups"], 1)
        self.assertEqual(c["future_multi_day_leads"], 2)
        self.assertEqual(c["future_uid_day_duplicate_leads"], 1)
        self.assertEqual(c["uid_day_held_multi_day_grouping"], 2)
        self.assertEqual(c["single_day_uid_day_for_source_review"], 2)
        self.assertFalse(r["approval_granted"])
        self.assertFalse(r["publisher_connected"])
        self.assertFalse(r["category_expansion_approved"])
        self.assertEqual(r["public_writes"], 0)

    def test_published_exact_id_and_range_are_held(self):
        lead1, lead2 = lead(123), lead(234, "2026-12-07")
        result = audited([
            lead1, lead2,
        ], published=catalog(
            {
                "id": "openagenda-123-2026-12-05", "title": "Lecture jeunesse",
                "city": "Villeurbanne", "venue": "Bibliothèque",
                "date_start": "2026-12-05", "date_end": "2026-12-05",
            },
            {
                "id": "human-reviewed-234", "title": "Lecture jeunesse",
                "city": "Villeurbanne", "venue": "Bibliothèque",
                "date_start": "2026-12-06", "date_end": "2026-12-08",
            },
        ))
        self.assertEqual(result["counts"]["uid_day_already_published"], 2)
        self.assertNotIn("single_day_uid_day_for_source_review",
                         result["counts"])

    def test_cross_agenda_same_uid_is_one_event_not_two_organizers(self):
        a = lead(123)
        b = lead(123, slug="ville-agrégateur",
                 collector="opendatasoft-index")
        b["source_url"] = b["source_url"].replace("ville-agrégateur", "ville-agregateur")
        out = audited([a, b])
        self.assertEqual(out["counts"]["future_cross_agenda_uid_groups"], 1)
        self.assertEqual(out["counts"]["future_uid_day_duplicate_leads"], 1)
        self.assertEqual(out["counts"]["single_day_uid_day_for_source_review"], 1)
        self.assertFalse(out["organizer_independently_attested"])

    def test_mismatching_titles_and_collector_url_conflicts_block(self):
        a, b = lead(123), lead(123, title="Autre séance",
                                     collector="opendatasoft-index")
        c, d = lead(234), lead(234, slug="other-source")
        report = audited([a, b, c, d])
        self.assertEqual(report["counts"]["uid_day_mirror_identity_conflicts"], 1)
        self.assertEqual(report["counts"]["single_day_uid_day_for_source_review"], 1)
        # One collector giving two different URLs for the exact UID/day is
        # ambiguous even when all titles and locations agree.
        e = lead(333)
        f = lead(333, slug="fake-second")
        report = audited([e, f])
        self.assertEqual(report["counts"]["uid_day_mirror_identity_conflicts"], 1)

    def test_existing_intake_gate_is_not_relaxed(self):
        rows = [lead(123, eligible=False), lead(234)]
        report = audited(rows)
        self.assertEqual(report["counts"]["uid_day_no_reviewed_venue_or_intake"], 1)
        self.assertEqual(report["existing_intake_block_reasons"]["venue_gps_unverified"], 1)
        self.assertEqual(report["counts"]["single_day_uid_day_for_source_review"], 1)

    def test_past_part_of_same_uid_prevents_naive_one_day_fallback(self):
        report = audited([lead(123, "2026-11-12"), lead(123, "2026-12-05")])
        self.assertEqual(report["counts"]["future_leads"], 1)
        self.assertEqual(report["counts"]["future_multi_day_uid_groups"], 1)
        self.assertEqual(report["counts"]["uid_day_held_multi_day_grouping"], 1)

    def test_spoofed_urls_and_invalid_uid_are_not_usable_candidates(self):
        a = lead(123)
        a["source_url"] = "https://openagenda.com.evil.org/fr/ville-test/events/123_abc"
        b = lead(234)
        b["external_id"] = "234<script>"
        report = audited([a, b])
        self.assertEqual(report["counts"]["future_leads"], 2)
        self.assertNotIn("single_day_uid_day_for_source_review",
                         report["counts"])
        self.assertFalse(report["approval_granted"])

    def test_no_private_leaks_even_with_arbitrary_reason_text(self):
        inputs = [lead(123)]
        def arbitrary_reason(*args):
            return "SECRET STUDIO 24: https://example.org/private"
        r = reconcile_backlog(
            inputs, catalog(), TODAY,
            eligible_fn=lambda x,t: True, reason_fn=arbitrary_reason,
        )
        raw = json.dumps(r)
        for blocked in (
            "Villeurbanne", "Bibliothèque", "Lecture jeunesse",
            "example.org", "SECRET STUDIO", "123", "openagenda.com",
        ):
            self.assertNotIn(blocked, raw)
        self.assertEqual(
            r["existing_intake_block_reasons"], {"invalid_metadata": 1},
        )

    def test_invalid_catalogues_or_unbounded_backlog_are_refused(self):
        for batch, pub in (
            ("not a list", catalog()),
            ([lead(123)] * 4001, catalog()),
            ([lead(123)], {"events": "invalid"}),
            ([lead(123)], catalog({"id": "duplicate"}, {"id": "duplicate"})),
        ):
            with self.subTest(batch_type=type(batch).__name__):
                with self.assertRaises(ValueError):
                    audited(batch, pub)


if __name__ == "__main__":
    unittest.main()
