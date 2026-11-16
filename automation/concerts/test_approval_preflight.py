"""Offline fail-closed tests: private approval preflight never publishes by itself."""
import copy
import datetime as dt
import json
import tempfile
import types
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import approval_preflight as gate

TODAY = dt.date(2026, 11, 9)


def event(i="go-c-20270401-example"):
    return {"id": i, "title": "Example", "date": "2027-04-01",
            "artistIds": ["example"], "venueId": "venue",
            "genres": ["Metal"], "status": "confirmed", "time": None,
            "officialUrl": "https://example.org/agenda/example",
            "sourceType": "salle", "organizer": "Venue"}


def row(i="go-c-20270401-example"):
    return {"reviewDecision": "approved",
            "reviewedBy": "automated-official-recheck",
            "reviewedAt": TODAY.isoformat(),
            "event": event(i), "newArtists": [],
            "officialEvidence": [{"url": "https://example.org/agenda/example",
                                  "proofType": "official-organizer-or-venue",
                                  "checkedAt": TODAY.isoformat(),
                                  "checkedFields": ["artists", "date", "venue", "genre"]}]}


def prior():
    return {"schema": "grossesondes.concert.approvals.v1",
            "version": 1, "approvals": [],
            "venueApprovals": [], "referenceCorrections": []}


