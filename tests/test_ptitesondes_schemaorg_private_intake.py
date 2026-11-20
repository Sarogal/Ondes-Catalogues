"""Private Schema.org intake: source pins, dedup, safety, no publication."""
from copy import deepcopy
from datetime import date, datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ptitesondes_schemaorg_private_intake import (
    SCHEMA, PINS_SCHEMA, STORAGE, _file, _read_private, _stage_private,
    _validate_hint, _from_lead, curated_schemaorg_sources,
    reconcile_schemaorg_hints, run_schemaorg_cycle,
    sample_registered_schemaorg_source,
)
from ptitesondes_institutional_source_policy import MANIFEST_PATH

TODAY = date(2026, 11, 20)
NOW = datetime(2026, 11, 20, 15, tzinfo=ZoneInfo("Europe/Paris"))
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
PIN = {"schema": PINS_SCHEMA, "entries": [
    {"source_id": "montpellier-mpt", "timezone": "Europe/Paris"},
]}


def hint(clock="09:15", url="https://mpt.montpellier.fr/evenement/atelier",
         city="Montpellier", category="atelier-creatif"):
    return {
        "source_url": url,
        "title": "Atelier créatif pour enfants",
        "venue": "Maison pour tous", "city": city,
        "date_start": "2026-11-22", "date_end": "2026-11-22",
        "start_local": clock, "category_hint_only": category,
        "source_format": "schema_org_jsonld",
        "audience_source_visible_confirmed": False,
        "price_evidence": "not_stated", "registration_evidence": "not_stated",
        "official_session_independently_proved": False,
        "organizer_independently_attested": False,
        "approved": False, "published": False,
    }


def trusted_source():
    return curated_schemaorg_sources(MANIFEST, PIN)[0]


def structured_page(url):
    e = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "EducationEvent",
                "name": "Atelier créatif pour enfants",
                "startDate": when,
                "location": {
                    "name": "Maison pour tous",
                    "address": {"addressLocality": "Montpellier"},
                },
            }
            for when in (
                "2026-11-22T09:15:00+01:00",
                "2026-11-22T10:30:00+01:00",
            )
        ],
    }
    return {
        "url": url,
        "html": "<html><head><script type='application/ld+json'>"
                + json.dumps(e) + "</script></head><body><main>Agenda familial</main></body></html>",
    }


