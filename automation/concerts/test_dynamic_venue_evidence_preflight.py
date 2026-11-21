"""Offline tests: independent nationwide venue evidence never grants publisher trust."""
from __future__ import annotations

import copy
import datetime as dt
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dynamic_venue_evidence_preflight as module

TODAY = dt.date(2026, 11, 20)
EVENT_DATE = "2027-02-13"
BASE = "https://synthetic-venue.example/agenda/"
EVENT = "https://synthetic-venue.example/evenements/groupe-invente-2027/"
OSM = "https://www.openstreetmap.org/node/812345671"
OSM_API = "https://api.openstreetmap.org/api/0.6/node/812345671.json"
VENUE = {
    "id": "imaginary-stage", "name": "Espace Imaginaire",
    "city": "Nîmes", "department": "30",
    "latitude": 43.835, "longitude": 4.361,
    "address": "1 rue des Tests", "postalCode": "30000",
}
SOURCES = {"schema": module.SOURCES, "venues": [{
    "name": VENUE["name"], "city": VENUE["city"],
    "department": VENUE["department"], "url": BASE,
}]}
CAT = {"schemaVersion": 1, "mode": "preview-public-unlisted",
       "venues": [VENUE], "artists": [], "events": []}
APPROVED = {"schema": module.APPROVALS, "approvals": []}
EVENT_OBJ = {
    "@type": "MusicEvent", "url": EVENT,
    "name": "Groupe Inventé + Second Act",
    "startDate": EVENT_DATE + "T21:00:00+01:00",
    "genre": ["Death Metal"],
    "performer": [
        {"@type": "MusicGroup", "name": "Groupe Inventé"},
        {"@type": "MusicGroup", "name": "Second Act"},
    ],
    "location": {
        "@type": "Place", "name": VENUE["name"], "sameAs": OSM,
        "address": {
            "@type": "PostalAddress", "streetAddress": "1 rue des Tests",
            "postalCode": "30000", "addressLocality": VENUE["city"],
            "addressRegion": "Occitanie", "addressCountry": "FR",
        },
    },
}
OSM_OBJECT = {"elements": [{
    "id": 812345671, "type": "node",
    "lat": VENUE["latitude"], "lon": VENUE["longitude"],
    "tags": {
        "name": VENUE["name"], "addr:city": VENUE["city"],
        "addr:postcode": "30000", "addr:country": "FR",
    },
}]}


def candidate(**kwargs):
    c = {
        "candidateId": "synthetic:independent-evidence-1",
        "source": "agenda_officiel_structuré",
        "sourceUrl": EVENT, "sourcePage": BASE,
        "date": EVENT_DATE, "name": EVENT_OBJ["name"],
        "leadArtist": EVENT_OBJ["name"],
        "venue": VENUE["name"], "city": VENUE["city"],
        "department": VENUE["department"],
        "classification": [], "reviewBucket": "genre_unknown",
        "reviewRequired": True, "publicationAllowed": False,
        "possibleExistingConcert": False,
    }
    c.update(kwargs)
    return c


def registry(rows=None):
    rows = rows or [candidate()]
    return {"schema": module.INTAKE,
            "items": {str(i): {
                "candidate": row,
                "status": "pending_review", "stableObservations": 2,
            } for i, row in enumerate(rows)}}


def page(event=None):
    return ('<html><script type="application/ld+json">'
            + json.dumps(event if event is not None else EVENT_OBJ)
            + '</script></html>')


