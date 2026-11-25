import json
import datetime as dt
import copy
import unittest
from unittest.mock import patch

from automation.concerts import existing_venue_geo_evidence as evidence

URL = "https://unknown-room.fr/events/metal-night"
OSM = "https://www.openstreetmap.org/node/12345"
VENUE = {"id": "new-room", "name": "New Room", "city": "Colmar",
         "region": "Grand Est", "department": "68",
         "address": "Adresse exacte à vérifier", "postalCode": "À vérifier",
         "latitude": 48.077, "longitude": 7.358,
         "geoPrecision": "centre de commune (position indicative, pas la salle)"}
EVENT = {"id": "event-1", "venueId": "new-room", "sourceType": "salle",
         "officialUrl": URL, "date": "2027-02-12"}


def document(**changes):
    row = {"@type": "MusicEvent", "name": "Metal night", "url": URL,
           "startDate": "2027-02-12T20:00:00+01:00",
           "location": {"@type": "Place", "name": "New Room",
                        "address": {"@type": "PostalAddress",
                                    "streetAddress": "19 rue des Jardins",
                                    "postalCode": "68000",
                                    "addressLocality": "Colmar",
                                    "addressCountry": "FR"}}}
    row.update(changes)
    return '<script type="application/ld+json">' + json.dumps(row) + '</script>'


