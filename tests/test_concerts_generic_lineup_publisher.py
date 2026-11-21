"""Publisher regression: generic signed patch, no per-venue or artist whitelist."""
from __future__ import annotations

import copy
import datetime as dt
import json
import unittest
from pathlib import Path
from unittest import mock

from scripts import concerts_cloud_sync as sync
from scripts import concert_published_lineup_contract as contract

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / "docs/grossesondes/concerts-reference.json").read_text())
PUBLIC = json.loads((ROOT / "docs/grossesondes/concerts.json").read_text())
TODAY = dt.date(2026, 11, 21)
TARGETS = (
    ("go-c-20261125-toulouse-marillion", "Marillion", "Lazuli"),
    ("go-c-20261126-toulouse-the-stranglers", "The Stranglers", "Brother Junior"),
)


def fixture():
    current = copy.deepcopy(BASE)
    old = {}
    for event_id, _lead, _support in TARGETS:
        event = next(e for e in PUBLIC["events"] if e["id"] == event_id)
        current["events"].append(copy.deepcopy(event))
        old[event_id] = event
    ids = {id for e in current["events"] for id in e["artistIds"]}
    ids.update(["marillion", "the-stranglers", "lazuli", "brother-junior"])
    present = {a["id"] for a in current["artists"]}
    current["artists"].extend(copy.deepcopy(a) for a in PUBLIC["artists"]
                              if a["id"] in ids and a["id"] not in present)
    signed = {"schema": sync.SCHEMA, "approvals": [], "lineupCorrections": []}
    for event_id, lead, support in TARGETS:
        event = old[event_id]
        signed["approvals"].append({
            "reviewDecision": "approved", "reviewedBy": "independent-official-verifier",
            "reviewedAt": "2026-11-03",
            "event": {k: copy.deepcopy(event[k]) for k in
                      ("id", "title", "date", "artistIds", "venueId", "genres",
                       "status", "officialUrl", "sourceType")},
            "newArtists": [], "officialEvidence": []})
        signed["lineupCorrections"].append(patch(event, lead, support))
    return current, signed


def patch(event, lead, support):
    names = [lead, support]
    return {
        "eventId": event["id"], "reviewDecision": "approved",
        "reviewedBy": "automated-official-recheck", "reviewedAt": "2026-11-21",
        "date": event["date"], "venueId": event["venueId"],
        "officialUrl": event["officialUrl"],
        "oldArtistIds": list(event["artistIds"]),
        "artistIds": list(event["artistIds"]) + [contract.normal(support).replace(" ", "-")],
        "title": lead + " + " + support, "newArtists": [],
        "officialEvidence": [{
            "url": event["officialUrl"],
            "proofType": "official-published-lineup-v1",
            "checkedAt": "2026-11-21",
            "checkedFields": ["artists", "date", "venue"],
            "confirmedArtists": names,
        }],
    }


def official_page(event_id, *, incorrect=None):
    event = next(e for e in PUBLIC["events"] if e["id"] == event_id)
    names = next((lead, support) for eid, lead, support in TARGETS if eid == event_id)
    date = ("25 novembre 2026" if event["date"] == "2026-11-25"
            else "26 novembre 2026")
    title = " + ".join(names)
    venue = "Le Bikini"
    if incorrect == "date":
        date = "27 novembre 2026"
    elif incorrect == "venue":
        venue = "Un autre lieu"
    elif incorrect == "lineup":
        title = names[0] + " + Un groupe non annoncé"
    extra = "<h1>Un autre concert</h1>" if incorrect == "extra" else ""
    return (f"<html><body><main><p>{date}</p><p>{venue}</p>"
            f"<h1>{title}</h1>{extra}"
            + "<article>Annonce du spectacle à venir.</article>" * 4
            + "</main></body></html>")


def safe_fixture_fetch(url):
    event = next(e for e in PUBLIC["events"] if e["officialUrl"] == url)
    return official_page(event["id"])


