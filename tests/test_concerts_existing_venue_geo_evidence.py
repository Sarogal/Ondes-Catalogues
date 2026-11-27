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
    def test_named_footer_address_after_exact_visible_event_and_independent_geo(self):
        event = dict(EVENT, title="Metal night")
        html = ("<h1>Metal night</h1><p>New Room</p>"
                "<p>Vendredi 12 02 2027 20:00</p>"
                "<h2>Vous devriez aimer...</h2><p>Other show</p>"
                "<footer><p>New Room, Allée des Jardins - 68000 Colmar"
                " / tél. : 03 00 00 00 00</p></footer>")
        with patch.object(evidence.official, "official_origin",
                          return_value="https://unknown-room.fr/agenda"), \
             patch.object(evidence.geo, "verify",
                          return_value=(OSM, 48.08, 7.36, "named-site-point")) as geo:
            row = evidence.verify(event, VENUE, fetch=lambda *a: html)
            self.assertEqual(row["venuePatch"]["address"], "Allée des Jardins")
            self.assertEqual(row["venuePatch"]["postalCode"], "68000")
            self.assertEqual(geo.call_args.args[0]["address"], "Allée des Jardins")
            self.assertFalse(row["publicationAllowed"])
            self.assertFalse(row["publisherAuthorityGranted"])

    def test_footer_requires_exact_event_venue_date_origin_and_visible_named_address(self):
        event = dict(EVENT, title="Metal night")
        prefix = "<h1>Metal night</h1><p>New Room</p><p>12 02 2027 20:00</p>"
        footer = "<footer><p>New Room, 19 rue des Jardins - 68000 Colmar</p></footer>"
        variants = [
            (prefix.replace("<p>New Room</p>", "<p>Other Room</p>") + footer, True),
            (prefix.replace("12 02", "13 02") + footer, True),
            (prefix.replace("Metal night", "Other show") + footer, True),
            (prefix + footer, False),
            (prefix + footer.replace("New Room,", "Other Room,"), True),
            (prefix + footer.replace("Colmar", "Paris"), True),
            (prefix + footer.replace("<footer>", "<footer hidden>"), True),
            (prefix + footer.replace("<p>", "<p style='display:none'>"), True),
            (prefix + footer.replace("</footer>", "<p>New Room, 21 rue des Jardins 68000 Colmar</p></footer>"), True),
            (prefix + "<p>13 02 2027 20:00</p>" + footer, True),
            (prefix + "<h2>New Room</h2><p>19 rue des Jardins 75000 Paris</p>" + footer, True),
            (prefix.replace("<p>New Room</p>", "") + "<h2>Vous devriez aimer...</h2><p>New Room</p>" + footer, True),
        ]
        for html, trusted in variants:
            with self.subTest(html=html, trusted=trusted), \
                 patch.object(evidence.official, "official_origin",
                              return_value="https://unknown-room.fr/agenda" if trusted else None), \
                 patch.object(evidence.geo, "verify",
                              side_effect=AssertionError("unverified address reached geography")):
                with self.assertRaises(ValueError):
                    evidence.verify(event, VENUE, fetch=lambda *a: html)

    def test_footer_does_not_override_explicit_practical_page_conflict(self):
        event = dict(EVENT, title="Metal night")
        html = ("<h1>Metal night</h1><p>12 02 2027 20:00</p>"
                "<p>Lieu</p><p>New Room</p><nav><a href='/infos/'>Infos pratiques</a></nav>"
                "<footer><p>New Room, 19 rue des Jardins 68000 Colmar</p></footer>")
        practical = ("<h1>Infos pratiques</h1><h2>New Room</h2>"
                     "<p>19 rue des Jardins 75000 Paris</p>")
        with patch.object(evidence.official, "official_origin",
                          return_value="https://unknown-room.fr/agenda"), \
             patch.object(evidence.geo, "verify",
                          side_effect=AssertionError("conflicting address reached geography")):
            with self.assertRaises(ValueError):
                evidence.verify(event, VENUE,
                                fetch=lambda url, cache: html if url == URL else practical)

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

    def test_geo_accepts_only_exact_canonical_event_among_distinct_cards(self):
        main = document()
        other = document(url="https://unknown-room.fr/events/another",
                         name="Another show", startDate="2027-03-10",
                         location={"@type": "Place", "name": "Other Room"})
        site = evidence.extract_address(other + main, EVENT, VENUE)
        self.assertEqual(site["address"], "19 rue des Jardins")
        for ambiguous in (
                main, document(url=None, name="Another show"),
                document(url=URL + "?other=1", name="Another show"),
                document(url="https://other.fr/events/another", name="Another show"),
                document(url="https://unknown-room.fr/events/another")):
            with self.subTest(ambiguous=ambiguous), self.assertRaises(ValueError):
                evidence.extract_address(main + ambiguous, EVENT, VENUE)

    def test_geo_normalizes_explicit_french_postal_format_without_guessing(self):
        place = {"@type": "Place", "name": "New Room",
                 "address": {"@type": "PostalAddress",
                             "streetAddress": "rue des Jardins",
                             "postalCode": "68 000", "addressLocality": "Colmar",
                             "addressCountry": {"@type": "Country", "name": "France"}}}
        site = evidence.extract_address(document(location=place), EVENT, VENUE)
        self.assertEqual(site["postalCode"], "68000")
        self.assertEqual(site["address"], "rue des Jardins")
        for key, value in (("postalCode", "68 00"), ("addressLocality", "Paris"),
                           ("addressCountry", {"@type": "Country", "name": "Belgium"}),
                           ("addressCountry", {"@type": "Place", "name": "France"})):
            wrong = copy.deepcopy(place)
            wrong["address"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                evidence.extract_address(document(location=wrong), EVENT, VENUE)

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

    def test_named_feature_diagnostics_are_fixed_and_do_not_change_matching(self):
        site = evidence.extract_address(document(), EVENT, VENUE)
        center = (48.08, 7.36)
        def node(ident=1, name="New Room", lat=48.08, extra=""):
            return (f'<node id="{ident}" lat="{lat}" lon="7.36">'
                    f'<tag k="name" v="{name}"/>{extra}</node>')
        def check(xml, expected):
            def fetch(url, cap):
                return '<osm version="0.6">' + xml + '</osm>', url
            with self.assertRaises(evidence.geo.NamedFeatureHeld) as err:
                evidence.geo._osm_map(site, center, fetch)
            self.assertEqual(err.exception.code, expected)
            self.assertEqual(str(err.exception),
                "Independent BAN/OSM site: one independent named OSM feature at exact address required")
        check(node(name="Other Room"), "osm_name_not_found")
        check(node(extra='<tag k="addr:postcode" v="75001"/>'), "osm_postal_fields_conflict")
        check(node(extra='<tag k="addr:housenumber" v="20"/>'), "osm_house_number_conflict")
        check(node(lat=48.083), "osm_feature_outside_radius")
        check(node(extra='<tag k="addr:street" v="Other Street"/>'), "osm_street_conflict")
        check(node() + node(ident=2), "osm_multiple_named_features")
        check('<way id="2"><tag k="name" v="New Room"/><nd ref="4"/></way>',
              "osm_geometry_missing")
        with patch.object(evidence.geo, "verify",
                          side_effect=evidence.geo.NamedFeatureHeld("osm_street_conflict")):
            with self.assertRaises(evidence.EvidenceHeld) as err:
                evidence.verify(EVENT, VENUE, fetch=lambda *a: document())
            self.assertEqual(err.exception.code, "osm_street_conflict")
        xml = '<osm version="0.6">' + node() + '</osm>'
        self.assertEqual(evidence.geo._osm_map(site, center,
            lambda url, cap: (xml, url)),
            ("https://www.openstreetmap.org/node/1", *center, "named-site-point"))

    def test_rejects_missing_independent_location(self):
        with patch.object(evidence.geo, "verify", side_effect=ValueError("ambiguous")):
            with self.assertRaises(ValueError):
                evidence.verify(EVENT, VENUE, fetch=lambda url, cache: document())


    def test_reserved_domain_is_rejected_before_network(self):
        bad = dict(EVENT, officialUrl="https://unknown-room.example/events/metal-night")
        with self.assertRaises(ValueError):
            evidence.verify(bad, VENUE, fetch=lambda *args: self.fail("must not fetch"))

    def test_same_slot_retries_rotate_across_all_rooms_and_event_pages(self):
        venues = [dict(VENUE, id=f"room-{i}") for i in range(12)]
        events = [dict(EVENT, id=f"event-{i}-{j}", venueId=f"room-{i}",
                       status="confirmed", date=f"2027-02-{12+j:02d}")
                  for i in range(12) for j in range(4)]
        data = {"venues": venues, "events": events}
        original = copy.deepcopy(data)
        day = dt.date(2026, 11, 26)
        called = []
        def held(event, venue, **kwargs):
            called.append((venue["id"], event["id"]))
            raise evidence.EvidenceHeld("event_fetch_unavailable")
        prior = None
        for cycle in range(6):
            prior = evidence.scan(data, day, slot=1, prior=prior, verify_one=held)
            self.assertEqual(prior["examinedVenues"], 4)
            self.assertEqual(prior["eventPagesExamined"], 8)
            self.assertFalse(prior["publicationAllowed"])
            if cycle == 2:
                self.assertEqual(len({vid for vid, _ in called}), 12)
        self.assertEqual(len(called), 48)
        self.assertEqual(len(set(called)), 48)
        self.assertEqual(data, original)
        self.assertEqual(set(prior["recentVenueIds"]), {v["id"] for v in venues})

    def test_new_room_is_preferred_and_future_or_untrusted_history_ignored(self):
        venues = [dict(VENUE, id=f"room-{i}") for i in range(5)]
        events = [dict(EVENT, id=f"event-{i}", venueId=f"room-{i}", status="confirmed")
                  for i in range(5)]
        data = {"venues": venues, "events": events}
        day = dt.date(2026, 11, 26)
        def held(*args, **kwargs):
            raise evidence.EvidenceHeld("event_fetch_unavailable")
        first = evidence.scan(data, day, slot=1, verify_one=held)
        next_run = evidence.scan(data, day, slot=1, prior=first, verify_one=held)
        self.assertEqual(len(set(next_run["recentVenueIds"])), 5)
        first_ids = [v["venueId"] for v in first["held"]]
        for invalid in ({**first, "publicationAllowed": True},
                        {**first, "asOf": "2026-11-27"}):
            reset = evidence.scan(data, day, slot=1, prior=invalid, verify_one=held)
            self.assertEqual([v["venueId"] for v in reset["held"]], first_ids)
        # Removing a corrected room also removes its obsolete memory.
        corrected = first_ids[0]
        data["venues"] = [dict(v, geoPrecision="named-site-point") if v["id"] == corrected else v
                          for v in venues]
        out = evidence.scan(data, day, slot=1, prior=next_run, verify_one=held)
        self.assertNotIn(corrected, out["recentVenueIds"])
        self.assertNotIn(corrected, out["recentEventIdsByVenue"])

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


class LinkedPracticalAddressTests(unittest.TestCase):
    def event(self, location="New Room, Grande Salle", link="/infos/"):
        return ("<p>12 février 2027</p><h1>Metal night</h1>"
                "<p>Lieu</p><p>" + location + "</p><nav>"
                '<a href="' + link + '">Infos pratiques</a></nav>')

    def page(self):
        return ("<h1>Infos pratiques</h1><h2>New Room</h2>"
                "<p>Concerts et musique actuelle</p>"
                "<p>19 rue des Jardins 68000 Colmar<br>03 00 00 00 00</p>")

    def test_dated_event_can_follow_visible_official_practical_link(self):
        event = dict(EVENT, title="Metal night")
        urls = []
        def fetch(url, cache):
            urls.append(url)
            return self.event() if url == URL else self.page()
        with patch.object(evidence.official, "official_origin",
                          return_value="https://unknown-room.fr/agenda"), \
             patch.object(evidence.geo, "verify",
                          return_value=(OSM, 48.08, 7.36, "named-site-point")):
            proof = evidence.verify(event, VENUE, fetch=fetch)
        self.assertEqual(urls, [URL, "https://unknown-room.fr/infos/"])
        self.assertEqual(proof["venuePatch"]["address"], "19 rue des Jardins")

    def test_offsite_hidden_or_unbound_link_cannot_supply_address(self):
        event = dict(EVENT, title="Metal night")
        for html, origin in (
            (self.event(location="Other Room"), "https://unknown-room.fr/"),
            (self.event(link="https://other.fr/infos/"), "https://unknown-room.fr/"),
            (self.event().replace("<nav>", "<nav hidden>"), "https://unknown-room.fr/"),
            (self.event(), None),
        ):
            with self.subTest(html=html), patch.object(
                    evidence.official, "official_origin", return_value=origin):
                with self.assertRaises(ValueError):
                    evidence.verify(event, VENUE, fetch=lambda url, cache: (
                        html if url == URL else self.fail("unsafe link fetched")))

    def test_practical_address_conflict_and_ticket_office_are_rejected(self):
        event = dict(EVENT, title="Metal night")
        for page in (
            self.page() + "<h2>New Room</h2><p>21 rue des Jardins 68000 Colmar</p>",
            "<h1>Infos pratiques</h1><h2>New Room</h2>"
            "<p>Billetterie</p><p>19 rue des Jardins 68000 Colmar</p>",
        ):
            with patch.object(evidence.official, "official_origin",
                              return_value="https://unknown-room.fr/"), self.assertRaises(ValueError):
                evidence.verify(event, VENUE, fetch=lambda url, cache: self.event() if url == URL else page)

    def test_scan_reports_fixed_reason_without_raw_error(self):
        event = dict(EVENT, status="confirmed")
        def fail(*args, **kwargs):
            raise evidence.EvidenceHeld("event_fetch_unavailable")
        report = evidence.scan({"venues": [VENUE], "events": [event]},
                               dt.date(2026, 11, 25), verify_one=fail)
        self.assertEqual(report["reasonCounts"], {"event_fetch_unavailable": 1})
        self.assertEqual(report["held"][0]["reasonCounts"], report["reasonCounts"])

    def test_hidden_practical_address_cannot_be_used(self):
        event = dict(EVENT, title="Metal night")
        for hidden in ('hidden', 'aria-hidden="true"', 'style="display:none"'):
            page = '<h1>Infos pratiques</h1><div ' + hidden + '>' + self.page() + '</div>'
            with patch.object(evidence.official, "official_origin",
                              return_value="https://unknown-room.fr/"), self.assertRaises(ValueError):
                evidence.verify(event, VENUE, fetch=lambda url, cache: self.event() if url == URL else page)

    def test_explicit_wrong_city_is_not_absent_address(self):
        event = dict(EVENT, title="Metal night")
        page = ("<p>12 février 2027</p><h1>Metal night</h1>"
                "<p>Lieu</p><h2>New Room</h2><p>19 rue des Jardins 75001 Paris</p>"
                '<nav><a href="/infos/">Infos pratiques</a></nav>')
        with patch.object(evidence.official, "official_origin",
                          return_value="https://unknown-room.fr/"), self.assertRaises(ValueError):
            evidence.verify(event, VENUE, fetch=lambda url, cache: (
                page if url == URL else self.fail("contradiction must not trigger fallback")))

class StandaloneVenueSourceTests(unittest.TestCase):
    def test_exact_named_footer_and_independent_geo_without_event(self):
        source = "https://unknown-room.fr/"
        html = "<footer><address>New Room: 19 rue des Jardins, 68000 Colmar</address></footer>"
        with patch.object(evidence, "registered_venue_source", return_value=source), \
             patch.object(evidence.geo, "verify", return_value=(OSM, 48.08, 7.36, "named-site-point")):
            proof = evidence.verify_venue_source(source, VENUE, fetch=lambda *a: html)
            self.assertIsNone(proof["eventId"])
            self.assertEqual(proof["venuePatch"]["address"], "19 rue des Jardins")
            self.assertFalse(proof["publicationAllowed"])
            for bad in (html.replace("New Room", "Other Room"),
                        html.replace("Colmar", "Paris"),
                        html + html.replace("19 rue", "21 rue")):
                with self.assertRaises(ValueError):
                    evidence.verify_venue_source(source, VENUE, fetch=lambda *a: bad)
        with patch.object(evidence, "registered_venue_source", return_value=None), \
             patch.object(evidence.address_source, "website_from_address",
                          return_value=("https://other.fr/", OSM)):
            with self.assertRaises(ValueError):
                evidence.verify_venue_source(source, VENUE, fetch=lambda *a: html)

    def test_standalone_follows_only_visible_exact_practical_page(self):
        source = "https://unknown-room.fr/"
        link = '<nav><a href="/infos/">Infos pratiques</a></nav>'
        address = "<h1>Infos pratiques</h1><h2>New Room</h2><p>19 rue des Jardins</p><p>68000 Colmar</p>"
        calls = []
        def fetch(url, cache):
            calls.append(url)
            return link if url == source else address
        with patch.object(evidence, "registered_venue_source", return_value=source), \
             patch.object(evidence.geo, "verify", return_value=(OSM, 48.08, 7.36, "named-site-point")):
            proof = evidence.verify_venue_source(source, VENUE, fetch=fetch)
            self.assertEqual(proof["venuePatch"]["address"], "19 rue des Jardins")
            self.assertEqual(calls, [source, source + "infos/"])
            for page in (
                    address.replace("Colmar", "Paris"),
                    address + "<h2>New Room</h2><p>21 rue des Jardins 68000 Colmar</p>",
                    address.replace("<h2>New Room</h2>", "<h2>Other Room</h2>"),
                    '<div hidden>' + address + '</div>'):
                with self.assertRaises(ValueError):
                    evidence.verify_venue_source(source, VENUE, fetch=lambda url, cache: link if url == source else page)
            for landing in (
                    link.replace("/infos/", "https://other.fr/infos/"),
                    '<div hidden>' + link + '</div>',
                    link + link.replace("/infos/", "/acces/"),
                    '<footer><address>New Room: 19 rue des Jardins, 75000 Paris</address></footer>' + link):
                with self.assertRaises(ValueError):
                    evidence.verify_venue_source(source, VENUE, fetch=lambda url, cache: landing if url == source else self.fail("unsafe fallback"))

    def test_scan_rotates_orphan_venue_without_event(self):
        source = "https://unknown-room.fr/"
        with patch.object(evidence, "registered_venue_source", return_value=source):
            report = evidence.scan({"venues": [VENUE], "events": []},
                                   dt.date(2026, 11, 25),
                                   verify_standalone=lambda url, venue, **kw: {
                                       "venueId": venue["id"], "officialUrl": url})
        self.assertEqual(report["venuesWithFutureOfficialEvents"], 0)
        self.assertEqual(report["standaloneSourcesExamined"], 1)
        self.assertEqual(report["eventPagesExamined"], 0)
        self.assertEqual(report["proposals"][0]["venueId"], VENUE["id"])

    def test_discovered_source_requires_independent_exact_osm_website(self):
        source = "https://unknown-room.fr/events/one"
        html = "<footer><address>New Room: 19 rue des Jardins, 68000 Colmar</address></footer>"
        with patch.object(evidence, "registered_venue_source", return_value=None), \
             patch.object(evidence.address_source, "website_from_address",
                          return_value=("https://unknown-room.fr/", OSM)) as website, \
             patch.object(evidence.geo, "verify", return_value=(OSM, 48.08, 7.36, "named-site-point")):
            proof = evidence.verify_venue_source(source, VENUE, fetch=lambda *a: html)
            website.assert_called_once()
            self.assertEqual(proof["officialUrl"], source)
            self.assertIsNone(proof["eventId"])
            self.assertFalse(proof["publicationAllowed"])
        for domain in ("https://other.fr/", "https://unknown-room.fr.evil.example/"):
            with patch.object(evidence, "registered_venue_source", return_value=None), \
                 patch.object(evidence.address_source, "website_from_address", return_value=(domain, OSM)), \
                 patch.object(evidence.geo, "verify", side_effect=AssertionError("unbound domain")):
                with self.assertRaises(ValueError):
                    evidence.verify_venue_source(source, VENUE, fetch=lambda *a: html)

    def test_discovery_hint_selection_exact_identity_and_no_competing_domain(self):
        today = dt.date(2026, 11, 25)
        source = "https://unknown-room.fr/events/one"
        lead = {"source": "agenda_officiel_new_room", "date": "2027-02-12",
                "venue": VENUE["name"], "city": VENUE["city"],
                "sourceUrl": source, "publicationAllowed": False, "reviewRequired": True}
        record = {"status": "pending_review", "candidate": lead}
        registry = {"schema": evidence.intake.REGISTRY_SCHEMA, "items": {"one": record}}
        venues = {VENUE["id"]: VENUE}
        self.assertEqual(evidence.discovered_venue_sources(registry, venues, today),
                         {VENUE["id"]: source})
        with patch.object(evidence, "registered_venue_source", return_value=None):
            result = evidence.scan({"venues": [VENUE], "events": []}, today,
                                   registry=registry,
                                   verify_standalone=lambda url, v, **kw: {"officialUrl": url})
            self.assertEqual(result["standaloneSourcesExamined"], 1)
            self.assertEqual(result["proposals"], [{"officialUrl": source}])
        for changes in ({"city": "Paris"}, {"date": "2020-01-01"},
                        {"sourceUrl": "https://openagenda.com/agenda/events/test"},
                        {"publicationAllowed": True}):
            denied = {**registry, "items": {"one": {**record, "candidate": {**lead, **changes}}}}
            self.assertEqual(evidence.discovered_venue_sources(denied, venues, today), {})
        registry["items"]["two"] = {**record, "candidate": {**lead, "sourceUrl": "https://other.fr/events/one"}}
        self.assertEqual(evidence.discovered_venue_sources(registry, venues, today), {})

    def test_practical_arrival_heading_with_exact_document_identity(self):
        source = "https://unknown-room.fr/"
        link = '<nav><a href="/infos/">Infos pratiques</a></nav>'
        page = ("<head><title>Infos pratiques - New Room</title></head>"
                "<h1>Infos pratiques</h1><h2>Comment venir ?</h2>"
                "<p>19 rue des Jardins, 68000 Colmar</p>"
                "<h2>Restaurant</h2><p>21 rue des Jardins, 68000 Colmar</p>")
        with patch.object(evidence, "registered_venue_source", return_value=source), \
             patch.object(evidence.geo, "verify", return_value=(OSM, 48.08, 7.36, "named-site-point")):
            proof = evidence.verify_venue_source(source, VENUE,
                fetch=lambda url, cache: link if url == source else page)
            self.assertEqual(proof["venuePatch"]["address"], "19 rue des Jardins")
            for bad in (
                    page.replace("New Room</title>", "Other Room</title>"),
                    page.replace("19 rue des Jardins, 68000 Colmar", "19 rue des Jardins, 75018 Paris"),
                    page.replace("Comment venir ?", "Réservations"),
                    page.replace("<h2>Restaurant</h2>", "<h2>Accès</h2>"),
                    page.replace("<h2>Restaurant</h2>", ""),
                    page.replace("<h2>Comment venir ?</h2>", '<h2 hidden>Comment venir ?</h2>')):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    evidence.verify_venue_source(source, VENUE,
                        fetch=lambda url, cache: link if url == source else bad)

    def test_named_arrival_section_with_label_and_administrative_complement(self):
        source = "https://unknown-room.fr/"
        link = '<nav><a href="/infos/">Infos pratiques</a></nav>'
        page = ("<head><title>Infos pratiques : accès – New Room</title></head>"
                "<h1>Infos pratiques</h1><h2>Venir à New Room</h2>"
                "<p><strong>ADRESSE</strong><br/>19 rue des Jardins, 68000 Colmar, Métropole de Exemple</p>"
                "<p>TRAM<br/>Arrêt central</p><h2>Restaurant</h2>"
                "<p>21 rue des Jardins, 68000 Colmar</p>")
        with patch.object(evidence, "registered_venue_source", return_value=source), \
             patch.object(evidence.geo, "verify", return_value=(OSM, 48.08, 7.36, "named-site-point")) as geo:
            proof = evidence.verify_venue_source(source, VENUE,
                fetch=lambda url, cache: link if url == source else page)
            self.assertEqual(proof["venuePatch"]["address"], "19 rue des Jardins")
            self.assertEqual(proof["venuePatch"]["postalCode"], "68000")
            self.assertEqual(geo.call_args.args[0]["city"], "Colmar")
            for bad in (
                    page.replace("Venir à New Room", "Venir à Other Room"),
                    page.replace("68000 Colmar, Métropole", "68000 Paris, Métropole"),
                    page.replace("Métropole de Exemple", "Paris"),
                    page.replace("Métropole de Exemple", "75018 Paris"),
                    page.replace("Métropole de Exemple", "Métropole de Exemple, Belgique"),
                    page.replace("ADRESSE", "BILLETTERIE")):
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    evidence.verify_venue_source(source, VENUE,
                        fetch=lambda url, cache: link if url == source else bad)
