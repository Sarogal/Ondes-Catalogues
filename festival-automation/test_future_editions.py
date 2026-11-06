import copy
from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))
from future_editions import (
    PROOF_MODE, edition_candidate, stable_candidate, merge_edition_candidates,
)
from official_watch import PAGES, GIT, ORIGIN, run

TODAY = "2026-11-04"
SOURCE = "https://example.org/festival"
PARENT = {
    "slug": "winter-rising-fest-2026",
    "name": "Winter Rising Fest 2026",
    "officialSite": SOURCE,
    "startDate": "2026-08-12",
    "endDate": "2026-08-13",
    "lat": 44.1, "lon": 3.2, "city": "Ancienne ville",
    "venue": "Ancienne salle", "price": "49 €",
    "lineup": ["Ancien groupe"], "bands": 1,
}
OBS = {
    "slug": PARENT["slug"], "name_on_source": "Winter Rising Fest 2027",
    "source_url": SOURCE, "publication_authorized": False,
    "startDate_source": "2027-08-12", "endDate_source": "2027-08-13",
    "hints": {"new_edition_year": 2027,
              "place_name_unverified": "Nouveau site ?"},
}


def patch(origin, day="2026-11-03"):
    return {
        "schema": "grossesondes.patch.v1", "safe_to_publish": False,
        "generated_at": day,
        "source": {"festivals": {
            "url": ORIGIN, "generatedAt": origin["generatedAt"],
            "count": len(origin["festivals"])},
            "history": {"count": 170}},
        "additions": [], "updates": [], "history_additions": [],
        "history_updates": [], "deferred": [],
    }


