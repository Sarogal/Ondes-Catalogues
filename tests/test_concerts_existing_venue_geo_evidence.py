import json
import unittest
from unittest.mock import patch

from automation.concerts import existing_venue_geo_evidence as evidence

URL = "https://unknown-room.example/events/metal-night"
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
                     document(url="https://other.example/events/metal-night"),
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
                          return_value=("https://unknown-room.example/", OSM)):
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
                ("https://other-room.example/", OSM),
                ("https://unknown-room.example/", "https://www.openstreetmap.org/node/12346"),
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