def run(reg=None, src=None, cat=None, approved=None, event=None,
        osm=None, redirect=False, limit=8, slot=2, robots=None):
    calls = []
    def fetch(url, **kwargs):
        calls.append(("official", url))
        if url != EVENT:
            raise AssertionError("Unexpected official host")
        return page(event), "https://untrusted.example/redirect/" if redirect else url
    def geo_fetch(url, cap):
        calls.append(("osm", url))
        if url != OSM_API:
            raise AssertionError("Unexpected geo URL")
        return json.dumps(OSM_OBJECT if osm is None else osm), url
    result = module.build(
        reg if reg is not None else registry(),
        src if src is not None else SOURCES,
        cat if cat is not None else CAT,
        approved if approved is not None else APPROVED,
        TODAY, fetch=fetch, robots=robots or (lambda url, cache: True),
        geo_fetch=geo_fetch, scan_slot=slot, limit=limit)
    return result, calls


class NationwideVenueAdmissionPreviewTests(unittest.TestCase):

    def test_unknown_osm_source_rechecks_new_venue_and_eight_unknown_bands_privately(self):
        """An unlisted announcing domain may research an entirely new venue."""
        source_home = "https://nouvelle-origine.fr/"
        event_url = "https://nouvelle-origine.fr/agenda/nuit-metal-2027/"
        new_place_osm = "https://www.openstreetmap.org/node/901234567"
        bands = ["Groupe Inventé " + str(i) for i in range(1, 9)]
        old_source = copy.deepcopy(VENUE)
        old_source["geoSource"] = OSM
        old_source["postalCode"] = "30000"
        catalogue = dict(copy.deepcopy(CAT), venues=[old_source])
        event = copy.deepcopy(EVENT_OBJ)
        event.update({
            "url": event_url, "name": "Nuit métal indépendante",
            "performer": [{"@type": "MusicGroup", "name": n} for n in bands],
            "location": {
                "@type": "Place", "name": "Place Libre",
                "sameAs": new_place_osm,
                "address": {
                    "@type": "PostalAddress", "streetAddress": "Place Libre",
                    "postalCode": "37000", "addressLocality": "Tours",
                    "addressRegion": "Centre-Val de Loire",
                    "addressCountry": "FR",
                },
            },
        })
        lead = candidate(
            candidateId="unlisted-offsite-eight-bands",
            sourceUrl=event_url, sourcePage=event_url,
            eventDetailUrl=event_url, name=event["name"],
            leadArtist=bands[0], officialArtistNames=bands,
            venue="Place Libre", city="Tours", department="37",
            newlyDiscoveredFirstPartySource=True,
            sourceAuthorityVerified=False,
            sourceVenueName=old_source["name"],
            sourceVenueCity=old_source["city"],
            sourceVenueDepartment=old_source["department"],
            venueOutsideSource=True, venueCatalogueId=None,
        )
        osm_origin = (
            '<osm><node id="812345671" lat="43.835" lon="4.361">'
            '<tag k="name" v="Espace Imaginaire"/>'
            '<tag k="addr:city" v="Nîmes"/>'
            '<tag k="addr:postcode" v="30000"/>'
            '<tag k="website" v="' + source_home + '"/>'
            '</node></osm>'
        )
        new_osm_data = {"elements": [{
            "id": 901234567, "type": "node",
            "lat": 47.395, "lon": 0.688,
            "tags": {
                "name": "Place Libre", "addr:city": "Tours",
                "addr:postcode": "37000", "addr:country": "FR",
            },
        }]}
        origin_url = "https://api.openstreetmap.org/api/0.6/node/812345671"
        new_site_api = "https://api.openstreetmap.org/api/0.6/node/901234567.json"
        calls = []
        def secure_fetch(url, cache):
            calls.append(url)
            if url == origin_url:
                return osm_origin
            if url == event_url:
                return page(event)
            if url == new_site_api:
                return json.dumps(new_osm_data)
            raise AssertionError("Unexpected external request: " + url)
        def no_insecure_fetch(*_args, **_kwargs):
            raise AssertionError("An unknown source cannot use the legacy fetch")
        def check(lead_row=lead, safe=secure_fetch):
            return module.build(
                registry([lead_row]),
                {"schema": module.SOURCES, "venues": []},
                catalogue, APPROVED, TODAY,
                fetch=no_insecure_fetch, robots=no_insecure_fetch,
                origin_fetch=safe, scan_slot=2, limit=8)
        output = check()
        self.assertEqual(output["newVenueCandidates"], 1)
        self.assertEqual(output["newSitesIndependentlyLocatedPrivateOnly"], 1)
        self.assertEqual(output["independentNamedGeoVerified"], 1)
        self.assertTrue(output["results"][0]["newSourceResearchedWithoutManifest"])
        self.assertEqual(
            output["results"][0]["proposedSite"]["name"], "Place Libre")
        self.assertFalse(output["results"][0]["proposedSite"]["publicationAllowed"])
        self.assertFalse(output["publisherTrustGranted"])
        self.assertEqual(output["approvalsProposed"], 0)
        self.assertEqual(calls, [origin_url, event_url, new_site_api])

        # Unknown source label alone is never sufficient. Provenance from OSM
        # is fresh, individually checked and its same-host link is mandatory.
        for change in (
            {"sourceUrl": "https://faux-domaine.fr/concert/",
             "sourcePage": "https://faux-domaine.fr/concert/",
             "eventDetailUrl": "https://faux-domaine.fr/concert/"},
            {"venueCatalogueId": old_source["id"]},
            {"sourceVenueCity": "Paris"},
            {"officialArtistNames": bands[:-1]},
            {"newlyDiscoveredFirstPartySource": False},
        ):
            with self.subTest(change=change):
                calls.clear()
                changed = dict(lead, **change)
                result = check(changed)
                self.assertEqual(
                    result["newSitesIndependentlyLocatedPrivateOnly"], 0)
                self.assertEqual(result["approvalsProposed"], 0)
                self.assertFalse(result["publisherTrustGranted"])

    def test_unknown_to_fixed_spec_venue_verified_but_not_promoted(self):
        before = copy.deepcopy((registry(), SOURCES, CAT, APPROVED))
        out, calls = run()
        self.assertEqual(out["eligible"], 1)
        self.assertEqual(out["fullyCorrelatedPrivateOnly"], 1)
        self.assertEqual(out["officialEventEvidenceVerified"], 1)
        self.assertEqual(out["independentNamedGeoVerified"], 1)
        self.assertEqual(calls, [("official", EVENT), ("osm", OSM_API)])
        self.assertFalse(out["publicationAllowed"])
        self.assertFalse(out["publisherTrustGranted"])
        self.assertEqual(out["approvalsProposed"], 0)
        self.assertNotIn("reviewDecision", str(out))
        self.assertEqual(before, (registry(), SOURCES, CAT, APPROVED))

    def test_source_in_registry_does_not_grant_trust(self):
        for change in (
            {"sourceUrl": "https://untrusted.example/evenements/fake/"},
            {"sourcePage": "https://untrusted.example/agenda/"},
            {"venue": "Une salle inconnue"},
            {"city": "Toulouse"},
            {"department": "31"},
        ):
            with self.subTest(change=change):
                out, calls = run(reg=registry([candidate(**change)]))
                self.assertEqual(out["fullyCorrelatedPrivateOnly"], 0)
                self.assertEqual(calls, [])

    def test_event_redirection_prevents_geo_fetch(self):
        out, calls = run(redirect=True)
        self.assertEqual(out["fullyCorrelatedPrivateOnly"], 0)
        self.assertEqual(calls, [("official", EVENT)])

    def test_independent_osm_must_match_exact_named_city_and_postcode(self):
        for key, value in (("name", "Other Theatre"),
                           ("addr:city", "Bordeaux"),
                           ("addr:postcode", "33000")):
            with self.subTest(key=key):
                osm = copy.deepcopy(OSM_OBJECT)
                osm["elements"][0]["tags"][key] = value
                out, calls = run(osm=osm)
                self.assertEqual(out["fullyCorrelatedPrivateOnly"], 0)
                self.assertEqual(len(calls), 2)

    def test_public_geo_mismatch_is_not_admitted(self):
        cat = copy.deepcopy(CAT)
        cat["venues"][0]["latitude"] = 44.0
        out, calls = run(cat=cat)
        self.assertEqual(out["fullyCorrelatedPrivateOnly"], 0)
        self.assertEqual(out["reasonCounts"]["public_site_coordinate_conflict"], 1)
        self.assertEqual(out["independentNamedGeoVerified"], 1)

    def test_missing_public_geo_is_review_not_trust(self):
        cat = copy.deepcopy(CAT)
        del cat["venues"][0]["latitude"]
        out, _ = run(cat=cat)
        self.assertEqual(out["reasonCounts"]["public_site_coordinate_missing"], 1)
        self.assertEqual(out["fullyCorrelatedPrivateOnly"], 0)

    def test_false_genre_unrelated_performer_and_absent_geo_block(self):
        bad = [
            {"genre": ["Hardcore Techno"]},
            {"performer": [{"@type": "MusicGroup", "name": "Wrong Group"}]},
            {"startDate": "2027-02-14"},
            {"location": {**EVENT_OBJ["location"], "sameAs": None,
                          "address": {"addressLocality": "Nîmes"}}},
        ]
        for modifications in bad:
            with self.subTest(case=str(modifications)[:80]):
                event = copy.deepcopy(EVENT_OBJ)
                event.update(modifications)
                out, calls = run(event=event)
                self.assertEqual(out["fullyCorrelatedPrivateOnly"], 0)
                self.assertEqual(calls, [("official", EVENT)])

    def test_robots_denial_sends_no_requests(self):
        out, calls = run(robots=lambda url, cache: False)
        self.assertEqual(calls, [])
        self.assertEqual(out["reasonCounts"]["official_page_robots_disallowed"], 1)

    def test_old_show_and_single_observation_never_checked(self):
        reg = registry([candidate(date="2025-01-02")])
        r, calls = run(reg=reg)
        self.assertEqual(r["eligible"], 0)
        self.assertEqual(calls, [])
        reg = registry()
        reg["items"]["0"]["stableObservations"] = 1
        r, calls = run(reg=reg)
        self.assertEqual(r["eligible"], 0)
        self.assertEqual(calls, [])

    def test_published_exact_url_date_never_reverified(self):
        cat = copy.deepcopy(CAT)
        cat["events"] = [{"officialUrl": EVENT, "date": EVENT_DATE}]
        r, calls = run(cat=cat)
        self.assertEqual(r["eligible"], 0)
        self.assertEqual(calls, [])

    def test_three_slots_disjoint_and_large_queue_eventually_covered(self):
        xs = [candidate(candidateId=f"lead-{i:03d}",
                        sourceUrl=f"https://synthetic-venue.example/evenements/lead-{i:03d}/")
              for i in range(49)]
        first = []
        for slot in (0, 1, 2):
            sel = module._select(xs, TODAY, slot, 8)
            self.assertLessEqual(len(sel), 8)
            first.extend(x["candidateId"] for x in sel)
        self.assertEqual(len(first), 24)
        self.assertEqual(len(set(first)), 24)
        union = set(first)
        for later in (1, 2):
            for slot in (0, 1, 2):
                union.update(x["candidateId"] for x in module._select(
                    xs, TODAY + dt.timedelta(days=later), slot, 8))
        self.assertEqual(len(union), 49)

    def test_unsupported_budget_and_slot_fail_closed(self):
        for val in (-1, 0, 13, True, "8"):
            with self.subTest(budget=val), self.assertRaises(ValueError):
                module._select([], TODAY, 1, val)
        for slot in (-1, 3, True, "0"):
            with self.subTest(slot=slot), self.assertRaises(ValueError):
                module._select([], TODAY, slot, 8)


if __name__ == "__main__":
    unittest.main()
