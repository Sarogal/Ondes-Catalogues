"""Fresh, exact same concert on two domains; no publisher authority."""
from __future__ import annotations

import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import source_cross_domain_live_recheck as live
import source_cross_domain_corroboration as source

DAY = dt.date(2026, 11, 21)
DATE = "2027-05-03"
CITY = "Tours"
VENUE = "Le Club Inconnu"
ARTIST = "METAL NOUVEAU"


def html(url, *, date=DATE, city=CITY, venue=VENUE,
         artist=ARTIST, band_count=1, genre="Thrash Metal",
         cancelled=False, canonical=True, extra=None):
    bill = [{"@type": "MusicGroup",
             "name": artist if i == 0 else f"JAZZ SUPPORT {i}",
             "genre": genre if i == band_count - 1 else "Jazz"}
            for i in range(band_count)]
    if band_count > 1:
        bill[0]["genre"] = "Jazz"
    if band_count == 1:
        bill[0]["genre"] = genre
    event = {"@type": "MusicEvent", "name": artist + " live",
             "startDate": date + "T20:00:00+02:00",
             "performer": bill, "location": {
                 "@type": "Place", "name": venue,
                 "address": {"@type": "PostalAddress",
                             "addressLocality": city,
                             "addressCountry": "FR"}}}
    if cancelled:
        event["eventStatus"] = "EventCancelled"
    if canonical:
        event["url"] = url
    nodes = [event] + ([extra] if extra else [])
    return ('<html><head><script type="application/ld+json">'
            + json.dumps(nodes, ensure_ascii=False)
            + '</script></head><body><main>Programme</main></body></html>')


def report(*, date=DATE, city=CITY, venue="club inconnu", second_domain="new-venue.fr",
           second_stable=True):
    urls = ["https://new-artist.fr/concerts/metal/",
            f"https://{second_domain}/agenda/metal-show/"]
    return {"schema": source.SCHEMA,
            "automaticTrustGranted": False,
            "publicationAllowed": False,
            "groups": [{
                "date": date, "city": city, "leadArtist": "metal nouveau",
                "normalizedVenue": venue,
                "reviewState": "cross_domain_stable_observation_needs_live_proof",
                "distinctDomainHints": 2, "sources": [
                    {"eventUrl": urls[0], "host": "new-artist.fr",
                     "independentDomainHint": "new-artist.fr",
                     "stableOnDistinctDays": True},
                    {"eventUrl": urls[1], "host": second_domain,
                     "independentDomainHint": second_domain,
                     "stableOnDistinctDays": second_stable},
                ],
            }]}


