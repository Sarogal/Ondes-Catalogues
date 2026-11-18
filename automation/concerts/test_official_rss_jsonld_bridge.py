"""Offline tests for the reusable RSS-linked first-party MusicEvent bridge."""
from __future__ import annotations

import datetime as dt
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discover
import official_rss_jsonld_bridge as bridge
import triage

TODAY = dt.date(2026, 11, 18)
SOURCE = {
    "name": "La Salle Fictive", "city": "Nîmes", "department": "30",
    "url": "https://venue.example/agenda/", "priority": "P1",
}
EVENT_URL = "https://venue.example/concerts/groupe-metal-2027/"
RSS = "https://venue.example/feed/"
LEAD = {
    "candidateId": "rss:unit-test", "source": "actualite_rss_non_datee",
    "sourceUrl": EVENT_URL, "date": None,
    "name": "Le groupe arrive bientôt", "leadArtist": "",
    "venue": SOURCE["name"], "city": SOURCE["city"],
    "department": "30", "publicationAllowed": False, "reviewRequired": True,
}


def html_for(**overrides):
    event = {
        "@type": "MusicEvent", "name": "Groupe Metal + Première Partie",
        "startDate": "2027-02-10T20:30:00+01:00",
        "url": EVENT_URL, "genre": ["Death Metal", "Grindcore"],
        "performer": [
            {"@type": "MusicGroup", "name": "Groupe Metal"},
            {"@type": "MusicGroup", "name": "Nouvelle Première Partie"}
        ],
        "location": {
            "@type": "MusicVenue", "name": SOURCE["name"],
            "address": {"addressLocality": SOURCE["city"],
                        "addressCountry": "FR"},
        },
    }
    event.update(overrides)
    return '<html><script type="application/ld+json">' + json.dumps(
        event, ensure_ascii=False) + '</script></html>'


def evaluate(lead=None, page=None, actual=None):
    return bridge.candidate_from_event_page(
        lead or LEAD, page if page is not None else html_for(),
        actual or EVENT_URL, SOURCE, set(), TODAY,
        read_ld=discover.read_ld, venue_candidate=discover.venue_candidate,
        norm=discover.norm)


