"""Offline security and scope tests for dynamic municipality-based research."""
import json
import unittest
from urllib.parse import urlparse

from national_municipal_source_research import (
    SCHEMA, HOST, MAX_RESULTS, mairie_records_url, _expected_request_path,
    verified_mairie_site, select_dossiers, research,
)

DAY = "2026-11-21"
INSEE = "08188"
CITY = "Monthermé"
ROOT = "https://www.mairie-fictive.fr/"
GOOD = {
    "nom": "Mairie - Monthermé",
    "code_insee_commune": INSEE,
    "statut_de_diffusion": "Publiable",
    "pivot": [{"type_service_local": "mairie",
               "code_insee_commune": [INSEE]}],
    "site_internet": json.dumps([{"valeur": ROOT + "agenda"}]),
}


def queue(rows=None):
    if rows is None:
        rows = [
            {"id": "national-" + format(i, "020x"),
             "name_hint": "Festival inconnu et indépendant " + str(i),
             "edition_year_hint": 2027,
             "city_hint": "Ville " + str(i)}
            for i in range(6)
        ]
    return {
        "schema": "grossesondes.national-festival-discovery-private.v1",
        "dossiers": rows,
    }


class DynamicMunicipalResearchTests(unittest.TestCase):
    def test_fixed_canonical_government_endpoint_no_user_host(self):
        u = mairie_records_url(INSEE)
        self.assertEqual(urlparse(u).hostname, HOST)
        self.assertIn("08188", u)
        from urllib.parse import parse_qs
        self.assertEqual(parse_qs(urlparse(u).query)["where"][0],
                         'code_insee_commune LIKE "08188" AND search(nom, "Mairie")')
        self.assertTrue(_expected_request_path(u).startswith(
            "/api/explore/v2.1/catalog/datasets/"))
        for bad in (
            "https://example.org/" + u.split(HOST, 1)[1],
            u + "&limit=1000",
            u + "#fragment",
            u.replace("08188", "08188%27%20OR%201%3D1"),
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    _expected_request_path(bad)
        for bad in ("", "0", "../admin", "1' OR true", "999999",
                    "0800?", "08188\n"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    mairie_records_url(bad)

    def test_exact_verified_mairie_and_only_one_unique_safe_homepage(self):
        result = verified_mairie_site(
            {"total_count": 1, "results": [GOOD]}, INSEE, CITY)
        self.assertEqual(result, ROOT)
        # Can handle DILA returning the list as an actual list, too.
        other = dict(GOOD, site_internet=[{"valeur": ROOT}])
        self.assertEqual(verified_mairie_site(
            {"total_count": 1, "results": [other]}, INSEE, CITY), ROOT)

    def test_refuses_unknown_city_other_service_multiple_sites_and_social(self):
        versions = (
            dict(GOOD, nom="Mairie - Paris"),
            dict(GOOD, code_insee_commune="75056"),
            dict(GOOD, nom="Salle de concert - Monthermé"),
            dict(GOOD, statut_de_diffusion="Non publiable"),
            dict(GOOD, pivot=[{"type_service_local": "gendarmerie",
                               "code_insee_commune": [INSEE]}]),
            dict(GOOD, site_internet="[]"),
            dict(GOOD, site_internet=[{"valeur": "https://127.0.0.1/"}]),
            dict(GOOD, site_internet=[{"valeur": "http://municipal.example/"}]),
            dict(GOOD, site_internet=[{"valeur": "https://facebook.com/events"}]),
            dict(GOOD, site_internet=[{"valeur": "https://exemple.fr/?admin=1"}]),
        )
        for row in versions:
            with self.subTest(row=row):
                self.assertIsNone(verified_mairie_site(
                    {"total_count": 1, "results": [row]}, INSEE, CITY))
        self.assertIsNone(verified_mairie_site(
            {"total_count": 2, "results": [GOOD, dict(GOOD, site_internet=[
                {"valeur": "https://autre-mairie.fr/"}])]}, INSEE, CITY))
        self.assertIsNone(verified_mairie_site(
            {"total_count": MAX_RESULTS + 1, "results": [GOOD]}, INSEE, CITY))

    def test_no_fixed_town_list_rotation_reaches_all_names(self):
        ids = set()
        for day in range(21, 27):
            from datetime import date
            selected, eligible = select_dossiers(
                queue(), date(2026, 11, day).isoformat(), limit=2)
            self.assertEqual(eligible, 6)
            self.assertEqual(len(selected), 2)
            ids.update(row["id"] for row in selected)
        self.assertEqual(len(ids), 6)

    def test_private_only_even_if_both_government_apis_identify_municipality(self):
        dossier = {
            "id": "national-" + "a" * 20,
            "name_hint": "Festival Foudre inconnu",
            "edition_year_hint": 2027,
            "city_hint": CITY,
        }
        called = []
        def geo(city):
            called.append(("geo", city))
            return {"codeInsee": INSEE, "city": CITY}
        def dila(endpoint):
            called.append(("dila", endpoint))
            return {"total_count": 1, "results": [GOOD]}
        report = research(queue([dossier]), DAY, commune_lookup=geo,
                          directory_fetch=dila, limit=2)
        self.assertEqual(report["schema"], SCHEMA)
        self.assertEqual(report["eligible_city_dossiers_count"], 1)
        self.assertEqual(report["municipal_websites_found_count"], 1)
        self.assertEqual(report["rows"][0]["municipal_website"], ROOT)
        self.assertEqual(len(called), 2)
        self.assertFalse(report["publication_authorized"])
        self.assertEqual(report["publications"], 0)
        self.assertNotIn("startDate", str(report))
        self.assertNotIn("officialSite", str(report))
        self.assertNotIn("approved", str(report).lower())

    def test_unknown_or_ambiguous_geography_does_not_call_other_service(self):
        dossier = {"id": "national-" + "b" * 20,
                   "name_hint": "Foudre Festival 2027", "city_hint": CITY,
                   "edition_year_hint": 2027}
        for answer in (None, {"codeInsee": "75056", "city": "Paris"},
                       {"codeInsee": "oops", "city": CITY}):
            with self.subTest(answer=answer):
                out = research(queue([dossier]), DAY,
                               commune_lookup=lambda city: answer,
                               directory_fetch=lambda url: self.fail(
                                   "DILA must not run without exact commune"))
                self.assertEqual(out["municipal_websites_found_count"], 0)

    def test_openagenda_without_city_is_not_automatically_trusted(self):
        rows = [{"id": "national-" + "c" * 20,
                 "name_hint": "Un festival sans lieu précis",
                 "city_hint": None, "edition_year_hint": 2027}]
        out = research(queue(rows), DAY,
                       commune_lookup=lambda _: self.fail("No geocoding"),
                       directory_fetch=lambda _: self.fail("No request"))
        self.assertEqual(out["eligible_city_dossiers_count"], 0)
        self.assertEqual(out["checked_count"], 0)
        self.assertEqual(out["rows"], [])

    def test_government_directory_error_only_produces_private_diagnostic(self):
        dossier = {"id": "national-" + "d" * 20,
                   "name_hint": "Foudre Festival 2027",
                   "city_hint": CITY, "edition_year_hint": 2027}
        out = research(queue([dossier]), DAY,
                       commune_lookup=lambda _: {"codeInsee": INSEE, "city": CITY},
                       directory_fetch=lambda _: (_ for _ in ()).throw(
                           OSError("Directory unavailable")))
        self.assertEqual(out["rows"][0]["status"],
                         "GOVERNMENT_DIRECTORY_UNAVAILABLE")
        self.assertFalse(out["publication_authorized"])
        self.assertEqual(out["publications"], 0)


if __name__ == "__main__":
    unittest.main()