class SchemaOrgPrivateIntakeTests(unittest.TestCase):
    def test_curated_manifest_and_timezone_pins_only(self):
        sources = curated_schemaorg_sources(MANIFEST, PIN)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["approved_host"], "mpt.montpellier.fr")
        self.assertEqual(sources[0]["timezone"], "Europe/Paris")
        with self.assertRaises(ValueError):
            curated_schemaorg_sources(MANIFEST, {
                "schema": PINS_SCHEMA,
                "entries": [{"source_id": "fake-site", "timezone": "Europe/Paris"}],
            })
        with self.assertRaises(ValueError):
            curated_schemaorg_sources(MANIFEST, {
                "schema": PINS_SCHEMA,
                "entries": [{"source_id": "montpellier-mpt",
                             "timezone": "Europe/Tokyo"}],
            })
        with self.assertRaises(ValueError):
            curated_schemaorg_sources(MANIFEST, {
                "schema": PINS_SCHEMA,
                "entries": [PIN["entries"][0], PIN["entries"][0]],
            })

    def test_true_registered_child_to_private_hints_without_approvals(self):
        source = trusted_source()
        child = "https://mpt.montpellier.fr/evenement/atelier"
        seen = []
        def discover(pin):
            seen.append(pin)
            return {"stage": "routing_suggestions_only",
                    "private_routing_proposals": [
                        {"url": child, "approved": False},
                    ]}
        def read(pin):
            seen.append(pin)
            return structured_page(pin["exact_url"])
        result = sample_registered_schemaorg_source(
            source, TODAY, discoverer=discover, page_reader=read)
        self.assertEqual(result["report"]["child_pages_read"], 1)
        self.assertEqual(result["report"]["private_hints_observed"], 2)
        self.assertEqual(len(result["hints"]), 2)
        self.assertEqual({x["start_local"] for x in result["hints"]},
                         {"09:15", "10:30"})
        self.assertEqual(seen[0]["exact_index_url"], source["index_url"])
        self.assertEqual(seen[1]["exact_url"], child)
        self.assertTrue(all(x["approved"] is False for x in result["hints"]))

    def test_outside_host_and_unpinned_query_are_refused_before_fetch(self):
        source = trusted_source()
        seen = []
        urls = [
            "https://evil.example.net/evenement/atelier",
            "https://mpt.montpellier.fr.evil.net/evenement/x",
            "https://mpt.montpellier.fr/evenement/a?tracking=1",
            "https://mpt.montpellier.fr/other/non-event",
        ]
        result = sample_registered_schemaorg_source(
            source, TODAY,
            discoverer=lambda pin: {
                "stage": "routing_suggestions_only",
                "private_routing_proposals": [
                    {"url": url, "approved": False} for url in urls]},
            page_reader=lambda pin: seen.append(pin))
        self.assertEqual(seen, [])
        self.assertEqual(result["report"]["child_pages_read"], 0)
        self.assertEqual(result["hints"], [])

    def test_two_clock_slots_and_cross_source_are_independent(self):
        a = reconcile_schemaorg_hints([], [hint()], TODAY)
        b = reconcile_schemaorg_hints(a["queue"], [hint(clock="10:30")], TODAY)
        self.assertEqual(len(b["queue"]), 2)
        self.assertEqual(len({r["hint_id"] for r in b["queue"]}), 2)
        c = reconcile_schemaorg_hints(b["queue"], [hint()], TODAY)
        self.assertEqual(len(c["queue"]), 2)
        self.assertEqual(c["report"]["reobserved_hints"], 1)
        self.assertEqual(sum(v["observations"] for v in c["queue"]), 4)
        d = reconcile_schemaorg_hints(
            c["queue"], [hint(url="https://mpt.montpellier.fr/evenement/different")],
            TODAY)
        self.assertEqual(len(d["queue"]), 3)

    def test_invalid_approval_or_fake_source_hint_does_not_survive(self):
        a = reconcile_schemaorg_hints([], [hint()], TODAY)["queue"][0]
        self.assertEqual(a["schema"], SCHEMA)
        self.assertFalse(a["first_party_visible_session_rechecked"])
        self.assertFalse(a["rights_reviewed"])
        self.assertFalse(a["approved"])
        for key in ("approved", "organizer_verified", "rights_reviewed",
                    "published", "first_party_visible_session_rechecked"):
            with self.subTest(key=key):
                bad = dict(a, **{key: True})
                with self.assertRaises(ValueError):
                    reconcile_schemaorg_hints([bad], [], TODAY)
        forge = hint()
        forge["approved"] = True
        out = reconcile_schemaorg_hints([], [forge], TODAY)
        self.assertEqual(out["report"]["malformed_hints_held"], 1)
        self.assertEqual(out["queue"], [])

    def test_expired_hints_archived_without_hiding_future(self):
        a = reconcile_schemaorg_hints([], [hint()], TODAY)["queue"]
        future = reconcile_schemaorg_hints(a, [], date(2026, 11, 21))
        self.assertEqual(len(future["queue"]), 1)
        past = reconcile_schemaorg_hints(a, [], date(2026, 11, 23))
        self.assertEqual(past["queue"], [])
        self.assertEqual(past["report"]["expired_hints_archived"], 1)

    def test_unclassified_kept_and_age_price_not_invented(self):
        row = hint(category=None)
        result = reconcile_schemaorg_hints([], [row], TODAY)
        self.assertEqual(result["report"]["unclassified_hints"], 1)
        self.assertEqual(len(result["queue"]), 1)
        self.assertNotIn("age_min", result["queue"][0])
        self.assertNotIn("price", result["queue"][0])
        self.assertFalse(result["report"]["publication_ready"])

    def test_run_rotation_includes_all_registered_sites_not_hardcoded_city(self):
        # Clone a separately registered institutional source into many
        # synthetic hosts; do not let candidates register sources themselves.
        manifest = deepcopy(MANIFEST)
        sites = []
        for n in range(1, 12):
            base = deepcopy(manifest["entries"][0])
            host = f"agenda{n}.ville.fr"
            base.update({
                "source_id": f"town-{n}",
                "approved_host": host,
                "index_url": f"https://{host}/agenda",
                "child_prefix": "/evenement/",
                "publisher_notice_url": f"https://{host}/legal",
                "external_authority_url": f"https://www.gouv.fr/mairie/{n}",
            })
            sites.append(base)
        manifest["entries"].extend(sites)
        pins = {"schema": PINS_SCHEMA,
                "entries": PIN["entries"] + [
                    {"source_id": e["source_id"], "timezone": "Europe/Paris"}
                    for e in sites]}
        seen = []
        def reader(source, day, **kwargs):
            seen.append(source["source_id"])
            return {"hints": [],
                    "report": {"child_pages_read": 1}}
        for batch in range(7):
            r = run_schemaorg_cycle(
                [], NOW, manifest=manifest, pins=pins,
                source_batch=batch, max_sources=2,
                source_reader=reader)
            self.assertEqual(r["report"]["source_batches_total"], 6)
            self.assertEqual(r["report"]["registered_sources"], 12)
        self.assertEqual(len(set(seen)), 12)

    def test_unavailable_source_does_not_erase_existing_hints(self):
        current = reconcile_schemaorg_hints([], [hint()], TODAY)["queue"]
        out = run_schemaorg_cycle(
            current, NOW, manifest=MANIFEST, pins=PIN,
            source_reader=lambda *a, **kw: {
                "hints": [], "report": {"child_pages_read": 0}})
        self.assertEqual(out["queue"], current)
        self.assertEqual(out["report"]["sources_unavailable"], 1)
        self.assertEqual(out["report"]["total_private_hints"], 1)
        self.assertNotIn("mpt.montpellier.fr", json.dumps(out["report"]))

    def test_private_stage_only_in_authenticated_checkout(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            subprocess.run(
                ["git", "init", "-q", "-b", "automation/ptitesondes-intake",
                 str(root)], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(root), "remote", "add", "origin",
                 "https://github.com/Sarogal/PtitesOndes"],
                check=True, capture_output=True)
            path = _file(root)
            self.assertEqual(path, root / STORAGE)
            self.assertEqual(_read_private(path), [])
            rows = reconcile_schemaorg_hints([], [hint(), hint(clock="10:30")],
                                            TODAY)["queue"]
            _stage_private(path, rows)
            self.assertEqual(_read_private(path), rows)
            self.assertNotIn("false-source-approval", path.read_text())
            forge = deepcopy(rows)
            forge[0]["published"] = True
            with self.assertRaises(ValueError):
                _stage_private(path, forge)
            self.assertEqual(_read_private(path), rows)
            subprocess.run(
                ["git", "-C", str(root), "remote", "set-url", "origin",
                 "https://github.com/evil/Other"],
                check=True, capture_output=True)
            with self.assertRaises(ValueError):
                _file(root)

    def test_read_and_stage_reject_symlink_escape(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            path = root / "hints.json"
            outside = root / "outside.txt"
            outside.write_text("UNCHANGED", encoding="utf-8")
            try:
                path.symlink_to(outside)
            except (OSError, NotImplementedError):
                self.skipTest("symlink unavailable")
            with self.assertRaises(ValueError):
                _read_private(path)
            with self.assertRaises(ValueError):
                _stage_private(path, [])
            self.assertEqual(outside.read_text(encoding="utf-8"), "UNCHANGED")

    def test_no_opens_browser_or_publisher_and_report_is_numeric(self):
        a = reconcile_schemaorg_hints([], [hint(city="Saint-Denis")], TODAY)
        public = json.dumps(a["report"], ensure_ascii=False)
        for val in ("Saint-Denis", "https://", "atelier", "2026-11-22"):
            self.assertNotIn(val, public)
        self.assertFalse(a["report"]["publisher_connected"])
        self.assertEqual(a["report"]["public_writes"], 0)
        self.assertFalse(a["report"]["approved"])


if __name__ == "__main__":
    unittest.main()
