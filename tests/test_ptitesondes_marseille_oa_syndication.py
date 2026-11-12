"""Reviewed Marseille municipal OA syndication, not a general redirect permission."""
from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_candidate_promotion import (
    reconciled_openagenda_url, registry_location, make_event, evaluate
)
from proof_text import verify_event


UID = "24285475"
CANONICAL = ("https://openagenda.com/bibliotheques-de-marseille/"
             "events/eveil-musical-8687467")
ORIGIN = ("https://openagenda.com/bibliotheques-de-territoire-marseille/"
          "events/24285475_eveil-musical-8687467")
VERIFIED_ORIGIN = ("https://openagenda.com/fr/bibliotheques-de-territoire-marseille/"
                   "events/24285475_eveil-musical-8687467")


def lead(**overrides):
    base = {
        "external_id": UID, "collector": "openagenda-v2",
        "source_url": ORIGIN, "title": "Éveil musical",
        "date_start": "2026-11-27", "date_end": "2026-11-27",
        "city": "Marseille", "venue": "Bibliothèque des Cinq-Avenues",
    }
    return dict(base, **overrides)


def record(**overrides):
    location = registry_location(lead())
    assert location is not None
    base = {
        "uid": UID, "canonicalurl": CANONICAL,
        "title_fr": "Éveil musical",
        "description_fr": "Atelier d'éveil musical en famille",
        "location_city": "Marseille", "location_name": "Bibliothèque des Cinq-Avenues",
        "location_countrycode": "FR",
        "location_coordinates": {"lat": location["lat"], "lon": location["lng"]},
        "location_department": "Bouches-du-Rhône",
        "location_region": "Provence-Alpes-Côte d'Azur",
        "originagenda_title": "Bibliothèques de Marseille",
        "timings": [{"begin": "2026-11-27T10:00:00+01:00"}],
        "status": {"id": 1},
    }
    return dict(base, **overrides)


def baseline():
    location = registry_location(lead())
    events = []
    for i in range(100):
        events.append({
            "id": "historic-" + str(i), "title": "Autre atelier " + str(i),
            "category": "eveil-musical", "category_label": "Éveil musical",
            "date_start": "2026-11-13", "date_end": "2026-11-13",
            "time": "09:00", "city": "Marseille", "venue": "Bibliothèque des Cinq-Avenues",
            "department": "Bouches-du-Rhône", "region": "Provence-Alpes-Côte d'Azur",
            "source_url": CANONICAL, "source_label": "Catalogue de test",
            "verified_at": "2026-11-12", "geo_verified_at": "2026-11-12",
            "geo_precision": "venue", "lat": location["lat"], "lng": location["lng"],
        })
    return {"version": 3, "updated_at": "2026-10-22T21:00:00+02:00",
            "events": events}


