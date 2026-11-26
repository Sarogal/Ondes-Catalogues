import unittest
from unittest.mock import Mock
from datetime import date
from ptitesondes_catalogue_geo_proof_batch import research_group as _research_group, run_batch, named_osm_query, administrative_commune_code


def research_group(*args, **kwargs):
    kwargs.setdefault("named_osm_get", lambda *_: {"elements": []})
    kwargs.setdefault("commune_get", lambda *_: [])
    return _research_group(*args, **kwargs)
from test_ptitesondes_shared_venue_location_evidence import directory, html, ban, GROUP, URL
import test_ptitesondes_unnumbered_official_geo_proof as unnumbered

DAY = date(2026, 11, 25)


def group(**kw):
    return dict(GROUP, active_ids=["event-1"], missing_ids=["event-1"],
                source_urls=[URL], **kw)


class CatalogueGeoProofTests(unittest.TestCase):
    def test_independent_proof_not_event_approval(self):
        result = research_group(group(), DAY, directory_get=lambda _: directory(),
                                html_get=lambda _: html(), ign_get=lambda _: ban())
        self.assertEqual(result["status"], "independent_venue_point_found")
        self.assertTrue(result["event_identity_recheck_required"])
        self.assertFalse(result["publication_ready"])
        self.assertEqual(result["venue_point"]["lat"], 44.5)

    def test_no_fetch_on_unverified_agenda_platform(self):
        read = Mock(side_effect=AssertionError("unexpected HTML read"))
        g = group()
        g["source_urls"] = ["https://openagenda.com/example/events/123_demo"]
        result = research_group(g, DAY, directory_get=lambda _: {},
                                html_get=read, ign_get=Mock())
        self.assertEqual(result["status"], "municipality_not_independently_identified")
        read.assert_not_called()

    def test_wrong_name_no_point(self):
        result = research_group(group(), DAY, directory_get=lambda _: directory(),
                                html_get=lambda _: html("Other place"),
                                ign_get=lambda _: ban())
        self.assertNotIn("venue_point", result)

    def test_no_number_uses_named_official_point_and_independent_osm(self):
        g = dict(unnumbered.GROUP, active_ids=["event"], missing_ids=["event"],
                 source_urls=[unnumbered.URL], point_hints=[dict(lat=0, lng=0)])
        osm_reader = Mock(return_value=unnumbered.osm())
        result = research_group(
            g, DAY, directory_get=lambda _: unnumbered.directory(),
            html_get=lambda _: unnumbered.html(), ign_get=Mock(side_effect=AssertionError()),
            osm_get=osm_reader)
        self.assertEqual(result["status"], "independent_venue_point_found")
        self.assertIn("named OSM", result["venue_point"]["geo_source"])
        osm_reader.assert_called_once_with(unnumbered.POINT)
        self.assertFalse(result["publication_ready"])

    def test_legacy_point_cannot_supply_missing_official_center(self):
        g = dict(unnumbered.GROUP, active_ids=["event"], missing_ids=["event"],
                 source_urls=[unnumbered.URL],
                 point_hints=[dict(lat=44.5, lng=2.25)])
        osm_reader = Mock(side_effect=AssertionError("unproven center"))
        result = research_group(
            g, DAY, directory_get=lambda _: unnumbered.directory(),
            html_get=lambda _: unnumbered.html(include_geo=False),
            ign_get=Mock(side_effect=AssertionError()), osm_get=osm_reader)
        self.assertNotIn("venue_point", result)
        osm_reader.assert_not_called()

    def test_ambiguous_osm_does_not_prove_location(self):
        g = dict(unnumbered.GROUP, active_ids=["event"], missing_ids=["event"],
                 source_urls=[unnumbered.URL])
        result = research_group(
            g, DAY, directory_get=lambda _: unnumbered.directory(),
            html_get=lambda _: unnumbered.html(),
            osm_get=lambda _: unnumbered.osm(duplicate=True))
        self.assertNotIn("venue_point", result)

    def test_municipal_event_address_without_postcode_reuses_ban(self):
        import test_ptitesondes_municipal_event_venue_ban as event
        g = dict(event.GROUP, active_ids=["event"], missing_ids=["event"],
                 source_urls=[event.URL])
        result = research_group(g, DAY, directory_get=lambda _: event.directory(),
                                html_get=lambda _: event.municipal(),
                                ign_get=lambda _: event.ban())
        self.assertEqual(result["status"], "independent_venue_point_found")
        self.assertIn("Municipal event venue", result["venue_point"]["geo_source"])
        self.assertFalse(result["publication_ready"])

    def test_external_source_needs_exact_address_and_independent_named_osm_host(self):
        from copy import deepcopy
        g = group()
        url = "https://independent-theatre.example/programme"
        g["source_urls"] = [url]
        response = ban()
        response["features"][0]["properties"].update(street="Rue des Chênes", citycode="12345")
        osm = {"elements": [{"type": "node", "id": 1, "lat": 44.5, "lon": 2.25,
                             "tags": {"name": GROUP["venue"], "addr:city": GROUP["city"],
                                      "addr:postcode": "12345",
                                      "website": "https://independent-theatre.example/"}}]}
        def check(data, page=None, geo=None):
            return research_group(g, DAY, directory_get=lambda _: {},
                                  html_get=lambda _: html() if page is None else page,
                                  ign_get=lambda _: response if geo is None else geo,
                                  osm_get=lambda _: data)
        result = check(osm)
        self.assertEqual(result["status"], "independent_venue_point_found")
        self.assertEqual(result["venue_point"]["official"], url)
        self.assertFalse(result["publication_ready"])
        for field, value in (("website", "https://another.example/"),
                             ("name", "Autre lieu"), ("addr:postcode", "99999"),
                             ("addr:city", "Autre ville")):
            bad = deepcopy(osm)
            bad["elements"][0]["tags"][field] = value
            self.assertNotIn("venue_point", check(bad))
        duplicate = deepcopy(osm)
        duplicate["elements"].append(dict(duplicate["elements"][0], id=2))
        self.assertNotIn("venue_point", check(duplicate))
        self.assertNotIn("venue_point", check(osm, page=html("Autre lieu")))
        street = deepcopy(response)
        street["features"][0]["properties"]["type"] = "street"
        self.assertNotIn("venue_point", check(osm, geo=street))

    def test_open_named_discovery_without_known_website_or_catalogue_point(self):
        from copy import deepcopy
        g = dict(unnumbered.GROUP, active_ids=["old-slug"], missing_ids=["old-slug"],
                 source_urls=[], point_hints=[dict(lat=0, lng=0)])
        response = unnumbered.osm(city=unnumbered.CITY)
        response["elements"][0]["tags"]["website"] = "https://independent-venue.example/"
        def check(data, page=None, d=None):
            named = Mock(return_value=data)
            result = research_group(
                g, DAY, directory_get=lambda _: unnumbered.directory() if d is None else d,
                html_get=lambda url: unnumbered.html() if url.startswith("https://independent-venue.example") and page is None else (page if url.startswith("https://independent-venue.example") else "<html>no venue</html>"),
                ign_get=Mock(side_effect=AssertionError("no numbered address")),
                osm_get=Mock(side_effect=AssertionError("no old point")),
                named_osm_get=named)
            return result, named
        result, named = check(response)
        self.assertEqual(result["status"], "independent_venue_point_found")
        self.assertEqual(result["venue_point"]["official"], "https://independent-venue.example/")
        self.assertFalse(result["publication_ready"])
        named.assert_called_once_with("12345", unnumbered.VENUE)
        self.assertNotIn("venue_point", check(response, unnumbered.html(point=(44.6, 2.25)))[0])
        self.assertNotIn("venue_point", check(response, unnumbered.html(venue="Autre lieu"))[0])
        self.assertNotIn("venue_point", check(response, d={})[0])
        duplicate = deepcopy(response)
        duplicate["elements"].append(dict(duplicate["elements"][0], id=43))
        self.assertNotIn("venue_point", check(duplicate)[0])
        street = deepcopy(response)
        street["elements"][0]["tags"].update({"addr:street": "Place de la Gare", "addr:postcode": "12345"})
        page = "<html><h1>Place du village</h1><p>Place de la Gare 12345 Ville-les-Bois</p></html>"
        self.assertIn("unnumbered street", check(street, page)[0]["venue_point"]["geo_source"])
        street["elements"][0]["tags"]["addr:postcode"] = "99999"
        self.assertNotIn("venue_point", check(street, page)[0])

    def test_admin_geo_fallback_without_municipal_site(self):
        g = dict(unnumbered.GROUP, department="Corse-du-Sud (2A)",
                 active_ids=["old"], missing_ids=["old"], source_urls=[])
        row = dict(nom=g["city"], code="2A123", codeDepartement="2A")
        response = unnumbered.osm(city=g["city"])
        response["elements"][0]["tags"]["website"] = "https://independent-venue.example/"
        named = Mock(return_value=response)
        r = research_group(g, DAY, directory_get=lambda _: {},
                           commune_get=lambda _: [row],
                           named_osm_get=named, html_get=lambda _: unnumbered.html(),
                           ign_get=Mock(side_effect=AssertionError()))
        self.assertEqual(r["status"], "independent_venue_point_found")
        self.assertFalse(r["publication_ready"])
        named.assert_called_once_with("2A123", g["venue"])
        for rows in ([], [row, row], [dict(row, code="2B123")],
                     [dict(row, nom="Other")], [dict(row, codeDepartement="2B")]):
            self.assertIsNone(administrative_commune_code(g, rows))
        self.assertIn('["ref:INSEE"="2A123"]', named_osm_query("2A123", g["venue"]))

    def test_named_query_is_bounded_and_literal(self):
        query = named_osm_query("12345", 'Théâtre "test"')
        self.assertIn('["ref:INSEE"="12345"]', query)
        self.assertIn('Théâtre \\"test\\"', query)
        with self.assertRaises(ValueError):
            named_osm_query("12345;out;", "Théâtre")

    def test_batch_bound_and_rotation(self):
        doc = dict(events=[dict(id=str(i), city="Ville", venue="Salle "+str(i),
                                date_start="2026-12-01") for i in range(5)])
        reader = Mock(return_value=dict(status="held"))
        first = run_batch(doc, DAY, researcher=reader)
        self.assertEqual(first["next_offset"], 3)
        self.assertEqual(reader.call_count, 3)
        last = run_batch(doc, DAY, first["next_offset"], researcher=reader)
        self.assertEqual(last["next_offset"], 0)
        self.assertEqual(reader.call_count, 5)
        self.assertEqual(last["public_writes"], 0)