class LiveCrossDomainTests(unittest.TestCase):
    def test_unknown_artist_venue_and_promoter_have_live_matching_proof(self):
        q = report()
        saved = copy.deepcopy(q)
        calls = []
        def fetch(url, cache):
            calls.append(url)
            return html(url)
        result = live.build(q, DAY, slot=2, fetch=fetch)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["eligibleCrossDomainGroups"], 1)
        self.assertEqual(result["examinedGroups"], 1)
        self.assertEqual(result["stateCounts"],
                         {"fresh_cross_domain_event_confirmed": 1})
        row = result["checks"][0]
        self.assertEqual(row["freshIndividualEventWitnesses"], 2)
        self.assertEqual(
            [w["host"] for w in row["verifiedWitnesses"]],
            ["new-artist.fr", "new-venue.fr"])
        self.assertTrue(row["crossDomainEventVerified"])
        self.assertFalse(row["sourceOwnershipVerified"])
        self.assertFalse(row["publisherAuthorityGranted"])
        self.assertFalse(row["publicationAllowed"])
        self.assertEqual(q, saved)

    def test_mixed_style_bill_accepts_a_single_metal_band_at_position_40(self):
        q = report()
        result = live.build(q, DAY, slot=2,
            fetch=lambda url, cache: html(
                url, artist=ARTIST, band_count=41))
        self.assertTrue(result["checks"][0]["crossDomainEventVerified"])

    def test_first_party_schema_microdata_is_generic_fallback(self):
        q = report()
        def microdata(url):
            return ('<html><body><main>'
                    '<section itemscope itemtype="https://schema.org/MusicEvent">'
                    '<meta itemprop="url" content="' + url + '"/>'
                    '<span itemprop="name">METAL NOUVEAU live</span>'
                    '<time itemprop="startDate" datetime="2027-05-03T20:00:00+02:00">03 Mai</time>'
                    '<div itemprop="performer" itemscope itemtype="https://schema.org/MusicGroup">'
                    '<span itemprop="name">METAL NOUVEAU</span>'
                    '<span itemprop="genre">Thrash Metal</span></div>'
                    '<div itemprop="location" itemscope itemtype="https://schema.org/Place">'
                    '<span itemprop="name">Le Club Inconnu</span>'
                    '<div itemprop="address" itemscope itemtype="https://schema.org/PostalAddress">'
                    '<span itemprop="addressLocality">Tours</span>'
                    '<span itemprop="addressCountry">FR</span></div></div>'
                    '</section></main></body></html>')
        result = live.build(q, DAY, slot=2,
                            fetch=lambda url, cache: microdata(url))
        self.assertTrue(result["checks"][0]["crossDomainEventVerified"])
        self.assertFalse(result["publicationAllowed"])

    def test_neither_fresh_page_may_borrow_a_second_events_bands(self):
        q = report()
        wrong_event = {"@type": "MusicEvent", "name": "Other",
                       "startDate": DATE, "performer": [
                           {"@type": "MusicGroup", "name": "other"}]}
        page = html("https://new-artist.fr/concerts/metal/",
                    extra=wrong_event)
        result = live.build(q, DAY, slot=2,
            fetch=lambda url, cache: (
                page if "new-artist.fr" in url else html(url)))
        self.assertTrue(result["checks"][0]["crossDomainEventVerified"])
        # If a second fully matching Event appears, ambiguity blocks witness.
        duplicated = html("https://new-artist.fr/concerts/metal/",
                          extra=json.loads(page.split(
                              '<script type="application/ld+json">')[1]
                              .split("</script>")[0])[0])
        result = live.build(q, DAY, slot=2,
            fetch=lambda url, cache: (
                duplicated if "new-artist.fr" in url else html(url)))
        self.assertFalse(result["checks"][0]["crossDomainEventVerified"])

    def test_wrong_date_city_site_artist_no_genre_and_cancellation_fail(self):
        for changed in (
            {"date": "2027-05-04"},
            {"city": "Paris"}, {"venue": "Autre Salle"},
            {"artist": "Faux Groupe"}, {"genre": "Jazz"},
            {"cancelled": True},
        ):
            with self.subTest(changed=changed):
                result = live.build(
                    report(), DAY, slot=2,
                    fetch=lambda url, cache: (
                        html(url, **changed) if "new-venue.fr" in url
                        else html(url, genre="Jazz")))
                self.assertFalse(result["checks"][0]["crossDomainEventVerified"])

    def test_single_unavailable_host_does_not_abort_other_witness(self):
        q = report()
        def fetch(url, cache):
            if "new-artist.fr" in url:
                raise ValueError("robots denied")
            return html(url)
        out = live.build(q, DAY, slot=2, fetch=fetch)
        self.assertEqual(out["checks"][0]["freshIndividualEventWitnesses"], 1)
        self.assertFalse(out["checks"][0]["crossDomainEventVerified"])

    def test_two_subdomains_of_one_owner_cannot_be_independent(self):
        q = report(second_domain="tickets.new-artist.fr")
        q["groups"][0]["sources"][1]["independentDomainHint"] = "new-artist.fr"
        result = live.build(q, DAY, slot=2, fetch=lambda url, cache: html(url))
        self.assertEqual(result["checks"][0]["freshIndividualEventWitnesses"], 2)
        self.assertFalse(result["checks"][0]["crossDomainEventVerified"])

    def test_wrong_site_source_and_unstable_observation_fail(self):
        q = report(second_stable=False)
        result = live.build(q, DAY, slot=2, fetch=lambda url, cache: html(url))
        self.assertFalse(result["checks"][0]["crossDomainEventVerified"])
        q = report()
        q["groups"][0]["sources"][1]["eventUrl"] = "https://evil.example.org/"
        result = live.build(q, DAY, slot=2, fetch=lambda url, cache: html(url))
        self.assertFalse(result["checks"][0]["crossDomainEventVerified"])

    def test_festival_ambiguous_unqualified_and_no_queue(self):
        for state in ("conflicting_venue_identity",
                      "cross_domain_observation_needs_second_day"):
            q = report()
            q["groups"][0]["reviewState"] = state
            out = live.build(q, DAY, slot=2, fetch=lambda *_:
                             self.fail("No fetch for excluded items"))
            self.assertEqual(out["examinedGroups"], 0)
        for bad in ({}, {**report(), "automaticTrustGranted": True},
                    {**report(), "publicationAllowed": True}):
            with self.assertRaises(ValueError):
                live.build(bad, DAY)

    def test_no_arbitrary_limit_on_fresh_source_domains(self):
        q = report()
        for i in range(9):
            name = f"new-festival-promo-{i}.fr"
            q["groups"][0]["sources"].append({
                "eventUrl": f"https://{name}/agenda/metal/",
                "host": name, "independentDomainHint": name,
                "stableOnDistinctDays": True,
            })
        all_seen = set()
        for n in range(5):
            cache = []
            def fetch(url, _cache):
                cache.append(url)
                return html(url)
            live.build(q, DAY + dt.timedelta(days=n), slot=2, fetch=fetch)
            all_seen.update(cache)
        self.assertEqual(len(all_seen), 11)


if __name__ == "__main__":
    unittest.main()
