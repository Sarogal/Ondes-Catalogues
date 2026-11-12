"""Reviewed Marseille municipal OA syndication, not a general redirect permission."""
from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_candidate_promotion import (
    reconciled_openagenda_url, registry_location, make_event
)
from proof_text import verify_event


UID = "24285475"
CANONICAL = ("https://openagenda.com/bibliotheques-de-marseille/"
             "events/eveil-musical-8687467")
ORIGIN = ("https://openagenda.com/bibliotheques-de-territoire-marseille/"
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


class MarseilleMunicipalSyndicationTests(unittest.TestCase):
    def test_only_exact_public_oa_uid_alias_is_accepted(self):
        self.assertEqual(reconciled_openagenda_url(lead(), record()), CANONICAL)
        event = make_event(lead(), record(), registry_location(lead()),
                           date(2026, 11, 12))
        self.assertEqual(event["source_url"], CANONICAL)
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

    def test_school_or_cancelled_occurrences_stay_blocked(self):
        with self.assertRaisesRegex(ValueError, "Statut"):
            make_event(lead(), record(status={"id": 3}),
                       registry_location(lead()), date(2026, 11, 12))


if __name__ == "__main__":
    unittest.main()
