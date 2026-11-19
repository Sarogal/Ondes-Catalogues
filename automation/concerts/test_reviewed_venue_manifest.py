"""Offline regression for data-driven reviewed venue contract and audit."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import MappingProxyType

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import generic_music_event as generic
import venue_admission_audit as admission


def load(data):
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "reviewed.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return generic.load_specs(path)


class ReviewedVenueManifestTests(unittest.TestCase):
    def setUp(self):
        self.pilot = json.loads(generic.MANIFEST.read_text(encoding="utf-8"))

    def test_pilot_identity_preserved_and_mapping_immutable(self):
        self.assertEqual(set(generic.SPECS), {"la-rayonne", "le-metronum"})
        self.assertIsInstance(generic.SPECS, MappingProxyType)
        with self.assertRaises(TypeError):
            generic.SPECS["new-venue"] = {}
        with self.assertRaises(TypeError):
            generic.SPECS["la-rayonne"]["host"] = "evil.example"

    def test_unreviewed_discovery_cannot_grant_host(self):
        malicious = {
            "venue": "Fake Venue", "city": "Paris", "department": "75",
            "sourceUrl": "https://example.org/official",
            "sourcePage": "https://example.org/agenda",
        }
        self.assertIsNone(generic.trusted_spec(malicious))
        self.assertNotIn("example.org", generic.ALLOWED_HOSTS)

    def test_extra_keys_bad_schema_wrong_domain_and_identity_fail_closed(self):
        mutations = [
            lambda x: x.update(schema="source-list"),
            lambda x: x.update(venues=[]),
            lambda x: x["venues"]["la-rayonne"].update(
                concertNames=["UNTRUSTED BAND"]),
            lambda x: x["venues"]["la-rayonne"].update(
                base="http://larayonne.org/"),
            lambda x: x["venues"]["la-rayonne"].update(
                host="larayonne.org.evil.example"),
            lambda x: x["venues"]["la-rayonne"].update(
                host="www.larayonne.org"),
            lambda x: x["venues"]["la-rayonne"].update(
                name=" "),
            lambda x: x["venues"]["la-rayonne"].update(
                department="UNKNOWN"),
            lambda x: x["venues"].update(
                {"bad/id": x["venues"]["la-rayonne"]}),
            lambda x: x["venues"].update(
                {"copy": x["venues"]["la-rayonne"]}),
        ]
        for mutate in mutations:
            data = copy.deepcopy(self.pilot)
            mutate(data)
            with self.subTest(mutation=repr(mutate)):
                with self.assertRaises(ValueError):
                    load(data)

    def test_separate_official_venues_can_share_host_after_review(self):
        data = copy.deepcopy(self.pilot)
        data["venues"]["second-hall"] = {
            "name": "Second Hall", "city": "Lyon", "department": "69",
            "host": "larayonne.org", "base": "https://larayonne.org/"}
        specs = load(data)
        self.assertEqual(specs["second-hall"]["name"], "Second Hall")

    def test_legitimate_www_host_and_corsican_department_can_be_reviewed(self):
        data = copy.deepcopy(self.pilot)
        data["venues"]["corsica-hall"] = {
            "name": "Corsica Hall", "city": "Ajaccio", "department": "2A",
            "host": "www.corsica.example", "base": "https://www.corsica.example/"}
        self.assertIn("corsica-hall", load(data))


class VenueAdmissionAuditTests(unittest.TestCase):
    def setUp(self):
        self.sources = {"schema": "grossesondes.concert.sourcelist.v1",
                        "venues": [
                            {"name": "La Rayonne", "city": "Villeurbanne",
                             "department": "69", "url": "https://larayonne.org/"},
                            {"name": "New Hall", "city": "Lyon",
                             "department": "69", "url": "https://venue.example/"},
                            {"name": "Invalid Source", "city": "Unknown",
                             "department": "00", "url": "http://bad.example/"}
                        ]}
        self.catalogue = {"schemaVersion": 1, "events": [
            {"venueId": "la-rayonne"}, {"venueId": "la-rayonne"}],
            "venues": [
                {"id": "la-rayonne", "name": "La Rayonne",
                 "city": "Villeurbanne", "department": "69",
                 "address": "7 rue Henri Legay",
                 "geoSource": "https://larayonne.org/evenement/1/"},
                {"id": "new-hall", "name": "New Hall", "city": "Lyon",
                 "department": "69", "address": "5 avenue de Test",
                 "geoSource": "https://venue.example/contact/"}]}

    def test_exact_matching_is_review_only(self):
        r = admission.evaluate(self.sources, self.catalogue)
        self.assertEqual(r["sourceCount"], 3)
        self.assertEqual(r["exactVenueMatches"], 2)
        self.assertEqual(r["unmatchedSources"], 1)
        self.assertEqual(r["reviewedVenueMatches"], 1)
        self.assertFalse(r["automaticTrustGranted"])
        self.assertFalse(r["publicationAllowed"])
        rows = {x["venueId"]: x for x in r["reviewQueue"]}
        self.assertEqual(rows["new-hall"]["reviewState"],
                         "needs_independent_official_event_proof")
        self.assertFalse(rows["new-hall"]["automaticTrustGrantedByAudit"])
        self.assertEqual(rows["la-rayonne"]["publishedEventsForVenue"], 2)

    def test_untrusted_domain_and_placeholder_geo_never_auto_admitted(self):
        self.sources["venues"][1]["url"] = "https://evil.example@venue.example/"
        r = admission.evaluate(self.sources, self.catalogue)
        self.assertEqual(r["reviewQueue"][0]["reviewState"],
                         "source_domain_invalid")
        self.sources["venues"][1]["url"] = "https://venue.example/"
        self.catalogue["venues"][1]["address"] = "Adresse exacte à vérifier"
        r = admission.evaluate(self.sources, self.catalogue)
        self.assertEqual(r["reviewQueue"][0]["reviewState"],
                         "needs_geographic_corroboration")

    def test_duplicated_public_identity_never_passes(self):
        self.catalogue["venues"].append(
            copy.deepcopy(self.catalogue["venues"][1]))
        r = admission.evaluate(self.sources, self.catalogue)
        self.assertEqual(r["ambiguousMatches"], 1)
        self.assertEqual(r["exactVenueMatches"], 1)

    def test_invalid_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            admission.evaluate({"venues": []}, self.catalogue)
        with self.assertRaises(ValueError):
            admission.evaluate(self.sources, {"events": [], "venues": []})


if __name__ == "__main__":
    unittest.main()
