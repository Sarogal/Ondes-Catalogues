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
from test_ptitesondes_open_world_patch_bridge import private_patch
from ptitesondes_national_backlog_bridge import _inventory_key
from ptitesondes_open_world_private_dossier_intake import (
    collect_research_dossiers, attach_research_dossiers,
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

    def load(self, **kwargs):
        return collect_research_dossiers(
            self.observation, self.research, TODAY,
            inventory_reader=lambda _: [self.record], **kwargs)

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

    def test_municipally_discovered_unknown_domain_creates_research_not_addition(self):
        self.write(report())
        rows, stats = self.load()
        self.assertEqual(len(rows), 1)
        self.assertEqual(stats["candidate_dossiers"], 1)
        self.assertEqual(stats["queued"], 1)
        self.assertEqual(rows[0]["official_event_url"], SOURCE)
        self.assertEqual(rows[0]["official_venue_url"], MUNICIPAL)
        self.assertEqual(
            rows[0]["municipal_source_reference_url"], MUNICIPAL)
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
        self.assertEqual(len(rows), 1)
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
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["official_venue_url"], MUNICIPAL)
        self.assertEqual(rows[0]["municipal_source_reference_url"], MUNICIPAL)

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
        self.assertEqual(len(rows), 1)
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
        self.assertEqual(len(first), 1)
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
        self.assertEqual(metrics["queued"], 1)
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
        self.assertEqual(len(slot1["open_world_research"]), 1)
        # The same clue and an empty following batch must preserve this row.
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
            for i in range(30)]
        waiting = attach_research_dossiers(patch, first, TODAY)
        self.assertEqual(len(waiting["open_world_research"]), 30)
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
            dict(base, open_world_research=[{"approved": True}] * 31),
        ):
            with self.subTest(value=str(changed)[:70]):
                with self.assertRaises(ValueError):
                    attach_research_dossiers(changed, [], TODAY)


if __name__ == "__main__":
    unittest.main()
