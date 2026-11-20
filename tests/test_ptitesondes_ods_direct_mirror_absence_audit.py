"""Bounded offline test for exact ODS-absent / OA direct evidence triage."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_ods_direct_mirror_absence_audit import (
    audit_missing_ods_direct, _safe_row, _exact_event_claim, SCHEMA,
)

TODAY = date(2026, 11, 20)


def lead(uid="12345", title="Éveil musical en famille",
         day="2026-12-10", collector="openagenda-v2",
         slug="bibliotheques-france"):
    return {
        "collector": collector, "external_id": uid,
        "source_url": (
            f"https://openagenda.com/fr/{slug}/events/{uid}_eveil-musical-en-famille"
        ),
        "date_start": day, "date_end": day, "title": title,
        "city": "Pointe-à-Pitre", "venue": "Médiathèque locale",
    }


def agenda(uid, key):
    return {"uid": uid, "slug": {
        551: "bibliotheques-france", 552: "autre-ville",
    }[uid]}


def event(agenda_uid, event_uid, key):
    return {
        "uid": int(event_uid), "status": 1, "removed": False,
        "title": {"fr": "Éveil musical en famille"},
        "timings": [{
            "begin": "2026-12-10T10:00:00-04:00",
        }],
        "rights": {"license": {"id": "not-a-licence"},
                   "licensor": {"name": "Nom inconnu"}},
        "age": None,
    }


def run(leads=None, existing=None, **kwargs):
    return audit_missing_ods_direct(
        [lead()] if leads is None else leads,
        [] if existing is None else existing,
        [551, 552], "synthetic-read-key", TODAY,
        ods_probe=lambda uid: "uid_absent",
        agenda_reader=agenda, event_reader=event,
        **kwargs)


class MirrorAbsencePrivateEvidenceTests(unittest.TestCase):
    def test_ods_absence_enables_exact_direct_read_but_no_rights(self):
        out = run()
        self.assertEqual(out["report"]["mirror_uid_absent"], 1)
        self.assertEqual(out["report"]["direct_api_matched_day_and_title"], 1)
        self.assertEqual(len(out["private_rows"]), 1)
        row = out["private_rows"][0]
        self.assertEqual(
            row["state"], "mirror_absent_direct_day_and_title_confirmed")
        self.assertEqual(row["agenda_uid"], 551)
        for k in ("rights_reviewed", "venue_geo_verified",
                  "family_audience_verified", "approved", "publication_ready",
                  "organizer_independently_verified", "publisher_connected"):
            self.assertIs(row[k], False)
        self.assertEqual(row["public_writes"], 0)
        self.assertEqual(out["report"]["public_writes"], 0)
        self.assertFalse(out["report"]["approved"])

    def test_ods_mirror_present_or_outage_is_never_rescued(self):
        for status in ("uid_unique", "uid_nonunique", "http_429",
                       "network_error", "invalid_json_or_schema"):
            with self.subTest(status=status):
                out = audit_missing_ods_direct(
                    [lead()], [], [551], "read-only", TODAY,
                    agenda_reader=agenda, event_reader=event,
                    ods_probe=lambda u: status)
                self.assertEqual(out["private_rows"], [])
                self.assertEqual(out["report"]["mirror_uid_absent"], 0)
                self.assertEqual(out["report"]["direct_api_matched_day_and_title"], 0)

    def test_mismatch_not_claimed_as_verified(self):
        for patch in (
            {"uid": 999}, {"status": 0}, {"removed": True},
            {"title": {"fr": "Autre spectacle"}},
            {"timings": []},
        ):
            with self.subTest(patch=patch):
                alternate = lambda a, e, k: dict(event(a, e, k), **patch)
                out = audit_missing_ods_direct(
                    [lead()], [], [551], "read-only", TODAY,
                    agenda_reader=agenda, event_reader=alternate,
                    ods_probe=lambda u: "uid_absent")
                self.assertEqual(out["report"]["direct_api_mismatch_held"], 1)
                self.assertEqual(out["report"]["direct_api_matched_day_and_title"], 0)

    def test_requires_exact_uid_prefixed_source_not_similar_title(self):
        rows = [
            lead(uid="12345", slug="unknown-website"),
            lead(uid="12345", collector="opendatasoft-index"),
            dict(lead(), source_url="https://evil.example/events/12345_x"),
            dict(lead(), source_url="https://openagenda.com/a/events/12345_x?token=secret"),
            dict(lead(), external_id="12346"),
            dict(lead(), external_id="hello"),
        ]
        out = run(leads=rows)
        self.assertEqual(out["private_rows"], [])
        self.assertGreaterEqual(
            out["report"]["malformed_or_non_uid_pinned_leads_held"], 5)
        self.assertEqual(out["report"]["unregistered_agendas_held"], 1)

    def test_exact_uid_day_recurs_without_identity_loss(self):
        initial = run()
        again = run(existing=initial["private_rows"])
        self.assertEqual(again["private_rows"], initial["private_rows"])
        self.assertEqual(again["report"]["private_rows_updated"], 1)

    def test_multiple_days_are_not_collapsed(self):
        rows = [lead(day="2026-12-10"), lead(day="2026-12-11")]
        out = run(leads=rows)
        self.assertEqual(out["report"]["mirror_uid_absent"], 2)
        self.assertEqual(out["report"]["direct_api_matched_day_and_title"], 1)
        self.assertEqual(len(out["private_rows"]), 2)
        self.assertEqual(len({r["audit_id"] for r in out["private_rows"]}), 2)

    def test_report_has_no_private_uid_title_city_or_token(self):
        out = run()
        shown = json.dumps(out["report"], ensure_ascii=False)
        for fragment in (
            "12345", "Éveil musical", "Pointe-à-Pitre", "bibliotheques-france",
            "https://", "synthetic-read-key", "source_url", "date_start",
        ):
            self.assertNotIn(fragment, shown)

    def test_private_approval_forgery_rejected(self):
        old = run()["private_rows"]
        for key in ("rights_reviewed", "approved", "publication_ready",
                    "family_audience_verified", "venue_geo_verified"):
            corrupted = [dict(old[0], **{key: True})]
            with self.subTest(key=key), self.assertRaises(ValueError):
                run(existing=corrupted)

    def test_malformed_agenda_and_unknown_slugs_not_independently_owned(self):
        out = audit_missing_ods_direct(
            [lead()], [], [551], "read-only", TODAY,
            agenda_reader=lambda uid, key: {"uid": uid, "slug": "other-slug"},
            ods_probe=lambda uid: "uid_absent", event_reader=event)
        self.assertEqual(out["report"]["unregistered_agendas_held"], 1)
        self.assertEqual(out["report"]["direct_api_matched_day_and_title"], 0)

    def test_cap_validation_and_conservative_holds(self):
        for max_work in (0, True, 26, "12"):
            with self.subTest(max_work=max_work), self.assertRaises(ValueError):
                run(max_work=max_work)
        with self.assertRaises(ValueError):
            audit_missing_ods_direct(
                [lead()], [], [551, 551], "key", TODAY,
                agenda_reader=agenda)
        with self.assertRaises(ValueError):
            audit_missing_ods_direct(
                [lead()], [], [], "key", TODAY,
                agenda_reader=agenda)


if __name__ == "__main__":
    unittest.main()
