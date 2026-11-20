"""Adversarial offline tests: no numbered address never grants venue approval."""
import json
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_unnumbered_venue_osm_official_hint import (
    named_venue_html, unnumbered_named_venue_hint,
)
from ptitesondes_generic_venue_osm_preflight import inspect_group, audit

CITY = "Ville-les-Bois"
VENUE = "Parc des familles"
GROUP = {"city":CITY, "venue":VENUE, "key":["ville les bois","parc des familles"],
         "uids":["721"], "lead_count":1, "unique_candidate_sessions":1}
CENTER = (44.5,2.25)
URL = "https://www.ville-les-bois.fr/lieux/parc-des-familles"
DAY = date(2026,11,20)


def dila():
    return {"total_count":1,"results":[{
        "nom":"Mairie - "+CITY, "categorie":"SL",
        "version_type":"Publiable", "statut_de_diffusion":"true",
        "copyright":"Direction de l'information légale et administrative (Premier ministre)",
        "url_service_public":"https://lannuaire.service-public.gouv.fr/occitanie/aveyron/uuid",
        "code_insee_commune":"12345",
        "pivot":json.dumps([{"type_service_local":"mairie",
                             "code_insee_commune":["12345"]}]),
        "adresse":json.dumps([{"nom_commune":CITY,"pays":"France"}]),
        "site_internet":json.dumps([
            {"libelle":"","valeur":"https://www.ville-les-bois.fr/"}]),
    }]}


def place_html(name=VENUE):
    return "<html><main><h1>"+name+"</h1><p>Un lieu ouvert aux familles.</p></main></html>"


def jsonld_place(name=VENUE, lat=44.5):
    node={"@type":"Park", "name":name,
          "geo":{"@type":"GeoCoordinates","latitude":lat,"longitude":2.25},
          "address":{"@type":"PostalAddress","addressLocality":CITY,
                     "addressCountry":"FR"}}
    return ("<html><script type='application/ld+json'>"
            +json.dumps(node, ensure_ascii=False)+"</script></html>")


def osm(name=VENUE, lat=44.5, city=CITY):
    tags={"name":name, "leisure":"park"}
    if city is not None:
        tags["addr:city"]=city
    return {"elements":[{"type":"way", "id":771,
                         "center":{"lat":lat,"lon":2.25}, "tags":tags}]}


def lead():
    return {"city":CITY,"venue":VENUE, "title":"Sortie familiale",
            "collector":"openagenda-v2", "external_id":"721",
            "date_start":"2026-12-12","date_end":"2026-12-12",
            "source_url":"https://openagenda.com/demo/events/721_sortie"}


def source(uid):
    return {"uid":uid, "location_city":CITY, "location_name":VENUE,
            "location_coordinates":{"lat":44.5, "lon":2.25}}


class UnnumberedVenueTests(unittest.TestCase):
    def test_named_municipal_page_and_single_osm_object_give_hint_only(self):
        value=unnumbered_named_venue_hint(
            GROUP,CENTER,osm(),dila(),URL,place_html())
        self.assertEqual(value["status"],
                         "named_municipal_venue_and_osm_hint_private_review")
        self.assertTrue(value["official_name_correlated"])
        self.assertTrue(value["osm_geometry_correlated"])
        self.assertTrue(value["city_osm_tag_confirmed"])
        self.assertFalse(value["gps_verified"])
        self.assertFalse(value["official_venue_verified"])
        self.assertFalse(value["event_sessions_verified"])
        self.assertFalse(value["publication_ready"])
        self.assertEqual(value["public_writes"],0)

    def test_no_restriction_to_park_or_a_curated_list_of_types(self):
        group={"city": CITY,"venue":"Esplanade du futur",
               "key":["ville les bois","esplanade du futur"]}
        obj=osm(name="Esplanade du futur")
        obj["elements"][0]["tags"]={"name":"Esplanade du futur",
                                     "highway":"pedestrian",
                                     "addr:city":CITY}
        value=unnumbered_named_venue_hint(
            group,CENTER,obj,dila(),URL,
            place_html("Esplanade du futur"))
        self.assertTrue(value["official_name_correlated"])
        self.assertFalse(value["publication_ready"])
        without_city=osm(city=None)
        value=unnumbered_named_venue_hint(
            GROUP,CENTER,without_city,dila(),URL,place_html())
        self.assertTrue(value["official_name_correlated"])
        self.assertFalse(value["city_osm_tag_confirmed"])

    def test_official_jsonld_identity_and_geo_must_agree(self):
        self.assertTrue(named_venue_html(GROUP,jsonld_place(),CENTER))
        self.assertFalse(named_venue_html(
            GROUP,jsonld_place(lat=44.51),CENTER))
        self.assertFalse(named_venue_html(
            GROUP,jsonld_place(name="Autre parc"),CENTER))
        conflicted=json.dumps([
            {"@type":"Park","name":VENUE},
            {"@type":"Park","name":"Autre parc"}],ensure_ascii=False)
        self.assertFalse(named_venue_html(
            GROUP,"<html><script type='application/ld+json'>"
            +conflicted+"</script></html>",CENTER))

    def test_untrusted_page_or_non_specific_homepage_rejected(self):
        for url,listing,body,loc in (
            ("https://pretend-municipality.example/park",dila(),place_html(),osm()),
            ("https://www.ville-les-bois.fr/",dila(),place_html(),osm()),
            (URL,{"total_count":0,"results":[]},place_html(),osm()),
            (URL,dila(),place_html("Wrong venue"),osm()),
            (URL,dila(),place_html(),osm(name="Other park")),
            (URL,dila(),place_html(),osm(lat=44.52)),
            (URL,dila(),place_html(),{"elements":[
                osm()["elements"][0],
                {**osm()["elements"][0],"id":772}]}),
        ):
            with self.subTest(url=url,body=body,osm=loc):
                value=unnumbered_named_venue_hint(
                    GROUP,CENTER,loc,listing,url,body)
                self.assertFalse(value["official_name_correlated"])
                self.assertFalse(value["publication_ready"])
                self.assertEqual(value["public_writes"],0)

    def test_private_pipeline_counts_hint_but_still_zero_verified_leads(self):
        records=[lead()]
        report=audit(records,DAY,record_fetch=source,
                     osm_fetch=lambda _:osm(),live=True, ign_fetch=None,
                     official_page_get=lambda g:(URL,place_html()),
                     dila_directory_get=lambda city:dila())
        self.assertEqual(report["unknown_unique_venues"],1)
        self.assertEqual(report["unnumbered_named_venue_private_hints"],1)
        self.assertEqual(report[
            "candidate_sessions_with_unnumbered_private_hint"],1)
        self.assertEqual(report["private_reusable_location_proofs"],0)
        self.assertEqual(report["verified_venue_leads"],0)
        self.assertFalse(report["gps_verified"])
        self.assertFalse(report["official_venue_verified"])
        self.assertFalse(report["publication_ready"])
        self.assertEqual(report["public_writes"],0)


if __name__ == "__main__":
    unittest.main()