class GenericPublishedLineupPublisherTests(unittest.TestCase):
    def test_both_bikini_regressions_and_idempotent_second_publisher_run(self):
        current, signed = fixture()
        pristine = copy.deepcopy(current)
        with mock.patch.object(contract, "network_fetch",
                               side_effect=safe_fixture_fetch) as fetched:
            updated, counts = sync.merge(BASE, current, signed, TODAY)
        self.assertEqual(fetched.call_count, 2)
        self.assertEqual(counts["newEvents"], 0)
        self.assertEqual(counts["newVenues"], 0)
        self.assertEqual(counts["newArtists"], 0)
        self.assertEqual(counts["correctedEvents"], 2)
        self.assertEqual(len(updated["events"]), len(current["events"]))
        self.assertEqual(updated["venues"], current["venues"])
        self.assertEqual(updated["artists"], current["artists"])
        self.assertEqual(current, pristine)
        for eid, lead, support in TARGETS:
            event = next(e for e in updated["events"] if e["id"] == eid)
            self.assertEqual(event["title"], lead + " + " + support)
            self.assertEqual(len(event["artistIds"]), 2)
            self.assertEqual(event["lastVerified"], "2026-11-21")
        with mock.patch.object(contract, "network_fetch",
                               side_effect=AssertionError("must not re-fetch")):
            repeated, summary = sync.merge(BASE, updated, signed, TODAY)
        self.assertEqual(summary["correctedEvents"], 0)
        self.assertEqual(updated, repeated)
        sync.protect_reference(BASE, repeated)
        sync.validate_catalogue(repeated)

    def test_bad_evidence_never_patches_and_old_cloud_stays_unchanged(self):
        for bad in ("date", "venue", "lineup", "extra"):
            with self.subTest(bad=bad):
                current, signed = fixture()
                initial = copy.deepcopy(current)
                def fake(url):
                    event = next(e for e in PUBLIC["events"] if e["officialUrl"] == url)
                    return official_page(event["id"], incorrect=bad)
                with mock.patch.object(contract, "network_fetch", side_effect=fake):
                    with self.assertRaises(ValueError):
                        sync.merge(BASE, current, signed, TODAY)
                self.assertEqual(initial, current)

    def test_national_patch_proposal_to_independent_publisher_end_to_end(self):
        from automation.concerts import published_lineup_patch_builder as builder
        from automation.concerts import published_lineup_audit as audit
        current, signed = fixture()
        report = {
            "schema": audit.SCHEMA, "publicationAllowed": False,
            "checks": [
                {"eventId": eid, "officialUrl": next(
                    e["officialUrl"] for e in current["events"] if e["id"] == eid),
                 "state": "published_lineup_incomplete",
                 "officialBillRechecked": True}
                for eid, lead, support in TARGETS
            ],
        }
        suggestions = builder.build(
            current, report, TODAY,
            fetch=lambda url, cache: safe_fixture_fetch(url))
        self.assertEqual(len(suggestions["proposals"]), 2)
        self.assertFalse(suggestions["publicationAllowed"])
        self.assertFalse(suggestions["publisherAuthorityGranted"])
        self.assertEqual(suggestions["held"], [])
        signed["lineupCorrections"] = suggestions["proposals"]
        from scripts import concerts_private_approval_preview as preview
        previous = copy.deepcopy(signed)
        previous.pop("lineupCorrections")
        with mock.patch.object(contract, "network_fetch",
                               side_effect=safe_fixture_fetch):
            self.assertEqual(
                preview.audit(previous, signed, BASE, current, TODAY), 2)
            merged, counts = sync.merge(BASE, current, signed, TODAY)
        self.assertEqual(counts["correctedEvents"], 2)
        self.assertEqual(counts["newEvents"], 0)
        self.assertEqual(len(merged["events"]), len(current["events"]))

    def test_patch_builder_rechecks_and_rejects_dishonest_audit(self):
        from automation.concerts import published_lineup_patch_builder as builder
        from automation.concerts import published_lineup_audit as audit
        current, signed = fixture()
        event = next(e for e in current["events"]
                     if e["id"] == TARGETS[0][0])
        record = {"eventId": event["id"], "officialUrl": event["officialUrl"],
                  "state": "published_lineup_incomplete",
                  "officialBillRechecked": True}
        report = {"schema": audit.SCHEMA, "publicationAllowed": False,
                  "checks": [record]}
        for mutation in ("false-state", "wrong-url", "fake-date",
                         "extra-event", "already-complete"):
            with self.subTest(mutation=mutation):
                damaged = copy.deepcopy(report)
                if mutation == "false-state":
                    damaged["checks"][0]["officialBillRechecked"] = False
                if mutation == "wrong-url":
                    damaged["checks"][0]["officialUrl"] = "https://evil.example/event"
                def fake(url, cache):
                    html = safe_fixture_fetch(url)
                    if mutation == "fake-date":
                        return html.replace("25 novembre", "26 novembre")
                    if mutation == "extra-event":
                        return html.replace("</main>", "<h1>Un autre événement</h1></main>")
                    if mutation == "already-complete":
                        return html.replace("Marillion + Lazuli", "Marillion")
                    return html
                result = builder.build(current, damaged, TODAY, fetch=fake)
                self.assertEqual(result["proposals"], [])

    def test_private_preview_accepts_only_append_only_lineup_corrections(self):
        from scripts import concerts_private_approval_preview as preview
        current, proposed = fixture()
        previous = copy.deepcopy(proposed)
        previous.pop("lineupCorrections")
        with mock.patch.object(contract, "network_fetch",
                               side_effect=safe_fixture_fetch):
            self.assertEqual(
                preview.audit(previous, proposed, BASE, current, TODAY), 2)
        tampered = copy.deepcopy(proposed)
        tampered["approvals"][0]["event"]["title"] = "Forged artist"
        with self.assertRaises(ValueError):
            preview.audit(previous, tampered, BASE, current, TODAY)
        tampered = copy.deepcopy(proposed)
        tampered["lineupCorrections"][0]["artistIds"].append("fake-artist")
        with self.assertRaises(ValueError):
            preview.audit(previous, tampered, BASE, current, TODAY)

    def test_signature_and_identity_tampering_are_refused(self):
        for bad in ("reviewer", "evidenceUrl", "proofDay", "date",
                    "venue", "support", "artistList", "oldIds"):
            with self.subTest(bad=bad):
                current, signed = fixture()
                row = signed["lineupCorrections"][0]
                if bad == "reviewer":
                    row["reviewedBy"] = "discovery-feed"
                elif bad == "evidenceUrl":
                    row["officialEvidence"][0]["url"] = "https://fake.example/show"
                elif bad == "proofDay":
                    row["officialEvidence"][0]["checkedAt"] = "2026-11-20"
                elif bad == "date":
                    row["date"] = "2026-11-26"
                elif bad == "venue":
                    row["venueId"] = "another-venue"
                elif bad == "support":
                    row["officialEvidence"][0]["confirmedArtists"][-1] = "Random Band"
                elif bad == "artistList":
                    row["artistIds"] = ["marillion", "artist-invented"]
                else:
                    row["oldArtistIds"] = ["stranglers"]
                with self.assertRaises(ValueError):
                    sync.merge(BASE, current, signed, TODAY)

    def test_brand_new_support_no_genre_invented_and_no_duplicate(self):
        current, signed = fixture()
        signed["lineupCorrections"] = [signed["lineupCorrections"][0]]
        row = signed["lineupCorrections"][0]
        row["artistIds"] = ["marillion", "groupe-inconnu"]
        row["title"] = "Marillion + Groupe Inconnu"
        row["officialEvidence"][0]["confirmedArtists"] = [
            "Marillion", "Groupe Inconnu"]
        row["newArtists"] = [{"id": "groupe-inconnu",
                              "name": "Groupe Inconnu", "aliases": []}]
        def changed(url):
            return safe_fixture_fetch(url).replace("Marillion + Lazuli",
                                                  "Marillion + Groupe Inconnu")
        with mock.patch.object(contract, "network_fetch", side_effect=changed):
            updated, counts = sync.merge(BASE, current, signed, TODAY)
        self.assertEqual(counts["newArtists"], 1)
        self.assertEqual(counts["correctedEvents"], 1)
        self.assertEqual([a for a in updated["artists"]
                          if a["id"] == "groupe-inconnu"],
                         [{"id": "groupe-inconnu", "name": "Groupe Inconnu", "aliases": []}])
        with mock.patch.object(contract, "network_fetch",
                               side_effect=AssertionError("no network on replay")):
            again, counts2 = sync.merge(BASE, updated, signed, TODAY)
        self.assertEqual(counts2["newArtists"], 0)
        self.assertEqual(again, updated)


if __name__ == "__main__":
    unittest.main()
