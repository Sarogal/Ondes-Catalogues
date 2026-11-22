"""OA-only admission must work without any municipal or venue web reader."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from test_ptitesondes_candidate_promotion import base
from test_ptitesondes_open_world_release_rehearsal import (
    TODAY, DAY, AGENDA, lead, oa_event,
)
from test_ptitesondes_open_world_patch_bridge import private_patch, readers
from ptitesondes_oa_first_party_admission import admit_live_openagenda
from ptitesondes_open_world_patch_bridge import merge_verified_open_world
from ptitesondes_open_world_private_dossier_intake import (
    collect_research_dossiers, attach_research_dossiers,
)
from test_ptitesondes_open_world_private_dossier_intake import entry


class OpenAgendaFirstPartyAdmissionTests(unittest.TestCase):
    def test_live_public_event_admitted_without_municipal_proof(self):
        reference = base()
        candidate, reason = admit_live_openagenda(
            lead(), DAY.isoformat(), AGENDA, oa_event(),
            reference, reference, TODAY)
        self.assertEqual(reason, "oa_direct_live_source_accepted")
        self.assertEqual(candidate["source_url"],
                         "https://openagenda.com/agenda-nouveau-organisateur/events/999401_conte-musical")
        self.assertEqual(candidate["time"], "10:00 ; 15:00")

    def test_real_merge_uses_only_openagenda_readers(self):
        reference = base()
        dossier = {
            "lead": lead(), "date_start": DAY.isoformat(),
            "official_event_url": "https://openagenda.com/agenda-nouveau-organisateur/events/999401",
            "official_venue_url": "https://openagenda.com/agenda-nouveau-organisateur/events/999401",
        }
        kwargs = readers()
        def no_other_sources(*args):
            raise AssertionError("a second source must not be required")
        for key in ("directory_reader", "official_reader", "ign_reader", "osm_reader"):
            kwargs[key] = no_other_sources
        result, audit, report = merge_verified_open_world(
            reference, reference, private_patch(reference, queue=[dossier]),
            TODAY, "oa_pk_open_world_release_rehearsal_test", **kwargs)
        self.assertEqual(audit["ajoutes"], 1)
        self.assertEqual(report["publisher_accepted_new"], 1)
        self.assertEqual(len(result["events"]), len(reference["events"]) + 1)

    def test_inventory_to_collector_to_private_patch_to_real_publisher(self):
        """No municipal report, external site, hand-picked dossier or network."""
        reference = base()
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            observations = root / "observation"
            research = root / "research"
            research.mkdir()
            dossiers, metrics = collect_research_dossiers(
                observations, research, TODAY,
                inventory_reader=lambda _: [entry()])
        self.assertEqual(metrics["reports"], 0)
        self.assertEqual(metrics["candidate_dossiers"], 1)
        self.assertEqual(len(dossiers), 1)
        self.assertEqual(dossiers[0]["date_start"], DAY.isoformat())
        patch = attach_research_dossiers(
            private_patch(reference, queue=[]), dossiers, TODAY)
        self.assertEqual(len(patch["open_world_research"]), 1)
        kwargs = readers()

        def no_external_site(*args):
            raise AssertionError("OpenAgenda must publish without another source")

        for key in ("directory_reader", "official_reader", "ign_reader", "osm_reader"):
            kwargs[key] = no_external_site
        result, audit, report = merge_verified_open_world(
            reference, reference, patch, TODAY,
            "oa_pk_open_world_release_rehearsal_test", **kwargs)
        self.assertEqual(audit["ajoutes"], 1)
        self.assertEqual(report["dossiers"], 1)
        self.assertEqual(report["admitted_to_merge"], 1)
        self.assertEqual(report["publisher_accepted_new"], 1)
        self.assertEqual(report["held"], 0)
        self.assertEqual(result["events"][:len(reference["events"])],
                         reference["events"])
        self.assertEqual(
            result["events"][-1]["id"],
            "openagenda-999401-" + DAY.isoformat())

    def test_recurring_event_each_exact_day_is_eligible(self):
        from datetime import timedelta
        from test_ptitesondes_open_world_release_rehearsal import sessions
        ref = base()
        next_day = DAY + timedelta(days=1)
        later = {**oa_event(), "timings": [
            *sessions(),
            {"begin": next_day.isoformat() + "T10:00:00+01:00",
             "end": next_day.isoformat() + "T10:40:00+01:00"},
        ]}
        candidate, reason = admit_live_openagenda(
            lead(), DAY.isoformat(), AGENDA, later, ref, ref, TODAY)
        self.assertEqual(reason, "oa_direct_live_source_accepted")
        self.assertEqual(candidate["time"], "10:00 ; 15:00")

    def test_other_openagenda_uid_url_cannot_publish(self):
        ref = base()
        patch = private_patch(ref, queue=[{
            "lead": lead(), "date_start": DAY.isoformat(),
            "official_event_url": "https://openagenda.com/agenda-nouveau-organisateur/events/123456",
            "official_venue_url": "https://openagenda.com/agenda-nouveau-organisateur/events/123456",
        }])
        result, audit, report = merge_verified_open_world(
            ref, ref, patch, TODAY,
            "oa_pk_open_world_release_rehearsal_test", **readers())
        self.assertEqual(audit["ajoutes"], 0)
        self.assertEqual(report["held_reason_counts"],
                         {"oa_direct_url_uid_or_slug_mismatch": 1})

    def test_cancellation_change_and_duplicate_are_held(self):
        ref = base()
        for modification in ({"status": 3}, {"removed": True},
                             {"timings": []}, {"attendanceMode": 2},
                             {"rights": {"license": {"id": "copyright"}}},
                             {"description": {"fr": "Spectacle pour enfants, scolaires uniquement"}},
                             {"timings": None}):
            live = {**oa_event(), **modification}
            candidate, reason = admit_live_openagenda(
                lead(), DAY.isoformat(), AGENDA, live, ref, ref, TODAY)
            self.assertIsNone(candidate, reason)
        accepted, _ = admit_live_openagenda(
            lead(), DAY.isoformat(), AGENDA, oa_event(), ref, ref, TODAY)
        duplicate = deepcopy(ref)
        duplicate["events"].append(accepted)
        candidate, reason = admit_live_openagenda(
            lead(), DAY.isoformat(), AGENDA, oa_event(), ref, duplicate, TODAY)
        self.assertIsNone(candidate)
        self.assertEqual(reason, "oa_direct_already_published")


if __name__ == "__main__":
    unittest.main()
