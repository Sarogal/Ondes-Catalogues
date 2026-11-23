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
    def test_cloud_summary_shows_only_safe_oa_hold_codes(self):
        from run_cloud_sync import redacted_blocker_counts
        from ptitesondes_oa_first_party_admission import PUBLIC_OA_DIRECT_REASONS
        self.assertIn("oa_direct_reuse_rights_missing", PUBLIC_OA_DIRECT_REASONS)
        self.assertIn("oa_direct_invalid_coordinates", PUBLIC_OA_DIRECT_REASONS)
        counts = redacted_blocker_counts({
            "oa_direct_invalid_coordinates": 2,
            "oa_direct_reuse_rights_missing": 3,
            "private-name-and-event-uid": 4,
        })
        self.assertEqual(counts, {
            "oa_direct_invalid_coordinates": 2,
            "oa_direct_reuse_rights_missing": 3,
            "other_private_reason": 4,
        })

    def test_live_oa_conditions_can_prove_child_audience_for_sung_comptines(self):
        from ptitesondes_candidate_promotion import category_for
        event = dict(
            oa_event(),
            title={"fr": "Les petites boîtes à musique"},
            description={"fr": "Envie de chanter Noël ? Découvrez les comptines revisitées."},
            age=None,
            conditions={"fr": "Entrée libre. Pour les enfants de 0 à 6 ans."},
        )
        item = dict(lead(), title="Les petites boîtes à musique")
        self.assertEqual(
            category_for(item["title"], event["description"]["fr"] +
                         " " + event["conditions"]["fr"])[0],
            "eveil-musical")
        # The synthetic 100-row baseline contains only the "conte-musical"
        # category; real production already contains "eveil-musical".
        reference = base()
        reference["events"][0]["category"] = "eveil-musical"
        reference["events"][0]["category_label"] = "Éveil musical"
        candidate, reason = admit_live_openagenda(
            item, DAY.isoformat(), AGENDA, event, reference, reference, TODAY)
        self.assertEqual(reason, "oa_direct_live_source_accepted")
        self.assertEqual(candidate["category"], "eveil-musical")
        self.assertEqual(candidate["date_start"], DAY.isoformat())

    def test_generic_youth_age_text_and_invalid_adult_age(self):
        from ptitesondes_oa_first_party_admission import explicit_child_age_text
        for positive in (
            "Les plus jeunes jusqu'' à 11 ans",
            "Atelier de 3 à 12 ans",
            "Pour les familles avec enfants de 0 à 6 ans",
            "Pour les petits de moins de 8 ans",
        ):
            with self.subTest(positive=positive):
                self.assertTrue(explicit_child_age_text(positive))
        for negative in (
            "Atelier pour les adultes jusqu'à 21 ans",
            "Cours entre 16 et 45 ans",
            "Réservation pour une conférence pour adultes",
            "Sans indication sur le public",
        ):
            with self.subTest(negative=negative):
                self.assertFalse(explicit_child_age_text(negative))

    def test_overseas_french_first_party_youth_workshop_without_age_field(self):
        """Generic Martinique/MQ contract, based on a real wording from OA.

        Only test metadata and synthetic coordinates are used; NO live event
        is published or geolocated by this test.
        """
        from ptitesondes_oa_first_party_admission import explicit_child_age_text
        desc = "Éveil musical et cours de musique pour les plus jeunes jusqu'' à 11 ans."
        self.assertTrue(explicit_child_age_text(desc))
        event = deepcopy(oa_event())
        event["title"] = {"fr": "ATELIER D'EVEIL MUSICAL"}
        event["description"] = {"fr": desc}
        event["conditions"] = {"fr": "Atelier culturel familial"}
        event["age"] = None
        event["timezone"] = "America/Martinique"
        event["timings"] = [
            {"begin": "2026-12-05T09:00:00-04:00",
             "end": "2026-12-05T11:00:00-04:00"}
        ]
        event["location"] = {
            "name": "Centre culturel fictif", "adminLevel4": "Commune fictive",
            "adminLevel1": "Martinique", "adminLevel2": "Martinique",
            "countryCode": "MQ", "latitude": 14.7, "longitude": -61.0,
        }
        item = dict(lead(), title="ATELIER D'EVEIL MUSICAL",
                    city_unverified="Commune fictive",
                    venue_unverified="Centre culturel fictif",
                    explicit_source_session_intervals=event["timings"])
        ref = base()
        ref["events"][0]["category"] = "eveil-musical"
        ref["events"][0]["category_label"] = "Éveil musical"
        candidate, reason = admit_live_openagenda(
            item, DAY.isoformat(), AGENDA, event, ref, ref, TODAY)
        self.assertEqual(reason, "oa_direct_live_source_accepted")
        self.assertEqual(candidate["region"], "Martinique")
        self.assertEqual(candidate["time"], "09:00")
        self.assertEqual(candidate["category"], "eveil-musical")

    def test_live_oa_conditions_restrict_adults_only_even_when_title_is_child(self):
        source = dict(oa_event(), conditions={
            "fr": "Réservé aux adultes uniquement. Pas d'accès familial."})
        candidate, reason = admit_live_openagenda(
            lead(), DAY.isoformat(), AGENDA, source, base(), base(), TODAY)
        self.assertIsNone(candidate)
        self.assertEqual(reason, "oa_direct_restricted_access")

    def test_children_conditions_do_not_turn_generic_exhibition_into_music(self):
        from ptitesondes_candidate_promotion import category_for
        source = dict(
            oa_event(),
            title={"fr": "Exposition de livres illustrés"},
            description={"fr": "Catalogue de comptines à découvrir en famille."},
            age=None,
            conditions={"fr": "Pour les enfants de 0 à 6 ans."},
        )
        self.assertIsNone(category_for(
            "Exposition de livres illustrés",
            source["description"]["fr"] + " " + source["conditions"]["fr"]))
        item = dict(lead(), title="Exposition de livres illustrés")
        candidate, reason = admit_live_openagenda(
            item, DAY.isoformat(), AGENDA, source, base(), base(), TODAY)
        self.assertIsNone(candidate)
        self.assertEqual(reason, "oa_direct_out_of_editorial_scope")

    def test_plural_musical_storytelling_and_baby_storytime_are_generic(self):
        from ptitesondes_candidate_promotion import category_for
        from ptitesondes_family_activity_classification import propose_family_activity
        self.assertEqual(category_for(
            "Contes musicaux", "Pour les enfants")[0], "conte-musical")
        self.assertEqual(category_for(
            "Lectures en musique", "Pour les enfants")[0], "conte-musical")
        self.assertEqual(propose_family_activity(
            "Bébés lecteurs aux Bordes",
            "Lecture et comptines pour les tout-petits")["category_proposal"],
            "lecture-jeunesse")
        # Mere library access is not a live performance.
        self.assertIsNone(propose_family_activity(
            "Ouverture de la bibliothèque jeunesse",
            "Accueil des enfants pendant les horaires d'ouverture"
        )["category_proposal"])

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

    def test_live_rescheduled_status_keeps_exact_sessions(self):
        reference = base()
        for status in (2, {"id": 2, "label": "Reprogrammé"},
                       {"id": 1, "label": "Programmé"}):
            with self.subTest(status=status):
                live = {**oa_event(), "status": status}
                candidate, reason = admit_live_openagenda(
                    lead(), DAY.isoformat(), AGENDA, live,
                    reference, reference, TODAY)
                self.assertEqual(reason, "oa_direct_live_source_accepted")
                self.assertEqual(candidate["time"], "10:00 ; 15:00")

        # Neither unknown nor unavailable status is an acceptable session.
        for status in (3, 4, 5, 6, {"id": 6}, {"id": "2"},
                       None, {"label": "Programmé"}):
            with self.subTest(status=status):
                candidate, reason = admit_live_openagenda(
                    lead(), DAY.isoformat(), AGENDA,
                    {**oa_event(), "status": status}, reference, reference,
                    TODAY)
                self.assertIsNone(candidate)
                self.assertEqual(
                    reason, "oa_direct_not_public_or_identity_changed")

    def test_uid_bound_event_envelope_support_without_identity_bypass(self):
        ref = base()
        dossier = {
            "lead": lead(), "date_start": DAY.isoformat(),
            "official_event_url":
                "https://openagenda.com/agenda-nouveau-organisateur/events/999401",
            "official_venue_url":
                "https://openagenda.com/agenda-nouveau-organisateur/events/999401",
        }
        patch = private_patch(ref, queue=[dossier])
        kwargs = readers()
        kwargs["event_reader"] = lambda *args: {"event": oa_event()}
        result, audit, report = merge_verified_open_world(
            ref, ref, patch, TODAY,
            "oa_pk_open_world_release_rehearsal_test", **kwargs)
        self.assertEqual(audit["ajoutes"], 1)
        self.assertEqual(report["publisher_accepted_new"], 1)

        for envelope in (
            {"event": {**oa_event(), "uid": 123456}},
            {"uid": 123456, "event": oa_event()},
            {"event": [oa_event()]},
        ):
            with self.subTest(shape=list(envelope)):
                kwargs["event_reader"] = lambda *args: envelope
                _, audit, report = merge_verified_open_world(
                    ref, ref, patch, TODAY,
                    "oa_pk_open_world_release_rehearsal_test", **kwargs)
                self.assertEqual(audit["ajoutes"], 0)
                self.assertGreater(report["held"], 0)

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
