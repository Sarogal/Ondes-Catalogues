"""Full no-network HTML-source recheck, publisher and post-publication watch.

One verified venue can publish many unrelated future bills; no per-show
allowlist, no invented musicians, and no arbitrary cap on named new acts.
Every negative case must fail at the independent verifier or publisher.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "automation/concerts"))
sys.path.insert(0, str(ROOT / "scripts"))

import generic_visible_bill as html_bill
import official_recheck
import published_watch
import triage
from concerts_cloud_sync import validate_approval, merge

TODAY = dt.date(2026, 11, 19)
SOURCE = {"name": "La Rayonne", "city": "Villeurbanne",
          "department": "69", "url": "https://larayonne.org/"}


def make(names=("ACT ONE", "ACT TWO"), day="2027-06-18",
         when="vendredi 18 juin 2027", genre="Death Metal",
         url="https://larayonne.org/evenement/synthetic-bill-2027/",
         guest=None):
    raw_title = " + ".join([*names, *([guest] if guest else [])])
    bill = "".join(
        "<h4><strong>► " + n + " – " + genre + " – FRANCE</strong></h4>"
        "<p>Le groupe " + n + " est présenté par le producteur.</p>"
        for n in names
    )
    page = (
        "<html><body><h1>" + raw_title + "</h1>"
        "<strong>" + when + "</strong>"
        "<p>à partir de 19h</p>"
        "La Rayonne<p>7 rue Henri Legay</p><p>69100 Villeurbanne</p>"
        "<h3>Production présente :</h3>" + bill
        + "<h4>▼ INFOS PRATIQUES</h4><p>Début des concerts : TBA</p>"
        "</body></html>"
    )
    candidate = html_bill.extract_candidate(page, url, SOURCE, TODAY, set())
    if candidate is None:
        raise AssertionError("Synthetic page failed discovery")
    candidate = triage.triage(candidate, catalogue={})
    cat = {"schemaVersion": 1, "mode": "preview-public-unlisted",
           "venues": [{"id": "la-rayonne", "name": "La Rayonne",
                       "city": "Villeurbanne", "department": "69"}],
           "artists": [], "events": []}
    assert candidate["date"] == day
    return candidate, page, cat


def publisher(approval, cat):
    return validate_approval(
        approval, {v["id"]: v for v in cat["venues"]},
        {a["id"]: a for a in cat["artists"]}, TODAY)


class VisibleBillPublisherEndToEndTests(unittest.TestCase):
    def test_one_two_eight_twenty_and_fifty_two_new_musicians_are_validated(self):
        for count in (1, 2, 8, 20, 52):
            names = tuple("ACT %03d" % i for i in range(count))
            with self.subTest(count=count):
                candidate, page, cat = make(names=names)
                self.assertEqual(candidate["reviewBucket"], "genre_tag_review")
                app = official_recheck.verify(candidate, page, cat, TODAY)
                event, new = publisher(app, cat)
                self.assertEqual(len(event["artistIds"]), count)
                self.assertEqual(len(new), count)
                self.assertEqual(app["officialEvidence"][0]["sourceStructure"],
                                 "verified-first-party-visible-bill-v1")
                self.assertEqual(app["officialEvidence"][0]["officialGenreLabels"],
                                 ["Death Metal"])
                self.assertEqual(app["event"]["time"], None)

    def test_multiple_unrelated_future_shows_can_publish_without_show_specific_patch(self):
        reference = json.loads(
            (ROOT / "docs/grossesondes/concerts-reference.json").read_text(
                encoding="utf-8"))
        candidate1, page1, _ = make(names=("ACT ONE", "ACT TWO"))
        app1 = official_recheck.verify(candidate1, page1, reference, TODAY)
        candidate2, page2, _ = make(
            names=("ACT THREE", "ACT FOUR"),
            day="2027-07-18", when="dimanche 18 juillet 2027",
            url="https://larayonne.org/evenement/second-synthetic-show-2027/")
        app2 = official_recheck.verify(candidate2, page2, reference, TODAY)
        approvals = {"schema": "grossesondes.concert.approvals.v1",
                     "approvals": [app1, app2]}
        combined, stats = merge(reference, reference, approvals, TODAY)
        self.assertEqual(stats["newEvents"], 2)
        again, second = merge(reference, combined, approvals, TODAY)
        self.assertEqual(second["newEvents"], 0)
        self.assertEqual(again, combined)

    def test_trailing_guest_surprise_does_not_create_unknown_artist(self):
        candidate, page, cat = make(names=("EISBRECHER",),
                                    guest="Guest surprise")
        app = official_recheck.verify(candidate, page, cat, TODAY)
        self.assertEqual(app["event"]["title"], "EISBRECHER")
        self.assertEqual(app["newArtists"],
                         [{"id": "eisbrecher", "name": "EISBRECHER"}])
        self.assertEqual(app["officialEvidence"][0]["unannouncedSupportLabel"],
                         "Guest surprise")
        publisher(app, cat)

    def test_two_distinct_days_of_stability_before_official_recheck(self):
        candidate, page, cat = make()
        row = {"candidate": candidate, "stableObservations": 1,
               "status": "pending_review"}
        registry = {"items": {"one": row}}
        empty = {"schema": "grossesondes.concert.approvals.v1", "approvals": []}
        no_network = lambda *_: self.fail("One-day lead may not be fetched")
        _, report = official_recheck.process(
            registry, cat, empty, TODAY, fetch=no_network)
        self.assertEqual(report["evaluated"], 0)
        row["stableObservations"] = 2
        reviewed, report = official_recheck.process(
            registry, cat, empty, TODAY, fetch=lambda *_: page)
        self.assertEqual(len(report["newApprovals"]), 1)
        self.assertEqual(len(reviewed["approvals"]), 1)
        publisher(reviewed["approvals"][0], cat)

    def test_independent_refetch_rejects_changed_date_bill_room_or_genre(self):
        candidate, page, cat = make()
        variants = [
            page.replace("18 juin 2027", "19 juin 2027"),
            page.replace("<h1>ACT ONE + ACT TWO</h1>",
                         "<h1>ACT ONE + DIFFERENT ACT</h1>"),
            page.replace("69100 Villeurbanne", "75000 Paris"),
            page.replace("La Rayonne<p>", "Different Hall<p>"),
            page.replace("Death Metal", "Jazz"),
            page.replace(
                "<h4><strong>► ACT TWO – Death Metal – FRANCE</strong></h4>", ""),
            page.replace(
                "<h4>▼ INFOS PRATIQUES</h4>",
                "<h4><strong>► THIRD ACT – Death Metal – FRANCE</strong></h4>"
                "<h4>▼ INFOS PRATIQUES</h4>"),
            page.replace(
                "<h3>Production présente :</h3>",
                "<p>Concert annulé</p><h3>Production présente :</h3>"),
        ]
        for altered in variants:
            with self.subTest(variant=altered[-140:]):
                with self.assertRaises(ValueError):
                    official_recheck.verify(candidate, altered, cat, TODAY)

    def test_publisher_rejects_forged_proofs_and_artist_aliases(self):
        candidate, page, cat = make()
        app = official_recheck.verify(candidate, page, cat, TODAY)
        for field, value in (
            ("sourceStructure", "verified-first-party-structured-event-v1"),
            ("officialGenreLabels", ["Jazz"]),
            ("visibleBillProfile", "unsafe-venue-bio"),
            ("officialArtistNames", ["ACT ONE", "FAKE ACT"]),
            ("verifiedVenueId", "fake-venue"),
            ("checkedFields", ["artists", "date"]),
        ):
            with self.subTest(field=field):
                forged = copy.deepcopy(app)
                forged["officialEvidence"][0][field] = value
                with self.assertRaises(ValueError):
                    publisher(forged, cat)
        for field, value in (
            ("venueId", "fake-venue"),
            ("organizer", "Unknown Promoter"),
            ("time", "20:00"),
            ("genres", ["Jazz"]),
            ("title", "ACT ONE + GHOST"),
            ("date", "2027-06-19"),
        ):
            with self.subTest(field=field):
                forged = copy.deepcopy(app)
                forged["event"][field] = value
                with self.assertRaises(ValueError):
                    publisher(forged, cat)
        collision = copy.deepcopy(cat)
        collision["artists"] = [{"id": "known-act", "name": "OTHER",
                                 "aliases": ["ACT TWO"]}]
        with self.assertRaisesRegex(ValueError, "alias"):
            official_recheck.verify(candidate, page, collision, TODAY)

    def test_foreign_domain_rejected_before_network_request(self):
        candidate, page, cat = make()
        forged = copy.deepcopy(candidate)
        forged["sourceUrl"] = (
            "https://untrusted.example/evenement/synthetic-bill-2027/")
        reg = {"items": {"x": {"candidate": forged,
                               "stableObservations": 2,
                               "status": "pending_review"}}}
        empty = {"schema": "grossesondes.concert.approvals.v1",
                 "approvals": []}
        out, report = official_recheck.process(
            reg, cat, empty, TODAY,
            fetch=lambda *_: self.fail("Foreign host must not be fetched"))
        self.assertEqual(report["newApprovals"], [])
        self.assertEqual(report["evaluated"], 1)
        self.assertEqual(len(report["held"]), 1)
        self.assertEqual(out["approvals"], [])

    def test_post_publication_watch_same_bill_and_disagreements(self):
        candidate, page, cat = make()
        app = official_recheck.verify(candidate, page, cat, TODAY)
        event = app["event"]
        artists = {a["id"]: a["name"] for a in app["newArtists"]}
        self.assertEqual(published_watch.source_kind(event),
                         "generic_structured")
        matched = published_watch.inspect(event, page, artists)
        self.assertEqual(matched["status"], "matched")
        moved = page.replace("18 juin 2027", "19 juin 2027")
        self.assertEqual(published_watch.inspect(
            event, moved, artists)["status"], "date_review")
        changed = page.replace(
            "<h1>ACT ONE + ACT TWO</h1>",
            "<h1>ACT ONE + DIFFERENT ACT</h1>").replace(
            "► ACT TWO – Death Metal", "► DIFFERENT ACT – Death Metal")
        self.assertEqual(published_watch.inspect(
            event, changed, artists)["status"], "lineup_review")
        relocated = page.replace("69100 Villeurbanne", "75000 Paris")
        self.assertEqual(published_watch.inspect(
            event, relocated, artists)["status"], "content_review")
        cancelled = page.replace(
            "<h3>Production présente :</h3>",
            "<p>Concert annulé</p><h3>Production présente :</h3>")
        self.assertEqual(published_watch.inspect(
            event, cancelled, artists)["status"], "content_review")


if __name__ == "__main__":
    unittest.main()