class MarseilleMunicipalSyndicationTests(unittest.TestCase):
    def test_only_exact_public_oa_uid_alias_is_accepted(self):
        self.assertEqual(reconciled_openagenda_url(lead(), record()), VERIFIED_ORIGIN)
        event = make_event(lead(), record(), registry_location(lead()),
                           date(2026, 11, 12))
        self.assertEqual(event["source_url"], VERIFIED_ORIGIN)
        self.assertEqual(event["time"], "10:00")
        self.assertEqual(event["id"], "openagenda-24285475-2026-11-27")

    def test_wrong_uid_slug_venue_or_origin_is_never_accepted(self):
        invalid = (
            lead(external_id="00001"),
            lead(source_url=ORIGIN.replace(UID + "_", "99999_")),
            lead(source_url=ORIGIN.replace("eveil-musical-8687467", "autre-fiche")),
            lead(source_url=ORIGIN.replace("bibliotheques-de-territoire-marseille",
                                           "unrelated-private-agenda")),
            lead(source_url=ORIGIN + "?user=1"),
            lead(collector="opendatasoft-index"),
        )
        for item in invalid:
            with self.subTest(item=item["source_url"]):
                with self.assertRaises(ValueError):
                    reconciled_openagenda_url(item, record())
        with self.assertRaisesRegex(ValueError, "URL canonique"):
            reconciled_openagenda_url(lead(),
                record(canonicalurl=CANONICAL.replace(
                    "bibliotheques-de-marseille", "agenda-inconnu")))

    def test_syndication_is_not_a_second_independent_event_proof(self):
        event = make_event(lead(), record(), registry_location(lead()),
                           date(2026, 11, 12))
        # An unreadable official calendar must never be accepted just
        # because two OpenAgenda aggregator URLs point to one UID.
        with patch("proof_text.read", return_value=(
            "<html><title>Loading...</title>Loading...</html>", ""
        )):
            approved, _ = verify_event(event, [])
        self.assertFalse(approved)
        with self.assertRaisesRegex(ValueError, "Position source"):
            make_event(lead(), record(
                location_coordinates={"lat": 45.0, "lon": 5.39}),
                registry_location(lead()), date(2026, 11, 12))
        with self.assertRaisesRegex(ValueError, "Lieu différent"):
            make_event(lead(), record(location_name="Annexe inconnue"),
                       registry_location(lead()), date(2026, 11, 12))

    def test_original_french_organizer_page_proves_session_not_bare_mirror(self):
        event = make_event(lead(), record(), registry_location(lead()),
                           date(2026, 11, 12))
        html = ("<html><head><title>Éveil musical | Bibliothèques de territoire"
                "</title></head><body><h1>Éveil musical</h1>"
                "<h2>Novembre 2026</h2><p>Vendredi 27</p>"
                "<p>10:00 - 10:45</p><p>Bibliothèque des Cinq-Avenues</p>"
                "<p>Marseille - Impasse Fissiaux</p>"
                "<p>Atelier musical pour les tout-petits de 6 mois à 3 ans</p>"
                "</body></html>")
        with patch("proof_text.read", return_value=(html, "")):
            ok, why = verify_event(event, [])
        self.assertTrue(ok, why)
        for altered in (
            html.replace("Novembre 2026", "Novembre 2025"),
            html.replace("Vendredi 27", "Vendredi 26"),
            html.replace("10:00", "11:00"),
            html.replace("Bibliothèque des Cinq-Avenues", "Lieu inconnu"),
            "<html><title>Loading</title></html>",
        ):
            with self.subTest(altered=altered[:70]):
                with patch("proof_text.read", return_value=(altered, "")):
                    self.assertFalse(verify_event(event, [])[0])

    def test_exact_origin_is_verified_only_after_mirror_date_failure(self):
        ref = baseline()
        primary = lead(collector="opendatasoft-index", source_url=CANONICAL)
        secondary = lead()
        checked_sources = []
        def verifier(event, originals):
            checked_sources.append(event["source_url"])
            if event["source_url"] == CANONICAL:
                return False, "date complète non confirmée sur la fiche officielle"
            return event["source_url"] == VERIFIED_ORIGIN, "fiche officielle contrôlée"
        patch, report = evaluate([primary, secondary], ref, ref,
                                 date(2026, 11, 12),
                                 fetch=lambda uid: record(), verifier=verifier)
        self.assertEqual(report["accepted_preflight"], 1)
        self.assertEqual(report["duplicate_collector_leads_skipped"], 1)
        self.assertEqual(checked_sources, [CANONICAL, VERIFIED_ORIGIN])
        self.assertEqual(len(patch["additions"]), 1)
        self.assertEqual(patch["additions"][0]["source_url"], VERIFIED_ORIGIN)
        self.assertFalse(patch["safe_to_publish"])

    def test_fallback_never_overrides_nondate_failure_or_nonverified_proof(self):
        ref = baseline()
        original = lead(collector="opendatasoft-index", source_url=CANONICAL)
        secondary = lead()
        calls = []
        def wrong_title(event, originals):
            calls.append(event["source_url"])
            return False, "titre non confirmé en en-tête de la fiche officielle"
        patch, report = evaluate([original, secondary], ref, ref,
                                 date(2026, 11, 12), fetch=lambda uid: record(),
                                 verifier=wrong_title)
        self.assertEqual(patch["additions"], [])
        self.assertEqual(report["accepted_preflight"], 0)
        self.assertEqual(calls, [CANONICAL])
        def still_missing(event, originals):
            return False, "date complète non confirmée sur la fiche officielle"
        patch, report = evaluate([original, secondary], ref, ref,
                                 date(2026, 11, 12), fetch=lambda uid: record(),
                                 verifier=still_missing)
        self.assertEqual(patch["additions"], [])
        self.assertEqual(report["accepted_preflight"], 0)

    def test_unreviewed_cross_agenda_cannot_be_fallback(self):
        ref = baseline()
        original = lead(collector="opendatasoft-index", source_url=CANONICAL)
        forged = lead(source_url=ORIGIN.replace(
            "bibliotheques-de-territoire-marseille", "unknown-venue-agenda"))
        patch, report = evaluate(
            [original, forged], ref, ref, date(2026, 11, 12),
            fetch=lambda uid: record(),
            verifier=lambda event, originals: (
                False, "date complète non confirmée sur la fiche officielle"
            ))
        self.assertEqual(patch["additions"], [])
        self.assertEqual(report["accepted_preflight"], 0)

    def test_school_or_cancelled_occurrences_stay_blocked(self):
        with self.assertRaisesRegex(ValueError, "Statut"):
            make_event(lead(), record(status={"id": 3}),
                       registry_location(lead()), date(2026, 11, 12))


if __name__ == "__main__":
    unittest.main()
