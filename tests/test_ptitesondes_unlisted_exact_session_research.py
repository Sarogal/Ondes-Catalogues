"""Offline end-to-end exact-session checks; NOT publisher tests."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
import socket
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ptitesondes_unlisted_exact_session_research import (
    review_unlisted_exact_sessions, public_redacted_exact_session_summary,
    SCHEMA,
)
from ptitesondes_dynamic_municipal_source_links import (
    SCHEMA as LINK_SCHEMA, scan_municipal_page,
)
from ptitesondes_unlisted_source_safe_recheck import read_unknown_https
from ptitesondes_openagenda_national_event_research import _time_sessions

TODAY = date(2026, 11, 21)
URL = "https://nouveau-theatre-unlisted.fr/representation"
KEY = "oa_pk_" + "x" * 32


def plan(instants, minutes=45):
    spans = []
    for beginning in instants:
        spans.append({
            "begin": beginning.isoformat(timespec="seconds"),
            "end": (beginning + timedelta(minutes=minutes))
                .isoformat(timespec="seconds"),
        })
    assert len(spans) == len(instants)
    return spans


def lead(spans, venue="Salle jamais enregistrée", city="Ville inconnue"):
    # OA intake research already returns sorted separate timings.
    sorted_spans, reason = _time_sessions(spans, TODAY)
    assert len(sorted_spans) == len(spans), reason
    return {
        "agenda_uid": 804312, "agenda_slug": "agenda-nouvel-artiste",
        "event_uid": 899001, "title": "Le conte sonore des lucioles",
        "venue_unverified": venue, "city_unverified": city,
        "explicit_source_session_intervals": sorted_spans,
        "publication_ready": False, "public_writes": 0,
        "decision": "candidate_for_independent_qualification",
    }


def api(lead, *, status=1, title=None, location=None, spans=None):
    return {
        "uid": lead["event_uid"], "state": 2,
        "status": status, "removed": False,
        "title": {"fr": title or lead["title"]},
        "location": location if location is not None else {
            "name": lead["venue_unverified"],
            "adminLevel4": lead["city_unverified"],
            "countryCode": "FR"},
        "timings": spans if spans is not None
            else lead["explicit_source_session_intervals"],
    }


def report(url=URL):
    return {
        "schema": LINK_SCHEMA,
        "status": "private_source_link_research_only",
        "municipal_domain_confirmed_by_dila": True,
        "candidate_domains_officially_approved": False,
        "source_candidates": [{
            "url": url, "publication_ready": False,
            "source_ownership_unverified": True,
        }],
    }


def event_jsonld(name, begin, end, venue="Salle jamais enregistrée",
                 city="Ville inconnue", **extra):
    return {
        "@context": "https://schema.org",
        "@type": "https://schema.org/ChildrensEvent",
        "name": name,
        "startDate": begin, "endDate": end,
        "location": {
            "@type": "Place", "name": venue,
            "address": {"@type": "PostalAddress",
                        "addressLocality": city}},
        **extra,
    }


def site(*events):
    payload = {
        "@context": "https://schema.org",
        "@graph": list(events),
    }
    return (
        "<html><body><script type='application/ld+json'>"
        + json.dumps(payload, ensure_ascii=False)
        + "</script><p>Programme des spectacles</p></body></html>"
    )


def check(item, html, *, given_links=None, event=None,
          agenda=None, key=KEY, source_reader=None,
          today=TODAY):
    return review_unlisted_exact_sessions(
        item, report() if given_links is None else given_links,
        URL, key, today,
        agenda_reader=(lambda uid, secret: (
            agenda if agenda is not None
            else {"uid": item["agenda_uid"], "slug": item["agenda_slug"]})),
        event_reader=(lambda uid, eid, secret: (
            event if event is not None else api(item))),
        source_reader=source_reader or (lambda url: html))


def instant(day, hour, minute=0, offset=1):
    return datetime(2026, 12, day, hour, minute,
                    tzinfo=timezone(timedelta(hours=offset)))


class UnlistedExactSessionsTests(unittest.TestCase):
    def test_six_distinct_sessions_same_day_preserved_and_crosschecked(self):
        spans = plan([instant(5, hour) for hour in (9, 10, 11, 14, 15, 17)])
        item = lead(spans)
        html = site(*(event_jsonld(
            item["title"], p["begin"], p["end"]) for p in spans))
        out = check(item, html)
        self.assertEqual(out["status"],
                         "structured_source_exact_sessions_research_only")
        self.assertTrue(out["oa_uid_slug_rechecked_live"])
        self.assertTrue(out["oa_timing_rechecked_live"])
        self.assertEqual(out["source_exact_session_count"], 6)
        self.assertEqual(out["source_sessions_claimed_not_independent"], spans)
        self.assertFalse(out["organizer_independently_attested"])
        self.assertFalse(out["event_source_independent_from_openagenda"])
        self.assertFalse(out["publication_ready"])
        self.assertEqual(out["public_writes"], 0)

    def test_fifty_sessions_in_overseas_timezones_no_artificial_four_cap(self):
        spans = []
        for offset in (4, -4):
            for day in range(5, 15):
                for hour in (9, 11, 14):
                    if len(spans) >= 50:
                        break
                    spans += plan([instant(day, hour, offset=offset)])
                if len(spans) >= 50:
                    break
            if len(spans) >= 50:
                break
        item = lead(spans, venue=None, city=None)
        html = site(*(event_jsonld(
            item["title"], p["begin"], p["end"],
            venue="Lieu nouvellement découvert",
            city="Commune jamais répertoriée") for p in spans))
        out = check(item, html)
        self.assertEqual(out["source_exact_session_count"], 50)
        self.assertEqual(len(out["source_sessions_claimed_not_independent"]), 50)
        self.assertFalse(out["venue_geography_verified"])

    def test_same_day_different_hours_are_not_confused(self):
        spans = plan([instant(5, 10), instant(5, 15)])
        item = lead(spans)
        html = site(event_jsonld(
            item["title"], spans[0]["begin"], spans[0]["end"]))
        out = check(item, html)
        self.assertEqual(out["source_exact_session_count"], 1)
        self.assertEqual(out["source_sessions_claimed_not_independent"], [spans[0]])

    def test_missing_end_date_or_timezone_is_not_a_confirmed_session(self):
        item = lead(plan([instant(5, 10)]))
        start, end = (item["explicit_source_session_intervals"][0][x]
                      for x in ("begin", "end"))
        html = site(
            {"@type": "MusicEvent", "name": item["title"],
             "startDate": start, "location": {"name": "Salle jamais enregistrée"}},
            {"@type": "TheaterEvent", "name": item["title"],
             "startDate": start[:-6], "endDate": end[:-6]},
        )
        out = check(item, html)
        self.assertEqual(out["source_exact_session_count"], 0)

    def test_timezone_offsets_can_represent_same_instant(self):
        item = lead(plan([instant(5, 10, offset=1)]))
        utc_start = instant(5, 9, offset=0)
        utc_span = plan([utc_start])
        html = site(event_jsonld(
            item["title"], utc_span[0]["begin"], utc_span[0]["end"]))
        out = check(item, html)
        self.assertEqual(out["source_exact_session_count"], 1)

    def test_wrong_event_title_or_neighbouring_session_is_not_evidence(self):
        spans = plan([instant(5, 10), instant(5, 15)])
        item = lead(spans)
        html = site(
            event_jsonld("Une autre pièce", spans[0]["begin"], spans[0]["end"]),
            event_jsonld(item["title"], spans[0]["begin"],
                         spans[1]["end"]))
        out = check(item, html)
        self.assertEqual(out["source_exact_session_count"], 0)

    def test_unknown_venue_is_kept_for_research_but_known_conflict_vetoes(self):
        span = plan([instant(5, 10)])
        item = lead(span)
        html = site(event_jsonld(
            item["title"], span[0]["begin"], span[0]["end"],
            venue="Autre lieu", city="Autre commune"))
        out = check(item, html)
        self.assertEqual(out["source_exact_session_count"], 0)
        self.assertEqual(out["source_venue_conflict_count"], 1)
        novel = lead(span, venue=None, city=None)
        out = check(novel, html)
        self.assertEqual(out["source_exact_session_count"], 1)
        self.assertFalse(out["venue_geography_verified"])

    def test_source_cancellation_takes_precedence_over_duplicate_scheduled_node(self):
        span = plan([instant(5, 10)])
        item = lead(span)
        neutral = event_jsonld(item["title"], span[0]["begin"], span[0]["end"])
        cancelled = event_jsonld(
            item["title"], span[0]["begin"], span[0]["end"],
            eventStatus="https://schema.org/EventCancelled")
        out = check(item, site(neutral, cancelled))
        self.assertEqual(out["source_exact_session_count"], 0)
        self.assertEqual(out["source_changed_or_cancelled_count"], 1)

    def test_schema_org_cancellation_object_is_not_a_positive_showtime(self):
        span = plan([instant(5, 10)])
        item = lead(span)
        cancelled = event_jsonld(
            item["title"], span[0]["begin"], span[0]["end"],
            eventStatus={"@id": "https://schema.org/EventCancelled"})
        out = check(item, site(cancelled))
        self.assertEqual(out["source_exact_session_count"], 0)
        self.assertEqual(out["source_changed_or_cancelled_count"], 1)

    def test_conflicting_second_location_vetoes_matching_first_location(self):
        span = plan([instant(5, 10)])
        item = lead(span)
        ambiguous = event_jsonld(
            item["title"], span[0]["begin"], span[0]["end"])
        ambiguous["location"] = [
            {"name": "Salle jamais enregistrée",
             "address": {"addressLocality": "Ville inconnue"}},
            {"name": "Autre salle",
             "address": {"addressLocality": "Autre commune"}},
        ]
        out = check(item, site(ambiguous))
        self.assertEqual(out["source_exact_session_count"], 0)
        self.assertEqual(out["source_venue_conflict_count"], 1)

    def test_live_openagenda_mismatch_in_agenda_title_and_time_fail_closed(self):
        span = plan([instant(5, 10)])
        item = lead(span)
        html = site(event_jsonld(item["title"],
                                 span[0]["begin"], span[0]["end"]))
        self.assertEqual(check(
            item, html, agenda={"uid": 99,
                                "slug": item["agenda_slug"]})["status"],
            "live_oa_agenda_uid_slug_conflict")
        self.assertEqual(check(
            item, html, event=api(item, title="Un autre spectacle"))["status"],
            "live_oa_event_identity_or_status_conflict")
        updated = plan([instant(5, 11)])
        self.assertEqual(check(
            item, html, event=api(item, spans=updated))["status"],
            "live_oa_exact_timings_changed")
        self.assertEqual(check(
            item, html, event=api(item, status=3))["status"],
            "live_oa_event_identity_or_status_conflict")
        self.assertEqual(check(
            item, html, event=api(
                item, location={"name": "Ville autre salle",
                                "adminLevel4": "Ville inconnue"}))["status"],
            "live_oa_event_location_changed")

    def test_reprogrammed_is_kept_as_research_never_auto_approved(self):
        span = plan([instant(5, 10)])
        item = lead(span)
        html = site(event_jsonld(item["title"],
                                 span[0]["begin"], span[0]["end"]))
        out = check(item, html, event=api(item, status=2))
        self.assertEqual(out["status"],
                         "rescheduled_needs_independent_current_session_confirmation")
        self.assertEqual(out["source_exact_session_count"], 1)
        self.assertFalse(out["approval_granted"])

    def test_unknown_categories_arent_rejected_by_vocabulary_lists(self):
        span = plan([instant(5, 10)])
        item = lead(span)
        item.pop("decision")
        item["review_state"] = "unknown_activity_requires_official_editorial_evidence"
        item["title"] = "Frisson sonore de la constellation racontée"
        html = site(event_jsonld(
            item["title"], span[0]["begin"], span[0]["end"]))
        out = check(item, html)
        self.assertEqual(out["source_exact_session_count"], 1)
        self.assertFalse(out["family_eligibility_verified"])

    def test_injected_source_claims_do_not_allow_approval_or_bypass(self):
        span = plan([instant(5, 10)])
        item = lead(span)
        html_reader = Mock(side_effect=AssertionError("must not fetch"))
        for bad_links in (
            dict(report(), status="official_approved"),
            dict(report(), municipal_domain_confirmed_by_dila=False),
            dict(report(), source_candidates=[]),
            dict(report(), source_candidates=[{
                "url": URL, "publication_ready": True,
                "source_ownership_unverified": False}]),
        ):
            with self.subTest(bad_links=bad_links):
                out = check(item, "", given_links=bad_links,
                            source_reader=html_reader)
                self.assertEqual(out["status"], "untrusted_or_incomplete_private_lead")
        html_reader.assert_not_called()

    def test_invalid_public_api_key_and_fake_intervals_are_held(self):
        span = plan([instant(5, 10)])
        item = lead(span)
        out = check(item, "", key="private_secret")
        self.assertEqual(out["status"], "untrusted_or_incomplete_private_lead")
        bad = deepcopy(item)
        bad["explicit_source_session_intervals"].append(
            deepcopy(bad["explicit_source_session_intervals"][0]))
        self.assertEqual(check(
            bad, "")["status"], "untrusted_or_incomplete_private_lead")
        bad = deepcopy(item)
        bad["explicit_source_session_intervals"][0]["begin"] = (
            bad["explicit_source_session_intervals"][0]["begin"][:-6])
        self.assertEqual(check(
            bad, "")["status"], "untrusted_or_incomplete_private_lead")

    def test_non_jsonld_visible_text_is_research_not_false_session_proof(self):
        span = plan([instant(5, 10)])
        item = lead(span)
        html = ("<html><h1>Le conte sonore des lucioles</h1>"
                "<p>5 décembre 2026 : 10h et 15h</p></html>")
        out = check(item, html)
        self.assertEqual(out["status"],
                         "no_exact_structured_source_sessions_yet")
        self.assertEqual(out["source_exact_session_count"], 0)

    def test_private_source_fetch_exception_is_sanitized(self):
        span = plan([instant(5, 10)])
        item = lead(span)
        def outage(url):
            raise OSError("PRIVATE-URL-SHOULD-NOT-LEAK")
        out = check(item, "", source_reader=outage)
        self.assertEqual(out["status"], "unlisted_source_not_recheckable")
        self.assertNotIn("PRIVATE-URL", json.dumps(out))

    def test_full_private_chain_dila_to_new_source_to_exact_session(self):
        """Real module-to-module path, fake providers, no outbound network."""
        city = "Ville inconnue"
        official_url = "https://www.ville-inconnue.fr/sorties"
        municipal_html = (
            "<html><body><main><a href='" + URL + "'>"
            "Le conte sonore des lucioles</a></main></body></html>")
        insee = "12345"
        dila = {
            "total_count": 1,
            "results": [{
                "nom": "Mairie - " + city, "categorie": "SL",
                "statut_de_diffusion": "true",
                "version_type": "Publiable",
                "copyright": (
                    "Direction de l'information légale "
                    "et administrative (Premier ministre)"),
                "url_service_public":
                    "https://lannuaire.service-public.gouv.fr/test/uuid",
                "code_insee_commune": insee,
                "pivot": json.dumps([{
                    "type_service_local": "mairie",
                    "code_insee_commune": [insee]}]),
                "adresse": json.dumps([{
                    "nom_commune": city, "pays": "France"}]),
                "site_internet": json.dumps([{
                    "libelle": "", "valeur": "https://www.ville-inconnue.fr/"}]),
            }],
        }
        discovered = scan_municipal_page(
            city, dila, {"url": official_url, "html": municipal_html})
        self.assertEqual(discovered["source_candidates_this_batch"], 1)
        self.assertEqual(discovered["source_candidates"][0]["url"], URL)

        item = lead(plan([instant(5, 10)]))
        beginning, ending = (
            item["explicit_source_session_intervals"][0][field]
            for field in ("begin", "end"))
        body = site(event_jsonld(item["title"], beginning, ending))
        raw = body.encode("utf-8")
        connected = []
        class FakeResponse:
            status = 200
            def getheader(self, header):
                return "text/html" if header == "Content-Type" else None
            def read(self, limit):
                return raw[:limit]
        class FakeConnection:
            def request(self, method, path, headers):
                connected.append((method, path))
            def getresponse(self):
                return FakeResponse()
            def close(self):
                connected.append(("closed",))
        def resolve(*args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
                     ("8.8.8.8", 443))]
        def connect(host, ip):
            self.assertEqual(host, "nouveau-theatre-unlisted.fr")
            self.assertEqual(ip, "8.8.8.8")
            return FakeConnection()
        def pinned_reader(url):
            return read_unknown_https(
                url, resolver=resolve, connection_factory=connect)

        result = check(
            item, "", given_links=discovered, source_reader=pinned_reader)
        self.assertEqual(result["source_exact_session_count"], 1)
        self.assertEqual(result["status"],
                         "structured_source_exact_sessions_research_only")
        self.assertEqual(connected, [
            ("GET", "/representation"), ("closed",)])
        self.assertFalse(result["organizer_independently_attested"])
        self.assertFalse(result["venue_geography_verified"])
        self.assertFalse(result["rights_reviewed"])
        self.assertFalse(result["publication_ready"])
        self.assertFalse(result["publisher_connected"])
        self.assertEqual(result["public_writes"], 0)

    def test_redacted_aggregates_never_leak_organizer_or_showtime(self):
        span = plan([instant(5, 10)])
        item = lead(span)
        out = check(item, site(event_jsonld(
            item["title"], span[0]["begin"], span[0]["end"])))
        public = public_redacted_exact_session_summary([out])
        self.assertEqual(public["checked"], 1)
        self.assertNotIn(item["title"], json.dumps(public))
        self.assertNotIn(URL, json.dumps(public))
        self.assertNotIn("2026-12-05", json.dumps(public))
        with self.assertRaises(ValueError):
            public_redacted_exact_session_summary(
                [dict(out, status="https://private.fr/source")])
        with self.assertRaises(ValueError):
            public_redacted_exact_session_summary(
                [dict(out, publisher_connected=True)])


if __name__ == "__main__":
    unittest.main()
