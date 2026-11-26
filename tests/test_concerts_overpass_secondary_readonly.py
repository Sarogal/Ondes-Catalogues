"""Offline safety tests for redundant read-only OSM transport.

Fail over ONLY after a network failure. A successful contradictory OSM
response is final and can never be overwritten by another provider.
"""
import json
import unittest

from automation.concerts import osm_read_only_fallback as readonly
from automation.concerts import independent_named_site_geo as geo
from automation.concerts import event_site_pair_recheck as pairing
from scripts import concert_dynamic_existing_venue as existing
import test_concerts_dynamic_existing_venue as fixture


class SecondaryReadOnlyOSMTests(unittest.TestCase):
    def test_only_three_static_providers_and_numeric_identifiers(self):
        first = readonly.element("node", "380889428")
        second = readonly.element("node", "380889428", provider=1)
        third = readonly.element("node", "380889428", provider=2)
        self.assertTrue(first.startswith(
            "https://overpass.private.coffee/api/interpreter?"))
        self.assertTrue(second.startswith(
            "https://overpass-api.de/api/interpreter?"))
        self.assertTrue(third.startswith(
            "https://overpass.openstreetmap.fr/api/interpreter?"))
        self.assertEqual(first.split("?", 1)[1], second.split("?", 1)[1])
        self.assertEqual(first.split("?", 1)[1], third.split("?", 1)[1])
        for provider in (-1, 3, True, "https://evil.invalid"):
            with self.subTest(provider=provider):
                with self.assertRaises(ValueError):
                    readonly.element("node", "380889428", provider=provider)
                with self.assertRaises(ValueError):
                    readonly.nearby(47.394, 0.687, 47.396, 0.689,
                                    provider=provider)
        with self.assertRaises(ValueError):
            readonly.element("node", "12);out body;")

    def test_osm_second_provider_can_restore_exact_domain_attribution(self):
        venue = next(v for v in fixture.BASE["venues"]
                     if v["id"] == fixture.VENUE_ID)
        visited = []
        def fetch(url, cache):
            visited.append(url)
            if url.startswith("https://api.openstreetmap.org/"):
                raise ValueError("editing API unreachable")
            if url.startswith("https://www.openstreetmap.org/api/"):
                raise TimeoutError("editing API unavailable")
            if url.startswith("https://overpass.private.coffee/"):
                raise TimeoutError("first read-only provider busy")
            if url.startswith("https://overpass-api.de/"):
                return fixture.osm()
            raise AssertionError("Unsupported host")
        self.assertEqual(
            existing.osm_identity(venue, fixture.EVENT, fetch, {}),
            venue["geoSource"])
        self.assertTrue(any("overpass.private.coffee" in x for x in visited))
        self.assertTrue(any("overpass-api.de" in x for x in visited))

        def wrong(url, cache):
            if url.startswith("https://overpass-api.de/"):
                return fixture.osm(website="https://forged.invalid")
            return fetch(url, cache)
        with self.assertRaises(ValueError):
            existing.osm_identity(venue, fixture.EVENT, wrong, {})

    def test_exact_government_address_osm_map_can_use_second_provider(self):
        site = {
            "name": "Salle Libre", "city": "Tours", "postalCode": "37000",
            "address": "1 rue Exemple", "region": "Centre-Val de Loire",
        }
        gov = json.dumps({"features": [{
            "geometry": {"type": "Point", "coordinates": [0.688, 47.395]},
            "properties": {
                "postcode": "37000", "city": "Tours",
                "street": "rue Exemple", "housenumber": "1",
                "type": "housenumber", "score": 0.82,
            },
        }]})
        xml = ('<osm version="0.6"><node id="912345678" '
               'lat="47.395" lon="0.688">'
               '<tag k="name" v="Salle Libre"/>'
               '<tag k="addr:city" v="Tours"/>'
               '<tag k="addr:postcode" v="37000"/>'
               '<tag k="addr:street" v="rue Exemple"/>'
               '<tag k="addr:housenumber" v="1"/>'
               '</node></osm>')
        visited = []
        def fetch(url, cap):
            visited.append(url)
            if url.startswith("https://data.geopf.fr/"):
                return gov, url
            if url.startswith("https://api.openstreetmap.org/"):
                raise ValueError("editing API blocked")
            if url.startswith("https://overpass.private.coffee/"):
                raise TimeoutError("provider timed out")
            if url.startswith("https://overpass-api.de/"):
                return xml, url
            raise AssertionError("Unexpected OSM proof route")
        point, lat, lon, precision = geo.verify(site, fetch)
        self.assertEqual(point, "https://www.openstreetmap.org/node/912345678")
        self.assertEqual(precision, "named-site-point")
        self.assertTrue(any("overpass-api.de" in u for u in visited))
        def contradiction(url, cap):
            if url.startswith("https://overpass.private.coffee/"):
                return xml.replace("Salle Libre", "Different Venue"), url
            return fetch(url, cap)
        with self.assertRaises(ValueError):
            geo.verify(site, contradiction)

    def test_old_osm_street_requires_active_exact_establishment_and_numbered_ban(self):
        from urllib.parse import parse_qs, urlsplit
        site = {"name": "Salle Libre", "city": "Tours", "postalCode": "37000",
                "address": "allée Nouvelle", "region": "Centre-Val de Loire"}
        website = "https://salle-libre.fr/agenda"
        siret = "12345678901234"
        row = {"siret": siret, "etat_administratif": "A",
               "statut_diffusion_etablissement": "O", "code_pays_etranger": None,
               "code_postal": "37000", "libelle_commune": "Tours",
               "numero_voie": "12", "indice_repetition": None,
               "type_voie": "ALLEE", "libelle_voie": "NOUVELLE"}
        xml = ('<osm version="0.6"><node id="912345678" lat="47.395" lon="0.688">'
               '<tag k="name" v="Salle Libre"/><tag k="addr:city" v="Tours"/>'
               '<tag k="addr:postcode" v="37000"/><tag k="addr:street" v="ancien quai"/>'
               '<tag k="addr:housenumber" v="12"/><tag k="website" v="https://salle-libre.fr/"/>'
               '<tag k="ref:FR:SIRET" v="' + siret + '"/></node></osm>')
        def run(*, official=website, establishment=row, osm=xml, far=False):
            visited = []
            def fetch(url, cap):
                visited.append(url)
                if url.startswith(geo.BAN):
                    query = parse_qs(urlsplit(url).query)["q"][0]
                    numbered = query.startswith("12 ")
                    props = {"postcode": "37000", "city": "Tours", "street": "allée Nouvelle",
                             "type": "housenumber" if numbered else "street", "score": 0.84}
                    if numbered:
                        props["housenumber"] = "12"
                    data = {"features": [{"geometry": {"type": "Point",
                            "coordinates": [0.698 if numbered and far else 0.688, 47.395]},
                            "properties": props}]}
                    return json.dumps(data), url
                if url.startswith(geo.OSM_MAP):
                    return osm, url
                if url.startswith(geo.ESTABLISHMENTS):
                    self.assertEqual(parse_qs(urlsplit(url).query)["q"], [siret])
                    return json.dumps({"results": [{"siren": siret[:9],
                                                   "siege": establishment,
                                                   "matching_etablissements": [establishment]}]}), url
                self.fail("unexpected fetch")
            result = geo.verify(site, fetch, official_website=official)
            self.assertEqual(sum(u.startswith(geo.ESTABLISHMENTS) for u in visited), 1)
            self.assertEqual(sum(u.startswith(geo.BAN) for u in visited), 2)
            return result
        self.assertEqual(run(), ("https://www.openstreetmap.org/node/912345678",
                                 47.395, 0.688, "named-site-point"))
        for changes in (
            {"official": None}, {"official": "https://another-room.fr/"},
            {"establishment": dict(row, etat_administratif="F")},
            {"establishment": dict(row, statut_diffusion_etablissement="P")},
            {"establishment": dict(row, siret="12345678900000")},
            {"establishment": dict(row, numero_voie="13")},
            {"establishment": dict(row, libelle_voie="AUTRE")},
            {"establishment": dict(row, code_postal="37100")},
            {"osm": xml.replace("Tours", "Paris")},
            {"osm": xml.replace(siret, "invalid")},
            {"osm": xml.replace("</osm>", xml[xml.index("<node"):xml.index("</osm>")].replace(
                'id="912345678"', 'id="912345679"', 1) + "</osm>")},
            {"far": True},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                run(**changes)

    def test_new_site_osm_node_exact_json_identity_from_second_provider(self):
        expected = {"name": "Salle Libre", "city": "Tours",
                    "postalCode": "37000"}
        obj = json.dumps({"elements": [{
            "id": 912345678, "type": "node", "lat": 47.395,
            "lon": 0.688, "tags": {
                "name": "Salle Libre", "addr:city": "Tours",
                "addr:postcode": "37000", "addr:country": "FR",
            },
        }]})
        def fetch(url, cap):
            if url.startswith("https://overpass-api.de/"):
                return obj, url
            raise TimeoutError("primary OSM transport unavailable")
        self.assertEqual(
            pairing._read_osm_node(
                "https://www.openstreetmap.org/node/912345678",
                expected, fetch),
            (47.395, 0.688))
        def forged(url, cap):
            if url.startswith("https://overpass-api.de/"):
                return obj.replace("Salle Libre", "Impostor Venue"), url
            return fetch(url, cap)
        with self.assertRaises(ValueError):
            pairing._read_osm_node(
                "https://www.openstreetmap.org/node/912345678",
                expected, forged)


if __name__ == "__main__":
    unittest.main()
