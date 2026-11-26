"""Offline contracts for independent signed administrative metadata."""
import unittest
from copy import deepcopy
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
for directory in (ROOT / 'scripts', ROOT / 'festival-automation'):
    sys.path.insert(0, str(directory))
from grossesondes_admin_metadata import apply, endpoint, validate_delta

DAY = "2026-11-26"
SITE = "https://festival.example.fr/"
ROW = {"slug": "festival-exemple", "city": "Ville Exemple", "geoCity": "Ville Exemple",
       "geoInsee": "78545", "geoPrecision": "commune", "showOnMap": True,
       "lat": 48.8, "lon": 2.06, "department": None, "region": None,
       "officialSite": SITE, "startDate": "2027-01-01", "endDate": "2027-01-02",
       "geoSource": "https://geo.api.gouv.fr/communes?nom=Ville+Exemple",
       "geoVerification": {"proofMode": "current-edition-commune-direct-official.v1",
          "firstObserved": DAY, "verifiedAt": DAY, "officialSite": SITE,
          "markerMeaning": "centre_indicatif_de_commune"}, "lineup": ["Band"]}
PAYLOAD = {"nom": "Ville Exemple", "code": "78545", "codeDepartement": "78",
           "departement": {"code": "78", "nom": "Yvelines"}, "codeRegion": "11",
           "region": {"code": "11", "nom": "Île-de-France"}}

def doc(*rows):
    return {"schema": 1, "festivals": list(rows)}

class AdminMetadataTests(unittest.TestCase):
    def test_exact_signed_code_and_additive_fields_only(self):
        calls = []
        def read(code):
            calls.append(code)
            return PAYLOAD
        original = doc(deepcopy(ROW))
        out, report = apply(original, original, DAY, reader=read)
        self.assertEqual(calls, ["78545"])
        self.assertEqual(out, doc(dict(ROW, department="78", region="Île-de-France")))
        self.assertEqual(len(report["accepted"]), 1)
        self.assertEqual(original, doc(ROW))
        self.assertEqual(apply(out, out, DAY, reader=read)[1]["checked"], 0)

    def test_invalid_missing_or_conflicting_proof_fails_closed(self):
        for bad in (dict(PAYLOAD, code="78000"), dict(PAYLOAD, nom="Autre ville"),
                    dict(PAYLOAD, codeDepartement="75"), dict(PAYLOAD, region={"code":"11","nom":"Autre"})):
            original = doc(ROW)
            self.assertEqual(apply(original, original, DAY, reader=lambda _: bad)[0], original)
        for row in (dict(ROW, department="75"), dict(ROW, geoVerification=None),
                    dict(ROW, showOnMap=False), dict(ROW, endDate="2026-01-01")):
            original = doc(row)
            self.assertEqual(apply(original, original, DAY, reader=lambda _: PAYLOAD)[0], original)
        self.assertEqual(apply(doc(dict(ROW, lat=48.9)), doc(ROW), DAY,
                               reader=lambda _: self.fail("changed marker"))[1]["checked"], 0)
        for bad in ("78545?x=1", "../78545", "https://example.fr/"):
            with self.assertRaises(ValueError):
                endpoint(bad)

    def test_unrelated_delta_never_authorized(self):
        original = doc(ROW)
        out, report = apply(original, original, DAY, reader=lambda _: PAYLOAD)
        out["festivals"][0]["lineup"] = []
        with self.assertRaises(ValueError):
            validate_delta(original, out, report)

if __name__ == "__main__":
    unittest.main()
