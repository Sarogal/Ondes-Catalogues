"""Fully offline proof and safe opt-in tests for OA + DILA municipal reader."""
import json
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_generic_venue_osm_preflight import inspect_group, groups_for_review
from ptitesondes_municipal_official_page_reader import (
    MunicipalOfficialPageReader, read_official_html,
)

CITY = "Ville-les-Bois"
VENUE = "Maison des enfants"
WEBSITE = "https://agenda.ville-les-bois.fr/maison-enfants"
OA_UID = "721"
AGENDA = 994311
DILA_COPYRIGHT = "Direction de l'information légale et administrative (Premier ministre)"


def lead(uid=OA_UID, slug="agenda-demo"):
    return {"city": CITY, "venue": VENUE, "collector": "openagenda-v2",
            "external_id": uid,
            "source_url": f"https://openagenda.com/{slug}/events/{uid}_conte-jeunesse",
            "title": "Conte jeunesse", "date_start": "2026-12-12",
            "date_end": "2026-12-12"}


def event(uid=OA_UID, website=WEBSITE):
    return {"uid": int(uid), "state": 2, "status": 1,
            "attendanceMode": 1, "removed": False,
            "location": {"name": VENUE, "adminLevel4": CITY,
                         "countryCode": "FR", "website": website}}


def dila():
    return {"total_count": 1, "results": [{
        "nom": "Mairie - " + CITY, "categorie": "SL",
        "statut_de_diffusion": "true", "version_type": "Publiable",
        "copyright": DILA_COPYRIGHT,
        "url_service_public": "https://lannuaire.service-public.gouv.fr/occitanie/aveyron/uuid",
        "code_insee_commune": "12345",
        "pivot": '[{"type_service_local":"mairie","code_insee_commune":["12345"]}]',
        "adresse": '[{"nom_commune":"Ville-les-Bois","pays":"France"}]',
        "site_internet": '[{"libelle":"","valeur":"https://www.ville-les-bois.fr/"}]',
    }]}


def html():
    return "<html><script type='application/ld+json'>" + json.dumps({
        "@type": "Place", "name": VENUE,
        "address": {"streetAddress": "12 Rue du Parc",
                    "postalCode": "12345", "addressLocality": CITY},
    }) + "</script><p>Page de la maison des enfants</p></html>"


def osm():
    return {"type": "node", "id": 13, "lat": 44.5, "lon": 2.25,
            "tags": {"name": VENUE, "addr:city": CITY,
                     "addr:housenumber": "12",
                     "addr:street": "Rue du Parc",
                     "addr:postcode": "12345"}}


def ban():
    return {"type": "FeatureCollection", "features": [{
        "type": "Feature", "properties": {
            "type": "housenumber", "score": 0.99, "housenumber": "12",
            "postcode": "12345", "city": CITY,
            "label": "12 Rue du Parc 12345 " + CITY},
        "geometry": {"type": "Point", "coordinates": [2.25, 44.5]},
    }]}


