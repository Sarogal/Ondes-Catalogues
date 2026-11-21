"""Connected, no-network publisher bridge. No PR-approval flags are trusted."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from test_ptitesondes_open_world_release_rehearsal import (
    AGENDA, DAY, KEY, SOURCE, TODAY, lead, oa_event, official_page,
)
from test_ptitesondes_unnumbered_official_geo_proof import (
    directory, html as official_venue_html, osm, URL as VENUE_URL,
)
from test_ptitesondes_candidate_promotion import base
from ptitesondes_open_world_patch_bridge import (
    prepare_open_world_patch, merge_verified_open_world,
)
from run_cloud_sync import public_summary
from merge_policy import ORIGIN


def dossier(**changes):
    out = {"lead": lead(), "date_start": DAY.isoformat(),
           "official_event_url": SOURCE,
           "official_venue_url": VENUE_URL}
    out.update(changes)
    return out


def private_patch(reference, queue=None):
    return {
        "schema": "ptitesondes.patch.v1",
        "generated_at": TODAY.isoformat(),
        "safe_to_publish": False,
        "source": {"url": ORIGIN, "version": 3,
                   "updated_at": reference["updated_at"],
                   "events_count": len(reference["events"])},
        "checks": {"ids_unique": True, "official_sources_verified": True,
                   "no_production_changes": True},
        "additions": [], "updates": [], "deferred": [],
        "open_world_research": [dossier()] if queue is None else queue,
    }


def readers(event=None, municipal_page=None, venue_page=None,
            overpass=None, **extra):
    def official(url):
        if url == SOURCE:
            return official_page() if municipal_page is None else municipal_page
        if url == VENUE_URL:
            return (official_venue_html() if venue_page is None else venue_page)
        raise AssertionError("untrusted URL was read")
    return dict(
        agenda_reader=lambda uid, key: AGENDA,
        event_reader=lambda uid, eid, key: (
            oa_event() if event is None else event),
        directory_reader=lambda city: directory(),
        official_reader=official,
        ign_reader=lambda candidate: {"type": "FeatureCollection",
                                       "features": []},
        osm_reader=lambda center: (
            osm() if overpass is None else overpass),
        legacy_checker=lambda candidate, original: (
            False, "legacy_verification_was_not_satisfied"),
        **extra,
    )


class OpenWorldPublisherBridgeTests(unittest.TestCase):
    def test_verified_unknown_municipal_event_reaches_actual_legacy_merge(self):
        reference = base()
        before = deepcopy(reference)
        published, audit, bridge = merge_verified_open_world(
            reference, reference, private_patch(reference), TODAY,
            KEY, **readers(),
        )
        self.assertEqual(audit["ajoutes"], 1)
        self.assertEqual(bridge["admitted_to_merge"], 1)
        self.assertEqual(bridge["publisher_accepted_new"], 1)
        self.assertEqual(bridge["held"], 0)
        self.assertFalse(bridge["publication_complete"])
        self.assertEqual(reference, before)
        self.assertEqual(len(published["events"]), 101)
        self.assertEqual(published["events"][:100], reference["events"])
        ev = published["events"][-1]
        self.assertEqual(ev["id"], "openagenda-999401-2026-12-05")
        self.assertEqual(ev["time"], "10:00 ; 15:00")
        self.assertEqual(ev["source_url"], SOURCE)
        self.assertNotIn("open_world_research", ev)

    def test_missing_key_keeps_every_new_dossier_unpublished_without_network(self):
        ref = base()
        calls = Mock(side_effect=AssertionError("no network without OA key"))
        x = readers()
        for name in ("agenda_reader", "event_reader", "directory_reader",
                     "official_reader", "osm_reader", "ign_reader"):
            x[name] = calls
        published, audit, result = merge_verified_open_world(
            ref, ref, private_patch(ref), TODAY, "", **x)
        self.assertEqual(published, ref)
        self.assertEqual(audit["ajoutes"], 0)
        self.assertEqual(result["held"], 1)
        self.assertEqual(
            result["held_reason_counts"],
            {"openagenda_public_read_key_unavailable": 1})
        calls.assert_not_called()

    def test_unknown_organizer_url_cannot_mint_municipal_authority(self):
        ref = base()
        outsider = "https://organisateur-inconnu.example/atelier"
        published, audit, result = merge_verified_open_world(
            ref, ref,
            private_patch(ref, [dossier(official_event_url=outsider)]),
            TODAY, KEY, **readers())
        self.assertEqual(published, ref)
        self.assertEqual(audit["ajoutes"], 0)
        self.assertEqual(result["held_reason_counts"],
                         {"independent_municipal_source_delegation_missing": 1})

    def test_unknown_first_party_organizer_is_admitted_only_by_municipal_delegation(self):
        # A first-party venue host not on any hand-maintained registry.
        # A separately DILA-authenticated municipal page names the venue
        # and explicitly references the organizer site. All fixture data
        # here is synthetic and no actual publication occurs.
        ref = base()
        outsider = "https://nouvel-organisateur.example/spectacles/conte-musical"
        municipal_reference = "https://www.ville-les-bois.fr/culture/lieu"
        reference_html = (
            "<html><main><article><h2>Place du village</h2>"
            "<p>La salle propose sa programmation sur "
            "https://nouvel-organisateur.example/spectacles</p>"
            "</article></main></html>"
        )
        checks = readers()
        original = checks["official_reader"]
        checks["official_reader"] = lambda url: (
            official_page() if url == outsider else
            reference_html if url == municipal_reference else
            original(url))
        item = dossier(
            official_event_url=outsider,
            municipal_source_reference_url=municipal_reference,
        )
        published, audit, result = merge_verified_open_world(
            ref, ref, private_patch(ref, [item]), TODAY, KEY, **checks)
        self.assertEqual(audit["ajoutes"], 1)
        self.assertEqual(result["held"], 0)
        self.assertEqual(published["events"][-1]["source_url"], outsider)

        # The municipal page's named venue/domain match is provenance,
        # never sufficient without the current official event's own times.
        altered = dict(checks)
        altered["official_reader"] = lambda url: (
            official_page((10,)) if url == outsider else
            reference_html if url == municipal_reference else original(url))
        rejected, audit, result = merge_verified_open_world(
            ref, ref, private_patch(ref, [item]), TODAY, KEY, **altered)
        self.assertEqual(rejected, ref)
        self.assertEqual(audit["ajoutes"], 0)
        self.assertEqual(result["held"], 1)

    def test_unknown_nonmunicipal_host_cannot_borrow_unrelated_city_link(self):
        ref = base()
        outsider = "https://nouvel-organisateur.example/spectacles/conte"
        reference = "https://www.ville-les-bois.fr/culture/lieu"
        checks = readers()
        original = checks["official_reader"]
        checks["official_reader"] = lambda url: (
            "<html><main><article><h2>Autre salle</h2>"
            "<p>nouvel-organisateur.example</p></article></main></html>"
            if url == reference else original(url))
        bad, audit, result = merge_verified_open_world(
            ref, ref, private_patch(ref, [dossier(
                official_event_url=outsider,
                municipal_source_reference_url=reference)]),
            TODAY, KEY, **checks)
        self.assertEqual(bad, ref)
        self.assertEqual(audit["ajoutes"], 0)
        self.assertEqual(result["held_reason_counts"],
                         {"independent_municipal_source_delegation_unconfirmed": 1})

    def test_changed_oa_schedule_cancellation_source_or_geo_are_not_admitted(self):
        ref = base()
        for kind, args in (
            ("changed_hour", {"event": {
                **oa_event(),
                "timings": [
                    {**oa_event()["timings"][0],
                     "begin": "2026-12-05T11:00:00+01:00"},
                    oa_event()["timings"][1]]}}),
            ("cancelled", {"event": {**oa_event(), "status": 3}}),
            ("copyright", {"event": {
                **oa_event(), "rights": {
                    "license": {"id": "copyright"},
                    "licensor": {"name": "Association"}}}}),
            ("wrong_official_page", {"municipal_page":
                official_page().replace("Jeune public", "Réservé aux adultes")}),
            ("geography", {"overpass": {"elements": [
                {**osm()["elements"][0],
                 "center": {"lat": 44.51, "lon": 2.25}}]}}),
        ):
            with self.subTest(kind=kind):
                public, audit, result = merge_verified_open_world(
                    ref, ref, private_patch(ref), TODAY, KEY,
                    **readers(**args))
                self.assertEqual(public, ref)
                self.assertEqual(audit["ajoutes"], 0)
                self.assertEqual(result["held"], 1)

    def test_forged_research_approval_field_cannot_publish(self):
        ref = base()
        forged = dossier(approved=True, publication_ready=True)
        with self.assertRaises(ValueError):
            merge_verified_open_world(
                ref, ref, private_patch(ref, [forged]),
                TODAY, KEY, **readers())
        too_many = [dossier() for _ in range(31)]
        with self.assertRaises(ValueError):
            merge_verified_open_world(
                ref, ref, private_patch(ref, too_many),
                TODAY, KEY, **readers())

    def test_patch_candidate_cannot_be_changed_after_live_verification(self):
        ref = base()
        patched, checker, report = prepare_open_world_patch(
            ref, ref, private_patch(ref), TODAY, KEY, **readers())
        self.assertEqual(report["admitted_to_merge"], 1)
        self.assertNotIn("open_world_research", patched)
        self.assertFalse(patched["safe_to_publish"])
        item = patched["additions"][0]
        ok, _ = checker(item, ref["events"])
        self.assertTrue(ok)
        for replacement in (
            {"venue": "Invented venue"},
            {"time": "09:00"},
            {"lat": 10.0},
            {"source_url": "https://unverified.example/shows"},
        ):
            with self.subTest(replacement=replacement):
                self.assertFalse(checker({**item, **replacement},
                                         ref["events"])[0])

    def test_duplicate_and_historical_changes_never_overwrite_published(self):
        ref = base()
        first, first_audit, _ = merge_verified_open_world(
            ref, ref, private_patch(ref), TODAY, KEY, **readers())
        self.assertEqual(first_audit["ajoutes"], 1)
        again, next_audit, next_report = merge_verified_open_world(
            ref, first, private_patch(ref), TODAY, KEY, **readers())
        self.assertEqual(again, first)
        self.assertEqual(next_audit["ajoutes"], 0)
        self.assertEqual(next_report["held"], 1)
        forged = deepcopy(first)
        forged["events"][0]["title"] = "Historical tampering"
        with self.assertRaisesRegex(ValueError, "historique"):
            merge_verified_open_world(
                ref, forged, private_patch(ref), TODAY, KEY, **readers())

    def test_empty_open_world_queue_uses_legacy_route_without_credentials(self):
        ref = base()
        calls = Mock(side_effect=AssertionError("no independent OA recheck"))
        x = readers()
        x["event_reader"] = calls
        result, audit, diag = merge_verified_open_world(
            ref, ref, private_patch(ref, []), TODAY, "", **x)
        self.assertEqual(result, ref)
        self.assertEqual(diag["dossiers"], 0)
        self.assertEqual(audit["ajoutes"], 0)
        calls.assert_not_called()

    def test_summary_counts_never_expose_private_research_or_url(self):
        report = {"initial": 549, "final": 550, "ajoutes": 1,
                  "attente": [], "open_world_counts": {
                      "research_dossiers": 2, "reviewed_for_merge": 1,
                      "held_for_independent_review": 1}}
        visible = public_summary(report)
        self.assertIn("Dossiers nationaux présentés : 2", visible)
        self.assertIn("Nouvelles fiches conformes : 1", visible)
        self.assertNotIn("openagenda-999401", visible)
        self.assertNotIn(SOURCE, visible)


if __name__ == "__main__":
    unittest.main()
