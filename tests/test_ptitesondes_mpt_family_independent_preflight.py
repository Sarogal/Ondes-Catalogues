"""Source/geo proof checks with synthetic official pages; no real publication."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ptitesondes_mpt_family_independent_preflight import (
    exact_primary_mpt_html, independent_family_preview,
)
from ptitesondes_mpt_independent_geo_pilot import reviewed_pilot_records

TODAY = date(2026, 11, 17)
MPT_URL = "https://mpt.montpellier.fr/evenement/bebes-lecteurs"
LEAD = {
    "provider": "montpellier_mpt",
    "title": "Bébés lecteurs", "city": "Montpellier",
    "venue": "Maison pour tous Frida Kahlo",
    "source_url": MPT_URL, "date_start": "2026-11-18",
    "date_end": "2026-11-18", "start_local": "10:30",
    "audience_claim": "explicit_baby",
    "category": "lecture-jeunesse",
    "price_evidence": "explicit_free",
    "registration_evidence": "explicit_required",
    "verification": "discovery_only_needs_official_and_independent_proof",
}
OFFICIAL = """<!doctype html><html><body><main>
<h1>Bébés lecteurs</h1>
<article>
<p>Invitation à un moment de partage spécialement conçu pour les tout-petits
de 0 à 3 ans accompagnés d'un parent, autour d'albums jeunesse.</p>
<ul><li><p>18 novembre 2026 - 10:30 &gt; 11:30</p></li></ul>
<p>Maison pour tous Frida Kahlo<br/>240 Rue Claude Levi-Strauss<br/>
34000 Montpellier</p>
<p>Sur inscription | Gratuit</p>
</article>
<h2>Autres événements</h2>
<h3>Bébés lecteurs</h3><li><p>19 novembre 2026 - 15:00 &gt; 16:00</p></li>
</main></body></html>"""


def geo_result(record, score=0.975):
    return {"features": [{
        "geometry": {"type": "Point",
                     "coordinates": [record["lng"], record["lat"]]},
        "properties": {
            "label": record["address_label"], "postcode": record["postcode"],
            "city": record["city"], "score": score, "type": "housenumber",
        },
    }]}


def base_catalogue():
    return json.loads(
        (ROOT / "docs/ptitesondes/sorties.json").read_text(encoding="utf-8")
    )


def do_preview(leads=None, official=OFFICIAL, geocoder=None,
               catalogue=None):
    records = reviewed_pilot_records()
    by_key = {r["geo_source_url"]: geo_result(r) for r in records}
    if geocoder:
        by_key.update(geocoder)
    return independent_family_preview(
        [deepcopy(LEAD)] if leads is None else leads,
        base_catalogue() if catalogue is None else catalogue, TODAY,
        official_get=lambda url: official,
        geocoder_get=lambda url: by_key[url],
    )


class MptIndependentPreflightTests(unittest.TestCase):
    def test_strict_read_only_independent_recheck_does_not_approve(self):
        report = do_preview()
        self.assertEqual(report["input_discovery_occurrences"], 1)
        self.assertEqual(report["eligible_for_independent_source_preflight"], 1)
        self.assertEqual(report["official_source_cues_passed"], 1)
        self.assertEqual(report["public_writes"], 0)
        self.assertFalse(report["approval_granted_to_publisher"])
        self.assertTrue(report["catalogue_unchanged"])
        self.assertEqual(report["human_approvals"], 0)

    def test_unrelated_sidebar_cannot_supply_missing_primary_date(self):
        page = OFFICIAL.replace(
            "18 novembre 2026 - 10:30 &gt; 11:30",
            "date non annoncée")
        # The sidebar is allowed to mention the exact requested time/day.
        page = page.replace("19 novembre 2026 - 15:00",
                            "18 novembre 2026 - 10:30")
        self.assertIsNone(exact_primary_mpt_html(
            page, expected_title="Bébés lecteurs",
            expected_day="2026-11-18", expected_clock="10:30"))
        report = do_preview(official=page)
        self.assertEqual(report["official_source_cues_passed"], 0)
        self.assertEqual(report["held_before_source_preflight"][
            "primary_article_title_or_session_mismatch"], 1)

    def test_hidden_or_scripted_session_cannot_pass_primary_gate(self):
        for wrapper in (
            '<span style="display: none">{}</span>',
            '<span aria-hidden="true">{}</span>',
            '<script>{}</script>',
        ):
            with self.subTest(wrapper=wrapper):
                page = OFFICIAL.replace(
                    "18 novembre 2026 - 10:30 &gt; 11:30",
                    wrapper.format("18 novembre 2026 - 10:30 &gt; 11:30"))
                self.assertIsNone(exact_primary_mpt_html(
                    page, expected_title="Bébés lecteurs",
                    expected_day="2026-11-18", expected_clock="10:30"))

    def test_wrong_date_title_and_url_all_refused(self):
        for extra in (
            {"date_start": "2026-11-19", "date_end": "2026-11-19"},
            {"title": "Atelier inventé"},
            {"source_url": "https://mpt.montpellier.fr.evil.test/evenement/bebes-lecteurs"},
            {"source_url": MPT_URL + "?redirect=other"},
        ):
            with self.subTest(extra=extra):
                lead = deepcopy(LEAD)
                lead.update(extra)
                report = do_preview(leads=[lead])
                self.assertEqual(report["official_source_cues_passed"], 0)
                self.assertEqual(report["public_writes"], 0)

    def test_unverified_or_aliased_buildings_stay_held(self):
        for extra in (
            {"venue": "Maison pour tous Frida Kahlo annexe"},
            {"city": "Lattes"},
            {"venue": "Médiathèque Émile Zola"},
        ):
            report = do_preview(leads=[dict(LEAD, **extra)])
            self.assertEqual(report["official_source_cues_passed"], 0)
            self.assertEqual(report["held_before_source_preflight"][
                "no_curated_venue"], 1)

    def test_live_ign_fuzzy_building_blocks_before_official_source(self):
        records = reviewed_pilot_records()
        key = records[1]["geo_source_url"]
        checked = geo_result(records[1])
        checked["features"][0]["properties"]["type"] = "street"
        report = do_preview(geocoder={key: checked})
        self.assertEqual(report["curated_geographic_venues_with_live_recheck"], 0)
        self.assertEqual(report["eligible_for_independent_source_preflight"], 0)
        self.assertEqual(report["held_before_source_preflight"][
            "independent_geo_not_currently_verified"], 1)

    def test_ambiguous_access_fails_source_gate_without_auto_waiver(self):
        candidate = dict(LEAD, price_evidence="ambiguous")
        report = do_preview(leads=[candidate])
        self.assertEqual(report["eligible_for_independent_source_preflight"], 1)
        self.assertEqual(report["official_source_cues_passed"], 0)
        self.assertIn("unresolved_access_contradiction",
                      report["held_by_independent_source_preflight"])

    def test_art_installation_must_not_publish_as_outdoor_nature(self):
        art = dict(LEAD,
                   title="Dans la forêt",
                   venue="Maison pour tous Albert Dubout",
                   source_url="https://mpt.montpellier.fr/evenement/dans-la-foret",
                   date_start="2026-11-25", date_end="2026-11-25",
                   start_local="14:00", category="sortie-nature")
        page = OFFICIAL.replace("Bébés lecteurs", "Dans la forêt")
        page = page.replace("pour les tout-petits", "pour les tout-petits, installation artistique")
        page = page.replace("18 novembre 2026 - 10:30", "25 novembre 2026 - 14:00")
        page = page.replace("Maison pour tous Frida Kahlo", "Maison pour tous Albert Dubout")
        report = do_preview(leads=[art], official=page)
        self.assertEqual(report["official_source_cues_passed"], 0)
        self.assertEqual(report["held_before_source_preflight"][
            "art_installation_requires_editorial_review"], 1)

    def test_duplicate_historical_event_fails_closed(self):
        catalogue = base_catalogue()
        copied = dict(catalogue["events"][0])
        copied.update({
            "id": "nonmusical-historical-fake",
            "title": "Bébés lecteurs", "city": "Montpellier",
            "venue": "Maison pour tous Frida Kahlo",
            "date_start": "2026-11-18", "date_end": "2026-11-18",
            "time": "10:30",
        })
        catalogue["events"].append(copied)
        r = do_preview(catalogue=catalogue)
        self.assertEqual(r["official_source_cues_passed"], 0)
        self.assertIn("already_published_from_any_source",
                      r["held_by_independent_source_preflight"])

    def test_malformed_catalogue_is_not_prevalidated(self):
        catalogue = base_catalogue()
        catalogue["events"] = []
        with self.assertRaises(ValueError):
            do_preview(catalogue=catalogue)

    def test_public_report_contains_only_bounded_anonymous_counts(self):
        r = do_preview()
        dump = json.dumps(r, ensure_ascii=False)
        for forbidden in ("Frida Kahlo", "Bébés lecteurs",
                          "http", "Montpellier", "source_url",
                          "venue_key", "additions", "updates", "patch"):
            self.assertNotIn(forbidden, dump)
        self.assertEqual(r["published_events"], 0)
        self.assertFalse(r["event_publisher_not_connected"] is False)


if __name__ == "__main__":
    unittest.main()
