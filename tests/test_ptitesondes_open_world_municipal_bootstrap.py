"""Offline open-world OA -> DILA -> municipality bootstrap tests.

No known source/agenda registry, and no public writes.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ptitesondes_open_world_municipal_bootstrap import (
    SCHEMA, bootstrap_municipal_sources, public_redacted_municipal_bootstrap,
)
from ptitesondes_openagenda_national_event_research import _time_sessions

TODAY = date(2026, 11, 21)
KEY = "oa_pk_" + "x" * 32
CITY = "Commune de l'inconnu"
VENUE = "Place des Histoires"
DOMAIN = "www.commune-inconnue.fr"
URL = "https://" + DOMAIN + "/"
EXTERNAL = "https://spectacle-inconnu.fr/agenda/contes-2027"


def slots():
    zone = timezone(timedelta(hours=1))
    beginnings = [datetime(2026, 12, 5, hour, tzinfo=zone)
                  for hour in (10, 14, 17, 18, 19, 20)]
    return [{
        "begin": begin.isoformat(timespec="seconds"),
        "end": (begin + timedelta(minutes=45))
            .isoformat(timespec="seconds"),
    } for begin in beginnings]


def lead():
    return {
        "agenda_uid": 987006, "event_uid": 5099001,
        "agenda_slug": "agenda-inconnu-jamais-configure",
        "title": "Récit musical de la nuit",
        "city_unverified": CITY, "venue_unverified": VENUE,
        "country_code_unverified": "FR",
        "explicit_source_session_intervals": slots(),
        "publication_ready": False, "public_writes": 0,
    }


def event(item=None, **updates):
    item = item or lead()
    data = {
        "uid": item["event_uid"], "state": 2, "status": 1,
        "removed": False, "title": {"fr": item["title"]},
        "timings": item["explicit_source_session_intervals"],
        "location": {
            "name": VENUE, "adminLevel4": CITY, "countryCode": "FR"},
    }
    data.update(updates)
    return data


def directory(site=URL, city=CITY):
    code = "12345"
    item = {
        "nom": "Mairie - " + city,
        "categorie": "SL", "statut_de_diffusion": "true",
        "version_type": "Publiable",
        "copyright":
            "Direction de l'information légale et administrative (Premier ministre)",
        "url_service_public":
            "https://lannuaire.service-public.gouv.fr/occitanie/xx/id",
        "code_insee_commune": code,
        "pivot": json.dumps([
            {"type_service_local": "mairie",
             "code_insee_commune": [code]}]),
        "adresse": json.dumps([
            {"nom_commune": city, "pays": "France"}]),
        "site_internet": json.dumps([
            {"libelle": "", "valeur": site}]),
    }
    return {"total_count": 1, "results": [item]}


def run(item=None, *, agenda=None, oa_event=None, dila=None,
        html=None, html_reader=None, directory_reader=None):
    item = item or lead()
    return bootstrap_municipal_sources(
        item, KEY, TODAY,
        agenda_reader=lambda uid, key: agenda if agenda is not None else {
            "uid": item["agenda_uid"], "slug": item["agenda_slug"]},
        event_reader=lambda uid, eid, key: (
            oa_event if oa_event is not None else event(item)),
        directory_reader=directory_reader or (lambda city:
            dila if dila is not None else directory()),
        municipal_html_reader=html_reader or (lambda url:
            html if html is not None else (
                "<html><body><main><a href='" + EXTERNAL
                + "'>Le spectacle</a>"
                + "<a href='sorties.html'>Programme local</a>"
                + "</main></body></html>")))


class MunicipalBootstrapTests(unittest.TestCase):
    def test_new_agenda_and_unknown_location_bootstrap_without_any_registry(self):
        out = run()
        self.assertEqual(out["status"],
                         "municipal_homepage_source_research_only")
        self.assertTrue(out["municipality_from_live_oa_not_registry"])
        self.assertEqual(out["municipal_origins_verified_by_dila"], 1)
        self.assertEqual(out["municipal_homepages_checked"], 1)
        self.assertEqual(out["source_links_found_in_pages"], 2)
        linked = out["private_link_reports"][0]["source_links"]
        self.assertEqual(linked["source_candidates_this_batch"], 2)
        self.assertEqual(
            [v["url"] for v in linked["source_candidates"]],
            [EXTERNAL, URL + "sorties.html"])
        self.assertFalse(out["organizer_domain_attested"])
        self.assertFalse(out["events_independently_attested"])
        self.assertFalse(out["source_rights_reviewed"])
        self.assertFalse(out["publisher_connected"])
        self.assertEqual(out["public_writes"], 0)

    def test_uncharted_city_is_allowed_but_dila_unavailable_is_not_a_denial(self):
        reading = Mock(side_effect=AssertionError("never fetch unknown city"))
        out = run(directory_reader=lambda city:
                  {"total_count": 0, "results": []}, html_reader=reading)
        self.assertEqual(out["status"], "dila_municipal_domain_not_verified")
        self.assertFalse(out["publication_ready"])
        reading.assert_not_called()
        out = run(directory_reader=lambda city:
                  (_ for _ in ()).throw(OSError("DILA down")),
                  html_reader=reading)
        self.assertEqual(out["status"], "dila_municipal_directory_unavailable")

    def test_different_agenda_uid_slug_or_event_uid_stops_before_dila(self):
        directory_reader = Mock(
            side_effect=AssertionError("should not call DILA"))
        for agenda, ev in [
            ({"uid": 984, "slug": lead()["agenda_slug"]}, event()),
            ({"uid": lead()["agenda_uid"], "slug": "new-slug"}, event()),
            (None, event(uid=89)),
            (None, event(state=3)),
            (None, event(status=3)),
            (None, event(removed=True)),
        ]:
            with self.subTest(agenda=agenda, ev=ev.get("status")):
                out = run(agenda=agenda, oa_event=ev,
                          directory_reader=directory_reader)
                self.assertIn(out["status"], {
                    "live_oa_agenda_identity_conflict",
                    "live_oa_event_identity_or_location_conflict",
                })
        directory_reader.assert_not_called()

    def test_missing_or_changed_local_session_stops_before_directory(self):
        original = lead()
        changed = deepcopy(original["explicit_source_session_intervals"])
        changed[0]["begin"] = "2026-12-05T09:00:00+01:00"
        for ev in (
            event(timings=changed),
            event(timings=[]),
        ):
            out = run(oa_event=ev)
            self.assertEqual(out["status"], "live_oa_explicit_session_changed")

    def test_city_and_venue_changes_need_research_not_implicit_confirmation(self):
        changed = event(location={
            "name": "Autre salle", "adminLevel4": CITY,
            "countryCode": "FR"})
        out = run(oa_event=changed)
        self.assertEqual(out["status"], "live_oa_city_or_venue_changed")
        changed = event(location={
            "name": VENUE, "adminLevel4": "Autre ville",
            "countryCode": "FR"})
        out = run(oa_event=changed)
        self.assertEqual(out["status"], "live_oa_city_or_venue_changed")

    def test_untrusted_international_event_is_not_a_municipal_french_claim(self):
        out = run(oa_event=event(location={
            "name": VENUE, "adminLevel4": CITY, "countryCode": "US"}))
        self.assertEqual(out["status"],
                         "live_oa_event_identity_or_location_conflict")

    def test_two_dila_verified_municipal_roots_do_not_depend_on_curated_sources(self):
        data = directory()
        data["results"][0]["site_internet"] = json.dumps([
            {"libelle": "", "valeur": URL},
            {"libelle": "", "valeur": "https://agenda.commune-inconnue.fr/"},
        ])
        calls = []
        def read(url):
            calls.append(url)
            if url == "https://agenda.commune-inconnue.fr/":
                raise OSError("temporary outage")
            return "<html><a href='" + EXTERNAL + "'>Spectacle</a></html>"
        out = run(dila=data, html_reader=read)
        self.assertEqual(out["municipal_origins_verified_by_dila"], 2)
        self.assertEqual(out["municipal_homepages_checked"], 1)
        self.assertEqual(out["municipal_homepages_unavailable"], 1)
        self.assertEqual(out["status"], "municipal_sources_partial_research")
        self.assertEqual(len(calls), 2)
        self.assertFalse(out["approval_granted"])

    def test_registered_towns_not_required_for_overseas_public_event(self):
        item = lead()
        item["city_unverified"] = "Saint-Denis"
        item["country_code_unverified"] = "RE"
        item["venue_unverified"] = "Théâtre outremer inconnu"
        instants = []
        offset = timezone(timedelta(hours=4))
        for i in range(5):
            instants.append({
                "begin": datetime(2026, 12, 5, 10 + i,
                                  tzinfo=offset).isoformat(),
                "end": datetime(2026, 12, 5, 10 + i, 45,
                                tzinfo=offset).isoformat(),
            })
        item["explicit_source_session_intervals"] = instants
        event_overseas = event(item, location={
            "name": "Théâtre outremer inconnu",
            "adminLevel4": "Saint-Denis",
            "countryCode": "RE",
            "adminLevel1": "La Réunion", "adminLevel2": "La Réunion",
        })
        out = run(item, oa_event=event_overseas, dila=directory(
            site="https://saint-denis.re/", city="Saint-Denis"))
        self.assertEqual(out["municipal_homepages_checked"], 1)
        self.assertEqual(out["status"],
                         "municipal_homepage_source_research_only")

    def test_no_event_type_dictionary_is_used_to_discard_unrecognized_formats(self):
        item = lead()
        item["title"] = "Bric-à-sons célestes de minuit"
        out = run(item, oa_event=event(item))
        self.assertEqual(out["municipal_homepages_checked"], 1)
        self.assertFalse(out["publication_ready"])

    def test_public_summary_contains_counts_only_not_urls_names_or_sessions(self):
        out = run()
        summary = public_redacted_municipal_bootstrap(out)
        doc = json.dumps(summary)
        self.assertNotIn(CITY, doc)
        self.assertNotIn(EXTERNAL, doc)
        self.assertNotIn("2026-12-05", doc)
        self.assertEqual(summary["homepages_checked"], 1)
        with self.assertRaises(ValueError):
            public_redacted_municipal_bootstrap(dict(
                out, status=EXTERNAL))
        with self.assertRaises(ValueError):
            public_redacted_municipal_bootstrap(dict(
                out, organizer_domain_attested=True))

    def test_tampering_cannot_self_approve_a_new_host(self):
        item = lead()
        item["publication_ready"] = True
        out = run(item)
        self.assertEqual(out["status"], "invalid_private_oa_lead")
        self.assertFalse(out["publisher_connected"])


if __name__ == "__main__":
    unittest.main()