def publisher_accept(reference, current, approvals, today):
    out = copy.deepcopy(current)
    for item in approvals["approvals"]:
        out["events"].append({**item["event"], "confidence": "official"})
    return out, {"newEvents": len(approvals["approvals"])}


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.before = prior()
        self.after = copy.deepcopy(self.before)
        self.after["approvals"].append(row())
        self.catalogue = {"events": []}

    def test_exact_publisher_acceptance_required(self):
        result = gate.validate_proposal(
            self.before, self.after, {}, self.catalogue, TODAY, publisher_accept)
        self.assertEqual(result["publishableEvents"], 1)
        self.assertTrue(result["validatedByPublisher"])

    def test_no_new_approvals_does_not_call_publisher(self):
        def fail(*args):
            self.fail("Publisher must not run without new approvals")
        stats = gate.validate_proposal(
            self.before, self.before, {}, self.catalogue, TODAY, fail)
        self.assertEqual(stats["publishableEvents"], 0)

    def test_publisher_holds_a_candidate(self):
        def hold(reference, current, approvals, today):
            return copy.deepcopy(current), {"newEvents": 0}
        with self.assertRaisesRegex(ValueError, "held or modified"):
            gate.validate_proposal(self.before, self.after, {}, self.catalogue,
                                   TODAY, hold)

    def test_private_failure_identifies_the_blocked_event_and_publisher_reason(self):
        def hold(reference, current, approvals, today):
            return copy.deepcopy(current), {
                "newEvents": 0,
                "held": [{
                    "candidateId": event()["id"],
                    "reason": "Official genre not independently confirmed",
                }],
            }
        with self.assertRaises(gate.PublisherRejections) as context:
            gate.validate_proposal(
                self.before, self.after, {}, self.catalogue, TODAY, hold)
        self.assertEqual(context.exception.rejections, [{
            "eventId": event()["id"],
            "publisherResult": "not emitted by publisher",
            "changedFields": [],
            "publisherReason": "Official genre not independently confirmed",
        }])
        self.assertIn("go-c-20270401-example", str(context.exception))
        self.assertNotIn("official.example", str(context.exception))

    def test_private_failure_lists_only_differing_field_names(self):
        def changed(reference, current, approvals, today):
            return {"events": [{**event(), "date": "2027-04-02"}]}, {
                "newEvents": 1, "held": []
            }
        with self.assertRaises(gate.PublisherRejections) as context:
            gate.validate_proposal(
                self.before, self.after, {}, self.catalogue, TODAY, changed)
        self.assertEqual(context.exception.rejections, [{
            "eventId": event()["id"],
            "publisherResult": "changed fields: date",
            "changedFields": ["date"],
            "publisherReason": None,
        }])
        self.assertNotIn("2027-04-02", str(context.exception))

    def test_collects_all_publisher_rejections_without_partial_approval(self):
        proposed = copy.deepcopy(self.after)
        additional = row("go-c-20270402-second")
        additional["event"]["date"] = "2027-04-02"
        additional["event"]["officialUrl"] = "https://example.org/agenda/second"
        additional["officialEvidence"][0]["url"] = "https://example.org/agenda/second"
        proposed["approvals"].append(additional)
        before = copy.deepcopy(proposed)
        def hold_all(reference, current, approvals, today):
            return copy.deepcopy(current), {"newEvents": 0, "held": [
                {"candidateId": event()["id"],
                 "reason": "No official rock genre"},
                {"candidateId": "go-c-20270402-second",
                 "reason": "Guest \nnot named"},
            ]}
        with self.assertRaises(gate.PublisherRejections) as context:
            gate.validate_proposal(self.before, proposed, {}, self.catalogue,
                                   TODAY, hold_all)
        rejected = context.exception.rejections
        self.assertEqual([row["eventId"] for row in rejected],
                         [event()["id"], "go-c-20270402-second"])
        self.assertEqual([row["publisherReason"] for row in rejected],
                         ["No official rock genre", "Guest  not named"])
        self.assertEqual(proposed, before)

    def test_partial_batch_is_reverified_exactly_before_selecting_two_good_rows(self):
        proposed = copy.deepcopy(self.after)
        for number, day in ((2, "2027-04-02"), (3, "2027-04-03")):
            new = row(f"go-c-2027040{number}-candidate-{number}")
            new["event"]["date"] = day
            new["event"]["officialUrl"] = f"https://example.org/agenda/{number}"
            new["officialEvidence"][0]["url"] = f"https://example.org/agenda/{number}"
            proposed["approvals"].append(new)
        rejected_id = proposed["approvals"][1]["event"]["id"]
        calls = []

        def partial_publisher(reference, current, approvals, today):
            ids = [r["event"]["id"] for r in approvals["approvals"]]
            calls.append(ids)
            kept = [r for r in approvals["approvals"]
                    if r["event"]["id"] != rejected_id]
            out = copy.deepcopy(current)
            out["events"].extend(
                [{**r["event"], "confidence": "official"} for r in kept])
            return out, {
                "newEvents": len(kept),
                "held": ([{"candidateId": rejected_id,
                          "reason": "Première partie non corroborée"}]
                         if rejected_id in ids else []),
            }

        stats, safe, refusals = gate.select_exact_publishable_subset(
            self.before, proposed, {}, self.catalogue, TODAY,
            partial_publisher)
        self.assertEqual(stats["newApprovals"], 2)
        self.assertTrue(stats["validatedByPublisher"])
        self.assertEqual(len(safe["approvals"]), 2)
        self.assertEqual([r["event"]["id"] for r in safe["approvals"]],
                         [proposed["approvals"][0]["event"]["id"],
                          proposed["approvals"][2]["event"]["id"]])
        self.assertEqual(len(refusals), 1)
        self.assertEqual(refusals[0]["eventId"], rejected_id)
        self.assertEqual([len(ids) for ids in calls], [3, 2])
        self.assertEqual(len(proposed["approvals"]), 3)
        self.assertEqual(self.before["approvals"], [])

    def test_partial_batch_preserves_large_private_history_and_correct_order(self):
        # Production-like queue size without loading any private approvals.
        previous = prior()
        previous["approvals"] = [
            row(f"go-c-20261201-historic-{i:03d}") for i in range(237)
        ]
        current = {"events": [
            copy.deepcopy(r["event"]) for r in previous["approvals"]
        ]}
        proposed = copy.deepcopy(previous)
        ids = [
            "go-c-20261204-paris-employed-to-serve",
            "go-c-20261203-paris-blackgold",
            "go-c-20270521-montpellier-vulves-assassines",
        ]
        for i, identity in enumerate(ids):
            item = row(identity)
            item["event"]["officialUrl"] = f"https://example.org/agenda/live-{i}"
            item["officialEvidence"][0]["url"] = item["event"]["officialUrl"]
            item["event"]["date"] = f"2027-04-0{i+1}"
            proposed["approvals"].append(item)
        original = copy.deepcopy(previous)
        full = copy.deepcopy(proposed)
        attempts = []

        def selective_publisher(reference, catalogue, candidate, today):
            additions = candidate["approvals"][len(previous["approvals"]):]
            attempts.append([r["event"]["id"] for r in additions])
            output = copy.deepcopy(catalogue)
            accepted = [
                r for r in additions if r["event"]["id"] != ids[1]
            ]
            output["events"].extend({
                **r["event"], "confidence": "official"
            } for r in accepted)
            return output, {"held": [
                {"candidateId": ids[1], "reason": "Identité non établie"}
            ] if len(accepted) != len(additions) else []}

        stats, safe, rejections = gate.select_exact_publishable_subset(
            previous, proposed, {}, current, TODAY, selective_publisher)
        self.assertEqual(attempts, [ids, [ids[0], ids[2]]])
        self.assertEqual(stats["newApprovals"], 2)
        self.assertEqual(safe["approvals"][:237], original["approvals"])
        self.assertEqual([r["event"]["id"] for r in safe["approvals"][237:]],
                         [ids[0], ids[2]])
        self.assertEqual([r["eventId"] for r in rejections], [ids[1]])
        self.assertEqual(previous, original)
        self.assertEqual(proposed, full)
        self.assertEqual(len(current["events"]), 237)

    def test_partial_batch_dry_run_does_not_change_private_approvals(self):
        today = dt.datetime.now(ZoneInfo("Europe/Paris")).date()
        before_data = prior()
        before_data["approvals"].append(row("go-c-20260101-previous"))
        candidate_data = copy.deepcopy(before_data)
        ids = ["go-c-20270401-first", "go-c-20270402-rejected",
               "go-c-20270403-third"]
        for i, identity in enumerate(ids):
            item = row(identity)
            item["reviewedAt"] = today.isoformat()
            item["event"]["date"] = f"2027-04-0{i+1}"
            item["event"]["officialUrl"] = f"https://example.org/live-{i}"
            item["officialEvidence"][0]["url"] = item["event"]["officialUrl"]
            candidate_data["approvals"].append(item)
        current = {"events": [copy.deepcopy(before_data["approvals"][0]["event"])]}
        calls = []

        def fake_publisher(reference, catalogue, candidate, as_of):
            self.assertEqual(as_of, today)
            appended = candidate["approvals"][1:]
            calls.append([item["event"]["id"] for item in appended])
            accepted = [r for r in appended if r["event"]["id"] != ids[1]]
            output = copy.deepcopy(catalogue)
            output["events"].extend(
                {**r["event"], "confidence": "official"} for r in accepted)
            return output, {"held": [
                {"candidateId": ids[1], "reason": "Refus officiel"}
            ] if len(accepted) != len(appended) else []}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / x for x in (
                "approved.json", "candidate.json", "reference.json",
                "catalogue.json", "report.json")]
            before, candidate, reference, catalogue, report = paths
            for path, data in (
                (before, before_data), (candidate, candidate_data),
                (reference, {"events": []}), (catalogue, current)):
                path.write_text(json.dumps(data), encoding="utf-8")
            argv = [
                "approval_preflight.py", "--before", str(before),
                "--candidate", str(candidate), "--reference", str(reference),
                "--catalogue", str(catalogue), "--report", str(report),
            ]  # No --apply: preflight validation must stay read-only.
            with patch("sys.argv", argv), patch.dict(sys.modules, {
                "concerts_cloud_sync": types.SimpleNamespace(merge=fake_publisher)
            }):
                gate.main()
            result = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(json.loads(before.read_text(encoding="utf-8")),
                             before_data)
            self.assertEqual(result["status"], "partially_validated")
            self.assertEqual(result["newApprovals"], 2)
            self.assertEqual(result["rejectedCount"], 1)
            self.assertEqual(result["rejected"][0]["eventId"], ids[1])
            self.assertFalse(result["applied"])
            self.assertEqual(calls, [ids, [ids[0], ids[2]]])

    def test_publisher_must_reprove_subset_after_mixed_rejection(self):
        proposed = copy.deepcopy(self.after)
        second = row("go-c-20270402-second")
        second["event"]["date"] = "2027-04-02"
        second["event"]["officialUrl"] = "https://example.org/agenda/second"
        second["officialEvidence"][0]["url"] = second["event"]["officialUrl"]
        proposed["approvals"].append(second)
        calls = []

        def untrustworthy_publisher(reference, current, approvals, today):
            calls.append(len(approvals["approvals"]))
            out = copy.deepcopy(current)
            if len(approvals["approvals"]) == 2:
                out["events"].append({**self.after["approvals"][0]["event"]})
                return out, {"newEvents": 1, "held": [
                    {"candidateId": second["event"]["id"],
                     "reason": "Genre non corroboré"}
                ]}
            # A second pass with only the good item mysteriously changes
            # its date: the old blanket-allow approach would miss this.
            tampered = copy.deepcopy(self.after["approvals"][0]["event"])
            tampered["date"] = "2027-04-09"
            out["events"].append(tampered)
            return out, {"newEvents": 1, "held": []}

        with self.assertRaises(gate.PublisherRejections):
            gate.select_exact_publishable_subset(
                self.before, proposed, {}, self.catalogue, TODAY,
                untrustworthy_publisher)
        self.assertEqual(calls, [2, 1])
        self.assertEqual(self.before["approvals"], [])

    def test_all_rejected_batch_still_fails_without_safe_subset(self):
        proposed = copy.deepcopy(self.after)
        def always_reject(reference, current, approvals, today):
            return copy.deepcopy(current), {"newEvents": 0, "held": [
                {"candidateId": event()["id"], "reason": "Pas de source"}
            ]}
        with self.assertRaises(gate.PublisherRejections):
            gate.select_exact_publishable_subset(
                self.before, proposed, {}, self.catalogue, TODAY,
                always_reject)

    def test_main_apply_writes_only_second_pass_accepted_rows(self):
        today = dt.datetime.now(ZoneInfo("Europe/Paris")).date()
        original = prior()
        proposed = copy.deepcopy(original)
        first = row("go-c-20270401-first")
        first["reviewedAt"] = today.isoformat()
        second = row("go-c-20270402-blocked")
        second["reviewedAt"] = today.isoformat()
        second["event"]["date"] = "2027-04-02"
        second["event"]["officialUrl"] = "https://example.org/agenda/blocked"
        second["officialEvidence"][0]["url"] = second["event"]["officialUrl"]
        third = row("go-c-20270403-third")
        third["reviewedAt"] = today.isoformat()
        third["event"]["date"] = "2027-04-03"
        third["event"]["officialUrl"] = "https://example.org/agenda/third"
        third["officialEvidence"][0]["url"] = third["event"]["officialUrl"]
        proposed["approvals"] = [first, second, third]
        blocked_id = second["event"]["id"]
        attempts = []

        def exact_publisher(reference, current, approvals, as_of):
            self.assertEqual(as_of, today)
            attempts.append(len(approvals["approvals"]))
            out = copy.deepcopy(current)
            accepted = [r for r in approvals["approvals"]
                        if r["event"]["id"] != blocked_id]
            out["events"] += [{**r["event"], "confidence": "official"}
                              for r in accepted]
            return out, {"newEvents": len(accepted), "held": (
                [{"candidateId": blocked_id, "reason": "Fausse date"}]
                if len(accepted) != len(approvals["approvals"]) else [])}

        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            before, candidate, reference, catalogue, report = (
                folder / name for name in
                ("approved.json", "proposal.json", "reference.json",
                 "catalogue.json", "preflight.json"))
            for path, data in (
                (before, original), (candidate, proposed),
                (reference, {"events": []}), (catalogue, {"events": []})):
                path.write_text(json.dumps(data), encoding="utf-8")
            args = ["approval_preflight.py", "--before", str(before),
                    "--candidate", str(candidate), "--reference",
                    str(reference), "--catalogue", str(catalogue),
                    "--report", str(report), "--apply"]
            with patch("sys.argv", args), patch.dict(
                    sys.modules, {"concerts_cloud_sync": types.SimpleNamespace(
                        merge=exact_publisher)}):
                gate.main()
            saved = json.loads(before.read_text(encoding="utf-8"))
            result = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["approvals"]), 2)
            self.assertEqual(saved["approvals"][0], first)
            self.assertEqual(saved["approvals"][1], third)
            self.assertEqual(result["status"], "partially_validated")
            self.assertEqual(result["proposedApprovals"], 3)
            self.assertEqual(result["newApprovals"], 2)
            self.assertEqual(result["rejectedCount"], 1)
            self.assertEqual(result["rejected"][0]["eventId"], blocked_id)
            self.assertTrue(result["applied"])
            self.assertEqual(attempts, [3, 2])

    def test_blocked_main_persists_private_diagnostics_without_approval_write(self):
        today = dt.datetime.now(ZoneInfo("Europe/Paris")).date()
        previous = prior()
        proposed = copy.deepcopy(previous)
        proposed_row = row()
        proposed_row["reviewedAt"] = today.isoformat()
        proposed["approvals"].append(proposed_row)

        def real_publisher_refuses(reference, current, approvals, as_of):
            self.assertEqual(as_of, today)
            return copy.deepcopy(current), {"newEvents": 0, "held": [
                {"candidateId": event()["id"],
                 "reason": "Genre non confirmé sur détail officiel"}
            ]}

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            before, candidate, reference, catalogue, report = (
                root / name for name in
                ("approved.json", "proposed.json", "reference.json",
                 "catalogue.json", "approval-preflight.json"))
            for filename, data in (
                (before, previous), (candidate, proposed),
                (reference, {"events": []}), (catalogue, {"events": []})):
                filename.write_text(
                    json.dumps(data, ensure_ascii=False), encoding="utf-8")
            argv = ["approval_preflight.py", "--before", str(before),
                    "--candidate", str(candidate), "--reference",
                    str(reference), "--catalogue", str(catalogue),
                    "--report", str(report), "--apply"]
            with patch("sys.argv", argv), patch.dict(
                    sys.modules, {
                        "concerts_cloud_sync": types.SimpleNamespace(
                            merge=real_publisher_refuses)}):
                with self.assertRaises(gate.PublisherRejections):
                    gate.main()
            self.assertEqual(json.loads(before.read_text(encoding="utf-8")),
                             previous)
            saved = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(saved["status"], "blocked")
            self.assertIs(saved["applied"], False)
            self.assertIs(saved["validatedByPublisher"], False)
            self.assertEqual(len(saved["rejected"]), 1)
            self.assertEqual(saved["rejected"][0]["eventId"], event()["id"])
            self.assertIn("Genre non confirmé",
                          saved["rejected"][0]["publisherReason"])
            self.assertNotIn("https://", str(saved["rejected"]))
            self.assertFalse((root / ".approved-preflight.json").exists())

    def test_publisher_cannot_silently_change_event_fields(self):
        def change(reference, current, approvals, today):
            return {"events": [{**event(), "date": "2027-04-02"}]}, {}
        with self.assertRaisesRegex(ValueError, "held or modified"):
            gate.validate_proposal(self.before, self.after, {}, self.catalogue,
                                   TODAY, change)

    def test_publisher_cannot_return_unexpected_number_of_events(self):
        def extra(reference, current, approvals, today):
            return {"events": [event(), {"id": "other"}]}, {}
        with self.assertRaisesRegex(ValueError, "Unexpected number"):
            gate.validate_proposal(self.before, self.after, {}, self.catalogue,
                                   TODAY, extra)

    def test_already_published_event_is_refused(self):
        with self.assertRaisesRegex(ValueError, "already in the public"):
            gate.validate_proposal(self.before, self.after, {},
                                   {"events": [event()]}, TODAY, publisher_accept)

    def test_approved_history_must_be_append_only(self):
        old = prior()
        old["approvals"] = [row("go-c-20270501-previous")]
        proposed = copy.deepcopy(old)
        proposed["approvals"][0]["event"]["title"] = "Tampered"
        with self.assertRaisesRegex(ValueError, "modified or removed"):
            gate.check_append_only(old, proposed, TODAY)

    def test_reviewer_and_date_cannot_be_spoofed(self):
        for key, value in (("reviewedBy", "human"),
                           ("reviewedAt", "2026-11-01"),
                           ("reviewDecision", "pending")):
            proposed = copy.deepcopy(self.after)
            proposed["approvals"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.check_append_only(self.before, proposed, TODAY)

    def test_protected_private_fields_cannot_change(self):
        proposed = copy.deepcopy(self.after)
        proposed["venueApprovals"].append({"venue": "unreviewed"})
        with self.assertRaisesRegex(ValueError, "metadata changed"):
            gate.check_append_only(self.before, proposed, TODAY)

    def test_duplicate_approval_ids_are_rejected(self):
        proposed = copy.deepcopy(self.after)
        proposed["approvals"].append(copy.deepcopy(row()))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            gate.check_append_only(self.before, proposed, TODAY)

    def test_more_than_sixteen_approvals_are_rejected(self):
        proposed = copy.deepcopy(self.before)
        proposed["approvals"] = [row(f"go-c-20270401-example-{i}") for i in range(17)]
        with self.assertRaisesRegex(ValueError, "Too many"):
            gate.check_append_only(self.before, proposed, TODAY)

    def test_trusted_main_merge_of_preflight_triggers_one_public_runner_pass(self):
        workflow = (
            Path(__file__).resolve().parents[2] / ".github" / "workflows"
            / "grossesondes-concerts-private-intake-on-public-runners.yml"
        ).read_text(encoding="utf-8")
        # The exact preflight edit must not wait for an unreliable schedule.
        self.assertIn("branches: [main]", workflow)
        self.assertIn(
            "      - 'automation/concerts/approval_preflight.py'", workflow)
        # PR changes are tested by the public-safe parity CI, without the
        # private credentials of this trusted-main intake job.
        self.assertNotIn("\n  pull_request:", workflow)
        self.assertIn(
            "github.ref == 'refs/heads/main'", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)

    def test_no_change_to_source_documents(self):
        previous = copy.deepcopy(self.before)
        proposed = copy.deepcopy(self.after)
        gate.validate_proposal(previous, proposed, {}, self.catalogue, TODAY,
                               publisher_accept)
        self.assertEqual(previous, self.before)
        self.assertEqual(proposed, self.after)


if __name__ == "__main__":
    unittest.main()
