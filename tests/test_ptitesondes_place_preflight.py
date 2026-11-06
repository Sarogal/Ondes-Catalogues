"""Independent PUBLIC validation tests: no network, no new claims."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from ptitesondes_place_preflight import FACTS,ANCHORS,examine,verify_private,official_proof
from ptitesondes_places import assert_append_only,validate

TODAY=date(2026,11,6)
CATALOGUE=json.loads((ROOT/"docs/ptitesondes/lieux.json").read_text(encoding="utf-8"))
VENUE=dict(FACTS,lat=47.2035757,lng=-1.6073739,reviewed_at="2026-11-06")

def private():
    return {"schema":"ptitesondes.place_release_review.v1","date":"2026-11-06",
            "mode":"private_proposal_only","safe_to_publish":False,
            "records":[{"city":"Nantes","venue":"Ludothèque Bellevue",
                        "status":"requires_independent_public_preflight"}],
            "proposals":[deepcopy(VENUE)]}

def page():
    return "<html><body>"+"".join("<p>"+x+"</p>" for x in ANCHORS)+"</body></html>"

def geo():
    return ('<osm version="0.6"><node id="2810810943" lat="47.2035757" '
            'lon="-1.6073739"><tag k="name" v="La ludothèque de la Meta"/>'
            '<tag k="amenity" v="toy_library"/><tag k="addr:city" v="Nantes"/>'
            '<tag k="addr:street" v="Rue Firmin Colas"/>'
            '<tag k="addr:housenumber" v="20"/><tag k="addr:postcode" v="44100"/>'
            '</node></osm>')

class PlacePreflightTests(unittest.TestCase):
    def test_verified_proposal_is_append_only(self):
        state,after=examine(private(),CATALOGUE,page(),geo(),TODAY)
        self.assertEqual(state,"independently_verified")
        self.assertEqual(len(after["places"]),len(CATALOGUE["places"])+1)
        self.assertEqual(after["places"][:-1],CATALOGUE["places"])
        self.assertEqual(after["places"][-1]["age_min"],None)
        self.assertEqual(after["places"][-1]["age_max"],None)
        self.assertEqual(validate(after),len(after["places"]))
        assert_append_only(CATALOGUE,after)
        state2,same=examine(private(),after,page(),geo(),TODAY)
        self.assertEqual(state2,"already_public")
        self.assertEqual(after,same)

    def test_private_is_not_an_approval(self):
        for key,bad in (("safe_to_publish",True),("schema","wrong"),
                        ("mode","approved")):
            p=private()
            p[key]=bad
            with self.subTest(key=key),self.assertRaises(ValueError):
                examine(p,CATALOGUE,page(),geo(),TODAY)
        p=private()
        p["records"][0]["status"]="not_configured"
        with self.assertRaises(ValueError):
            examine(p,CATALOGUE,page(),geo(),TODAY)

    def test_forged_editorial_claims_are_blocked(self):
        for key,bad in (("age_min",0),("age_max",18),("admission","gratuit"),
                        ("address","25 rue du Jamet, 44100 Nantes"),
                        ("postal_code","99999"),("category","musee-enfants"),
                        ("is_publicly_accessible",False),
                        ("activities",["jeu inventé"])):
            p=private()
            p["proposals"][0][key]=bad
            with self.subTest(key=key),self.assertRaises(ValueError):
                examine(p,CATALOGUE,page(),geo(),TODAY)
        with self.assertRaises(ValueError):
            examine(private(),CATALOGUE,page().replace("8,80","0,00"),geo(),TODAY)

    def test_html_script_tags_cannot_forge_evidence(self):
        html="<html><script>"+" ".join(ANCHORS)+"</script></html>"
        with self.assertRaises(ValueError):
            official_proof(html)

    def test_osm_exact_object_and_address(self):
        for altered in (geo().replace('id="2810810943"','id="123"'),
                        geo().replace('v="20"','v="25"'),
                        geo().replace('v="Nantes"','v="Paris"'),
                        geo().replace('v="toy_library"','v="library"'),
                        geo().replace('lat="47.2035757"','lat="47.5000000"')):
            with self.subTest(xml=altered[:55]),self.assertRaises(ValueError):
                examine(private(),CATALOGUE,page(),altered,TODAY)

    def test_stale_private_or_added_field(self):
        for stamp in ("2026-10-01","2026-11-07","not-a-date"):
            p=private()
            p["proposals"][0]["reviewed_at"]=stamp
            with self.subTest(stamp=stamp),self.assertRaises(ValueError):
                verify_private(p,TODAY)
        p=private()
        p["proposals"][0]["unreviewed_info"]="foo"
        with self.assertRaises(ValueError):
            verify_private(p,TODAY)

    def test_alias_duplicate_stays_blocked(self):
        old=deepcopy(CATALOGUE)
        old["places"].append(dict(VENUE,id="nantes-ludotheque-meta-alias",
                                  name="La ludothèque de la Meta"))
        with self.assertRaises(ValueError):
            examine(private(),old,page(),geo(),TODAY)
