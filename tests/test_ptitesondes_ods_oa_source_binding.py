"""Offline adversarial UID binding for ODS-syndicated OpenAgenda venues."""
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ptitesondes_ods_oa_source_binding import (
    ods_source_parts, ods_immutable_source_match,
    ods_origin_agenda_uid, independently_confirm_ods_agenda,
)
from ptitesondes_municipal_official_page_reader import MunicipalOfficialPageReader

CITY = "Ville-les-Bois"
VENUE = "Maison des enfants"
SLUG = "agenda-demo"
UID = "721"
URL = "https://openagenda.com/agenda-demo/events/conte-familial"
OFFICIAL = "https://www.ville-les-bois.fr/lieux/maison-enfants"


def group():
    return {"city": CITY, "venue": VENUE, "uids": [UID]}


def ods():
    return {"uid": int(UID), "canonicalurl": URL,
            "location_city": CITY, "location_name": VENUE,
            "location_countrycode": "FR",
            "location_coordinates": {"lat": 44.5, "lon": 2.25},
            "status": json.dumps({"id": 1, "label": {"fr": "Programmé"}})}


def lead():
    return {"collector": "opendatasoft-index", "city": CITY, "venue": VENUE,
            "external_id": UID, "source_url": URL,
            "title": "Conte familial", "date_start": "2026-12-12",
            "date_end": "2026-12-12"}


def dila():
    return {"total_count": 1, "results": [{
        "nom": "Mairie - " + CITY, "categorie": "SL",
        "version_type": "Publiable", "statut_de_diffusion": "true",
        "copyright": "Direction de l'information légale et administrative (Premier ministre)",
        "url_service_public": "https://lannuaire.service-public.gouv.fr/occitanie/aveyron/uuid",
        "code_insee_commune": "12345",
        "pivot": '[{"type_service_local":"mairie","code_insee_commune":["12345"]}]',
        "adresse": '[{"nom_commune":"Ville-les-Bois","pays":"France"}]',
        "site_internet": '[{"libelle":"","valeur":"https://www.ville-les-bois.fr/"}]',
    }]}


def event():
    return {"uid": int(UID), "state": 2, "status": 1,
            "attendanceMode": 1, "removed": False,
            "location": {"name": VENUE, "adminLevel4": CITY,
                         "countryCode": "FR", "website": OFFICIAL}}


