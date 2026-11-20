"""Offline source-agnostic JSON-LD discovery; no official-proof shortcuts."""
from datetime import date
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_generic_schemaorg_event_discovery import (
    parse_schemaorg_private_event_hints, redact_schemaorg_report, SCHEMA,
)


def pin(*, tz="Europe/Paris", child="https://agenda.example.fr/evenements/famille"):
    return {
        "approved_host": "agenda.example.fr",
        "exact_child_url": child,
        "child_prefix": "/evenements/",
        "timezone": tz,
    }


def event(*, when="2026-11-22T09:15:00+01:00",
          title="Atelier créatif pour les enfants",
          venue="Place de la Tour Eiffel", city="Paris", status=None):
    e = {
        "@type": "EducationEvent",
        "name": title,
        "startDate": when,
        "location": {
            "@type": "Place", "name": venue,
            "address": {"@type": "PostalAddress", "addressLocality": city},
        },
        "audience": {"@type": "Audience", "audienceType": "Famille"},
        "offers": {"price": 0, "priceCurrency": "EUR"},
        "organizer": {"name": "Faux organisateur non vérifié"},
    }
    if status:
        e["eventStatus"] = "https://schema.org/" + status
    return e


def page(*events, url=None):
    structure = {"@context": "https://schema.org", "@graph": list(events)}
    body = ("<html><head><script type=\"application/ld+json\">"
            + json.dumps(structure, ensure_ascii=False)
            + "</script></head><body><main>Programme municipal</main></body></html>")
    return {"url": url or pin()["exact_child_url"], "html": body}


