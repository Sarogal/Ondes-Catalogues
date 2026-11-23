"""Source-wide real-Publisher regression for Trabendo's visible official bills.

No album, group, show, URL or event ID is an allowlist. The two sample
concerts are synthetic HTML with actual first-party page layout only.
The independent producer and Publisher MUST each re-read the whole event.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import unittest
from pathlib import Path
from unittest import mock

from automation.concerts import dynamic_osm_official_proposals as producer
from automation.concerts import trabendo_official_single_source as visible
from automation.concerts import dynamic_first_party_venue_proposals as parser
from automation.concerts import approval_preflight
from scripts import concert_dynamic_existing_venue as identity
from scripts import concerts_cloud_sync as publisher

ROOT = Path(__file__).resolve().parents[1]
TODAY = dt.date(2026, 11, 23)
VENUE = "le-trabendo-paris"
PAGE = "https://www.letrabendo.net/programmation/"
SHOWS = (
    ("Klone", "2027-04-22", "22 avril 2027",
     "https://www.letrabendo.net/programmation/klone/"),
    ("Witch club satan", "2027-04-28", "28 avril 2027",
     "https://www.letrabendo.net/programmation/witch-club-satan/"),
)


def official_html(title, shown_day, *, genre="Metal", room="Trabendo",
                  cancellation="", others=""):
    return (f"<html><head><title>{title} – Trabendo</title></head><body>"
            "<main><h1>Trabendo</h1><h2>Le Trabendo présente :</h2>"
            "<p>Programmation officielle en salle, artiste nommé.</p>"
            f"<div>{shown_day}</div><strong>{title}</strong>"
            f"<span>concert ― {genre}</span>"
            f"<p>→ {room} - Salle de concert</p>"
            "<p>Ouverture des portes 19:00</p>"
            + cancellation + "<section>Vous devriez aimer " + others +
            "</section></main></body></html>")


def lead(title, show_date, url):
    return {"status": "pending_review", "stableObservations": 2,
            "candidate": {
                "candidateId": "independent-trabendo:" + title.lower(),
                "source": "agenda_officiel_trabendo_detail",
                "sourceUrl": url,
                "sourcePage": PAGE,
                "date": show_date, "name": title, "leadArtist": title,
                "venue": "Le Trabendo", "city": "Paris", "department": "75",
                "reviewBucket": "genre_tag_review",
                "possibleExistingConcert": False,
                "publicationAllowed": False, "reviewRequired": True}}


class TrabendoOfficialPublisherTests(unittest.TestCase):
    def setUp(self):
        self.catalogue = json.loads(
            (ROOT / "docs/grossesondes/concerts.json").read_text("utf-8"))
        self.venue = next(v for v in self.catalogue["venues"]
                          if v["id"] == VENUE)
        self.assertEqual(self.venue["postalCode"], "75019")

    def test_two_unrelated_shows_automatically_publish_from_one_site(self):
        pages = {url: official_html(title, shown_day)
                 for title, _, shown_day, url in SHOWS}
        calls = []
        def fetch(url, cache):
            calls.append(url)
            if url not in pages:
                self.fail("Unexpected fetch: " + url)
            return pages[url]

        reg = {"schema": "grossesondes.concert.intake.v1",
               "items": {title: lead(title, day, url)
                         for title, day, _, url in SHOWS}}
        before = {"schema": publisher.SCHEMA, "approvals": []}
        copy_reg = copy.deepcopy(reg)
        with mock.patch.object(identity, "safe_fetch", side_effect=fetch):
            proposed, diag = producer.build(
                reg, self.catalogue, before, TODAY, fetch=fetch)
            self.assertEqual(diag["stateCounts"],
                             {"independently_verified_proposal": 2}, diag)
            self.assertEqual(len(proposed["approvals"]), 2)
            self.assertEqual(len(approval_preflight.check_append_only(
                before, proposed, TODAY)), 2)
            events = [p["event"] for p in proposed["approvals"]]
            self.assertEqual({e["date"] for e in events},
                             {"2027-04-22", "2027-04-28"})
            self.assertTrue(all(e["venueId"] == VENUE and e["time"] is None
                                and e["genres"] == ["metal"] for e in events))
            self.assertTrue(all(
                p["officialEvidence"][0]["proofType"] ==
                identity.OFFICIAL_SOURCE_PROFILE
                for p in proposed["approvals"]))
            published, stats = publisher.merge(
                self.catalogue, self.catalogue, proposed, TODAY)
            self.assertEqual(stats["newEvents"], 2, stats.get("held"))
            self.assertEqual(published["events"][-2]["venueId"], VENUE)
            again, second = publisher.merge(
                self.catalogue, published, proposed, TODAY)
            self.assertEqual(second["newEvents"], 0)
            self.assertEqual(published, again)
        self.assertGreaterEqual(len(calls), 6)
        self.assertEqual(set(calls), set(pages))
        self.assertEqual(reg, copy_reg)

    def test_official_page_alone_suffices_for_a_two_band_headline(self):
        title = "ACT ALPHA + ACT BETA"
        url = "https://www.letrabendo.net/programmation/unknown-band/"
        html = official_html(title, "22 avril 2027")
        first = visible.verified_bill(html, url, self.venue, TODAY)
        self.assertEqual(first["names"], ["ACT ALPHA", "ACT BETA"])
        self.assertEqual(first["genres"], ["metal"])
        self.assertEqual(
            parser._individual_event(html, url, "2027-04-22",
                                     self.venue, accept_generic=True),
            (["ACT ALPHA", "ACT BETA"], ["metal"]))

    def test_identity_date_genre_and_cancellation_fail_closed(self):
        title, date, written, url = SHOWS[0]
        good = official_html(title, written)
        self.assertEqual(
            visible.verified_bill(good, url, self.venue, TODAY)["date"], date)
        bad = [
            official_html(title, "23 avril 2027"),
            official_html(title, written, genre="Electro"),
            official_html(title, written, room="Another Room"),
            official_html(title, written, cancellation="Concert annulé"),
            good.replace("<title>Klone – Trabendo</title>",
                         "<title>Other Band – Trabendo</title>"),
            good.replace("22 avril 2027", "22 avril 2025"),
        ]
        for altered in bad:
            with self.subTest(html=altered[-140:]):
                if altered == bad[0]:
                    with self.assertRaises(ValueError):
                        parser._individual_event(
                            altered, url, date, self.venue,
                            accept_generic=True)
                else:
                    with self.assertRaises(ValueError):
                        visible.verified_bill(altered, url, self.venue, TODAY)

    def test_foreign_host_or_venue_can_never_claim_official_source(self):
        title, date, written, url = SHOWS[0]
        html = official_html(title, written)
        for bad_url in (
            "https://evil.example/programmation/klone/",
            "https://www.letrabendo.net/programmation/klone/?preview=1",
            "http://www.letrabendo.net/programmation/klone/",
            "https://www.letrabendo.net/programmation/",
        ):
            self.assertFalse(visible.supports(self.venue, bad_url))
            with self.assertRaises(ValueError):
                visible.verified_bill(html, bad_url, self.venue, TODAY)
        changed = dict(self.venue, city="Lyon")
        self.assertFalse(visible.supports(changed, url))
        changed = dict(self.venue, id="another-venue")
        self.assertFalse(visible.supports(changed, url))

    def test_structured_contradictions_cannot_fall_back_to_html(self):
        title, date, written, url = SHOWS[0]
        content = official_html(title, written)
        injected = ('<script type="application/ld+json">'
                    + json.dumps({
                        "@context": "https://schema.org",
                        "@type": "MusicEvent",
                        "name": "FAKE OTHER SHOW", "startDate": date,
                        "location": {"name": "Other Room"},
                        "performer": [{"@type": "MusicGroup",
                                       "name": "FAKE ARTIST"}],
                        "genre": "Metal",
                    }) + "</script>")
        with self.assertRaises(ValueError):
            parser._individual_event(
                content.replace("</head>", injected + "</head>"),
                url, date, self.venue, accept_generic=True)


if __name__ == "__main__":
    unittest.main()
