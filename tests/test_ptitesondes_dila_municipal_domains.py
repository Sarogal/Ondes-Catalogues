"""Offline tests for official DILA municipal website provenance."""
from copy import deepcopy
import json
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_dila_municipal_domains import (
    dila_query, municipal_site_hosts, approved_municipal_page_host,
    redacted_directory_status, _host,
)

CITY = "Ville-les-Bois"
SITE = "https://www.ville-les-bois.fr/"
PAGE = "https://agenda.ville-les-bois.fr/jeunesse/maison-enfants"
DILA = "Direction de l'information légale et administrative (Premier ministre)"


def mairie(city=CITY, site=SITE, insee="12345"):
    return {
        "nom": f"Mairie - {city}", "categorie": "SL",
        "statut_de_diffusion": "Publiable", "copyright": DILA,
        "url_service_public":
            "https://lannuaire.service-public.gouv.fr/occitanie/aveyron/uuid-abc",
        "code_insee_commune": insee,
        "pivot": json.dumps([{"type_service_local": "mairie",
                               "code_insee_commune": [insee]}]),
        "adresse": json.dumps([{"nom_commune": city, "pays": "France",
                                 "code_postal": "12345"}]),
        "site_internet": json.dumps([{"libelle": "", "valeur": site}]),
    }


def payload(*rows):
    return {"total_count": len(rows), "results": list(rows)}