class ExistingVenueGeoEvidenceTests(unittest.TestCase):
    def test_exact_address_does_not_mutate_original(self):
        site = evidence.extract_address(document(), EVENT, VENUE)
        self.assertEqual(site["address"], "19 rue des Jardins")
        self.assertEqual(site["postalCode"], "68000")
        self.assertEqual(site["id"], VENUE["id"])
        self.assertEqual(VENUE["address"], "Adresse exacte à vérifier")

    def test_rejects_other_event_date_and_domain(self):
        for html in (document(startDate="2027-02-13"),
                     document(url="https://other.fr/events/metal-night"),
                     document() + document()):
            with self.subTest(html=html), self.assertRaises(ValueError):
                evidence.extract_address(html, EVENT, VENUE)

    def test_rejects_other_room_or_address(self):
        for location in (
            {"@type": "Place", "name": "Other Room"},
            {"@type": "Place", "name": "New Room",
             "address": {"@type": "PostalAddress", "streetAddress": "19 rue des Jardins",
                         "postalCode": "68000", "addressLocality": "Paris",
                         "addressCountry": "FR"}},
        ):
            with self.assertRaises(ValueError):
                evidence.extract_address(document(location=location), EVENT, VENUE)

    def test_unknown_venue_uses_independently_attributed_website(self):
        with patch.object(evidence.geo, "verify", return_value=(OSM, 48.08, 7.36, "named-site-point")), \
             patch.object(evidence.official, "official_origin", return_value=None), \
             patch.object(evidence.address_source, "website_from_address",
                          return_value=("https://unknown-room.fr/", OSM)):
            row = evidence.verify(EVENT, VENUE, fetch=lambda url, cache: document())
        self.assertEqual(row["venuePatch"]["geoSource"], OSM)
        self.assertEqual(row["venuePatch"]["address"], "19 rue des Jardins")
        self.assertEqual(row["venueId"], VENUE["id"])
        self.assertFalse(row["publicationAllowed"])
        self.assertFalse(row["publisherAuthorityGranted"])
        self.assertNotIn("reviewDecision", row)

    def test_wrong_domain_or_feature_rejected(self):
        with patch.object(evidence.geo, "verify", return_value=(OSM, 48.08, 7.36, "named-site-point")), \
             patch.object(evidence.official, "official_origin", return_value=None):
            for homepage, feature in (
                ("https://other-room.fr/", OSM),
                ("https://unknown-room.fr/", "https://www.openstreetmap.org/node/12346"),
            ):
                with patch.object(evidence.address_source, "website_from_address",
                                  return_value=(homepage, feature)), self.assertRaises(ValueError):
                    evidence.verify(EVENT, VENUE, fetch=lambda url, cache: document())

    def test_named_building_not_a_municipal_centroid(self):
        venue = dict(VENUE, geoPrecision="centre indicatif du bâtiment nommé New Room")
        self.assertFalse(evidence.eligible(venue))
        with self.assertRaises(ValueError):
            evidence.verify(EVENT, venue, fetch=lambda *args: self.fail("must not fetch"))

    def test_rejects_missing_independent_location(self):
        with patch.object(evidence.geo, "verify", side_effect=ValueError("ambiguous")):
            with self.assertRaises(ValueError):
                evidence.verify(EVENT, VENUE, fetch=lambda url, cache: document())


    def test_reserved_domain_is_rejected_before_network(self):
        bad = dict(EVENT, officialUrl="https://unknown-room.example/events/metal-night")
        with self.assertRaises(ValueError):
            evidence.verify(bad, VENUE, fetch=lambda *args: self.fail("must not fetch"))

    def test_rotation_covers_more_than_one_batch_without_mutating_catalogue(self):
        venues = [dict(VENUE, id=f"room-{i}") for i in range(9)]
        events = [dict(EVENT, id=f"event-{i}", venueId=f"room-{i}",
                       status="confirmed") for i in range(9)]
        data = {"venues": venues, "events": events}
        original = copy.deepcopy(data)
        seen = set()
        def held(event, venue, **kwargs):
            seen.add(venue["id"])
            raise ValueError("no evidence")
        day = dt.date(2026, 11, 25)
        for slot in range(3):
            report = evidence.scan(data, day, slot=slot, verify_one=held)
            self.assertLessEqual(report["examinedVenues"], 4)
            self.assertLessEqual(report["eventPagesExamined"], 8)
            self.assertFalse(report["publicationAllowed"])
            self.assertEqual(report["proposals"], [])
        self.assertEqual(seen, {v["id"] for v in venues})
        self.assertEqual(data, original)

    def test_scan_skips_expired_cancelled_and_precise(self):
        precise = dict(VENUE, id="precise", geoPrecision="named-site-point")
        event = dict(EVENT, status="confirmed")
        data = {"venues": [VENUE, precise], "events": [
            dict(event, id="past", date="2026-01-01"),
            dict(event, id="cancelled", status="cancelled"),
            dict(event, id="accurate", venueId="precise"),
            event]}
        seen = []
        def verify_one(e, v, **kwargs):
            seen.append(e["id"])
            return {"venueId": v["id"], "publicationAllowed": False}
        report = evidence.scan(data, dt.date(2026, 11, 25), verify_one=verify_one)
        self.assertEqual(seen, [EVENT["id"]])
        self.assertEqual(len(report["proposals"]), 1)
        self.assertFalse(report["publisherAuthorityGranted"])

    def test_scan_enforces_budget_and_unique_venue_ids(self):
        day = dt.date(2026, 11, 25)
        for kwargs in ({"limit": 5}, {"per_venue": 3}, {"slot": 3}):
            with self.assertRaises(ValueError):
                evidence.scan({"venues": [], "events": []}, day, **kwargs)
        with self.assertRaises(ValueError):
            evidence.scan({"venues": [VENUE, VENUE], "events": []}, day)


    def test_visible_address_without_jsonld_and_without_street_number(self):
        event = dict(EVENT, title="Metal night")
        for street in ("19 rue des Jardins", "rue des Jardins"):
            html = ("<h1>Metal night</h1><p>12 février 2027</p>"
                    "<h2>Lieu : New Room</h2><address>" + street +
                    "<br>68000 Colmar</address>")
            site = evidence.extract_address(html, event, VENUE)
            self.assertEqual(site["address"], street)
            self.assertEqual(site["postalCode"], "68000")

    def test_visible_address_requires_exact_event_title_date_and_named_room(self):
        event = dict(EVENT, title="Metal night")
        template = "<h1>{title}</h1><p>{day}</p><h2>{room}</h2><p>19 rue des Jardins, 68000 Colmar</p>"
        for title, day, room in (
            ("Other gig", "12 février 2027", "New Room"),
            ("Metal night", "13 février 2027", "New Room"),
            ("Metal night", "12 février 2027", "Other Room"),
        ):
            with self.assertRaises(ValueError):
                evidence.extract_address(template.format(title=title, day=day, room=room), event, VENUE)

    def test_visible_footer_ticket_office_and_recommendations_never_supply_address(self):
        event = dict(EVENT, title="Metal night")
        prefix = "<h1>Metal night</h1><p>12 février 2027</p>"
        for fragment in (
            "<footer><h2>New Room</h2><p>19 rue des Jardins, 68000 Colmar</p></footer>",
            "<h2>New Room</h2><p>Billetterie 19 rue des Jardins, 68000 Colmar</p>",
            "<h2>Autres concerts</h2><h3>New Room</h3><p>19 rue des Jardins, 68000 Colmar</p>",
            "<h2>New Room</h2><p>19 rue des Jardins, 68000 Paris</p>",
        ):
            with self.assertRaises(ValueError):
                evidence.extract_address(prefix + fragment, event, VENUE)

    def test_visible_conflicting_addresses_are_rejected(self):
        event = dict(EVENT, title="Metal night")
        html = ("<h1>Metal night</h1><time datetime='2027-02-12'>12 février</time>"
                "<h2>New Room</h2><p>19 rue des Jardins, 68000 Colmar</p>"
                "<h2>New Room</h2><p>21 rue des Jardins, 68000 Colmar</p>")
        with self.assertRaises(ValueError):
            evidence.extract_address(html, event, VENUE)

    def test_visible_fallback_never_masks_conflicting_structured_claim(self):
        event = dict(EVENT, title="Metal night")
        html = ("<h1>Metal night</h1><p>12 février 2027</p>"
                "<h2>New Room</h2><p>19 rue des Jardins, 68000 Colmar</p>")
        absent = document(location={"@type": "Place", "name": "New Room"})
        self.assertEqual(evidence.extract_address(absent + html, event, VENUE)["postalCode"], "68000")
        for structured in (document(startDate="2027-02-13"),
                           document(location={"@type": "Place", "name": "Other Room"}),
                           document(location={"@type": "Place", "name": "New Room", "address": {}})):
            with self.assertRaises(ValueError):
                evidence.extract_address(structured + html, event, VENUE)
