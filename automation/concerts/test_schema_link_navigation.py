"""Official Event JSON-LD may link exact show pages without /concert/ in URL."""
from __future__ import annotations

import datetime as dt
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discover

TODAY = dt.date(2026, 11, 20)
AGENDA = "https://official-stage.example/agenda/"
NO_KEYWORD = "https://official-stage.example/metallica-sur-la-place-2027/"
def event(**kw):
    obj = {
        "@type": "MusicEvent", "name": "Metallica + First Act",
        "url": NO_KEYWORD, "startDate": "2027-07-18T21:00:00+02:00",
        "performer": [
            {"@type": "MusicGroup", "name": "Metallica"},
            {"@type": "MusicGroup", "name": "First Act"},
        ],
        "location": {
            "@type": "Place", "name": "Place éphémère",
            "address": {"addressLocality": "Paris", "addressCountry": "FR"},
        },
    }
    obj.update(kw)
    return obj

def html(rows):
    return '<script type="application/ld+json">' + json.dumps(
        {"@graph": rows}, ensure_ascii=False) + '</script>'

class OpenFirstPartySchemaNavigationTests(unittest.TestCase):
    def test_official_detail_without_concert_path_is_discoverable(self):
        self.assertFalse(discover.EVENT_URL.search(
            "/metallica-sur-la-place-2027/"))
        links = discover.linked_first_party_event_urls(
            html([event()]), AGENDA, TODAY)
        self.assertEqual(links, [NO_KEYWORD])
        self.assertEqual(
            discover.select_generic_official_detail_links(
                links, TODAY, 1, limit=3),
            [NO_KEYWORD])

    def test_event_without_genre_still_an_investigatory_lead_not_an_approval(self):
        # A genre must be independently proved before publication, but
        # lack of an event tag must not prevent finding a full first-party
        # detail page where the evidence might be present.
        links = discover.linked_first_party_event_urls(
            html([event(**{"@type": "Event", "genre": None})]),
            AGENDA, TODAY)
        self.assertEqual(links, [NO_KEYWORD])

    def test_external_tracking_generic_and_malformed_links_never_followed(self):
        invalid = (
            "https://tickets.example/live/band/",
            "http://official-stage.example/band/",
            NO_KEYWORD + "?ref=social",
            "https://official-stage.example/agenda/",
            "https://evil.example@official-stage.example/band/",
            "/metallica-sur-la-place-2027/",
            None,
        )
        for url in invalid:
            with self.subTest(url=url):
                links = discover.linked_first_party_event_urls(
                    html([event(url=url)]), AGENDA, TODAY)
                self.assertEqual(links, [])

    def test_cancellation_expiry_and_untyped_performer_cannot_generate_link(self):
        invalid = (
            {"eventStatus": "https://schema.org/EventCancelled"},
            {"eventStatus": "https://schema.org/EventPostponed"},
            {"eventStatus": "https://schema.org/EventRescheduled"},
            {"startDate": "2025-07-18"},
            {"performer": {"@type": "Organization", "name": "An organizer"}},
            {"performer": None},
            {"@type": "Organization"},
        )
        for change in invalid:
            with self.subTest(change=change):
                links = discover.linked_first_party_event_urls(
                    html([event(**change)]), AGENDA, TODAY)
                self.assertEqual(links, [])

    def test_rotating_candidates_preserve_all_artists_no_fixed_stage_allowlist(self):
        rows = []
        for i in range(17):
            url = f"https://official-stage.example/groupe-{i:02d}-2027/"
            rows.append(event(url=url))
        links = discover.linked_first_party_event_urls(
            html(rows + [rows[0]]), AGENDA, TODAY)
        self.assertEqual(len(links), 17)
        seen = set()
        for delta in (0, 1, 2):
            for slot in (0, 1, 2):
                seen.update(discover.select_generic_official_detail_links(
                    links, TODAY + dt.timedelta(days=delta), slot, limit=3))
        self.assertEqual(seen, set(links))

    def test_non_json_ld_menu_or_page_link_cannot_create_schema_authority(self):
        doc = (
            '<h1>Menu</h1><a href="' + NO_KEYWORD + '">Concert</a>'
            '<script type="application/ld+json">{"@type":"Organization",'
            '"url":"' + NO_KEYWORD + '"}</script>'
        )
        self.assertEqual(discover.linked_first_party_event_urls(
            doc, AGENDA, TODAY), [])

if __name__ == "__main__":
    unittest.main()
