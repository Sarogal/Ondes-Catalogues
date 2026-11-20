"""HTML microdata may prove a new physical concert site without JSON-LD.

All people, sites, dates, and responses in this test are synthetic. The normal
first-party source registry, independent OSM fetch, and publisher remain
mandatory. An HTML page is not a new trusted source by itself.
"""
from __future__ import annotations

import copy
import datetime as dt
import html
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts import concerts_cloud_sync as publisher
import approval_preflight as gate
import event_site_microdata
import event_site_pair_recheck as reviewer
import official_recheck
from test_event_site_pair_recheck import fixture, DAY, EVENT, API, OSM


def microdata(*, title="7WEEKS + NEW METAL SUPPORT",
              date="2027-05-17", genre="Heavy Metal",
              venue="Esplanade des Tests", artists=("7WEEKS", "NEW METAL SUPPORT"),
              canonical=EVENT, hidden=False, extra="", status=""):
    performers = "".join(
        '<div itemprop="performer" itemscope '
        'itemtype="https://schema.org/MusicGroup">'
        '<span itemprop="name">' + html.escape(artist) + '</span></div>'
        for artist in artists
    )
    return (
        '<main><article ' + ('hidden ' if hidden else '')
        + 'itemscope itemtype="https://schema.org/MusicEvent">'
        + '<h1 itemprop="name">' + html.escape(title) + '</h1>'
        + '<a itemprop="url" href="' + html.escape(canonical, quote=True)
        + '">Fiche officielle du concert</a>'
        + '<time itemprop="startDate" datetime="' + html.escape(date)
        + '">' + date + '</time>'
        + '<meta itemprop="genre" content="' + html.escape(genre) + '">'
        + ('<meta itemprop="eventStatus" content="' + html.escape(status) + '">'
           if status else '')
        + performers
        + '<div itemprop="location" itemscope '
          'itemtype="https://schema.org/Place">'
          '<strong itemprop="name">' + html.escape(venue) + '</strong>'
          '<a itemprop="sameAs" href="' + OSM + '">Plan du site</a>'
          '<div itemprop="address" itemscope '
          'itemtype="https://schema.org/PostalAddress">'
          '<span itemprop="streetAddress">Avenue des Essais</span>'
          '<span itemprop="postalCode">75007</span>'
          '<span itemprop="addressLocality">Paris</span>'
          '<span itemprop="addressRegion">Île-de-France</span>'
          '<meta itemprop="addressCountry" content="FR">'
          '</div></div></article></main>'
        + extra
    )


def fetched(page, osm, calls):
    def get(url, limit):
        calls.append(url)
        if url == EVENT:
            return page, EVENT
        if url == API:
            return json.dumps(osm), API
        raise AssertionError("Unexpected fetch target " + str(url))
    return get