class FutureEditionTests(unittest.TestCase):
    def test_new_edition_has_only_independently_verifiable_data(self):
        entry = edition_candidate(PARENT, PARENT, OBS, {PARENT["slug"]: PARENT}, TODAY)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["slug"], "winter-rising-fest-2027")
        self.assertEqual(entry["proofMode"], PROOF_MODE)
        self.assertEqual(entry["evidence"], [SOURCE])
        self.assertEqual((entry["startDate"], entry["endDate"]), ("2027-08-12", "2027-08-13"))
        self.assertIs(entry["showOnMap"], False)
        self.assertEqual(entry["lineup"], [])
        self.assertEqual(entry["bands"], 0)
        for field in ("lat", "lon", "city", "department", "region", "venue", "price"):
            self.assertIsNone(entry[field], field)
        self.assertIs(entry["dateRangeIsContinuous"], False)
        self.assertEqual(PARENT["lineup"], ["Ancien groupe"])

    def test_unregistered_parent_and_disputed_identity_refused(self):
        base = {PARENT["slug"]: PARENT}
        self.assertIsNone(edition_candidate(PARENT, dict(PARENT, officialSite="https://other.org"),
                                            OBS, base, TODAY))
        self.assertIsNone(edition_candidate(PARENT, PARENT, dict(OBS, source_url="https://other.org"),
                                            base, TODAY))
        self.assertIsNone(edition_candidate(PARENT, PARENT, dict(OBS, name_on_source="Other Fest 2027"),
                                            base, TODAY))
        self.assertIsNone(edition_candidate(PARENT, PARENT, dict(OBS, name_on_source="Winter Rising Fest"),
                                            base, TODAY))

    def test_missing_changed_and_sensitive_dates_refused(self):
        base = {PARENT["slug"]: PARENT}
        for changes in (
            {"endDate_source": None}, {"startDate_source": "2026-08-12"},
            {"startDate_source": "2027-08-14", "endDate_source": "2027-08-13"},
            {"startDate_source": "2027-08-12", "endDate_source": "2027-08-24"},
            {"hints": {"new_edition_year": 2027, "sensitive_event_status": "EventCancelled"}},
        ):
            with self.subTest(changes=changes):
                self.assertIsNone(edition_candidate(PARENT, PARENT, {**OBS, **changes},
                                                    base, TODAY))

    def test_wrong_year_existing_slug_and_similar_published_name_refused(self):
        base = {PARENT["slug"]: PARENT}
        self.assertIsNone(edition_candidate(
            PARENT, PARENT, {**OBS, "hints": {"new_edition_year": 2028}}, base, TODAY))
        self.assertIsNone(edition_candidate(
            PARENT, PARENT, OBS, dict(base, **{"winter-rising-fest-2027": {}}), TODAY))
        self.assertIsNone(edition_candidate(
            PARENT, PARENT, OBS, dict(base, other={
                "name": "Winter Rising Fest (2027)", "startDate": "2027-08-12"}), TODAY))

    def test_two_consecutive_distinct_days_and_changed_observation(self):
        row = edition_candidate(PARENT, PARENT, OBS, {PARENT["slug"]: PARENT}, TODAY)
        state = {}
        self.assertFalse(stable_candidate(state, row, TODAY))
        self.assertFalse(stable_candidate(state, row, TODAY))
        changed = dict(row, startDate="2027-08-13")
        self.assertFalse(stable_candidate(state, changed, "2026-11-05"))
        self.assertTrue(stable_candidate(state, dict(changed, lastVerified="2026-11-06",
                                                   verified_at="2026-11-06"), "2026-11-06"))
        self.assertFalse(stable_candidate({}, row, TODAY))
        state2 = {}
        self.assertFalse(stable_candidate(state2, row, TODAY))
        self.assertFalse(stable_candidate(state2, row, "2026-11-07"))

    def test_yearless_slug_uses_frozen_parent_date_and_rejects_inference(self):
        parent = dict(PARENT, slug="cernunnos-pagan-fest",
                      name="Cernunnos Pagan Fest",
                      startDate="2027-02-12", endDate="2027-02-14")
        obs = dict(OBS, slug=parent["slug"],
                   name_on_source="Cernunnos Pagan Fest 2028",
                   startDate_source="2028-02-11", endDate_source="2028-02-13",
                   hints={"new_edition_year": 2028})
        published = {parent["slug"]: parent}
        proposed = edition_candidate(parent, parent, obs, published, TODAY)
        self.assertIsNotNone(proposed)
        self.assertEqual(proposed["slug"], "cernunnos-pagan-fest-2028")
        self.assertEqual(proposed["originSlug"], "cernunnos-pagan-fest")
        self.assertEqual(proposed["startDate"], "2028-02-11")
        self.assertIs(proposed["showOnMap"], False)
        self.assertEqual(proposed["lineup"], [])
        self.assertIsNone(proposed["venue"])
        self.assertIsNone(proposed["lat"])
        self.assertIsNone(edition_candidate(
            parent, dict(parent, startDate="2026-02-12"), obs, published, TODAY))
        self.assertIsNone(edition_candidate(
            dict(parent, name="Cernunnos Pagan Fest 2026"),
            dict(parent, name="Cernunnos Pagan Fest 2026"),
            obs, published, TODAY))
        self.assertIsNone(edition_candidate(
            dict(parent, startDate=None), dict(parent, startDate=None),
            obs, published, TODAY))
        self.assertIsNone(edition_candidate(
            parent, parent, obs, dict(published, **{"cernunnos-pagan-fest-2028": {}}), TODAY))

    def test_embedded_year_and_city_slug_not_treated_as_yearless(self):
        parent = dict(PARENT, slug="shred-fest-2027-montpellier",
                      name="Shred Fest 2027 — Montpellier",
                      startDate="2027-02-04")
        obs = dict(OBS, slug=parent["slug"],
                   name_on_source="Shred Fest 2028 — Montpellier",
                   hints={"new_edition_year": 2028},
                   startDate_source="2028-02-04", endDate_source="2028-02-04")
        self.assertIsNone(edition_candidate(
            parent, parent, obs, {parent["slug"]: parent}, TODAY))

    def test_invalid_source_state_rejected(self):
        entry = edition_candidate(PARENT, PARENT, OBS, {PARENT["slug"]: PARENT}, TODAY)
        with self.assertRaises(ValueError):
            stable_candidate({"future_edition_observations": []}, entry, TODAY)

    def test_merge_preserves_preexisting_private_proposals(self):
        origin = {"schema": 1, "generatedAt": "2026-10-25",
                  "festivals": [PARENT]}
        candidate = edition_candidate(PARENT, PARENT, OBS, {PARENT["slug"]: PARENT}, TODAY)
        p = patch(origin)
        p["additions"].append({"slug": "manual-2027"})
        older = copy.deepcopy(p)
        self.assertEqual(merge_edition_candidates(p, [candidate, candidate], origin, TODAY), 1)
        self.assertEqual(p["additions"][0], older["additions"][0])
        self.assertIs(p["safe_to_publish"], False)
        self.assertEqual(merge_edition_candidates(p, [candidate], origin, "2026-11-05"), 0)
        p["source"]["festivals"]["count"] = 900
        with self.assertRaises(ValueError):
            merge_edition_candidates(p, [candidate], origin, TODAY)


