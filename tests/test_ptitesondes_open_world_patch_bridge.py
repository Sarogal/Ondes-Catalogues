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
from run_cloud_sync import public_summary, redacted_blocker_counts
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

    def test_nonmusical_child_show_and_storytelling_reach_real_publisher(self):
        # Radio-adjacent performing arts are recognized by the national
        # discovery. A fully corroborated candidate must also be publishable,
        # despite historical catalogue categories being musical-only.
        for title, description, expected in (
            ("Spectacle pour enfants",
             "Spectacle de marionnettes jeune public pour enfants",
             "spectacle-jeunesse"),
            ("Lecture d'histoires pour enfants",
             "Lecture d'histoires jeunesse pour les familles",
             "lecture-jeunesse"),
        ):
            with self.subTest(title=title):
                live = oa_event()
                live["title"] = {"fr": title}
                live["description"] = {"fr": description}
                item = lead()
                item["title"] = title
                # An untrusted category proposal cannot grant publication;
                # the Publisher derives the category from the live OA read.
                item["editorial_category_proposal"] = "concert"
                page = official_page().replace(
                    "Conte musical pour enfants", title)
                original = base()
                published, audit, report = merge_verified_open_world(
                    original, original, private_patch(original, [
                        dossier(lead=item)]), TODAY, KEY,
                    **readers(event=live, municipal_page=page))
                self.assertEqual(audit["ajoutes"], 1)
                self.assertEqual(report["held"], 0)
                self.assertEqual(published["events"][-1]["category"], expected)
                self.assertEqual(published["events"][:100], original["events"])
                self.assertFalse(report["publication_complete"])

    def test_generic_gouter_and_arbitrary_category_cannot_be_published(self):
        for title, description in (
            ("Goûter au parc",
             "Rendez-vous convivial pour les enfants et familles"),
            ("Atelier de bricolage",
             "Activité pour enfants avec matériel de loisirs créatifs"),
            ("Spectacle réservé aux adultes",
             "Spectacle jeunesse interdit aux enfants"),
        ):
            with self.subTest(title=title):
                live = oa_event()
                live["title"] = {"fr": title}
                live["description"] = {"fr": description}
                item = lead()
                item["title"] = title
                item["editorial_category_proposal"] = "spectacle-jeunesse"
                page = official_page().replace(
                    "Conte musical pour enfants", title)
                reference = base()
                published, audit, result = merge_verified_open_world(
                    reference, reference,
                    private_patch(reference, [dossier(lead=item)]),
                    TODAY, KEY, **readers(
                        event=live, municipal_page=page))
                self.assertEqual(audit["ajoutes"], 0)
                self.assertEqual(result["admitted_to_merge"], 0)
                self.assertEqual(published, reference)

    def test_legacy_source_checker_cannot_self_enable_child_art_categories(self):
        from merge_policy import merge
        reference = base()
        item = {**reference["events"][0], "id": "new-child-reading",
                "category": "lecture-jeunesse",
                "category_label": "Lecture jeunesse"}
        patch = private_patch(reference, [])
        patch["additions"] = [item]
        with self.assertRaises(ValueError):
            merge(reference, reference, patch, TODAY,
                  verified_child_arts=frozenset({"lecture-jeunesse"}))
        with self.assertRaises(ValueError):
            merge(reference, reference, patch, TODAY,
                  verified_child_arts={"lecture-jeunesse"})

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

    def test_dila_municipal_event_page_proves_venue_without_postcode(self):
        # A city event page can document "L'Etage ... Adresse 1 esplanade"
        # without a JSON-LD Place or postal code. A real BAN street address
        # and OA point must still match. All fixture names are synthetic.
        ref = base()
        outsider = "https://nouvel-organisateur.example/spectacles/conte-musical"
        source_reference = "https://www.ville-les-bois.fr/culture/lieu"
        venue_reference = "https://www.ville-les-bois.fr/agenda/autre-spectacle"
        domain_page = (
            "<html><main><article><h2>Place du village</h2>"
            "<p>Voir la programmation sur nouvel-organisateur.example</p>"
            "</article></main></html>"
        )
        venue_page = (
            "<html><main><article><h1>Un ancien événement</h1>"
            "<div>Place du village</div>"
            "<h2>Adresse</h2><p>1 esplanade des Rêves</p>"
            "</article></main></html>")
        fixtures = readers()
        old = fixtures["official_reader"]
        fixtures["official_reader"] = lambda url: (
            official_page() if url == outsider else
            domain_page if url == source_reference else
            venue_page if url == venue_reference else old(url))
        fixtures["ign_reader"] = lambda c: {
            "type": "FeatureCollection", "features": [{
                "type": "Feature",
                "properties": {
                    "type": "housenumber", "score": 0.99,
                    "city": c["city"], "street": "Esplanade des rêves",
                    "postcode": "12345", "housenumber": "1",
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [2.25, 44.5],
                },
            }]}
        # If the BAN check succeeds, the OSM fallback must not be called.
        fixtures["osm_reader"] = Mock(
            side_effect=AssertionError("BAN should suffice"))
        patched, audit, report = merge_verified_open_world(
            ref, ref, private_patch(ref, [dossier(
                official_event_url=outsider,
                official_venue_url=venue_reference,
                municipal_source_reference_url=source_reference,
            )]), TODAY, KEY, **fixtures)
        self.assertEqual(audit["ajoutes"], 1)
        self.assertEqual(report["held"], 0)
        self.assertEqual(patched["events"][-1]["source_url"], outsider)
        fixtures["osm_reader"].assert_not_called()

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

    def test_missing_oa_gps_is_rescued_only_by_named_municipal_ban_address(self):
        # OpenAgenda supplies the precise event identity, title and sessions
        # but does NOT have coordinates. An exact named municipal venue and
        # independently unique BAN housenumber can still geolocate it.
        from test_ptitesondes_municipal_event_venue_ban import ban
        ref = base()
        live = oa_event()
        live["location"] = {
            k: v for k, v in live["location"].items()
            if k not in ("latitude", "longitude")}
        html = official_page().replace(
            "</article>", "<h2>Adresse</h2>"
            "<p>1 esplanade Charles-de-Gaulle</p></article>")
        fixtures = readers(event=live)
        old = fixtures["official_reader"]
        fixtures["official_reader"] = lambda url: (
            html if url == SOURCE else old(url))
        fixtures["ign_reader"] = lambda query: ban()
        fixtures["osm_reader"] = Mock(
            side_effect=AssertionError("exact BAN should suffice"))
        final, audit, counts = merge_verified_open_world(
            ref, ref, private_patch(ref, [dossier(
                official_event_url=SOURCE, official_venue_url=SOURCE)]),
            TODAY, KEY, **fixtures)
        self.assertEqual(audit["ajoutes"], 1)
        self.assertEqual(counts["held"], 0)
        self.assertEqual(final["events"][:100], ref["events"])
        new = final["events"][-1]
        self.assertEqual((new["lat"], new["lng"]), (44.5, 2.25))
        self.assertEqual(new["geo_precision"], "venue")
        fixtures["osm_reader"].assert_not_called()

    def test_missing_or_partial_oa_gps_can_never_justify_approximation(self):
        from test_ptitesondes_municipal_event_venue_ban import ban
        ref = base()
        html = official_page().replace(
            "</article>", "<h2>Adresse</h2>"
            "<p>1 esplanade Charles-de-Gaulle</p></article>")
        for kind, location, geo in (
            ("partial", {"latitude": 44.5}, ban()),
            ("contradiction", {}, ban(street="Rue des Roses")),
            ("wrong_citycode", {}, dict(ban(),
                              features=[dict(ban()["features"][0],
                                  properties={**ban()["features"][0]["properties"],
                                              "citycode": "99999"})])),
            ("ambiguous", {}, {"type": "FeatureCollection",
                               "features": ban()["features"] * 2}),
            ("no_municipal_address", {}, ban()),
        ):
            with self.subTest(kind=kind):
                live = oa_event()
                live["location"] = {
                    k: v for k, v in live["location"].items()
                    if k not in ("latitude", "longitude")}
                live["location"].update(location)
                fixtures = readers(event=live)
                old = fixtures["official_reader"]
                fixtures["official_reader"] = lambda url: (
                    (official_page() if kind == "no_municipal_address" else html)
                    if url == SOURCE else old(url))
                fixtures["ign_reader"] = lambda query: geo
                result, report, counts = merge_verified_open_world(
                    ref, ref, private_patch(ref, [dossier(
                        official_event_url=SOURCE, official_venue_url=SOURCE)]),
                    TODAY, KEY, **fixtures)
                self.assertEqual(result, ref)
                self.assertEqual(report["ajoutes"], 0)
                self.assertEqual(counts["held"], 1)

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

    def test_public_blocker_report_redacts_untrusted_reason_keys(self):
        private_url = "https://secret-candidate.example/unknown-event"
        grouped = redacted_blocker_counts({
            "rehearsal_source_exact_sessions_changed": 2,
            "fresh_independent_venue_proof_missing": 1,
            private_url: 3,
            "venue_à_une_adresse_secrète": 1,
        })
        self.assertEqual(grouped, {
            "fresh_independent_venue_proof_missing": 1,
            "other_private_reason": 4,
            "rehearsal_source_exact_sessions_changed": 2,
        })
        report = {
            "initial": 549, "final": 549, "ajoutes": 0, "attente": [],
            "open_world_counts": {
                "research_dossiers": 7, "reviewed_for_merge": 0,
                "held_for_independent_review": 7,
                "reason_counts": grouped,
            }}
        visible = public_summary(report)
        self.assertIn("rehearsal_source_exact_sessions_changed : 2", visible)
        self.assertIn("other_private_reason : 4", visible)
        self.assertNotIn(private_url, visible)
        self.assertNotIn("venue_à_une_adresse_secrète", visible)

    def test_live_rehearsal_reject_records_exact_safe_stage(self):
        original = base()
        rejected, audit, bridge = merge_verified_open_world(
            original, original, private_patch(original), TODAY, KEY,
            **readers(municipal_page=official_page((10,))))
        self.assertEqual(audit["ajoutes"], 0)
        self.assertEqual(rejected, original)
        self.assertEqual(
            bridge["held_reason_counts"],
            {"rehearsal_municipal_exact_session_title_venue_or_family_unproved": 1})

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