class ODSOAVenueBindingTests(unittest.TestCase):
    def test_human_slug_source_is_candidate_not_uid_proof(self):
        self.assertEqual(ods_source_parts(URL), SLUG)
        self.assertNotIn(UID, URL)
        self.assertTrue(ods_immutable_source_match(group(), UID, URL, ods()))

    def test_source_link_deceptive_or_incorrect_never_accepted(self):
        for url in (
            "http://openagenda.com/agenda-demo/events/conte-familial",
            "https://openagenda.com.evil.test/agenda-demo/events/conte-familial",
            "https://openagenda.com@evil.test/agenda-demo/events/conte-familial",
            "https://openagenda.com/agenda-demo/events/conte?secret=1",
            "https://openagenda.com/agenda-demo/events/conte#frag",
            "https://openagenda.com/agenda-demo/invented/conte",
            "https://openagenda.com/agenda-demo/events/%2Fmalicious",
        ):
            with self.subTest(url=url):
                self.assertIsNone(ods_source_parts(url))
        self.assertIsNone(ods_source_parts(None))

    def test_ods_record_must_bind_uid_url_city_venue_and_country(self):
        cases = (
            {"uid": 9999},
            {"canonicalurl": "https://openagenda.com/agenda-demo/events/other"},
            {"location_city": "Autreville"},
            {"location_name": "Autre lieu"},
            {"location_countrycode": "GB"},
        )
        for patch in cases:
            with self.subTest(patch=patch):
                self.assertFalse(ods_immutable_source_match(
                    group(), UID, URL, {**ods(), **patch}))
        self.assertFalse(ods_immutable_source_match(
            group(), "9999", URL, ods()))

    def test_ods_scheduled_is_json_dict_with_id_one(self):
        for state in (
            {"id": 0}, {"id": 2}, {"id": "1"}, "programmed",
            "not-json", "{invalid", None, 1,
        ):
            with self.subTest(state=state):
                self.assertFalse(ods_immutable_source_match(
                    group(), UID, URL, {**ods(), "status": state}))
        self.assertTrue(ods_immutable_source_match(
            group(), UID, URL, {**ods(), "status": {"id": 1}}))

    def test_missing_conflicting_or_nan_geography_fails_closed(self):
        for point in ({}, {"lat": 99, "lon": 2.25},
                      {"lat": 44.5, "lon": float("nan")}, None):
            with self.subTest(point=point):
                self.assertFalse(ods_immutable_source_match(
                    group(), UID, URL, {
                        **ods(), "location_coordinates": point,
                    }))

    def test_reader_accepts_pinned_ods_only_after_oa_and_dila(self):
        oda = Mock(return_value=ods())
        oa = Mock(return_value=event())
        html = Mock(return_value="<html><p>Lieu municipal.</p></html>")
        reader = MunicipalOfficialPageReader(
            [lead()], [994311], "private-test-read-only-key",
            agenda_reader=lambda aid, key:
                {"uid": aid, "slug": "agenda-demo"},
            event_reader=oa, directory_reader=lambda city: dila(),
            html_reader=html, ods_reader=oda)
        self.assertEqual(reader.official_page_get(group()),
                         (OFFICIAL, "<html><p>Lieu municipal.</p></html>"))
        self.assertEqual(oda.call_count, 1)
        self.assertEqual(oa.call_count, 1)
        self.assertEqual(html.call_count, 1)

    def test_ods_venue_without_oa_website_uses_dila_exact_link(self):
        homepage = "https://www.ville-les-bois.fr/"
        listing = ("<html><main><a href='/lieux/maison-enfants'>"
                   "Maison des enfants</a></main></html>")
        site = Mock(side_effect=lambda url: (
            listing if url == homepage else "<html><p>Lieu vérifiable</p></html>"))
        event_without_site = event()
        event_without_site["location"]["website"] = None
        reader = MunicipalOfficialPageReader(
            [lead()], [994311], "private-test-read-only-key",
            agenda_reader=lambda aid, key: {"uid": aid, "slug": SLUG},
            event_reader=lambda *args: event_without_site,
            directory_reader=lambda city: dila(),
            html_reader=site, ods_reader=lambda uid: ods())
        self.assertEqual(reader.official_page_get(group()), (
            OFFICIAL, "<html><p>Lieu vérifiable</p></html>"))
        self.assertEqual(site.call_count, 2)
        self.assertFalse(hasattr(reader, "publisher"))

    def test_dynamic_unlisted_agenda_confirmed_by_direct_oa(self):
        agenda_id = 887766
        row = {**ods(), "originagenda_uid": agenda_id}
        official_html = "<html><h1>Maison des enfants</h1></html>"
        direct_agenda = Mock(return_value={
            "uid": agenda_id, "slug": SLUG})
        direct_event = Mock(return_value=event())
        website = Mock(return_value=official_html)
        # EMPTY curated list: discovery must not depend on exhaustive
        # pre-registration of every agenda on French territory.
        reader = MunicipalOfficialPageReader(
            [lead()], [], "private-test-read-only-key",
            agenda_reader=direct_agenda, event_reader=direct_event,
            directory_reader=lambda city:dila(), html_reader=website,
            ods_reader=lambda uid:row)
        self.assertEqual(reader.official_page_get(group()),
                         (OFFICIAL, official_html))
        direct_agenda.assert_called_once_with(agenda_id,
                                              "private-test-read-only-key")
        direct_event.assert_called_once_with(
            agenda_id, UID, "private-test-read-only-key")
        website.assert_called_once_with(OFFICIAL)
        self.assertEqual(reader.dynamic_agenda_slug_map, {SLUG: agenda_id})

    def test_unlisted_agenda_missing_or_invalid_uid_blocks(self):
        for bad_id in (None, "not-an-id", 0, False, 10**15):
            row = {**ods(), "originagenda_uid": bad_id}
            direct_agenda = Mock(return_value={"uid": 887766, "slug": SLUG})
            official = Mock(return_value="unreachable")
            reader = MunicipalOfficialPageReader(
                [lead()], [], "private-test-read-only-key",
                agenda_reader=direct_agenda, event_reader=lambda *a:event(),
                directory_reader=lambda city:dila(), html_reader=official,
                ods_reader=lambda uid:row)
            with self.subTest(uid_type=str(bad_id)):
                self.assertEqual(reader.official_page_get(group()),
                                 (None, None))
                direct_agenda.assert_not_called()
                official.assert_not_called()

    def test_unlisted_agenda_wrong_direct_slug_or_uid_blocks(self):
        agenda_id = 887766
        for wrong in ({"uid": agenda_id, "slug": "different-calendar"},
                      {"uid": 123, "slug": SLUG}):
            direct = Mock(return_value=wrong)
            official = Mock(return_value="unreachable")
            reader = MunicipalOfficialPageReader(
                [lead()], [], "private-test-read-only-key",
                agenda_reader=direct, event_reader=lambda *a:event(),
                directory_reader=lambda city:dila(), html_reader=official,
                ods_reader=lambda uid:{**ods(), "originagenda_uid":agenda_id})
            self.assertEqual(reader.official_page_get(group()),
                             (None, None))
            official.assert_not_called()

    def test_curated_agenda_identity_cannot_be_overridden_by_ods(self):
        official = Mock(return_value="unreachable")
        reader = MunicipalOfficialPageReader(
            [lead()], [994311], "private-test-read-only-key",
            agenda_reader=lambda aid, key:{"uid":aid, "slug":SLUG},
            event_reader=lambda *a:event(),
            directory_reader=lambda city:dila(),
            html_reader=official,
            ods_reader=lambda uid:{**ods(), "originagenda_uid": 887766})
        self.assertEqual(reader.official_page_get(group()), (None, None))
        official.assert_not_called()

    def test_direct_agenda_uid_corroboration_is_not_ownership_proof(self):
        row={**ods(), "originagenda_uid":"887766"}
        self.assertEqual(ods_origin_agenda_uid(row),887766)
        self.assertEqual(independently_confirm_ods_agenda(
            row, SLUG,
            lambda uid,key: {"uid":uid, "slug":SLUG},
            "private-test-read-only-key"),887766)
        self.assertIsNone(independently_confirm_ods_agenda(
            row, SLUG,
            lambda uid,key: {"uid":uid, "slug":"other-agenda"},
            "private-test-read-only-key"))

    def test_wrong_ods_record_blocks_oa_and_official_read(self):
        oda = Mock(return_value={**ods(), "uid": 8})
        oa = Mock(return_value=event())
        html = Mock(return_value="not reached")
        reader = MunicipalOfficialPageReader(
            [lead()], [994311], "private-test-read-only-key",
            agenda_reader=lambda aid, key: {"uid": aid, "slug": SLUG},
            event_reader=oa, directory_reader=lambda city: dila(),
            html_reader=html, ods_reader=oda)
        self.assertEqual(reader.official_page_get(group()), (None, None))
        oa.assert_not_called()
        html.assert_not_called()

    def test_different_agenda_uid_blocks_ods_binding(self):
        oda = Mock(return_value=ods())
        reader = MunicipalOfficialPageReader(
            [lead()], [994311], "private-test-read-only-key",
            agenda_reader=lambda aid, key: {"uid": aid, "slug": "other-agenda"},
            event_reader=lambda *args: event(), directory_reader=lambda city:dila(),
            html_reader=lambda url:"never", ods_reader=oda)
        self.assertEqual(reader.official_page_get(group()), (None, None))
        oda.assert_not_called()

    def test_ods_network_failure_blocks_official_page(self):
        reader = MunicipalOfficialPageReader(
            [lead()], [994311], "private-test-read-only-key",
            agenda_reader=lambda aid, key: {"uid": aid, "slug": SLUG},
            event_reader=lambda *args: event(), directory_reader=lambda city:dila(),
            html_reader=lambda url:"never",
            ods_reader=Mock(side_effect=OSError("unavailable")))
        self.assertEqual(reader.official_page_get(group()), (None, None))


if __name__ == "__main__":
    unittest.main()