class MunicipalOfficialPageReaderTests(unittest.TestCase):
    def reader(self, leads=None, *, directory=None, agenda=None,
               events=None, page=None):
        rows = leads if leads is not None else [lead()]
        directory = directory or Mock(return_value=dila())
        agenda = agenda or Mock(return_value={"uid": AGENDA, "slug": "agenda-demo"})
        events = events or Mock(return_value=event())
        page = page or Mock(return_value=html())
        return MunicipalOfficialPageReader(
            rows, [AGENDA], "private-test-key",
            agenda_reader=agenda, event_reader=events,
            directory_reader=directory, html_reader=page,
        ), directory, agenda, events, page

    def test_full_private_pipeline_uses_real_reader_callbacks(self):
        reader, d, a, e, p = self.reader()
        group = groups_for_review([lead()], date(2026, 11, 20))[0]
        result = inspect_group(
            group,
            record_fetch=lambda uid: {
                "uid": uid, "location_name": VENUE,
                "location_city": CITY, "location_coordinates":
                    {"lat": 44.5, "lon": 2.25}},
            osm_fetch=lambda xy: {"elements": [osm()]},
            ign_fetch=lambda candidate: ban(),
            official_page_get=reader.official_page_get,
            dila_directory_get=reader.dila_directory_get,
        )
        self.assertTrue(result["official_page"]["official_identity_verified"])
        self.assertFalse(result["official_page"]["publication_ready"])
        self.assertEqual(result["official_page"]["public_writes"], 0)
        self.assertEqual(d.call_count, 1)
        self.assertEqual(a.call_count, 1)
        self.assertEqual(e.call_count, 1)
        self.assertEqual(p.call_count, 1)

    def test_reader_caches_dila_agendas_and_html(self):
        reader, d, a, e, p = self.reader()
        group = groups_for_review([lead()], date(2026, 11, 20))[0]
        self.assertEqual(reader.official_page_get(group), (WEBSITE, html()))
        self.assertEqual(reader.official_page_get(group), (WEBSITE, html()))
        self.assertEqual(d.call_count, 1)
        self.assertEqual(a.call_count, 1)
        self.assertEqual(p.call_count, 1)

    def test_municipality_homepage_one_hop_to_named_venue(self):
        homepage = "https://www.ville-les-bois.fr/"
        venue_page = homepage + "lieux/maison-enfants"
        listing = ("<html><main><a href='/lieux/maison-enfants'>"
                   "Maison des enfants</a></main></html>")
        page = Mock(side_effect=lambda url:
                    listing if url == homepage else html())
        reader, d, a, e, p = self.reader(
            events=Mock(return_value=event(website=homepage)), page=page)
        group = groups_for_review([lead()], date(2026, 11, 20))[0]
        self.assertEqual(reader.official_page_get(group), (venue_page, html()))
        self.assertEqual(page.call_count, 2)
        self.assertEqual(reader.official_page_get(group), (venue_page, html()))
        self.assertEqual(page.call_count, 2)
        # No third-level navigation or publication.
        self.assertFalse(hasattr(reader, "publisher"))

    def test_missing_openagenda_venue_website_uses_dila_site_only(self):
        home = "https://www.ville-les-bois.fr/"
        target = home + "lieux/maison-enfants"
        directory = ("<html><main><a href='/lieux/maison-enfants'>"
                     "Maison des enfants</a></main></html>")
        page = Mock(side_effect=lambda url: directory if url == home else html())
        source = Mock(return_value=event(website=None))
        reader, _, _, _, _ = self.reader(events=source, page=page)
        group = groups_for_review([lead()], date(2026, 11, 20))[0]
        self.assertEqual(reader.official_page_get(group), (target, html()))
        self.assertEqual(page.call_count, 2)

    def test_missing_openagenda_website_without_exact_venue_link_stays_blocked(self):
        home = "https://www.ville-les-bois.fr/"
        page = Mock(return_value=(
            "<html><a href='/agenda/'>Agenda familles</a></html>"))
        reader, _, _, _, _ = self.reader(
            events=Mock(return_value=event(website="")), page=page)
        group = groups_for_review([lead()], date(2026, 11, 20))[0]
        self.assertEqual(reader.official_page_get(group), (None, None))
        page.assert_called_once_with(home)

    def test_self_declared_conflicting_website_never_falls_back_to_dila(self):
        page = Mock(return_value=html())
        reader, _, _, _, _ = self.reader(events=Mock(return_value=event(
            website="https://fake-municipality.example/lieu")), page=page)
        group = groups_for_review([lead()], date(2026, 11, 20))[0]
        self.assertEqual(reader.official_page_get(group), (None, None))
        page.assert_not_called()

    def test_ambiguous_homepage_links_never_crawl(self):
        homepage = "https://www.ville-les-bois.fr/"
        html_home = ("<html><main>"
                     "<a href='/lieux/maison-enfants'>Maison des enfants</a>"
                     "<a href='/lieux/maison-enfants-2'>Maison des enfants</a>"
                     "</main></html>")
        page = Mock(return_value=html_home)
        reader, d, a, e, p = self.reader(
            events=Mock(return_value=event(website=homepage)), page=page)
        group = groups_for_review([lead()], date(2026, 11, 20))[0]
        self.assertEqual(reader.official_page_get(group), (homepage, html_home))
        self.assertEqual(page.call_count, 1)

    def test_untrusted_oa_website_never_fetched(self):
        reader, d, a, e, p = self.reader(events=Mock(return_value=event(
            website="https://pretend-official.example/lieu")))
        group = groups_for_review([lead()], date(2026, 11, 20))[0]
        self.assertEqual(reader.official_page_get(group), (None, None))
        p.assert_not_called()

    def test_ambiguous_dila_or_invalid_agenda_never_fetched(self):
        for directory, agenda in (
            (Mock(return_value={"total_count": 0, "results": []}), None),
            (None, Mock(return_value={"uid": AGENDA, "slug": "wrong-agenda"})),
        ):
            reader, _, _, _, page = self.reader(directory=directory, agenda=agenda)
            group = groups_for_review([lead()], date(2026, 11, 20))[0]
            self.assertEqual(reader.official_page_get(group), (None, None))
            page.assert_not_called()

    def test_mismatched_uid_city_location_never_fetched(self):
        for change in (
            {"uid": 888},
            {"location": {**event()["location"], "adminLevel4": "Other Town"}},
            {"state": 1},
        ):
            bad = event()
            bad.update(change)
            reader, _, _, _, page = self.reader(
                events=Mock(return_value=bad))
            group = groups_for_review([lead()], date(2026, 11, 20))[0]
            self.assertEqual(reader.official_page_get(group), (None, None))
            page.assert_not_called()

    def test_many_occurrences_sampled_without_blocking_venue(self):
        # Four dates/events in the same place must not automatically
        # exclude this municipality. Only three UID identities are sampled;
        # none of their sessions receives publication approval.
        lead_rows = [lead(str(uid)) for uid in range(721, 725)]
        events = Mock(side_effect=lambda agenda, uid, key: event(uid))
        reader, _, _, _, page = self.reader(leads=lead_rows, events=events)
        group = groups_for_review(lead_rows, date(2026, 11, 20))[0]
        self.assertEqual(reader.official_page_get(group), (WEBSITE, html()))
        self.assertEqual(events.call_count, 3)
        self.assertEqual(page.call_count, 1)

    def test_direct_oa_uid_center_does_not_require_ods_mirror(self):
        from ptitesondes_generic_venue_osm_preflight import source_center
        from ptitesondes_shared_venue_location_evidence import (
            mint_private_location_proof, location_from_proof,
        )
        direct = event()
        direct["location"].update({"latitude": 44.5, "longitude": 2.25})
        ods = Mock(side_effect=AssertionError("ODS mirror must not be read"))
        reader = MunicipalOfficialPageReader(
            [lead()], [AGENDA], "private-test-key",
            agenda_reader=Mock(return_value={
                "uid": AGENDA, "slug": "agenda-demo"}),
            event_reader=Mock(return_value=direct),
            directory_reader=Mock(return_value=dila()),
            html_reader=Mock(return_value=html()),
            ods_reader=ods,
        )
        group = groups_for_review([lead()], date(2026, 11, 20))[0]
        center, why = source_center(
            group, lambda uid: reader.source_record_for_group(group, uid))
        self.assertEqual(center, (44.5, 2.25))
        self.assertIsNone(why)
        evidence = inspect_group(
            group,
            record_fetch=Mock(side_effect=AssertionError("ODS forbidden")),
            osm_fetch=Mock(side_effect=AssertionError("OSM not needed")),
            ign_fetch=lambda candidate: ban(),
            official_page_get=reader.official_page_get,
            dila_directory_get=reader.dila_directory_get,
            official_geocode=True,
            source_record_from_reader=reader.source_record_for_group,
            shared_proof_day=date(2026, 11, 20))
        self.assertTrue(evidence["shared_location_proof_private_review"])
        self.assertEqual(evidence["status"],
                         "official_address_ban_private_review")
        self.assertTrue(evidence["official_geocode"][
            "independent_geo_correlated"])
        self.assertFalse(evidence["official_geocode"]["publication_ready"])
        self.assertEqual(evidence["official_geocode"]["public_writes"], 0)
        proof = mint_private_location_proof(
            group, dila(), WEBSITE, html(), lambda candidate: ban(),
            date(2026, 11, 20), source_center=center)
        self.assertIsNotNone(proof)
        self.assertIsNotNone(location_from_proof(
            proof, CITY, VENUE, date(2026, 11, 20), center))
        ods.assert_not_called()

    def test_shared_private_proof_report_is_not_publication_admission(self):
        from ptitesondes_generic_venue_osm_preflight import audit
        today = date(2026, 11, 20)
        direct = event()
        direct["location"].update({"latitude":44.5, "longitude":2.25})
        reader, _, _, _, _ = self.reader(
            events=Mock(return_value=direct))
        report = audit(
            [lead()], today,
            record_fetch=Mock(side_effect=AssertionError("ODS forbidden")),
            osm_fetch=Mock(side_effect=AssertionError("OSM not needed")),
            live=True, ign_fetch=lambda candidate: ban(),
            official_page_get=reader.official_page_get,
            dila_directory_get=reader.dila_directory_get,
            official_geocode=True,
            source_record_from_reader=reader.source_record_for_group,
            shared_proof_preview=True)
        self.assertEqual(report["private_reusable_location_proofs"], 1)
        self.assertEqual(report["leads_with_private_reusable_proof"], 1)
        self.assertEqual(report["verified_venue_leads"], 0)
        self.assertFalse(report["publication_ready"])
        self.assertFalse(report["gps_verified"])
        self.assertEqual(report["public_writes"], 0)
        self.assertEqual(len(report["records"]), 1)
        self.assertTrue(report["records"][0][
            "shared_location_proof_private_review"])

    def test_second_independent_geo_read_failure_cannot_mint_shared_proof(self):
        today = date(2026, 11, 20)
        direct = event()
        direct["location"].update({"latitude":44.5, "longitude":2.25})
        reader, _, _, _, _ = self.reader(
            events=Mock(return_value=direct))
        group = groups_for_review([lead()], today)[0]
        first_ok_second_error = Mock(side_effect=[
            ban(), {"type":"FeatureCollection", "features":[]}])
        result = inspect_group(
            group, record_fetch=Mock(side_effect=AssertionError("ODS forbidden")),
            osm_fetch=Mock(side_effect=AssertionError("OSM not needed")),
            ign_fetch=first_ok_second_error,
            official_page_get=reader.official_page_get,
            dila_directory_get=reader.dila_directory_get,
            official_geocode=True,
            source_record_from_reader=reader.source_record_for_group,
            shared_proof_day=today)
        self.assertEqual(first_ok_second_error.call_count, 2)
        self.assertTrue(result["official_geocode"]["independent_geo_correlated"])
        self.assertFalse(result["shared_location_proof_private_review"])
        self.assertFalse(result["official_geocode"]["publication_ready"])

    def test_direct_oa_center_rejects_conflicting_uid_agenda_and_gps(self):
        from ptitesondes_generic_venue_osm_preflight import source_center
        group = groups_for_review([lead()], date(2026, 11, 20))[0]
        valid = event()
        valid["location"].update({"latitude":44.5, "longitude":2.25})
        badcases = [
            ({"uid":722}, "agenda-demo"),
            ({"state":1}, "agenda-demo"),
            ({"location":{**valid["location"], "adminLevel4":"other town"}}, "agenda-demo"),
            ({"location":{**valid["location"], "latitude": float("nan")}}, "agenda-demo"),
            ({"location":{**valid["location"], "longitude": 200}}, "agenda-demo"),
            ({}, "different-slug"),
        ]
        for change, slug in badcases:
            with self.subTest(change=change, slug=slug):
                bad = {**valid, **change}
                reader = MunicipalOfficialPageReader(
                    [lead()], [AGENDA], "private-test-key",
                    agenda_reader=Mock(return_value={"uid":AGENDA, "slug":slug}),
                    event_reader=Mock(return_value=bad),
                    directory_reader=Mock(side_effect=AssertionError("no DILA read")),
                    html_reader=Mock(side_effect=AssertionError("no HTML read")),
                    ods_reader=Mock(side_effect=AssertionError("no ODS read")),
                )
                center, why = source_center(
                    group, lambda uid: reader.source_record_for_group(group, uid))
                self.assertIsNone(center)
                self.assertIsNotNone(why)

    def test_direct_oa_center_rejects_ambiguous_source_binding(self):
        from ptitesondes_generic_venue_osm_preflight import source_center
        entries = [lead(), lead(slug="other-agenda")]
        group = groups_for_review(entries, date(2026, 11, 20))[0]
        reader, _, agenda, events, page = self.reader(leads=entries)
        center, why = source_center(
            group, lambda uid: reader.source_record_for_group(group, uid))
        self.assertIsNone(center)
        self.assertIsNotNone(why)
        agenda.assert_not_called()
        events.assert_not_called()
        page.assert_not_called()

    def test_html_reader_validates_redirects_and_content_type(self):
        class Response:
            def __init__(self, target=WEBSITE, kind="text/html", data=b"hello"):
                self.status = 200
                self.target = target
                self.headers = {"Content-Type": kind}
                self.data = data
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def geturl(self):
                return self.target
            def read(self, size):
                return self.data[:size]
        self.assertEqual(read_official_html(
            WEBSITE, opener=lambda req, timeout: Response()), "hello")
        for bad in (
            Response(target="https://other-site.fr/redirect"),
            Response(kind="application/json"), Response(data=b""),
        ):
            with self.assertRaises(ValueError):
                read_official_html(
                    WEBSITE, opener=lambda req, timeout, r=bad: r)

    def test_reader_never_calls_network_on_no_matching_private_oa_lead(self):
        reader, d, a, e, p = self.reader(leads=[])
        group = {"city": CITY, "venue": VENUE, "uids": [OA_UID]}
        self.assertEqual(reader.official_page_get(group), (None, None))
        d.assert_not_called()
        a.assert_not_called()
        e.assert_not_called()
        p.assert_not_called()

    def test_unavailable_event_or_html_fails_closed(self):
        for fail_event in (True, False):
            bad = Mock(side_effect=OSError("unavailable"))
            reader, _, _, _, page = self.reader(
                events=bad if fail_event else None,
                page=bad if not fail_event else None)
            group = groups_for_review([lead()], date(2026, 11, 20))[0]
            self.assertEqual(reader.official_page_get(group), (None, None))


if __name__ == "__main__":
    unittest.main()