class DILAMunicipalDomainsTests(unittest.TestCase):
    def test_query_fixed_provider_safe_parameters(self):
        u = urlsplit(dila_query("Saint-Étienne"))
        self.assertEqual(u.scheme, "https")
        self.assertEqual(u.hostname, "api-lannuaire.service-public.gouv.fr")
        fields = parse_qs(u.query)
        self.assertIn('nom LIKE "Saint-Étienne"', fields["where"][0])
        self.assertIn('pivot LIKE "mairie"', fields["where"][0])
        self.assertEqual(fields["limit"], ["30"])

    def test_no_query_injection_from_city(self):
        for city in ('Ville" OR true', 'Saint\\Ville', 'X\nOR true', "", " "):
            with self.subTest(city=city), self.assertRaises(ValueError):
                dila_query(city)

    def test_only_one_exact_dila_mairie_document(self):
        data = payload(mairie())
        self.assertEqual(municipal_site_hosts(CITY, data),
                         frozenset({"www.ville-les-bois.fr"}))
        self.assertEqual(approved_municipal_page_host(PAGE, CITY, data),
                         "agenda.ville-les-bois.fr")

    def test_other_city_and_other_service_fail_closed(self):
        for change in (
            {"nom": "Mairie - Autre-ville"},
            {"categorie": "SIL"},
            {"statut_de_diffusion": "Brouillon"},
            {"copyright": "Portail inconnu"},
            {"code_insee_commune": "99999"},
        ):
            with self.subTest(change=change):
                x = mairie()
                x.update(change)
                self.assertEqual(municipal_site_hosts(CITY, payload(x)),
                                 frozenset())

    def test_postal_city_and_pivot_independently_bound(self):
        x = mairie()
        x["adresse"] = json.dumps([{"nom_commune": "Autre-ville",
                                    "pays": "France"}])
        self.assertFalse(municipal_site_hosts(CITY, payload(x)))
        x = mairie()
        x["pivot"] = json.dumps([{"type_service_local": "gendarmerie",
                                  "code_insee_commune": ["12345"]}])
        self.assertFalse(municipal_site_hosts(CITY, payload(x)))
        x = mairie()
        x["pivot"] = json.dumps([{"type_service_local": "mairie",
                                  "code_insee_commune": ["99999"]}])
        self.assertFalse(municipal_site_hosts(CITY, payload(x)))

    def test_duplicate_mairies_and_truncated_search_fail(self):
        x = mairie()
        self.assertFalse(municipal_site_hosts(CITY, payload(x, deepcopy(x))))
        too_many = payload(x)
        too_many["total_count"] = 31
        self.assertFalse(municipal_site_hosts(CITY, too_many))

    def test_untrusted_shared_and_social_hosts_rejected(self):
        for url in ("https://facebook.com/mairie", "https://www.wordpress.com",
                    "http://www.ville-les-bois.fr/",
                    "https://127.0.0.1/", "https://localhost/",
                    "https://www.ville-les-bois.fr:8080/"):
            self.assertIsNone(_host(url))
            self.assertFalse(municipal_site_hosts(CITY, payload(mairie(site=url))))

    def test_unrelated_and_deceptive_subdomains_rejected(self):
        resp = payload(mairie())
        for url in ("https://ville-les-bois.fr.evil.invalid/lieu",
                    "https://autre-ville.fr/lieu",
                    "https://ville-les-bois.fr@evil.invalid/lieu",
                    "http://agenda.ville-les-bois.fr/lieu"):
            self.assertIsNone(approved_municipal_page_host(url, CITY, resp))
        self.assertEqual(approved_municipal_page_host(
            "https://www.ville-les-bois.fr/lieu", CITY, resp),
            "www.ville-les-bois.fr")

    def test_full_geographic_pipeline_uses_dila_not_manual_host_claims(self):
        from datetime import date
        from ptitesondes_generic_venue_osm_preflight import (
            inspect_group, groups_for_review,
        )
        day = date(2026, 11, 20)
        group = groups_for_review([{
            "collector": "openagenda-v2", "external_id": "123",
            "title": "Conte jeunesse", "city": CITY,
            "venue": "Maison des enfants",
            "date_start": "2026-12-12", "date_end": "2026-12-12",
            "source_url": "https://openagenda.com/agenda-test/events/conte",
        }], day)[0]
        osm = {
            "type": "node", "id": 11, "lat": 44.5, "lon": 2.25,
            "tags": {"name": "Maison des enfants", "addr:city": CITY,
                     "addr:housenumber": "12", "addr:street": "Rue du Parc",
                     "addr:postcode": "12345"},
        }
        address = "12 Rue du Parc 12345 " + CITY
        ban = {"type": "FeatureCollection", "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [2.25, 44.5]},
            "properties": {"type": "housenumber", "score": 0.99,
                           "housenumber": "12", "postcode": "12345",
                           "city": CITY, "label": address},
        }]}
        schema = {"@context": "https://schema.org", "@type": "Place",
                  "name": "Maison des enfants",
                  "address": {"@type": "PostalAddress",
                              "streetAddress": "12 Rue du Parc",
                              "postalCode": "12345", "addressLocality": CITY}}
        html = ("<html><script type='application/ld+json'>"
                + json.dumps(schema)
                + "</script><p>Informations officielles</p></html>")
        def source(uid):
            return {"uid": uid, "location_name": "Maison des enfants",
                    "location_city": CITY,
                    "location_coordinates": {"lat": 44.5, "lon": 2.25}}
        kwargs = {
            "record_fetch": source,
            "osm_fetch": lambda c: {"elements": [osm]},
            "ign_fetch": lambda c: ban,
            "official_page_get": lambda g: (
                "https://agenda.ville-les-bois.fr/maison-enfants", html),
            "approved_official_hosts":
                frozenset({"agenda.ville-les-bois.fr"}),
        }
        good = inspect_group(group, dila_directory_get=lambda c: payload(
            mairie(city=CITY, site="https://www.ville-les-bois.fr/")),
            **kwargs)
        self.assertTrue(good["official_page"]["official_identity_verified"])
        self.assertFalse(good["official_page"]["publication_ready"])
        self.assertEqual(good["official_page"]["public_writes"], 0)
        # A prior host allowlist cannot override a missing DILA attestation.
        spoof = inspect_group(
            group, dila_directory_get=lambda c: payload(mairie(
                city=CITY, site="https://www.other-municipality.fr/")), **kwargs)
        self.assertFalse(spoof["official_page"]["official_identity_verified"])
        error = inspect_group(
            group, dila_directory_get=lambda c: (_ for _ in ()).throw(
                ConnectionError("provider unavailable")), **kwargs)
        self.assertFalse(error["official_page"]["official_identity_verified"])

    def test_without_websites_fails_as_unknown_not_fake_verified(self):
        row = mairie()
        row["site_internet"] = None
        self.assertFalse(municipal_site_hosts(CITY, payload(row)))
        report = redacted_directory_status(CITY, payload(row), PAGE)
        self.assertFalse(report["candidate_page_host_correlated"])
        self.assertFalse(report["publication_ready"])
        self.assertEqual(report["public_writes"], 0)

    def test_directory_authenticity_and_canonical_link(self):
        row = mairie()
        row["url_service_public"] = (
            "https://lannuaire.service-public.gouv.fr.evil.invalid/mairie")
        self.assertFalse(municipal_site_hosts(CITY, payload(row)))
        row = mairie()
        row["url_service_public"] = "https://untrusted.fr/"
        self.assertFalse(municipal_site_hosts(CITY, payload(row)))

    def test_cannot_use_self_declared_openagenda_website_as_dila_evidence(self):
        data = payload(mairie())
        self.assertIsNone(approved_municipal_page_host(
            "https://openagenda.com/example/events/1", CITY, data))
        self.assertIsNone(approved_municipal_page_host(
            "https://pretend-official.fr/lieux/enfants", CITY, data))
        public_report = redacted_directory_status(CITY, data, PAGE)
        self.assertTrue(public_report["directory_municipality_matched"])
        self.assertTrue(public_report["candidate_page_host_correlated"])
        self.assertFalse(public_report["official_venue_verified"])
        self.assertFalse(public_report["event_sessions_verified"])
        self.assertEqual(public_report["public_writes"], 0)
        self.assertNotIn(CITY, json.dumps(public_report))


if __name__ == "__main__":
    unittest.main()
