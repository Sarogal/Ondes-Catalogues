"""Offline and private-only research dossier selection for actual publisher."""
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from test_ptitesondes_open_world_release_rehearsal import lead, TODAY
from test_ptitesondes_open_world_patch_bridge import private_patch, dossier
from test_ptitesondes_candidate_promotion import base
from ptitesondes_national_backlog_bridge import _inventory_key
from ptitesondes_open_world_private_dossier_intake import (
    collect_research_dossiers, attach_research_dossiers,
    review_batch_for_cron, choose_national_bridge_batch,
    published_ids_from_catalogue,
)
from ptitesondes_private_research_carry_forward import (
    carry_same_day_research,
)

SOURCE = "https://www.nouvelle-salle.example/spectacles/conte-musical"
MUNICIPAL = "https://www.commune-inconnue.example/evenement/ancien-concert"
EXTERNAL = "https://nouvelle-salle.example/spectacles/ancien-concert"


def entry():
    item = lead()
    return ({"new_agenda_candidates": [{"agenda_uid": item["agenda_uid"]}]},
            "a" * 64,
            {"event_leads": [item], "campaign_meta": {"segment": 0}},
            TODAY, 0)


def report(ref=None, source=SOURCE, linked=EXTERNAL, municipal=MUNICIPAL):
    return {"ref": ref or _inventory_key(entry()),
            "day": TODAY.isoformat(),
            "review": {
                "schema": "ptitesondes.private_open_world_candidate_rotation.v1",
                "publication_ready": False, "public_writes": 0,
                "private_unverified_oa_web_leads": [{
                    "url": source, "source_field": "canonicalUrl",
                    "candidate_only": True, "owner_verified": False,
                    "publication_ready": False, "source_rights_reviewed": False,
                }],
                "private_research_reviews": [{
                    "municipal_url": municipal, "source_url": linked,
                    "diagnostic": {"status": "research_only"},
                }],
            }}


class NationalPrivateDossierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)
        self.observation = self.parent / "observations"
        self.research = self.parent / "research"
        self.day = self.research / "reports" / TODAY.isoformat()
        self.day.mkdir(parents=True)
        self.record = entry()

    def write(self, data):
        path = self.day / (data["ref"] + ".json")
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf8")

    def load(self, *, include_direct=False, **kwargs):
        rows, metrics = collect_research_dossiers(
            self.observation, self.research, TODAY,
            inventory_reader=lambda _: [self.record], **kwargs)
        if include_direct:
            return rows, metrics
        # Legacy municipal-research assertions remain scoped to that lane.
        # OA-only dossiers have dedicated coverage below.
        rows = [row for row in rows if not row["official_event_url"].startswith(
            "https://openagenda.com/")]
        metrics = dict(metrics, queued=len(rows), candidate_dossiers=(
            metrics["candidate_dossiers"] - len(self.direct_dossiers())))
        return rows, metrics

    def direct_dossiers(self):
        rows, _ = collect_research_dossiers(
            self.observation, self.research, TODAY,
            inventory_reader=lambda _: [self.record])
        return [row for row in rows if row["official_event_url"].startswith(
            "https://openagenda.com/")]

    def test_reclaims_confirmed_public_dossiers_without_dropping_new_sources(self):
        day = (TODAY + timedelta(days=10)).isoformat()
        old = [
            dict(dossier(), lead=dict(lead(), event_uid=50000+i),
                 date_start=day)
            for i in range(80)
        ]
        new = [
            dict(dossier(), lead=dict(lead(), event_uid=60000+i),
                 date_start=day)
            for i in range(15)
        ]
        published = {
            f"openagenda-{50000+i}-{day}" for i in range(70)
        }
        patch = private_patch(base(), queue=old)
        result = attach_research_dossiers(
            patch, new, TODAY, published_ids=published)
        kept = result["open_world_research"]
        self.assertEqual(len(kept), 25)
        self.assertEqual(
            [x["lead"]["event_uid"] for x in kept],
            [50000+i for i in range(70, 80)]
            + [60000+i for i in range(15)])
        self.assertEqual(len(patch["open_world_research"]), 80)
        self.assertEqual(len(new), 15)
        self.assertNotIn("safe_to_publish", kept[0])
        self.assertFalse(result["safe_to_publish"])

    def test_no_source_registry_or_session_limit_in_public_duplicate_pruning(self):
        day = (TODAY + timedelta(days=20)).isoformat()
        long_series = [dict(dossier(), lead=dict(lead(), event_uid=777777),
                            date_start=(TODAY + timedelta(days=k)).isoformat())
                       for k in range(1, 48)]
        unknown = dict(dossier(), lead=dict(
            lead(), agenda_uid=88888888, agenda_slug="new-unknown-commune",
            event_uid=777778), date_start=day)
        patch = private_patch(base(), queue=long_series)
        filtered = attach_research_dossiers(
            patch, [unknown], TODAY, published_ids={
                f"openagenda-777777-{(TODAY + timedelta(days=k)).isoformat()}"
                for k in range(1, 16)})
        sessions = filtered["open_world_research"]
        self.assertEqual(len(sessions), 33)
        self.assertEqual(sum(x["lead"]["event_uid"] == 777777 for x in sessions),
                         32)
        self.assertEqual(sessions[-1]["lead"]["agenda_slug"],
                         "new-unknown-commune")

    def test_invalid_public_snapshot_never_authorizes_queue_filtering(self):
        for value in (None, [], {}, {"events": "corrupt"},
                      {"events": [{"id": 123}]}):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "invalid_public_duplicate_snapshot"):
                    published_ids_from_catalogue(value)
        self.assertEqual(published_ids_from_catalogue(
            {"events": [{"id": "openagenda-42-2026-12-05"}]}),
            {"openagenda-42-2026-12-05"})

    def test_malformed_or_wrong_type_published_ids_rejected(self):
        patch = private_patch(base(), queue=[dossier()])
        for bad in ([], "openagenda-1", {123}, {False}):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ValueError, "invalid_public_duplicate_snapshot"):
                    attach_research_dossiers(
                        patch, [], TODAY, published_ids=bad)

    def test_no_legacy_review_slots_cover_all_four_scheduled_batches(self):
        for cron, hour, batch in (
            ("17 07 * * *", 7, 0),
            ("17 10 * * *", 10, 1),
            ("17 14 * * *", 14, 2),
            ("17 18 * * *", 18, 3),
        ):
            with self.subTest(cron=cron):
                self.assertEqual(review_batch_for_cron(cron, hour), batch)
        # Unknown/manual triggers are still deterministic UTC four-way runs.
        self.assertEqual(review_batch_for_cron("", 2), 0)
        self.assertEqual(review_batch_for_cron("", 23), 3)
        for invalid in (-1, 24, "7", True):
            with self.assertRaises(ValueError):
                review_batch_for_cron("", invalid)

    def test_no_legacy_slot_first_cycle_transmits_small_oa_only_queue(self):
        batch = review_batch_for_cron("17 07 * * *", 7)
        rows, metrics = self.load(include_direct=True, batch_index=batch)
        self.assertEqual(metrics["reports"], 0)
        self.assertEqual(metrics["queued"], 1)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["official_event_url"].startswith(
            "https://openagenda.com/"))
        # Future slots must not repeat the same dossier.
        for cron, hour in (("17 10 * * *", 10),
                           ("17 14 * * *", 14),
                           ("17 18 * * *", 18)):
            next_rows, _ = self.load(include_direct=True, batch_index=(
                review_batch_for_cron(cron, hour)))
            self.assertEqual(next_rows, [])

    def test_private_workflow_uses_cron_aware_batch_selector(self):
        source = (ROOT / ".github/workflows/"
                  "ptitesondes-private-intake-on-public-runners.yml").read_text(
                      encoding="utf-8")
        self.assertIn('choose_national_bridge_batch(os.getenv("REVIEW_CRON","")', source)
        self.assertIn('batch-index "$OA_BRIDGE_BATCH"', source)
        self.assertIn(
            'if [[ -d "$STATE/national-observation/index/reports" ]]; then',
            source)
        self.assertNotIn(
            'if [[ ${#REVIEW_SLOTS[@]} -eq 0 && -d "$STATE/national-observation/index/reports" ]]; then',
            source)
        # The bridge runs *after* the historical slot loop and reads the
        # current private patch, even when slot 3 was the only replayed slot.
        self.assertLess(source.index("          done\n          # National"),
                        source.index('choose_national_bridge_batch'))
        self.assertIn('"$STATE/patch-$DAY.json")"', source)
        self.assertNotIn(
            'if [[ -d "$STATE/national-observation/research/reports" ]]; then',
            source)

    def test_slot_three_cannot_starve_first_party_batch_zero_after_deploy(self):
        # The 18:47 UTC external rescue run can process historical slot 3,
        # while slots 0-2 were consumed by the former production version.
        # The OA queue starts empty and has only one eligible first batch.
        for cron in ("", "17 18 * * *"):
            with self.subTest(cron=cron):
                selected = choose_national_bridge_batch(cron, 18, [])
                self.assertEqual(selected, 0)
                batch, counts = self.load(
                    include_direct=True, batch_index=selected)
                self.assertEqual(counts["queued"], 1)
                patch = private_patch({"updated_at": "unused", "events": []},
                                      queue=[])
                forwarded = attach_research_dossiers(patch, batch, TODAY)
                self.assertEqual(len(forwarded["open_world_research"]), 1)
                self.assertEqual(forwarded["additions"], [])
                self.assertFalse(forwarded["safe_to_publish"])
                # Once a dossier exists, the regular scheduling partition
                # resumes and cannot replace the outstanding request.
                self.assertEqual(
                    choose_national_bridge_batch(
                        cron, 18, forwarded["open_world_research"]), 3)

    def test_bridge_batch_fails_closed_on_untrusted_private_queue(self):
        for bad in (None, {}, "no", [None] * 81):
            with self.subTest(bad=type(bad).__name__):
                with self.assertRaises(ValueError):
                    choose_national_bridge_batch("", 18, bad)

    def test_private_actions_summary_exposes_only_bounded_queue_count(self):
        workflow = (ROOT / ".github/workflows/"
                    "ptitesondes-private-intake-on-public-runners.yml"
                    ).read_text(encoding="utf-8")
        self.assertIn('OA_HANDOFF_COUNT="$(python -c', workflow)
        self.assertIn('assert type(q) is list and len(q)<=80', workflow)
        self.assertIn('Dossiers OA sauvegardés en privé', workflow)
        self.assertIn('Dossiers OA en prévisualisation uniquement', workflow)
        self.assertNotIn('print(q)', workflow)
        self.assertNotIn('print(q[0])', workflow)

    def test_direct_openagenda_can_stage_without_research_root(self):
        missing = self.parent / "never-collected-external-web-clues"
        self.assertFalse(missing.exists())
        rows, counts = collect_research_dossiers(
            self.observation, missing, TODAY,
            inventory_reader=lambda _: [self.record])
        self.assertEqual(counts["reports"], 0)
        self.assertEqual(counts["queued"], 1)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["official_event_url"].startswith(
            "https://openagenda.com/"))

    def test_openagenda_uid_queues_without_municipal_or_external_link(self):
        rows, metrics = self.load(include_direct=True)
        self.assertEqual(len(rows), 1)
        self.assertEqual(metrics["queued"], 1)
        self.assertEqual(rows[0]["official_event_url"],
                         "https://openagenda.com/agenda-nouveau-organisateur/events/999401")
        self.assertEqual(rows[0]["official_event_url"], rows[0]["official_venue_url"])
        self.assertFalse(rows[0]["lead"]["publication_ready"])

    def test_research_queue_survives_an_entire_new_collector_run(self):
        ref = {"updated_at": "unchanged", "events": []}
        old = private_patch(ref, queue=[])
        old = attach_research_dossiers(old, [{
            "lead": lead(), "date_start": TODAY.isoformat(),
            "official_event_url": SOURCE,
            "official_venue_url": MUNICIPAL,
        }], TODAY)
        # Fresh daily collection may know *nothing* about open-world research.
        fresh = private_patch(ref, queue=[])
        fresh.pop("open_world_research")
        fresh["deferred"] = [{"title": "Other private lead"}]
        result = carry_same_day_research(old, fresh, TODAY)
        self.assertEqual(result["open_world_research"], old["open_world_research"])
        self.assertEqual(result["deferred"], fresh["deferred"])
        self.assertEqual(result["additions"], fresh["additions"])
        self.assertFalse(result["safe_to_publish"])
        # No review slots in the next run: a second carry is idempotent.
        repeat = carry_same_day_research(result, fresh, TODAY)
        self.assertEqual(repeat, result)
        self.assertNotIn("open_world_research", fresh)

    def test_carry_never_changes_fresh_verified_historical_additions(self):
        ref = {"updated_at": "unchanged", "events": []}
        old = private_patch(ref, queue=[])
        old = attach_research_dossiers(old, [{
            "lead": lead(), "date_start": TODAY.isoformat(),
            "official_event_url": SOURCE,
            "official_venue_url": MUNICIPAL,
        }], TODAY)
        fresh = private_patch(ref, queue=[])
        fresh["additions"] = [{"id": "already-verified-by-private-preflight"}]
        carried = carry_same_day_research(old, fresh, TODAY)
        self.assertEqual(carried["additions"], fresh["additions"])
        self.assertEqual(len(carried["open_world_research"]), 1)

    def test_carry_rejects_stale_or_mismatched_private_patches(self):
        ref = {"updated_at": "unchanged", "events": []}
        old = private_patch(ref, queue=[])
        fresh = private_patch(ref, queue=[])
        for changed in (
            dict(old, generated_at=(TODAY - timedelta(days=1)).isoformat()),
            dict(old, safe_to_publish=True),
            dict(old, source=dict(old["source"], updated_at="other")),
            dict(old, open_world_research=[{"url": SOURCE}]),
            dict(old, updates=[{"id": "unapproved-change"}]),
            dict(old, checks={"ids_unique": False}),
        ):
            with self.subTest(mutation=list(changed)):
                with self.assertRaises(ValueError):
                    carry_same_day_research(changed, fresh, TODAY)

    def test_private_workflow_carries_queue_before_patch_overwrite(self):
        workflow = (
            ROOT / ".github/workflows/ptitesondes-private-intake-on-public-runners.yml"
        ).read_text(encoding="utf-8")
        carry = "public/scripts/ptitesondes_private_research_carry_forward.py"
        overwrite = 'cp "$OUT/patch-$DAY.json" "$STATE/patch-$DAY.json"'
        self.assertIn(carry, workflow)
        self.assertIn(overwrite, workflow)
        self.assertLess(workflow.index(carry), workflow.index(overwrite))
        self.assertIn('if [[ -s "$STATE/patch-$DAY.json" ]]; then', workflow)
        self.assertIn("ne pas écraser la file", workflow)
        # The per-report collector already enforces the rolling 14-day
        # freshness cap. No outside research folder is needed to queue
        # UID-first OpenAgenda leads from the private indexed inventory.
        self.assertIn(
            'if [[ -d "$STATE/national-observation/index/reports" ]]; then',
            workflow)
        self.assertNotIn(
            'if [[ -d "$STATE/national-observation/research/reports/$DAY" ]]; then',
            workflow)

    def test_municipally_discovered_unknown_domain_creates_research_not_addition(self):
        self.write(report())
        rows, stats = self.load()
        self.assertEqual(len(rows), 2)
        self.assertEqual(stats["candidate_dossiers"], 2)
        self.assertEqual(stats["queued"], 2)
        self.assertTrue(all(row["official_event_url"] == SOURCE for row in rows))
        municipal = next(row for row in rows
                         if row["official_venue_url"] == MUNICIPAL)
        self.assertEqual(municipal["municipal_source_reference_url"], MUNICIPAL)
        self.assertFalse(rows[0]["lead"]["publication_ready"])
        ref = {"updated_at": "unused", "events": []}
        patch = private_patch(ref, queue=[])
        out = attach_research_dossiers(patch, rows, TODAY)
        self.assertEqual(out["additions"], [])
        self.assertFalse(out["safe_to_publish"])
        self.assertEqual(out["open_world_research"], rows)
        self.assertEqual(len(patch["additions"]), 0)
        self.assertEqual(patch["open_world_research"], [])
        # A later review slot often discovers no new dossier: this must NOT
        # delete a prior slot's pending requests before the Publisher runs.
        refreshed = attach_research_dossiers(out, [], TODAY)
        self.assertEqual(refreshed["open_world_research"], rows)
        self.assertFalse(refreshed["safe_to_publish"])

    def test_canonical_source_remains_eligible_even_with_municipal_backlink(self):
        # A second source is optional; the Publisher must receive the OA
        # canonical URL as its own independent research candidate.
        self.write(report(source=SOURCE, linked=EXTERNAL, municipal=MUNICIPAL))
        rows, counts = self.load()
        self.assertEqual(counts["candidate_dossiers"], 2)
        self.assertEqual({row["official_venue_url"] for row in rows},
                         {SOURCE, MUNICIPAL})
        self.assertTrue(all(row["official_event_url"] == SOURCE for row in rows))
        self.assertTrue(all(row["lead"]["publication_ready"] is False
                            for row in rows))

    def test_unpaired_canonical_url_is_research_only_not_autoapproval(self):
        # Any unknown publisher-supplied source is untrusted. It can be
        # presented for independent DILA verification, but cannot approve.
        for source, linked in (
            ("https://other.example/spectacle", EXTERNAL),
            (SOURCE, "https://nouvelle-salle.example.evil.test/spectacle"),
        ):
            with self.subTest(source=source):
                self.write(report(source=source, linked=linked))
                rows, counts = self.load()
                self.assertEqual(counts["queued"], 1)
                self.assertEqual(rows[0]["official_event_url"], source)
                self.assertEqual(rows[0]["official_venue_url"], source)
                self.assertNotIn("municipal_source_reference_url", rows[0])
                ref = {"updated_at": "unused", "events": []}
                queued = attach_research_dossiers(
                    private_patch(ref, queue=[]), rows, TODAY)
                self.assertFalse(queued["safe_to_publish"])
                self.assertEqual(queued["additions"], [])

    def test_unpaired_exact_venue_website_is_an_untrusted_research_request(self):
        item = report()
        item["review"]["private_unverified_oa_web_leads"][0][
            "source_field"] = "location.website"
        item["review"]["private_research_reviews"] = []
        self.write(item)
        rows, metrics = self.load()
        self.assertEqual(metrics["queued"], 1)
        self.assertEqual(rows[0]["official_event_url"], SOURCE)
        self.assertEqual(rows[0]["official_venue_url"], SOURCE)
        self.assertNotIn("municipal_source_reference_url", rows[0])
        self.assertFalse(rows[0]["lead"]["publication_ready"])
        ref = {"updated_at": "unchanged", "events": []}
        private = attach_research_dossiers(
            private_patch(ref, queue=[]), rows, TODAY)
        self.assertEqual(private["additions"], [])
        self.assertFalse(private["safe_to_publish"])

    def test_unrelated_registration_link_without_backlink_never_promoted(self):
        item = report()
        item["review"]["private_unverified_oa_web_leads"][0][
            "source_field"] = "registration"
        item["review"]["private_research_reviews"] = []
        self.write(item)
        self.assertEqual(self.load()[0], [])

    def test_private_runner_prepares_national_dossiers_without_legacy_slots(self):
        workflow = (ROOT / ".github" / "workflows" /
                    "ptitesondes-private-intake-on-public-runners.yml"
                    ).read_text(encoding="utf-8")
        # The independent bridge must be present after the legacy review
        # loop whether it yielded zero or four slots. It is not conditional
        # on the legacy slot count anymore.
        guard = 'if [[ -d "$STATE/national-observation/index/reports" ]]; then'
        self.assertGreaterEqual(workflow.count(guard), 2)
        fallback = workflow[workflow.rindex(guard):]
        self.assertIn("ptitesondes_open_world_private_dossier_intake.py",
                      fallback)
        self.assertIn("patch-national-bridge-$DAY.json", fallback)
        self.assertIn("push_private 'data(ptitesondes): transmettre",
                      fallback)
        self.assertLess(workflow.index("          done\n          # National"),
                        workflow.rindex(guard))
        self.assertLess(workflow.rindex(guard),
                        workflow.index("# Dashboard redacted"))
        self.assertIn('if [[ "$RUN_MODE" == "write" ]]; then',
                      fallback)

    def test_unsafe_or_noncanonical_url_never_enters_direct_lane(self):
        for source in (
            "http://nouvelle-salle.example/spectacle",
            "https://openagenda.com/agenda/dummy",
            "https://nouvelle-salle.example/",
            "https://nouvelle-salle.example@evil.test/event",
        ):
            with self.subTest(source=source):
                self.write(report(source=source, linked=EXTERNAL))
                rows, counts = self.load()
                self.assertEqual(rows, [])
                self.assertEqual(counts["queued"], 0)
        other = report()
        other["review"]["private_unverified_oa_web_leads"][0][
            "source_field"] = "registration"
        other["review"]["private_research_reviews"] = []
        self.write(other)
        self.assertEqual(self.load()[0], [])

    def test_stale_rotation_clues_remain_eligible_for_live_recheck(self):
        # A link discovered yesterday still deserves an independent live
        # Publisher check today. It never becomes a cached "verified" flag.
        prior_day = TODAY - timedelta(days=1)
        data = report()
        data["day"] = prior_day.isoformat()
        old = self.research / "reports" / prior_day.isoformat()
        old.mkdir(parents=True)
        (old / (data["ref"] + ".json")).write_text(
            json.dumps(data), encoding="utf8")
        rows, counts = self.load()
        self.assertEqual(len(rows), 2)
        self.assertEqual(counts["reports"], 1)
        self.assertEqual(rows[0]["official_event_url"], SOURCE)

    def test_sources_and_municipal_links_found_on_different_days_can_pair(self):
        previous = TODAY - timedelta(days=2)
        old = report()
        old["day"] = previous.isoformat()
        old["review"]["private_research_reviews"] = []
        day_dir = self.research / "reports" / previous.isoformat()
        day_dir.mkdir(parents=True)
        (day_dir / (old["ref"] + ".json")).write_text(
            json.dumps(old), encoding="utf8")
        new = report()
        new["review"]["private_unverified_oa_web_leads"] = []
        self.write(new)
        rows, counts = self.load()
        self.assertEqual(counts["reports"], 2)
        self.assertEqual(counts["pairs"], 1)
        self.assertEqual(len(rows), 2)
        self.assertTrue(any(row["official_venue_url"] == MUNICIPAL for row in rows))
        self.assertEqual(next(row for row in rows if row["official_venue_url"] == MUNICIPAL)["municipal_source_reference_url"], MUNICIPAL)

    def test_old_research_does_not_become_permanent_authority(self):
        old = report()
        distant = TODAY - timedelta(days=15)
        old["day"] = distant.isoformat()
        old_dir = self.research / "reports" / distant.isoformat()
        old_dir.mkdir(parents=True)
        (old_dir / (old["ref"] + ".json")).write_text(
            json.dumps(old), encoding="utf8")
        rows, stats = self.load()
        self.assertEqual(rows, [])
        self.assertEqual(stats["reports"], 0)

    def test_untrusted_approval_flag_is_not_forwarded(self):
        value = report()
        value["review"]["private_unverified_oa_web_leads"][0][
            "owner_verified"] = True
        self.write(value)
        rows, _ = self.load()
        self.assertEqual(rows, [])
        value = report()
        value["review"]["private_research_reviews"][0]["diagnostic"] = {
            "publisher_connected": True, "approved": True}
        self.write(value)
        rows, _ = self.load()
        self.assertEqual(len(rows), 2)
        self.assertNotIn("diagnostic", rows[0])
        self.assertNotIn("approved", str(rows[0]))

    def test_stale_report_date_and_forged_research_shape_fail_closed(self):
        value = report()
        value["day"] = "2026-11-20"
        self.write(value)
        with self.assertRaises(ValueError):
            self.load()
        value = report()
        value["day"] = TODAY.isoformat()
        value["review"]["publication_ready"] = True
        self.write(value)
        with self.assertRaises(ValueError):
            self.load()

    def test_partitions_do_not_repeat_a_dossier_across_slots(self):
        self.write(report())
        first, _ = self.load(batch_index=0)
        second, _ = self.load(batch_index=1)
        self.assertEqual(len(first), 2)
        self.assertEqual(second, [])
        fourth, _ = self.load(batch_index=3)
        self.assertEqual(fourth, [])

    def test_private_dossier_to_real_publisher_merge_synthetic_pipeline(self):
        # Exercise the ACTUAL producer contract and Publisher in one test.
        # Every source is a synthetic independent fixture. A green producer
        # test alone must never be mistaken for a publication.
        from test_ptitesondes_open_world_patch_bridge import readers
        from test_ptitesondes_open_world_release_rehearsal import (
            SOURCE as EVENT_PAGE,
        )
        from test_ptitesondes_unnumbered_official_geo_proof import (
            URL as VENUE_PAGE,
        )
        from ptitesondes_open_world_patch_bridge import (
            merge_verified_open_world,
        )
        from test_ptitesondes_candidate_promotion import base

        ref = base()
        self.write(report(
            source=EVENT_PAGE, linked=EVENT_PAGE, municipal=VENUE_PAGE))
        requests, metrics = self.load()
        self.assertEqual(metrics["queued"], 2)
        requests = [row for row in requests if row["official_venue_url"] != EVENT_PAGE]
        self.assertEqual(len(requests), 1)
        self.assertNotIn("municipal_source_reference_url", requests[0])
        staged = attach_research_dossiers(
            private_patch(ref, queue=[]), requests, TODAY)
        self.assertFalse(staged["safe_to_publish"])
        self.assertEqual(staged["additions"], [])
        # A later private review slot may have no discoveries.
        cumulative = attach_research_dossiers(staged, [], TODAY)
        self.assertEqual(len(cumulative["open_world_research"]), 1)
        published, audit, summary = merge_verified_open_world(
            ref, ref, cumulative, TODAY,
            "oa_pk_offline_research_to_publisher", **readers())
        self.assertEqual(audit["ajoutes"], 1)
        self.assertEqual(summary["publisher_accepted_new"], 1)
        self.assertEqual(summary["held"], 0)
        self.assertEqual(published["events"][:100], ref["events"])
        self.assertEqual(published["events"][-1]["source_url"], EVENT_PAGE)
        self.assertFalse(summary["publication_complete"])

    def test_later_review_slot_keeps_and_deduplicates_queued_dossiers(self):
        reference = {"updated_at": "unused", "events": []}
        patch = private_patch(reference, queue=[])
        a = self.load()[0]
        self.assertEqual(a, [])
        first = report()
        self.write(first)
        a = self.load()[0]
        slot1 = attach_research_dossiers(patch, a, TODAY)
        # Both distinct venue-research requests must survive one review slot;
        # the new OpenAgenda-first lane must not collapse the existing paths.
        self.assertEqual(len(a), 2)
        self.assertEqual(slot1["open_world_research"], a)
        # The same clues and an empty following batch must preserve both rows.
        slot2 = attach_research_dossiers(slot1, a, TODAY)
        slot3 = attach_research_dossiers(slot2, [], TODAY)
        self.assertEqual(slot2["open_world_research"], a)
        self.assertEqual(slot3["open_world_research"], a)
        self.assertEqual(slot3["additions"], [])

    def test_cumulative_research_queue_has_bounded_capacity_without_approval(self):
        reference = {"updated_at": "unused", "events": []}
        patch = private_patch(reference, queue=[])
        seed = self.load()[0]
        self.assertEqual(seed, [])
        original = report()
        self.write(original)
        item = self.load()[0][0]
        first = [
            {**item, "lead": {**item["lead"], "event_uid": 900000 + i}}
            for i in range(80)]
        waiting = attach_research_dossiers(patch, first, TODAY)
        self.assertEqual(len(waiting["open_world_research"]), 80)
        later = attach_research_dossiers(waiting, [{
            **item, "lead": {**item["lead"], "event_uid": 990000},
        }], TODAY)
        self.assertEqual(later["open_world_research"], first)
        self.assertEqual(later["additions"], [])
        self.assertFalse(later["safe_to_publish"])

    def test_no_report_yields_safe_empty_queue_and_no_new_publish_claim(self):
        rows, metrics = self.load()
        self.assertEqual(rows, [])
        self.assertEqual(metrics["queued"], 0)
        ref = {"updated_at": "unused", "events": []}
        patch = private_patch(ref, queue=[])
        out = attach_research_dossiers(patch, rows, TODAY)
        self.assertEqual(out["additions"], [])
        self.assertEqual(out["open_world_research"], [])

    def test_private_patch_rejects_unexpected_authority_or_excess(self):
        ref = {"updated_at": "unused", "events": []}
        base = private_patch(ref, queue=[])
        for changed in (
            dict(base, safe_to_publish=True),
            dict(base, schema="ptitesondes.patch.replacement"),
            dict(base, generated_at="2026-11-20"),
            dict(base, open_world_research={"approved": True}),
            dict(base, open_world_research=[{"approved": True}] * 81),
        ):
            with self.subTest(value=str(changed)[:70]):
                with self.assertRaises(ValueError):
                    attach_research_dossiers(changed, [], TODAY)


if __name__ == "__main__":
    unittest.main()