class OfficialRssJsonldBridgeTests(unittest.TestCase):
    def test_dated_first_party_bill_remains_quarantined(self):
        candidate = evaluate()
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["date"], "2027-02-10")
        self.assertEqual(candidate["source"], "agenda_officiel_structuré")
        self.assertEqual(candidate["sourceUrl"], EVENT_URL)
        self.assertEqual(candidate["classification"], ["Death Metal", "Grindcore"])
        self.assertEqual(candidate["discoveryBridge"], "official-rss-music-event-v1")
        self.assertNotIn("officialDetailFound", candidate)
        checked = triage.triage(candidate, catalogue={})
        self.assertEqual(checked["reviewBucket"], "genre_tag_review")
        self.assertIs(checked["publicationAllowed"], False)
        self.assertIs(checked["reviewRequired"], True)

    def test_confirmed_headliner_and_trailing_surprise_guest_are_discoverable(self):
        import copy
        sample = [
            {"@type": "MusicGroup", "name": "Groupe Metal"},
            {"@type": "MusicGroup", "name": "Invité surprise"},
        ]
        self.assertEqual(bridge.official_named_bill(sample),
                         (["Groupe Metal"], "Invité surprise"))
        original = sample[1].copy()
        row = evaluate(page=html_for(performer=sample))
        self.assertIsNotNone(row)
        self.assertEqual(row["leadArtist"], "Groupe Metal")
        self.assertEqual(row["unannouncedSupportLabel"], "Invité surprise")
        self.assertEqual(row["classification"], ["Death Metal", "Grindcore"])
        self.assertFalse(row["publicationAllowed"])
        self.assertTrue(row["reviewRequired"])
        self.assertEqual(sample[1], original)
        reviewed = triage.triage(row, catalogue={})
        self.assertEqual(reviewed["reviewBucket"], "genre_tag_review")
        self.assertFalse(reviewed["publicationAllowed"])

    def test_unannounced_guest_must_be_trailing_and_follow_named_artist(self):
        named = {"@type": "MusicGroup", "name": "Groupe Metal"}
        unnamed = {"@type": "MusicGroup", "name": "Guest"}
        for performers in (
                [unnamed], [unnamed, named], [named, unnamed, named],
                [named, unnamed, unnamed]):
            with self.subTest(performers=performers):
                self.assertIsNone(bridge.official_named_bill(performers))
                self.assertIsNone(evaluate(page=html_for(performer=performers)))
        self.assertEqual(bridge.official_named_bill([named, unnamed]),
                         (["Groupe Metal"], "Guest"))

    def test_actual_band_with_guest_in_its_name_is_not_a_placeholder(self):
        official = [
            {"@type": "MusicGroup", "name": "Guest House Massacre"},
            {"@type": "MusicGroup", "name": "Band of Souls"},
        ]
        self.assertEqual(bridge.official_named_bill(official),
                         (["Guest House Massacre", "Band of Souls"], None))
        row = evaluate(page=html_for(performer=official))
        self.assertIsNotNone(row)
        self.assertEqual(row["leadArtist"],
                         "Guest House Massacre + Band of Souls")
        self.assertNotIn("unannouncedSupportLabel", row)

    def test_feed_date_is_not_used_for_concert_date(self):
        xml = ('<rss><channel><item><title>Groupe annonce une tournée</title>'
               '<pubDate>Wed, 18 Nov 2026 08:00:00 GMT</pubDate>'
               '<link>' + EVENT_URL + '</link></item></channel></rss>')
        import feeds
        original = feeds.rss_candidates(xml, SOURCE, RSS)
        self.assertIsNone(original[0]["date"])
        enriched = evaluate(original[0])
        self.assertEqual(enriched["date"], "2027-02-10")
        self.assertNotEqual(original[0]["candidateId"], enriched["candidateId"])

    def test_foreign_hosts_and_suspicious_urls_are_excluded(self):
        urls = [
            "https://thirdparty.example/concerts/groupe-metal-2027/",
            "http://venue.example/concerts/groupe-metal-2027/",
            "https://user:pass@venue.example/concerts/groupe-metal-2027/",
            "https://venue.example:444/concerts/groupe-metal-2027/",
            "https://venue.example/feed/",
            "https://venue.example/comments/concerts/",
            "https://venue.example/concerts/post.pdf",
            "https://venue.example/concerts/show?tracking=1",
            "https://venue.example/concerts/show#fragment",
            "https://venue.example/agenda",
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertFalse(bridge.official_event_url(url, SOURCE["url"]))
        self.assertIsNone(evaluate({**LEAD, "sourceUrl":
            "https://thirdparty.example/concerts/groupe-metal-2027/"}))

    def test_mismatched_redirect_or_schema_canonical_fails(self):
        self.assertIsNone(evaluate(actual="https://venue.example/concerts/other/"))
        self.assertIsNone(evaluate(page=html_for(
            url="https://venue.example/concerts/other/")))
        self.assertIsNone(evaluate(page=html_for(
            url="https://tickets.example/show/1")))

    def test_cancelled_postponed_foreign_multi_event_fail(self):
        self.assertIsNone(evaluate(page=html_for(
            eventStatus="https://schema.org/EventCancelled")))
        self.assertIsNone(evaluate(page=html_for(
            eventStatus={"@id": "https://schema.org/EventPostponed"})))
        base = json.loads(html_for().split('application/ld+json">')[1].split("</script>")[0])
        base2 = dict(base, name="Autre concert")
        multi = '<script type="application/ld+json">' + json.dumps(
            [base, base2]) + '</script>'
        self.assertIsNone(evaluate(page=multi))
        foreign = dict(base["location"]["address"], addressCountry="BE")
        self.assertIsNone(evaluate(page=html_for(
            location={**base["location"], "address": foreign})))

    def test_no_named_performer_or_other_venue_stays_unqualified(self):
        self.assertIsNone(evaluate(page=html_for(performer=None)))
        self.assertIsNone(evaluate(page=html_for(performer="Groupe Metal")))
        self.assertIsNone(evaluate(page=html_for(performer={
            "@type": "MusicGroup", "name": "Guest"})))
        self.assertIsNone(evaluate(page=html_for(location={
            "name": "Une autre salle", "address": {
                "addressLocality": "Nîmes", "addressCountry": "FR"}})))

    def test_rotation_bounded_without_rss_head_starvation(self):
        leads = [{**LEAD, "sourceUrl":
                  f"https://venue.example/concerts/show-{i}-2027/"}
                 for i in range(17)]
        slots = [bridge.select_leads(
            leads, SOURCE["url"], TODAY, slot, limit=2)
            for slot in (0, 1, 2)]
        self.assertTrue(all(len(s) == 2 for s in slots))
        self.assertEqual(len(set(r["sourceUrl"] for s in slots for r in s)), 6)
        self.assertNotEqual(
            bridge.select_leads(leads, SOURCE["url"], TODAY, 0, limit=2),
            bridge.select_leads(leads, SOURCE["url"],
                                TODAY + dt.timedelta(days=1), 0, limit=2))
        self.assertEqual(bridge.select_leads(
            [{**LEAD, "sourceUrl": "https://evil.invalid/events/show"}],
            SOURCE["url"], TODAY, 0), [])

    def test_full_scan_keeps_undated_rss_and_adds_dated_event(self):
        xml = ('<rss><channel><item><title>Nouvelle date officielle</title>'
               '<link>' + EVENT_URL + '</link></item></channel></rss>')
        fetched = []
        def download(url, **kwargs):
            fetched.append(url)
            if url == SOURCE["url"]:
                return "<html><body>Agenda</body></html>", url
            if url == RSS:
                return xml, url
            if url == EVENT_URL:
                return html_for(), url
            raise AssertionError("Unexpected fetch: " + url)
        report = []
        with patch.object(discover, "download", side_effect=download), \
             patch.object(discover, "robots_allow", return_value=True), \
             patch.object(discover.feeds, "feed_links",
                          return_value={"ics": [], "rss": [RSS]}):
            rows = discover.scan_venues(
                {"venues": [SOURCE]}, set(), TODAY, report, scan_slot=0)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len([c for c in rows if c.get("date") is None]), 1)
        dated = [c for c in rows if c.get("date") == "2027-02-10"]
        self.assertEqual(len(dated), 1)
        self.assertEqual(dated[0]["discoveryBridge"],
                         "official-rss-music-event-v1")
        self.assertIs(dated[0]["publicationAllowed"], False)
        self.assertEqual(report[0]["rssStructured"]["attempted"], 1)
        self.assertEqual(report[0]["rssStructured"]["dated"], 1)
        self.assertEqual(fetched.count(EVENT_URL), 1)


if __name__ == "__main__":
    unittest.main()
