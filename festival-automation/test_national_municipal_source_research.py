"""Offline security and scope tests for dynamic municipality-based research."""
import json
import unittest
from urllib.parse import urlparse

from national_municipal_source_research import (
    SCHEMA, HOST, MAX_RESULTS, mairie_records_url, _expected_request_path,
    verified_mairie_site, select_dossiers, research,
    delegated_commune_url, parent_commune_url, _expected_geo_request_path,
    delegated_municipal_commune,
)

DAY = "2026-11-21"
INSEE = "08188"
CITY = "Monthermé"
ROOT = "https://www.mairie-fictive.fr/"
GOOD = {
    "nom": "Mairie - Monthermé",
    "code_insee_commune": INSEE,
    "statut_de_diffusion": "true",
    "pivot": [{"type_service_local": "mairie",
               "code_insee_commune": [INSEE]}],
    # The real DILA record may list the homepage and several service pages.
    "site_internet": json.dumps([
        {"valeur": ROOT.rstrip("/")},
        {"valeur": ROOT + "4442-demande-d-acte.htm"},
    ]),
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
        # Accept the documented public record's string status but not false.
        self.assertEqual(verified_mairie_site(
            {"total_count": 1, "results": [dict(GOOD, statut_de_diffusion=True)]},
            INSEE, CITY), ROOT)
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
            dict(GOOD, statut_de_diffusion="false"),
            dict(GOOD, statut_de_diffusion=False),
            {k: v for k, v in GOOD.items() if k != "statut_de_diffusion"},
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
                               delegated_lookup=lambda _: None,
                               directory_fetch=lambda url: self.fail(
                                   "DILA must not run without exact commune"))
                self.assertEqual(out["municipal_websites_found_count"], 0)

    def test_delegated_municipality_canonical_government_routes(self):
        # Research identity is never a direct festival website permission.
        name = "Saint-Macaire-en-Mauges"
        delegated = delegated_commune_url(name)
        parent = parent_commune_url("49301")
        self.assertEqual(urlparse(delegated).hostname, "geo.api.gouv.fr")
        self.assertIn("communes_associees_deleguees", delegated)
        self.assertEqual(_expected_geo_request_path(delegated),
                         urlparse(delegated).path + "?" +
                         urlparse(delegated).query)
        self.assertEqual(_expected_geo_request_path(parent),
                         urlparse(parent).path + "?" + urlparse(parent).query)
        for bad in (
            delegated.replace("geo.api.gouv.fr", "localhost.evil.example"),
            delegated + "&nom=Paris",
            delegated + "#fragment",
            delegated.replace("Saint-Macaire", "../private"),
            parent.replace("/communes/", "/communes/../admin/"),
            parent.replace("49301", "127.0.0.1"),
            "https://127.0.0.1/communes_associees_deleguees?nom=Paris",
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    _expected_geo_request_path(bad)

    def test_delegated_name_rechecks_no_current_commune_and_exact_parent(self):
        delegated_city, parent = "Saint-Macaire-en-Mauges", "Sèvremoine"
        delegated_response = [{
            "nom": delegated_city, "code": "49301",
            "type": "commune-deleguee", "chefLieu": "49301",
            "codeDepartement": "49"}]
        parent_response = {"nom": parent, "code": "49301",
                           "codeDepartement": "49"}
        requested = []
        def current(url):
            requested.append(("current", url))
            return {"type": "FeatureCollection", "features": []}
        def geo(url):
            requested.append(("geo", url))
            if url == delegated_commune_url(delegated_city):
                return delegated_response
            self.assertEqual(url, parent_commune_url("49301"))
            return parent_response
        result = delegated_municipal_commune(
            delegated_city, reader=geo, current_reader=current)
        self.assertEqual(result["city"], parent)
        self.assertEqual(result["codeInsee"], "49301")
        self.assertEqual(result["delegated_city"], delegated_city)
        self.assertEqual(result["delegated_code_insee"], "49301")
        self.assertEqual(len(requested), 3)
        self.assertEqual(requested[0][0], "current")

        # Integration: only the independent parent mairie, never a venue,
        # geo-pin or festival officialSite, can be recorded as research.
        source = {
            "id": "national-" + "e" * 20,
            "name_hint": "Festival inconnu du village 2027",
            "edition_year_hint": 2027, "city_hint": delegated_city}
        parent_mairie = {
            "nom": "Mairie - Sèvremoine", "code_insee_commune": "49301",
            "statut_de_diffusion": "true",
            "pivot": [{"type_service_local": "mairie",
                       "code_insee_commune": ["49301"]}],
            "site_internet": json.dumps([
                {"valeur": "https://www.sevremoine.fr/"}]),
        }
        looked_up = []
        out = research(
            queue([source]), DAY,
            commune_lookup=lambda city: None,
            delegated_lookup=lambda city: result,
            directory_fetch=lambda u: looked_up.append(u) or {
                "total_count": 1, "results": [parent_mairie]})
        self.assertEqual(out["municipal_websites_found_count"], 1)
        row = out["rows"][0]
        self.assertEqual(row["municipal_website"],
                         "https://www.sevremoine.fr/")
        self.assertEqual(row["parent_commune"], "Sèvremoine")
        self.assertEqual(row["delegated_commune"], delegated_city)
        self.assertEqual(row["administrative_relation"],
                         "COMMUNE_DELEGUEE_RESEARCH_ONLY")
        self.assertIn("49301", looked_up[0])
        self.assertFalse(out["publication_authorized"])
        self.assertEqual(out["publications"], 0)
        self.assertNotIn("officialSite", str(out))
        self.assertNotIn("lat", str(out).lower())

    def test_delegated_ambiguous_or_foreign_relation_never_fetches_mairie(self):
        name = "Village aux noms communs"
        sample = {"nom": name, "code": "49301",
                  "type": "commune-deleguee", "chefLieu": "49301",
                  "codeDepartement": "49"}
        parent = {"nom": "Commune Parente", "code": "49301",
                  "codeDepartement": "49"}
        empty = {"type": "FeatureCollection", "features": []}
        cases = [
            ("current-name-ambiguous",
             {"type": "FeatureCollection", "features": [
                 {"properties": {"nom": name}}]}, [sample], parent),
            ("unreviewed-third-type", empty,
             [dict(sample, type="arrondissement")], parent),
            ("two-homonymous-delegated", empty, [sample, sample], parent),
            ("parent-department-changed", empty, [sample],
             dict(parent, codeDepartement="75")),
            ("foreign-code", empty, [dict(sample, chefLieu="not-code")],
             parent),
            ("different-current-parent", empty, [sample],
             dict(parent, code="75056")),
            ("unavailable-government", empty, [sample], None),
        ]
        for label, current_doc, candidates, parent_doc in cases:
            with self.subTest(label=label):
                def geo(url):
                    if url == delegated_commune_url(name):
                        return candidates
                    return parent_doc
                result = delegated_municipal_commune(
                    name, reader=geo, current_reader=lambda _: current_doc)
                self.assertIsNone(result)
        source = {"id": "national-" + "f" * 20,
                  "name_hint": "Unknown Fest 2027",
                  "edition_year_hint": 2027, "city_hint": name}
        out = research(
            queue([source]), DAY, commune_lookup=lambda _: None,
            delegated_lookup=lambda _: None,
            directory_fetch=lambda _: self.fail(
                "Unproven delegated commune must not reach DILA"))
        self.assertEqual(out["rows"][0]["status"],
                         "COMMUNE_NOT_IDENTIFIED")
        self.assertEqual(out["publications"], 0)

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
