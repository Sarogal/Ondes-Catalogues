"""Offline and private-only research dossier selection for actual publisher."""
from copy import deepcopy
from datetime import date
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
        # Daily requalification may replace a prior research list, never
        # inherit a "safe_to_publish" claim from an earlier run.
        refreshed = attach_research_dossiers(out, [], TODAY)
        self.assertEqual(refreshed["open_world_research"], [])

    def test_unrelated_website_is_not_paired_or_approved(self):
        for source, linked in (
            ("https://other.example/spectacle", EXTERNAL),
            (SOURCE, "https://nouvelle-salle.example.evil.test/spectacle"),
            ("http://nouvelle-salle.example/spectacle", EXTERNAL),
            ("https://openagenda.com/agenda/dummy", EXTERNAL),
            ("https://nouvelle-salle.example/", EXTERNAL),
        ):
            with self.subTest(source=source, linked=linked):
                self.write(report(source=source, linked=linked))
                rows, counts = self.load()
                self.assertEqual(rows, [])
                self.assertEqual(counts["queued"], 0)

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
