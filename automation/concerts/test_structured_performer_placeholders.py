"""Official structured event may erroneously identify Organization as performer.

Never trust this field as an artist. A visible metal tag in the event detail
may be recorded for *private review* only, not new approvals/publication.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discover
import official_html_evidence
import official_rss_jsonld_bridge
import structured_first_party_preflight
import triage

TODAY = dt.date(2026, 11, 19)
URL = "https://larayonne.org/evenement/eisbrecher/"
SOURCE = {"name": "La Rayonne", "city": "Villeurbanne",
          "department": "69", "url": "https://larayonne.org/"}
CATALOGUE = {"schemaVersion": 1, "mode": "preview-public-unlisted",
             "events": [], "venues": [], "artists": []}
APPROVALS = {"schema": "grossesondes.concert.approvals.v1", "approvals": []}


def event(kind="Event", genre="Rock", performer=None):
    return {
        "@type": kind, "name": "EISBRECHER",
        "startDate": "2027-09-18T19:00:00+02:00",
        "url": URL, "genre": genre,
        "performer": performer if performer is not None else {
            "@type": "Organization", "name": "Organization"},
        "location": {"@type": "MusicVenue", "name": "La Rayonne",
                     "address": {"addressLocality": "Villeurbanne",
                                 "addressCountry": "FR"}},
    }


def discovered(raw=None):
    raw = raw if raw is not None else event()
    row = discover.venue_candidate(raw, SOURCE, URL, set(), TODAY.isoformat())
    return triage.triage(row, catalogue=CATALOGUE)


def html(raw=None):
    raw = raw if raw is not None else event()
    return (
        '<script type="application/ld+json">'
        + json.dumps(raw) + '</script>'
        '<h1>EISBRECHER</h1>'
        '<strong>samedi 18 septembre 2027</strong>'
        '<p>La Rayonne</p><p>69100 Villeurbanne</p>'
        '<h4>► EISBRECHER – Metal Indus –</h4>'
    )


class StructuredPerformerPlaceholderTests(unittest.TestCase):
    def test_organization_placeholder_is_not_a_discovered_band(self):
        row = discovered()
        self.assertEqual(row["leadArtist"], "EISBRECHER")
        self.assertEqual(row["structuredPerformerProof"], "missing_review_only")
        self.assertEqual(row["reviewBucket"], "genre_unknown")
        self.assertNotEqual(row["leadArtist"], "Organization")
        self.assertFalse(row["publicationAllowed"])
        self.assertTrue(row["reviewRequired"])

    def test_valid_named_performer_and_surprise_guest_are_preserved(self):
        named = [{"@type": "MusicGroup", "name": "EISBRECHER"},
                 {"@type": "Person", "name": "Guest"}]
        row = discovered(event(kind="MusicEvent", genre="Death Metal",
                               performer=named))
        self.assertEqual(row["leadArtist"], "EISBRECHER")
        self.assertEqual(row["unannouncedSupportLabel"], "Guest")
        self.assertNotIn("structuredPerformerProof", row)
        self.assertEqual(row["reviewBucket"], "genre_tag_review")

    def test_non_organization_wrong_type_never_becomes_named_band(self):
        row = discovered(event(
            kind="MusicEvent", genre="Death Metal",
            performer={"@type": "Organization", "name": "Unverified Promoter"}))
        self.assertEqual(row["leadArtist"], "EISBRECHER")
        self.assertEqual(row["structuredPerformerProof"], "missing_review_only")
        self.assertIsNone(official_rss_jsonld_bridge.official_named_bill(
            event()["performer"]))

    def test_html_label_is_held_without_independent_artists(self):
        row = discovered()
        result = official_html_evidence.inspect(row, html(), URL, SOURCE)
        self.assertEqual(result["status"],
                         "html_event_genre_visible_lineup_unverified")
        self.assertEqual(result["genres"], ["Metal Indus"])
        self.assertFalse(result["publicationAllowed"])
        self.assertEqual(result["approvalsProposed"], 0)

    def test_private_preflight_keeps_html_genre_separate_from_approval(self):
        row = discovered()
        registry = {"schema": "grossesondes.concert.intake.v1",
                    "items": {"event": {
                        "candidate": row, "status": "pending_review",
                        "stableObservations": 2}}}
        sources = {"schema": "grossesondes.concert.sourcelist.v1",
                   "venues": [SOURCE]}
        report = structured_first_party_preflight.build(
            registry, sources, CATALOGUE, APPROVALS, TODAY,
            fetch=lambda url, **kwargs: (html(), url),
            robots=lambda url, cache: True, limit=8,
        )
        self.assertEqual(report["exploratoryAttempted"], 1)
        self.assertEqual(report["htmlGenreVisibleLineupUnverified"], 1)
        self.assertEqual(report["htmlGenreEvidenceFound"], 0)
        self.assertEqual(report["structureMatched"], 0)
        self.assertEqual(report["approvalsProposed"], 0)
        self.assertFalse(report["publicationAllowed"])
        self.assertEqual(report["results"][0]["status"], "held")
        self.assertEqual(report["results"][0]["htmlGenreLabels"],
                         ["Metal Indus"])

    def test_generic_structured_publisher_refuses_organization_performer(self):
        import generic_music_event
        from unittest.mock import patch
        # A hostile row can claim reviewBucket='genre_tag_review', but the
        # independent official verifier never treats Organization as musician.
        row = discovered(event(kind="MusicEvent", genre="Death Metal"))
        self.assertEqual(row["reviewBucket"], "genre_tag_review")
        with self.assertRaisesRegex(
                ValueError, "Détail de concert officiel non corroboré"):
            generic_music_event.verify(
                row, html(event(kind="MusicEvent", genre="Death Metal")),
                {"venues": [{"id": "la-rayonne", "name": "La Rayonne",
                             "city": "Villeurbanne", "department": "69"}],
                 "artists": [], "events": []}, TODAY)


if __name__ == "__main__":
    unittest.main()
