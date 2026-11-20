"""Fresh official structured genre proof may requalify unconfirmed discovery.

Synthetic fixtures, offline only. No candidate, approval or public data is written.
"""
import copy
import datetime as dt
import json
import unittest

import official_recheck
from test_generic_music_event import make, publish

DAY = dt.date(2026, 11, 19)


def unconfirmed():
    candidate, page, catalogue, raw = make(
        names=("NEW METAL ACT", "FIRST SUPPORT", "SECOND SUPPORT"))
    candidate = copy.deepcopy(candidate)
    candidate["classification"] = []
    candidate["reviewBucket"] = "genre_unknown"
    candidate["genreEvidence"] = None
    return candidate, page, catalogue, raw


class FreshOfficialGenreRequalificationTests(unittest.TestCase):
    def test_unknown_genre_recovered_on_fresh_official_detail(self):
        lead, page, cat, _ = unconfirmed()
        approval = official_recheck.verify(lead, page, cat, DAY)
        self.assertEqual(approval["event"]["genres"], ["Death Metal"])
        self.assertEqual(len(approval["newArtists"]), 3)
        self.assertEqual(approval["officialEvidence"][0]["sourceStructure"],
                         "verified-first-party-structured-event-v1")
        event, artists = publish(approval, cat)
        self.assertEqual(len(event["artistIds"]), 3)
        self.assertEqual(len(artists), 3)

    def test_process_proposes_and_real_publisher_validates(self):
        lead, page, cat, _ = unconfirmed()
        registry = {"items": {"example": {
            "status": "pending_review", "stableObservations": 2,
            "candidate": lead,
        }}}
        before = {"schema": "grossesondes.concert.approvals.v1",
                  "approvals": []}
        after, report = official_recheck.process(
            registry, cat, before, DAY, fetch=lambda *_: page)
        self.assertEqual(report["evaluated"], 1)
        self.assertEqual(len(report["newApprovals"]), 1)
        self.assertEqual(before["approvals"], [])
        publish(after["approvals"][0], cat)

    def test_no_stability_or_untrusted_host_means_no_network(self):
        lead, page, cat, _ = unconfirmed()
        registry = {"items": {"example": {
            "status": "pending_review", "stableObservations": 1,
            "candidate": lead,
        }}}
        before = {"schema": "grossesondes.concert.approvals.v1",
                  "approvals": []}
        def forbidden(*_):
            self.fail("Untrusted lead should never trigger HTTP")
        _, report = official_recheck.process(
            registry, cat, before, DAY, fetch=forbidden)
        self.assertEqual(report["evaluated"], 0)
        registry["items"]["example"]["stableObservations"] = 2
        registry["items"]["example"]["candidate"]["sourceUrl"] = (
            "https://unreviewed.example/show/2027")
        _, report = official_recheck.process(
            registry, cat, before, DAY, fetch=forbidden)
        self.assertEqual(report["newApprovals"], [])
        self.assertEqual(report["evaluated"], 0)
        self.assertEqual(report["awaitingIndependentSourceAdmission"], 1)
        self.assertEqual(report["held"], [])

    def test_fresh_metal_on_menu_or_biography_is_not_proof(self):
        lead, _, cat, raw = unconfirmed()
        raw.pop("genre")
        page = ('<nav>Death Metal, Punk</nav>'
                '<script type="application/ld+json">'
                + json.dumps(raw) + '</script>'
                '<section class="artist-bio">Death Metal</section>')
        with self.assertRaises(ValueError):
            official_recheck.verify(lead, page, cat, DAY)

    def test_identity_date_cancellation_and_official_genre_stay_strict(self):
        lead, _, cat, raw = unconfirmed()
        cases = (
            {"name": "Some other concert"},
            {"startDate": "2027-03-14T20:00:00+01:00"},
            {"performer": [{"@type": "MusicGroup", "name": "OTHER"}]},
            {"location": {"name": "Fake stage",
                          "address": {"addressLocality": "Paris",
                                      "addressCountry": "FR"}}},
            {"eventStatus": "https://schema.org/EventCancelled"},
            {"eventStatus": "https://schema.org/EventPostponed"},
            {"genre": ["Jazz"]},
            {"genre": ["Hardcore Techno"]},
        )
        for mutation in cases:
            with self.subTest(mutation=mutation):
                markup = ('<script type="application/ld+json">'
                          + json.dumps({**raw, **mutation}) + '</script>')
                with self.assertRaises(ValueError):
                    official_recheck.verify(lead, markup, cat, DAY)

    def test_duplicate_concert_is_rejected(self):
        lead, page, cat, _ = unconfirmed()
        approval = official_recheck.verify(lead, page, cat, DAY)
        cat["events"].append(approval["event"])
        with self.assertRaises(ValueError):
            official_recheck.verify(lead, page, cat, DAY)

    def test_unconfirmed_label_cannot_hide_a_known_genre(self):
        lead, page, cat, _ = unconfirmed()
        lead["classification"] = ["Death Metal"]
        with self.assertRaisesRegex(ValueError, "catégorie de revue"):
            official_recheck.verify(lead, page, cat, DAY)


if __name__ == "__main__":
    unittest.main()