class FutureEditionWatchTests(unittest.TestCase):
    def test_full_two_day_watch_creates_one_private_addition(self):
        origin = {"schema": 1, "generatedAt": "2026-10-25",
                  "festivals": [dict(PARENT)] + [
                      {"slug": f"unused-{i}", "name": f"Unused {i}", "officialSite": None}
                      for i in range(99)
                  ]}
        full_html = (
            "<main>" + "Annonce officielle de la prochaine édition du festival. " * 8
            + "</main><script type='application/ld+json'>"
            + json.dumps({"@type": "MusicEvent", "name": "Winter Rising Fest 2027",
                          "startDate": "2027-08-12", "endDate": "2027-08-13"})
            + "</script>")
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / "patch-2026-11-03.json").write_text(
                json.dumps(patch(origin)), encoding="utf-8")
            first = run(folder, TODAY, limit=1, download_json=lambda u: origin,
                        download_page=lambda u: full_html)
            self.assertEqual(first["candidateEditionCount"], 0)
            self.assertEqual(first["deferredAdded"], 1)
            state = json.loads((folder / "source-watch-state.json").read_text())
            self.assertIn("winter-rising-fest-2027", state["future_edition_observations"])
            second = run(folder, "2026-11-05", limit=1,
                         download_json=lambda u: origin, download_page=lambda u: full_html)
            self.assertEqual(second["candidateEditionCount"], 1)
            result = json.loads((folder / "patch-2026-11-05.json").read_text())
            self.assertEqual(len(result["additions"]), 1)
            self.assertEqual(result["additions"][0]["proofMode"], PROOF_MODE)
            self.assertIs(result["additions"][0]["showOnMap"], False)
            self.assertIs(result["safe_to_publish"], False)
            third = run(folder, "2026-11-05", limit=1,
                        download_json=lambda u: origin, download_page=lambda u: full_html)
            self.assertEqual(third["candidateEditionCount"], 0)
            self.assertEqual(len(json.loads(
                (folder / "patch-2026-11-05.json").read_text())["additions"]), 1)

    def test_yearless_watch_detects_next_edition_only_after_second_day(self):
        parent = dict(PARENT, slug="cernunnos-pagan-fest",
                      name="Cernunnos Pagan Fest",
                      startDate="2027-02-12", endDate="2027-02-14")
        catalogue = {"schema": 1, "generatedAt": "2026-10-25",
                     "festivals": [parent] + [
                         {"slug": f"unused-{i}", "name": f"Unused {i}",
                          "officialSite": None} for i in range(99)
                     ]}
        page = (
            "<main>" + "Annonce nouvelle édition avec dates officielles. " * 8
            + "</main><script type='application/ld+json'>"
            + json.dumps({"@type": "MusicEvent", "name": "Cernunnos Pagan Fest 2028",
                          "startDate": "2028-02-11", "endDate": "2028-02-13"})
            + "</script>")
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "patch-2026-11-03.json").write_text(
                json.dumps(patch(catalogue)), encoding="utf-8")
            first = run(folder, TODAY, limit=1, download_json=lambda u: catalogue,
                        download_page=lambda u: page)
            second = run(folder, "2026-11-05", limit=1,
                         download_json=lambda u: catalogue,
                         download_page=lambda u: page)
            self.assertEqual(first["candidateEditionCount"], 0)
            self.assertEqual(second["candidateEditionCount"], 1)
            candidate = json.loads(
                (folder / "patch-2026-11-05.json").read_text(encoding="utf-8"))
            self.assertEqual(candidate["additions"][0]["slug"], "cernunnos-pagan-fest-2028")
            self.assertIs(candidate["safe_to_publish"], False)

    def test_conflicting_official_events_cannot_promote(self):
        origin = {"schema": 1, "generatedAt": "2026-10-25",
                  "festivals": [dict(PARENT)] + [
                      {"slug": f"unused-{i}", "name": f"Unused {i}", "officialSite": None}
                      for i in range(99)
                  ]}
        conflicting = (
            "<p>" + "Festival metal programme officiel. " * 8 + "</p>"
            + "<script type='application/ld+json'>"
            + json.dumps({"@graph": [
                {"@type": "MusicEvent", "name": "Winter Rising Fest 2027",
                 "startDate": "2027-08-12", "endDate": "2027-08-13"},
                {"@type": "MusicEvent", "name": "Winter Rising Fest 2027",
                 "startDate": "2027-08-14", "endDate": "2027-08-15"},
            ]}) + "</script>")
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / "patch-2026-11-03.json").write_text(
                json.dumps(patch(origin)), encoding="utf-8")
            for day in ("2026-11-04", "2026-11-05"):
                report = run(folder, day, limit=1,
                             download_json=lambda u: origin,
                             download_page=lambda u: conflicting)
                self.assertEqual(report["candidateEditionCount"], 0)
            self.assertEqual(json.loads(
                (folder / "source-watch-state.json").read_text()
            ).get("future_edition_observations", {}), {})


if __name__ == "__main__":
    unittest.main()
