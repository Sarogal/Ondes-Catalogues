"""Atomic private approval gate: event-scoped site never signs alone.

Synthetic inputs only; publisher doubles emulate the exact contract. The
production publisher keeps exclusive responsibility for source and geo proof.
"""
import copy
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import approval_preflight as gate

DAY = dt.date(2026, 11, 20)
DAY_STR = DAY.isoformat()


def event(n=1):
    ident = f"go-c-2027042{n}-france-future-metal"
    url = f"https://official.example/events/synthetic-{n}"
    venue_id = f"go-site-synthetic-{n}"
    return {
        "reviewDecision": "approved",
        "reviewedBy": "automated-official-recheck",
        "reviewedAt": DAY_STR,
        "officialEvidence": [{"url": url, "proofType": "official-organizer-or-venue",
                              "checkedAt": DAY_STR,
                              "checkedFields": ["artists", "date", "venue", "genre"]}],
        "event": {
            "id": ident, "title": "Future Metal", "date": f"2027-04-2{n}",
            "artistIds": ["future-metal"], "venueId": venue_id,
            "genres": ["Metal"], "status": "confirmed", "time": None,
            "officialUrl": url, "sourceType": "organisateur",
        },
        "newArtists": [],
    }


def site(e):
    concert = e["event"]
    return {
        "venueKind": "independent-event-site-v1",
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": DAY_STR,
        "venue": {"id": concert["venueId"], "name": "Synthetic Public Square"},
        "eventBinding": {
            "eventId": concert["id"], "eventDate": concert["date"],
            "eventOfficialUrl": concert["officialUrl"],
        },
    }


def ledger(rows=(), sites=()):
    return {
        "schema": "grossesondes.concert.approvals.v1",
        "approvals": list(rows), "venueApprovals": list(sites), "version": 1,
    }


def publisher(reference, current, proposed, today):
    out = copy.deepcopy(current)
    published = []
    for approval in proposed["approvals"]:
        e = approval["event"]
        published.append(e["id"])
        out["events"].append({**e, "confidence": "published"})
    out["venues"].extend(copy.deepcopy(row["venue"])
                         for row in proposed["venueApprovals"]
                         if row["eventBinding"]["eventId"] in published)
    return out, {"newEvents": len(published), "newVenues": len(out["venues"])}


class PairedEventSitePreflightTests(unittest.TestCase):
    def setUp(self):
        self.before = ledger()
        self.one = event(1)
        self.one_site = site(self.one)
        self.proposed = ledger([self.one], [self.one_site])
        self.current = {"events": [], "venues": []}

    def test_atomic_pair_passes_with_exact_publisher_reconciliation(self):
        p = copy.deepcopy(self.proposed)
        before = copy.deepcopy(self.before)
        outcome = gate.validate_proposal(self.before, p, {}, self.current,
                                         DAY, publisher)
        self.assertEqual(outcome["newApprovals"], 1)
        self.assertEqual(outcome["publishableEvents"], 1)
        self.assertTrue(outcome["validatedByPublisher"])
        self.assertEqual(before, self.before)
        self.assertEqual(p, self.proposed)

    def test_site_without_new_concert_cannot_be_signed(self):
        candidate = ledger([], [self.one_site])
        with self.assertRaises(ValueError):
            gate.check_append_only(self.before, candidate, DAY)

    def test_no_other_site_approvals_can_self_register(self):
        for field, value in (
            ("venueKind", "unreviewed-location"),
            ("reviewDecision", "pending"),
            ("reviewedBy", "raw-candidate"),
            ("reviewedAt", "2026-11-01"),
        ):
            candidate = copy.deepcopy(self.proposed)
            candidate["venueApprovals"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                gate.check_append_only(self.before, candidate, DAY)

    def test_exact_site_event_binding_must_survive(self):
        modifications = (
            ("eventId", "other-event"), ("eventDate", "2027-04-22"),
            ("eventOfficialUrl", "https://other.example/fake"),
        )
        for key, wrong in modifications:
            candidate = copy.deepcopy(self.proposed)
            candidate["venueApprovals"][0]["eventBinding"][key] = wrong
            with self.subTest(key=key), self.assertRaises(ValueError):
                gate.check_append_only(self.before, candidate, DAY)
        candidate = copy.deepcopy(self.proposed)
        candidate["approvals"][0]["event"]["venueId"] = "different-venue"
        with self.assertRaises(ValueError):
            gate.check_append_only(self.before, candidate, DAY)

    def test_existing_venue_signature_cannot_be_modified_or_reordered(self):
        before = ledger([self.one], [self.one_site])
        two = event(2)
        proposed = ledger([self.one, two], [self.one_site, site(two)])
        changed = copy.deepcopy(proposed)
        changed["venueApprovals"][0]["venue"]["name"] = "Tampered"
        with self.assertRaises(ValueError):
            gate.check_append_only(before, changed, DAY)
        changed = copy.deepcopy(proposed)
        changed["venueApprovals"].reverse()
        with self.assertRaises(ValueError):
            gate.check_append_only(before, changed, DAY)

    def test_publisher_cannot_add_missing_changed_or_extra_geography(self):
        for mode in ("missing", "changed", "extra", "orphan-event"):
            def evil(reference, current, approvals, today):
                actual, counts = publisher(reference, current, approvals, today)
                # Baseline must remain honest; test the forged PROPOSAL only.
                if approvals["approvals"]:
                    if mode == "missing":
                        actual["venues"] = []
                    elif mode == "changed":
                        actual["venues"][0]["name"] = "Substituted"
                    elif mode == "extra":
                        actual["venues"].append({"id": "unsigned-map-pin"})
                    elif mode == "orphan-event":
                        actual["events"] = []
                return actual, counts
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                gate.validate_proposal(self.before, self.proposed, {},
                                       self.current, DAY, evil)

    def test_partial_rejection_removes_exact_corresponding_site(self):
        second = event(2)
        proposed = ledger([self.one, second],
                          [self.one_site, site(second)])
        def partial(reference, current, data, today):
            out = copy.deepcopy(current)
            for a in data["approvals"]:
                if a["event"]["id"] != second["event"]["id"]:
                    out["events"].append({**a["event"], "confidence": "valid"})
            accepted_ids = {r["id"] for r in out["events"]}
            out["venues"].extend(copy.deepcopy(v["venue"])
                                 for v in data["venueApprovals"]
                                 if v["eventBinding"]["eventId"] in accepted_ids)
            return out, {
                "newEvents": len(out["events"]),
                "newVenues": len(out["venues"]),
                "held": [{"candidateId": second["event"]["id"],
                          "reason": "Official event still unproven"}],
            }
        stats, safe, rejected = gate.select_exact_publishable_subset(
            self.before, proposed, {}, self.current, DAY, partial)
        self.assertEqual(stats["newApprovals"], 1)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(safe["approvals"], [self.one])
        self.assertEqual(safe["venueApprovals"], [self.one_site])


if __name__ == "__main__":
    unittest.main()
