"""Offline adversarial tests of municipal, OA and unlisted event *claims*."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_independent_municipal_event_research import (
    corroborate_municipal_event_claims, public_redacted_municipal_event_summary,
)

DAY = date(2026, 11, 21)
KEY = "oa_pk_" + "k" * 40
CITY = "La Ville Inconnue"
VENUE = "Salle musicale sans adresse"
MUNICIPAL = "https://www.ville-inconnue.fr/programmation/jeunesse"
UNKNOWN = "https://organisateur-nouveau.fr/spectacle"
TITLE = "Contes en ondes"


def timing(hour):
    start = datetime(2026, 12, 5, hour, 0,
                     tzinfo=timezone(timedelta(hours=1)))
    end = start + timedelta(minutes=50)
    return {"begin": start.isoformat(timespec="seconds"),
            "end": end.isoformat(timespec="seconds")}


def lead(*hours):
    return {
        "agenda_uid": 9000123, "agenda_slug": "agenda-nouveau-non-liste",
        "event_uid": 707799, "title": TITLE,
        "city_unverified": CITY, "venue_unverified": VENUE,
        "explicit_source_session_intervals": [
            timing(hour) for hour in (hours or (10, 15))],
        "publication_ready": False, "public_writes": 0,
    }


def schema_event(slot, *, title=TITLE, city=CITY, venue=VENUE,
                 status=None):
    event = {"@type": "ChildrensEvent", "name": title,
             "startDate": slot["begin"], "endDate": slot["end"],
             "location": {
                 "name": venue,
                 "address": {"addressLocality": city}}}
    if status is not None:
        event["eventStatus"] = status
    return event


def html(events, *, links=(UNKNOWN,)):
    content = "<html><body><main>"
    for href in links:
        content += "<a href='" + href + "'>Voir le programme</a>"
    content += "<script type='application/ld+json'>" + json.dumps({
        "@context": "https://schema.org",
        "@graph": events}, ensure_ascii=False) + "</script></main></body></html>"
    return content


def dila(site="https://www.ville-inconnue.fr/", city=CITY):
    code = "12345"
    return {"total_count": 1, "results": [{
        "nom": "Mairie - " + city, "categorie": "SL",
        "statut_de_diffusion": "true", "version_type": "Publiable",
        "copyright":
            "Direction de l'information légale et administrative (Premier ministre)",
        "url_service_public":
            "https://lannuaire.service-public.gouv.fr/test/municipality",
        "code_insee_commune": code,
        "pivot": json.dumps([{
            "type_service_local": "mairie",
            "code_insee_commune": [code]}]),
        "adresse": json.dumps([{
            "nom_commune": city, "pays": "France"}]),
        "site_internet": json.dumps([{"libelle": "", "valeur": site}]),
    }]}


def run(item=None, *, municipal_html=None, organizer_html=None,
        directory=None, agenda=None, event=None,
        municipality_url=MUNICIPAL, discovered_url=UNKNOWN):
    item = item or lead()
    events = [schema_event(slot)
              for slot in item["explicit_source_session_intervals"]]
    program = (html(events) if municipal_html is None else municipal_html)
    external = (html(events, links=()) if organizer_html is None
                else organizer_html)
    def live_event(uid, eid, key):
        return event if event is not None else {
            "uid": item["event_uid"],
            "state": 2, "status": 1, "removed": False,
            "title": {"fr": item["title"]},
            "timings": item["explicit_source_session_intervals"],
            "location": {
                "name": item["venue_unverified"],
                "adminLevel4": item["city_unverified"],
                "countryCode": "FR"},
        }
    return corroborate_municipal_event_claims(
        item, municipality_url, discovered_url, KEY, DAY,
        directory_reader=lambda city:
            dila() if directory is None else directory,
        municipal_html_reader=lambda url: program,
        external_html_reader=lambda url: external,
        oa_agenda_reader=lambda uid, key:
            agenda if agenda is not None else {
                "uid": item["agenda_uid"], "slug": item["agenda_slug"]},
        oa_event_reader=live_event)


class MunicipalThreeSourceTests(unittest.TestCase):
    def test_three_distinct_web_and_api_claims_for_each_exact_showtime(self):
        out = run()
        self.assertEqual(out["status"],
                         "three_sites_same_exact_session_claims_research_only")
        self.assertTrue(out["municipal_page_host_correlated_with_live_dila"])
        self.assertTrue(out["municipal_source_link_confirmed"])
        self.assertEqual(out["municipal_program_exact_claims_count"], 2)
        self.assertEqual(out["third_party_exact_claims_count"], 2)
        self.assertEqual(out["triple_corresponding_session_count"], 2)
        self.assertFalse(out["source_authors_proved_independent"])
        self.assertFalse(out["organizer_domain_independently_owned"])
        self.assertFalse(out["source_rights_reviewed"])
        self.assertFalse(out["editorial_scope_verified"])
        self.assertFalse(out["venue_geography_verified"])
        self.assertFalse(out["publication_ready"])
        self.assertEqual(out["public_writes"], 0)

    def test_just_a_municipal_link_cannot_confirm_showtimes(self):
        out = run(municipal_html=html([]))
        self.assertEqual(out["status"],
                         "municipal_link_but_no_exact_program_session")
        self.assertEqual(out["triple_corresponding_session_count"], 0)

    def test_correct_title_but_wrong_hours_never_proves_other_session(self):
        expected = lead(10, 15)
        municipality = html([schema_event(timing(10))])
        external = html([schema_event(timing(15))], links=())
        out = run(expected, municipal_html=municipality,
                  organizer_html=external)
        self.assertEqual(out["status"], "no_shared_exact_claimed_session")
        self.assertEqual(out["municipal_program_exact_claims_count"], 1)
        self.assertEqual(out["third_party_exact_claims_count"], 1)
        self.assertEqual(out["triple_corresponding_session_count"], 0)

    def test_organizer_link_after_eighty_other_links_is_still_found(self):
        noise = tuple(
            f"https://unrelated-{i}.fr/a" for i in range(85))
        municipal = html(
            [schema_event(timing(10))], links=noise + (UNKNOWN,))
        out = run(lead(10), municipal_html=municipal)
        self.assertEqual(out["status"],
                         "three_sites_same_exact_session_claims_research_only")
        self.assertTrue(out["municipal_source_link_confirmed"])

    def test_unknown_municipal_link_must_exist_exactly(self):
        no_link = html([schema_event(timing(10))], links=())
        out = run(lead(10), municipal_html=no_link)
        self.assertEqual(out["status"],
                         "municipal_page_no_exact_source_link")
        similar = html([schema_event(timing(10))],
                       links=(UNKNOWN + "-evil",))
        out = run(lead(10), municipal_html=similar)
        self.assertEqual(out["status"],
                         "municipal_page_no_exact_source_link")

    def test_spoofed_municipal_domain_fails_before_fetching_external(self):
        out = run(directory=dila(site="https://other-municipality.fr/"))
        self.assertEqual(out["status"],
                         "municipal_page_not_correlated_with_dila")
        out = run(municipality_url="https://www.ville-inconnue.fr.evil.fr/program")
        self.assertEqual(out["status"],
                         "municipal_page_not_correlated_with_dila")

    def test_same_host_claims_are_not_counted_as_distinct_sources(self):
        out = run(discovered_url="https://www.ville-inconnue.fr/other")
        self.assertEqual(out["status"],
                         "unverified_or_incomplete_research_source")

    def test_cancelled_municipal_session_is_not_positive(self):
        item = lead(10)
        municipal = html([schema_event(
            timing(10), status="https://schema.org/EventCancelled")])
        out = run(item, municipal_html=municipal)
        self.assertEqual(out["status"],
                         "municipal_link_but_no_exact_program_session")
        self.assertEqual(out["third_party_exact_claims_count"], 0)

    def test_cancelled_external_session_is_not_positive(self):
        item = lead(10)
        external = html([schema_event(
            timing(10), status={"@id": "https://schema.org/EventCancelled"})],
            links=())
        out = run(item, organizer_html=external)
        self.assertEqual(out["status"],
                         "no_shared_exact_claimed_session")
        self.assertEqual(out["triple_corresponding_session_count"], 0)

    def test_changed_oa_schedule_or_status_holds_even_if_pages_match(self):
        item = lead(10)
        changed = {
            "uid": item["event_uid"], "state": 2, "status": 1,
            "title": {"fr": item["title"]},
            "location": {"name": VENUE, "adminLevel4": CITY,
                         "countryCode": "FR"},
            "timings": [timing(11)]}
        out = run(item, event=changed)
        self.assertEqual(out["status"], "oa_or_third_party_claims_not_current")
        changed["timings"] = item["explicit_source_session_intervals"]
        changed["status"] = 2
        out = run(item, event=changed)
        self.assertEqual(out["status"], "oa_or_third_party_claims_not_current")

    def test_six_same_day_and_new_venue_and_organizer_are_not_list_blocked(self):
        item = lead(9, 10, 11, 14, 15, 17)
        item["title"] = "Improvisation sonore jamais catégorisée"
        events = [schema_event(t,
                               title=item["title"]) for t in
                  item["explicit_source_session_intervals"]]
        out = run(item, municipal_html=html(events),
                  organizer_html=html(events, links=()))
        self.assertEqual(out["triple_corresponding_session_count"], 6)
        self.assertFalse(out["editorial_scope_verified"])

    def test_source_page_unavailable_is_not_misread_as_negative_evidence(self):
        item = lead()
        def fail(_):
            raise OSError("sensitive network details")
        out = corroborate_municipal_event_claims(
            item, MUNICIPAL, UNKNOWN, KEY, DAY,
            directory_reader=lambda city: dila(),
            municipal_html_reader=fail)
        self.assertEqual(out["status"], "municipal_program_page_unavailable")
        self.assertNotIn("sensitive", json.dumps(out))

    def test_public_aggregate_never_leaks_dates_and_private_domains(self):
        out = run()
        public = public_redacted_municipal_event_summary(out)
        raw = json.dumps(public)
        for forbidden in (UNKNOWN, MUNICIPAL, CITY, TITLE, "2026-12-05"):
            self.assertNotIn(forbidden, raw)
        self.assertEqual(public["claim_matches"], 2)
        for altered in (
            dict(out, publication_ready=True),
            dict(out, status=UNKNOWN),
            dict(out, organizer_domain_independently_owned=True)):
            with self.assertRaises(ValueError):
                public_redacted_municipal_event_summary(altered)


if __name__ == "__main__":
    unittest.main()
