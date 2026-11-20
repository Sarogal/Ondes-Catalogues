"""Read-only anomaly monitoring for source-wide approved structured venues.

A newly published event is automatically observable without a new concert ID
in this code. No test opens network connections or writes production data.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generic_music_event as gen
import published_watch as watch

TODAY = dt.date(2026, 11, 19)


def sample(venue_id="la-rayonne", *, kind="MusicEvent",
           performers=("ACT ONE", "ACT TWO")):
    source = gen.SPECS[venue_id]
    day = "2027-03-13"
    url = source["base"] + source["eventPathPrefix"].lstrip("/") + "verified-metal-night/"
    names = [x for x in performers if x != "Guest"]
    record = {
        "id": "go-c-20270313-" + gen.slug(source["city"]) + "-act-one",
        "date": day, "title": " + ".join(names), "venueId": venue_id,
        "officialUrl": url, "artistIds": [gen.slug(x) for x in names],
        "genres": ["Death Metal"], "sourceType": "salle",
        "organizer": source["name"], "status": "confirmed",
        "time": None,
    }
    raw = {
        "@type": kind, "name": " + ".join(performers), "url": url,
        "startDate": day + "T20:00:00+01:00",
        "genre": ["Death Metal"],
        "performer": [{"@type": "MusicGroup", "name": x}
                      for x in performers],
        "location": {
            "@type": "MusicVenue", "name": source["name"],
            "address": {"addressLocality": source["city"],
                        "addressCountry": "FR"},
        },
    }
    artists = {gen.slug(x): x for x in names}
    return record, raw, artists


def html(raw):
    return '<script type="application/ld+json">' + json.dumps(
        raw, ensure_ascii=False) + '</script>'


class GenericStructuredPublishedWatchTests(unittest.TestCase):
    def test_future_concerts_of_both_approved_venues_auto_eligible(self):
        for venue in gen.SPECS:
            for kind in ("MusicEvent", "Event"):
                with self.subTest(venue=venue, kind=kind):
                    record, data, artists = sample(venue, kind=kind)
                    self.assertEqual(
                        watch.source_kind(record), "generic_structured")
                    result = watch.inspect(record, html(data), artists)
                    self.assertEqual(result["status"], "matched")
                    self.assertEqual(result["observedDate"], record["date"])

    def test_new_concert_id_and_new_acts_need_no_watcher_registration(self):
        record, raw, _ = sample()
        names = ["FRESH ACT 001", "FRESH ACT 002", "FRESH ACT 003"]
        record["id"] = "go-c-20270313-villeurbanne-fresh-act-001"
        record["title"] = " + ".join(names)
        record["artistIds"] = [gen.slug(n) for n in names]
        raw["name"] = record["title"]
        raw["performer"] = [{"@type": "MusicGroup", "name": n} for n in names]
        self.assertEqual(watch.source_kind(record), "generic_structured")
        self.assertEqual(watch.inspect(
            record, html(raw), dict(zip(record["artistIds"], names))
        )["status"], "matched")

    def test_changed_dates_names_genre_room_and_cancel_are_review_only(self):
        rec, raw, artists = sample()
        variants = [
            ({"startDate": "2027-04-13T20:00:00+02:00"}, "date_review"),
            ({"performer": [{"@type": "MusicGroup", "name": "ACT ONE"},
                            {"@type": "MusicGroup", "name": "NEW SUPPORT"}]},
             "lineup_review"),
            ({"genre": ["Rock"]}, "content_review"),
            ({"location": {"@type": "MusicVenue", "name": "Other Hall",
                           "address": {"addressLocality": "Paris",
                                       "addressCountry": "FR"}}},
             "content_review"),
            ({"eventStatus": {"@id": "https://schema.org/EventCancelled"}},
             "content_review"),
            ({"url": "https://larayonne.org/evenement/unrelated-show/"},
             "content_review"),
            ({"performer": None}, "lineup_review"),
            ({"startDate": None}, "content_review"),
        ]
        before = json.dumps([rec, raw, artists], sort_keys=True)
        for changed, expected in variants:
            with self.subTest(changed=changed):
                result = watch.inspect(
                    rec, html({**raw, **changed}), artists)
                self.assertEqual(result["status"], expected)
                self.assertNotEqual(result["status"], "matched")
        self.assertEqual(json.dumps(
            [rec, raw, artists], sort_keys=True), before)

    def test_ambiguous_document_never_claims_matched(self):
        rec, raw, artists = sample()
        candidates = [
            "",
            "<html>No official structured event</html>",
            html([raw, {**raw, "name": "DIFFERENT SHOW"}]),
        ]
        for page in candidates:
            with self.subTest(length=len(page)):
                self.assertEqual(
                    watch.inspect(rec, page, artists)["status"],
                    "content_review")

    def test_trailing_guest_not_promoted_to_artist(self):
        rec, raw, artists = sample(performers=("ACT ONE", "ACT TWO", "Guest"))
        self.assertEqual(watch.inspect(
            rec, html(raw), artists)["status"], "matched")
        extra = {**raw, "performer": [
            {"@type": "MusicGroup", "name": "ACT ONE"},
            {"@type": "MusicGroup", "name": "Guest"},
            {"@type": "MusicGroup", "name": "ACT TWO"},
        ]}
        self.assertEqual(watch.inspect(
            rec, html(extra), artists)["status"], "lineup_review")

    def test_host_path_provenance_and_identity_reject_spoofing(self):
        rec, _, _ = sample()
        changed = [
            {"venueId": "unreviewed-venue"},
            {"officialUrl": "https://evil.example/evenement/verified-metal-night/"},
            {"officialUrl": rec["officialUrl"].replace(
                "larayonne.org", "larayonne.org.evil.example")},
            {"officialUrl": rec["officialUrl"] + "?tracking=1"},
            {"officialUrl": "https://larayonne.org/agenda/"},
            {"id": "go-c-20270314-villeurbanne-act-one"},
            {"id": "go-c-20270313-paris-act-one"},
            {"date": "not-a-date"},
            {"sourceType": "aggregateur"},
            {"organizer": "Untrusted source"},
        ]
        for change in changed:
            with self.subTest(change=change):
                self.assertIsNone(watch.source_kind({**rec, **change}))

    def test_read_only_runner_reports_anomaly_without_mutating_catalogue(self):
        rec, raw, arts = sample()
        other = {"id": "dummy", "date": "2027-01-01",
                 "venueId": "unreviewed-venue",
                 "officialUrl": "https://example.invalid/not-a-show",
                 "artistIds": [], "title": "Dummy"}
        catalogue = {
            "schemaVersion": 1, "mode": "preview-public-unlisted",
            "venues": [{"id": str(i)} for i in range(53)],
            "artists": [{"id": k, "name": v} for k, v in arts.items()],
            "events": [copy.deepcopy(other) for _ in range(126)] + [rec],
        }
        # The runner requires unique public event IDs. Dummy historical
        # entries deliberately have different IDs and are never eligible.
        for i, item in enumerate(catalogue["events"][:-1]):
            item["id"] = "dummy-%03d" % i
        before = json.dumps(catalogue, sort_keys=True)
        changed = {**raw, "startDate": "2027-03-14T20:00:00+01:00"}
        report = watch.run(
            catalogue, TODAY, limit=24,
            fetch=lambda url: (html(changed), url),
            robots=lambda url, cache: True,
        )
        self.assertEqual(report["checked"], 1)
        self.assertEqual(report["counts"], {"date_review": 1})
        self.assertEqual(report["needsReview"][0]["id"], rec["id"])
        self.assertFalse(report["publicationAllowed"])
        self.assertEqual(json.dumps(catalogue, sort_keys=True), before)


if __name__ == "__main__":
    unittest.main()