class SchemaOrgGenericPrivateDiscoveryTest(unittest.TestCase):
    today = date(2026, 11, 20)

    def test_two_exact_sessions_one_official_page_not_collapsed(self):
        first = event()
        second = event(when="2026-11-22T10:30:00+01:00")
        result = parse_schemaorg_private_event_hints(
            page(first, second), pin(), self.today)
        self.assertEqual(len(result["private_leads"]), 2)
        self.assertEqual(
            {x["start_local"] for x in result["private_leads"]},
            {"09:15", "10:30"})
        self.assertEqual(result["counts"]["future_exact_sessions"], 2)
        self.assertTrue(all(x["source_url"] == pin()["exact_child_url"]
                            for x in result["private_leads"]))
        self.assertEqual(
            {x["category_hint_only"] for x in result["private_leads"]},
            {"atelier-creatif"})
        self.assertFalse(result["publication_ready"])

    def test_not_hardcoded_to_any_venue_city_or_region(self):
        rows = [
            event(venue="Berge du canal", city="Sète"),
            event(when="2026-11-22T12:30:00+01:00",
                  venue="Esplanade publique", city="Brest"),
        ]
        out = parse_schemaorg_private_event_hints(page(*rows), pin(), self.today)
        self.assertEqual({x["city"] for x in out["private_leads"]},
                         {"Sète", "Brest"})
        self.assertEqual(len(out["private_leads"]), 2)

    def test_missing_price_age_and_registration_are_not_invented(self):
        out = parse_schemaorg_private_event_hints(
            page(event()), pin(), self.today)
        candidate = out["private_leads"][0]
        self.assertEqual(candidate["price_evidence"], "not_stated")
        self.assertEqual(candidate["registration_evidence"], "not_stated")
        self.assertIs(candidate["audience_source_visible_confirmed"], False)
        self.assertIs(candidate["official_session_independently_proved"], False)
        self.assertIs(candidate["organizer_independently_attested"], False)
        self.assertIs(candidate["approved"], False)
        self.assertIs(candidate["published"], False)
        self.assertNotIn("lat", candidate)
        self.assertNotIn("lng", candidate)

    def test_unclassified_events_are_retained_as_private_hints(self):
        out = parse_schemaorg_private_event_hints(
            page(event(title="Rendez-vous à la mairie")), pin(), self.today)
        self.assertEqual(len(out["private_leads"]), 1)
        self.assertIsNone(out["private_leads"][0]["category_hint_only"])
        self.assertEqual(out["counts"]["unclassified_sessions_requiring_review"], 1)
        self.assertFalse(out["publication_ready"])

    def test_musical_theme_never_impersonates_nonmusical_category(self):
        out = parse_schemaorg_private_event_hints(
            page(event(title="Concert rock et atelier peinture")),
            pin(), self.today)
        self.assertEqual(len(out["private_leads"]), 1)
        self.assertIsNone(out["private_leads"][0]["category_hint_only"])

    def test_date_only_or_naive_ambiguous_dst_cannot_invent_clock(self):
        rows = [
            event(when="2026-11-22"),
            event(when="2026-10-25T02:30:00"),
        ]
        a = parse_schemaorg_private_event_hints(
            page(rows[0]), pin(), self.today)
        b = parse_schemaorg_private_event_hints(
            page(rows[1]), pin(), date(2026, 10, 20))
        self.assertEqual(a["counts"]["missing_exact_clock"], 1)
        self.assertEqual(b["counts"]["ambiguous_timezone"], 1)
        self.assertEqual(a["private_leads"], [])
        self.assertEqual(b["private_leads"], [])

    def test_official_timezone_pin_handles_guadeloupe_and_noumea(self):
        a = parse_schemaorg_private_event_hints(
            page(event(when="2026-11-23T00:30:00+01:00")),
            pin(tz="America/Guadeloupe"), self.today)
        self.assertEqual(a["private_leads"][0]["date_start"], "2026-11-22")
        self.assertEqual(a["private_leads"][0]["start_local"], "19:30")
        b = parse_schemaorg_private_event_hints(
            page(event(when="2026-11-22T10:00:00+01:00")),
            pin(tz="Pacific/Noumea"), self.today)
        self.assertEqual(b["private_leads"][0]["date_start"], "2026-11-22")
        self.assertEqual(b["private_leads"][0]["start_local"], "20:00")

    def test_cancelled_and_past_events_not_exposed_as_future(self):
        rows = [
            event(status="EventCancelled"),
            event(when="2026-11-18T10:00:00+01:00"),
        ]
        out = parse_schemaorg_private_event_hints(
            page(*rows), pin(), self.today)
        self.assertEqual(out["private_leads"], [])
        self.assertEqual(out["counts"]["cancelled_or_postponed"], 1)
        self.assertEqual(out["counts"]["non_future"], 1)

    def test_missing_city_venue_and_malicious_html_are_held(self):
        for place in ("", "<script>x</script>"):
            with self.subTest(place=place):
                out = parse_schemaorg_private_event_hints(
                    page(event(city=place)), pin(), self.today)
                self.assertEqual(out["counts"]["missing_venue_or_city"], 1)
                self.assertEqual(out["private_leads"], [])

    def test_wrong_pin_host_path_and_timezone_are_refused(self):
        a = page(event())
        bad_pins = (
            dict(pin(), approved_host="other.example.fr"),
            dict(pin(), exact_child_url="https://other.example.fr/evenements/x"),
            dict(pin(), child_prefix="/protected/"),
            dict(pin(), timezone=[]),
            dict(pin(), timezone="Asia/Tokyo"),
            dict(pin(), approved=True),
        )
        for bad in bad_pins:
            with self.subTest(pin=bad):
                result = parse_schemaorg_private_event_hints(
                    a, bad, self.today)
                self.assertEqual(result["private_leads"], [])
                self.assertEqual(result["stage"], "invalid_trusted_child_or_page")

    def test_multiple_scripts_and_duplicates_deduplicated(self):
        base = page(event())
        once = base["html"].replace(
            "</head>", "<script type=\"application/ld+json\">"
            + json.dumps(event(), ensure_ascii=False)
            + "</script></head>")
        out = parse_schemaorg_private_event_hints(
            dict(base, html=once), pin(), self.today)
        self.assertEqual(len(out["private_leads"]), 1)

    def test_report_redacts_names_urls_dates_and_future_rights_claims(self):
        out = parse_schemaorg_private_event_hints(
            page(event(venue="Rond-point privé", city="Saint-Denis")),
            pin(), self.today)
        public = redact_schemaorg_report(out)
        blob = json.dumps(public, ensure_ascii=False)
        self.assertEqual(public["schema"], SCHEMA)
        for text in ("Saint-Denis", "Rond-point", "https://",
                     "2026-11-22", "review_id", "source_url",
                     "Famille", "09:15"):
            self.assertNotIn(text, blob)
        self.assertFalse(public["publication_ready"])
        self.assertEqual(public["public_writes"], 0)

    def test_multiple_geographically_distinct_events_same_page_retained(self):
        one = event(title="Atelier peinture", city="Lille")
        other = event(title="Atelier peinture", city="Fort-de-France")
        out = parse_schemaorg_private_event_hints(
            page(one, other), pin(), self.today)
        self.assertEqual(len(out["private_leads"]), 2)


if __name__ == "__main__":
    unittest.main()