class EventSiteMicrodataProofTests(unittest.TestCase):
    def test_microdata_reader_is_generic_and_event_scoped(self):
        rows = event_site_microdata.read_microdata_events(microdata())
        self.assertEqual(len(rows), 1)
        event = rows[0]
        self.assertEqual(event["@type"], "MusicEvent")
        self.assertEqual(event["name"], "7WEEKS + NEW METAL SUPPORT")
        self.assertEqual(event["startDate"], "2027-05-17")
        self.assertEqual(event["genre"], "Heavy Metal")
        self.assertEqual(len(event["performer"]), 2)
        self.assertEqual(event["location"]["name"], "Esplanade des Tests")
        self.assertEqual(event["location"]["address"]["postalCode"], "75007")
        self.assertEqual(event["location"]["sameAs"], OSM)

    def test_html_microdata_reaches_real_independent_publisher(self):
        lead, _, cat, osm = fixture()
        ledger = {"schema": publisher.SCHEMA,
                  "approvals": [], "venueApprovals": []}
        page = microdata()
        fetch = fetched(page, osm, [])
        event, site = reviewer.verify(lead, cat, DAY, fetch=fetch)
        self.assertEqual(event["event"]["artistIds"],
                         ["7weeks", "new-metal-support"])
        self.assertEqual(site["venue"]["geoSource"], OSM)
        self.assertEqual(site["venue"]["geoPrecision"], "named-site-point")
        registry = {"items": {"synthetic": {
            "status": "pending_review", "stableObservations": 2,
            "candidate": lead,
        }}}
        proposed, report = official_recheck.process(
            registry, cat, ledger, DAY, site_fetch=fetch)
        self.assertEqual(len(report["newApprovals"]), 1)
        self.assertEqual(len(report["newSiteApprovals"]), 1)
        self.assertEqual(ledger["approvals"], [])
        reference = json.loads(publisher.REFERENCE.read_text(encoding="utf-8"))
        result = gate.validate_proposal(
            ledger, proposed, reference, copy.deepcopy(reference),
            DAY, publisher.merge)
        self.assertTrue(result["validatedByPublisher"])
        self.assertEqual(result["publishableEvents"], 1)

    def test_wrong_venue_date_genre_artist_or_status_rejected_before_map_lookup(self):
        lead, _, cat, osm = fixture()
        bad = (
            microdata(date="2027-05-18"),
            microdata(genre="Hardcore Techno"),
            microdata(venue="Different Site"),
            microdata(artists=("OTHER BAND", "NEW METAL SUPPORT")),
            microdata(status="https://schema.org/EventCancelled"),
            microdata(canonical="https://untrusted.example/show/"),
            microdata(hidden=True),
            microdata(artists=()),
        )
        for page in bad:
            with self.subTest(page=page[:90]):
                calls = []
                with self.assertRaises(ValueError):
                    reviewer.verify(lead, cat, DAY,
                                    fetch=fetched(page, osm, calls))
                self.assertEqual(calls, [EVENT])

    def test_unrelated_cards_cannot_donate_missing_genre_or_date(self):
        lead, _, cat, osm = fixture()
        unrelated = microdata(
            title="OTHER ACT", artists=("OTHER ACT",),
            canonical="https://7weeks.fr/concerts/unrelated-2027/")
        cases = (
            microdata(genre="Jazz", extra=unrelated),
            microdata(date="2027-05-18", extra=unrelated),
            microdata(artists=("OTHER BAND",), extra=unrelated),
        )
        for page in cases:
            with self.subTest(n=len(page)):
                calls = []
                with self.assertRaises(ValueError):
                    reviewer.verify(lead, cat, DAY,
                                    fetch=fetched(page, osm, calls))
                self.assertEqual(calls, [EVENT])

    def test_unique_microdata_concert_and_unrelated_carousel_is_accepted(self):
        lead, _, cat, osm = fixture()
        unrelated = microdata(
            title="OTHER ACT", artists=("OTHER ACT",),
            canonical="https://7weeks.fr/concerts/unrelated-2027/")
        event, site = reviewer.verify(
            lead, cat, DAY, fetch=fetched(microdata(extra=unrelated), osm, []))
        self.assertEqual(event["event"]["artistIds"],
                         ["7weeks", "new-metal-support"])
        self.assertEqual(site["venue"]["geoSource"], OSM)

    def test_ambiguous_two_matching_cards_never_publish(self):
        lead, _, cat, osm = fixture()
        page = microdata(extra=microdata(genre="Punk"))
        with self.assertRaisesRegex(ValueError, "one unambiguous"):
            reviewer.verify(lead, cat, DAY, fetch=fetched(page, osm, []))

    def test_bad_jsonld_cannot_be_masked_by_separate_good_microdata(self):
        lead, raw, cat, osm = fixture()
        raw["genre"] = ["Jazz"]
        bad_schema = ('<script type="application/ld+json">'
                      + json.dumps(raw, ensure_ascii=False) + '</script>')
        with self.assertRaises(ValueError):
            reviewer.verify(lead, cat, DAY,
                            fetch=fetched(bad_schema + microdata(), osm, []))

    def test_hidden_template_script_and_untyped_lineup_cannot_grant_authority(self):
        pages = (
            '<template>' + microdata() + '</template>',
            '<script>' + microdata() + '</script>',
            microdata(artists=()).replace(
                '</article>', '<footer>7WEEKS + NEW METAL SUPPORT</footer>'
                '</article>'),
        )
        lead, _, cat, osm = fixture()
        for page in pages:
            with self.subTest(page=page[:30]):
                self.assertEqual(event_site_microdata.read_microdata_events(
                    page), [] if page.startswith("<template>") or page.startswith("<script>") else
                    event_site_microdata.read_microdata_events(page))
                with self.assertRaises(ValueError):
                    reviewer.verify(lead, cat, DAY,
                                    fetch=fetched(page, osm, []))


if __name__ == "__main__":
    unittest.main()
