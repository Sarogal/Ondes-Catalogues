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

    def test_generic_event_cannot_be_accepted_by_first_discovery_alone(self):
        # Opt-in to generic Event is limited to independent diagnostics:
        # the RSS first-pass discovery policy still requires MusicEvent.
        generic = html_for(**{"@type": "Event"})
        self.assertIsNone(evaluate(page=generic))
        row = bridge.candidate_from_event_page(
            LEAD, generic, EVENT_URL, SOURCE, set(), TODAY,
            read_ld=discover.read_ld,
            venue_candidate=discover.venue_candidate,
            norm=discover.norm, allow_generic_event=True)
        self.assertIsNotNone(row)
        self.assertEqual(row["discoveryBridge"],
                         "independent-generic-event-genre-v1")
        self.assertFalse(row["publicationAllowed"])
        self.assertNotIn("officialDetailFound", row)

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

    def test_large_named_bills_are_not_rejected_by_artist_count(self):
        # A real concert announcement can list more than 40 bands.
        # Every name is explicitly first-party and individually typed.
        # No threshold based solely on the number of new bands is allowed.
        performers = [
            {"@type": "MusicGroup", "name": f"Artiste confirmé {i:02d}"}
            for i in range(52)
        ]
        self.assertEqual(
            bridge.official_named_bill(performers),
            ([p["name"] for p in performers], None),
        )
        result = evaluate(page=html_for(performer=performers))
        self.assertIsNotNone(result)
        self.assertEqual(len(result["leadArtist"].split(" + ")), 52)
        self.assertFalse(result["publicationAllowed"])

    def test_large_bill_still_rejects_duplicate_and_invalid_artist(self):
        valid = [
            {"@type": "MusicGroup", "name": f"Groupe {i:02d}"}
            for i in range(52)
        ]
        for malicious in (
            valid + [valid[0]],
            valid + [{"@type": "Event", "name": "Not a performer"}],
            valid + [{"@type": "MusicGroup", "name": "Surprise"}],
        ):
            with self.subTest(last=malicious[-1]):
                self.assertIsNone(bridge.official_named_bill(malicious))
                self.assertIsNone(evaluate(page=html_for(performer=malicious)))

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

    def test_fair_global_budget_rotates_across_all_official_venues(self):
        queue = []
        for i in range(18):
            base = f"https://venue{i:02d}.example/agenda/"
            source = {"name": f"Venue {i:02d}", "url": base}
            leads = [{**LEAD, "sourceUrl":
                      f"https://venue{i:02d}.example/concerts/date-2027/"}]
            queue.append((source, base, leads, {}))
        first = bridge.select_venue_probes(queue, TODAY, 0)
        second = bridge.select_venue_probes(queue, TODAY, 1)
        self.assertEqual(len(first), 12)
        self.assertEqual(len(second), 12)
        self.assertEqual(len({id(row[2]) for row in first}), 12)
        # No venue remains permanently at the tail of the input list.
        self.assertEqual(len({row[1] for row in first + second}), 18)
        self.assertTrue(all(bridge.official_event_url(row[3]["sourceUrl"],
                                                        row[1])
                            for row in first + second))

    def test_consecutive_slots_and_days_advance_over_long_rss_feed(self):
        base = SOURCE["url"]
        leads = [{**LEAD, "sourceUrl":
                  f"https://venue.example/concerts/old-date-{i:02d}/"}
                 for i in range(17)]
        checked = []
        for n in range(3):
            day = TODAY + dt.timedelta(days=n)
            for slot in (0, 1, 2):
                selected = bridge.select_leads(leads, base, day, slot, limit=2)
                checked.extend(item["sourceUrl"] for item in selected)
        # Nine cycles * two links should cover all 17 distinct items.
        self.assertEqual(len(set(checked)), 17)
        self.assertEqual(len(checked), 18)

    def test_full_scan_fair_rss_allocation_preserves_undated_leads(self):
        import re
        sources = []
        for i in range(18):
            sources.append({
                "name": f"Venue {i:02d}", "city": "Nîmes",
                "department": "30", "priority": "P1",
                "url": f"https://venue{i:02d}.example/agenda/",
            })
        fetched_details = []
        def download(url, **kwargs):
            match = re.search(r"venue([0-9]{2})[.]example", url)
            self.assertIsNotNone(match)
            index = match.group(1)
            official = f"https://venue{index}.example/concerts/show-2027/"
            if url.endswith("/agenda/"):
                return "<html><body>Agenda</body></html>", url
            if url.endswith("/feed/"):
                return (f"<rss><channel><item><title>Annonce {index}</title>"
                        f"<link>{official}</link></item></channel></rss>"), url
            if url == official:
                fetched_details.append(index)
                event = {
                    "@type": "MusicEvent", "name": f"Metal Band {index}",
                    "url": official, "startDate": "2027-03-11",
                    "genre": ["Death Metal"],
                    "performer": {"@type": "MusicGroup",
                                  "name": f"Metal Band {index}"},
                    "location": {"name": f"Venue {index}",
                                 "address": {"addressLocality": "Nîmes",
                                             "addressCountry": "FR"}},
                }
                return ('<script type="application/ld+json">' +
                        json.dumps(event) + '</script>'), url
            raise AssertionError("Unexpected URL: " + url)
        def feeds_for(html, final, same_host):
            return {"ics": [], "rss": [final.replace("/agenda/", "/feed/")]}
        venue_sets = []
        for slot in (0, 1):
            fetched_details.clear()
            infos = []
            with patch.object(discover, "download", side_effect=download), \
                 patch.object(discover, "robots_allow", return_value=True), \
                 patch.object(discover.feeds, "feed_links",
                              side_effect=feeds_for):
                rows = discover.scan_venues(
                    {"venues": sources}, set(), TODAY, infos, scan_slot=slot)
            self.assertEqual(len(fetched_details), 12)
            self.assertEqual(len({x for x in fetched_details}), 12)
            self.assertEqual(len([x for x in rows if x["date"] is None]), 18)
            self.assertEqual(len([x for x in rows if x["date"] is not None]), 12)
            self.assertEqual(sum(i["rssStructured"]["attempted"]
                                 for i in infos), 12)
            self.assertEqual(sum(i["rssStructured"]["dated"]
                                 for i in infos), 12)
            self.assertTrue(all(x["publicationAllowed"] is False for x in rows))
            venue_sets.append(set(fetched_details))
        self.assertEqual(len(venue_sets[0] | venue_sets[1]), 18)

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
