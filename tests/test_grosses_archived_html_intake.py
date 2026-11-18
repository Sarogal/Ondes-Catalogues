"""Synthetic offline tests of archived festival admission (no private secrets)."""
from __future__ import annotations

import copy
from datetime import date
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import grossesondes_archived_html_intake as engine
from grossesondes_cloud_sync import collect_registered_edition_sources
from grossesondes_structured_edition import (
    ARCHIVED_HTML_PROOF_MODE, validate_archived_structured_edition,
)

MOZHELL = (
    '<html><body><article><h2>Nouvelle édition</h2>'
    '<p>Le <strong>MozHell Open Air</strong> revient les '
    '<strong>23, 24 et 25 juillet 2027</strong> à Insming.</p>'
    '</article></body></html>'
)
SIXSIXSIX = (
    '<html><body><nav>Festival 666</nav><main>'
    '<h1>13 - 14 - 15 | AOUT | 2027</h1>'
    '<p>Bienvenue au Festival 666</p></main></body></html>'
)


def historic(slug, name, site, start, end):
    return {
        "slug": slug, "name": name, "officialSite": site,
        "lastKnownYear": 2026, "startDate": start, "endDate": end,
        "lineup": ["Old Act"], "lat": 48.0, "lon": 5.0,
        "venue": "Ancien lieu", "price": "Ancien tarif",
    }


MOZ = historic("mozhell-open-air", "MozHell Open Air",
              "https://www.mozhell.fr/fr/", "2026-07-24", "2026-07-26")
SIX = historic("festival-666", "Festival 666",
              "https://www.festival666.com/", "2026-08-07", "2026-08-09")


class ArchivedHtmlIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.day1 = date(2026, 11, 17)
        self.day2 = date(2026, 11, 18)
        self.calendar = {"schema": 1, "generatedAt": "2026-11-14",
                         "festivals": []}
        self.history = {"schema": 2, "knownFestivals": [copy.deepcopy(MOZ),
                                                        copy.deepcopy(SIX)]}
        self.patch = {
            "schema": "grossesondes.patch.v1", "generated_at": "2026-11-17",
            "safe_to_publish": False,
            "source": {"festivals": {
                "url": "https://grosses-ondes.fr/data/festivals.json",
                "generatedAt": "2026-11-01", "count": 123}},
            "additions": [{"slug": "unrelated-preserved"}],
            "updates": [{"slug": "never-touched"}],
            "history_additions": [], "history_updates": [], "deferred": [],
        }
        (self.folder / "patch-2026-11-17.json").write_text(
            json.dumps(self.patch), encoding="utf-8")
        (self.folder / "source-watch-state.json").write_text(
            json.dumps({"schema": "grossesondes.source-watch.v1"}),
            encoding="utf-8")
        self.pages = {
            engine.PINNED_ARCHIVED_HTML_SOURCES["mozhell-open-air"]["proofUrl"]:
                MOZHELL,
            engine.PINNED_ARCHIVED_HTML_SOURCES["festival-666"]["proofUrl"]:
                SIXSIXSIX,
        }
        self.visits = []

    def fetch(self, url, *, registered=False, raw=False):
        self.visits.append((url, registered, raw))
        return self.pages[url]

    def test_private_diagnostic_identifies_missing_date_without_releasing_html(self):
        official = engine.PINNED_ARCHIVED_HTML_SOURCES["festival-666"]["proofUrl"]
        self.pages[official] = "<html><body>Festival 666 : programme à venir</body></html>"
        result = engine.run(self.folder, self.calendar, self.history,
                            self.day1, self.fetch)
        self.assertEqual(result["privateCandidatesAdded"], 0)
        statefile = self.folder / "source-watch-state.json"
        serialized = statefile.read_text(encoding="utf-8")
        state = json.loads(serialized)
        statuses = state["archived_html_proof_last_result_private"]
        self.assertEqual(statuses["festival-666"]["result"],
                         "visible_dates_absent_or_ambiguous")
        self.assertEqual(statuses["mozhell-open-air"]["result"],
                         "second_independent_day_pending")
        self.assertEqual(statuses["festival-666"]["checked_on"], "2026-11-17")
        self.assertNotIn("programme à venir", serialized)
        self.assertNotIn("www.festival666.com", serialized)
        self.assertFalse((self.folder / "patch-2026-11-18.json").exists())

    def test_private_diagnostic_distinguishes_official_fetch_error(self):
        fail_url = engine.PINNED_ARCHIVED_HTML_SOURCES["festival-666"]["proofUrl"]
        def denied(url, **kwargs):
            if url == fail_url:
                raise OSError("403 server error; private internal response")
            return self.fetch(url, **kwargs)
        result = engine.run(self.folder, self.calendar, self.history,
                            self.day1, denied)
        self.assertEqual(result["officialProofsEligible"], 1)
        state = (self.folder / "source-watch-state.json").read_text()
        self.assertEqual(json.loads(state)[
            "archived_html_proof_last_result_private"]["festival-666"]["result"],
            "official_page_fetch_failed")
        self.assertNotIn("403 server error", state)
        self.assertFalse(result["publicWrites"])

    def test_private_diagnostic_marks_second_day_append_and_duplicate(self):
        engine.run(self.folder, self.calendar, self.history, self.day1, self.fetch)
        engine.run(self.folder, self.calendar, self.history, self.day2, self.fetch)
        state = json.loads((self.folder / "source-watch-state.json").read_text())
        statuses = state["archived_html_proof_last_result_private"]
        self.assertEqual(statuses["festival-666"]["result"], "added_to_private_patch")
        self.assertEqual(statuses["mozhell-open-air"]["result"], "added_to_private_patch")
        engine.run(self.folder, self.calendar, self.history, self.day2, self.fetch)
        state = json.loads((self.folder / "source-watch-state.json").read_text())
        statuses = state["archived_html_proof_last_result_private"]
        self.assertEqual(statuses["festival-666"]["result"], "already_in_private_patch")
        self.assertEqual(statuses["mozhell-open-air"]["result"], "already_in_private_patch")

    def test_pinned_organizer_page_is_same_https_origin_and_path(self):
        valid = engine.pinned_first_party
        site = "https://www.mozhell.fr/fr/"
        self.assertTrue(valid(site,
            "https://www.mozhell.fr/fr/le-mozhell-est-de-retour-pour-une-nouvelle-edition-en-2027"))
        self.assertTrue(valid("https://www.festival666.com/",
                              "https://www.festival666.com/"))
        for unsafe in (
            "http://www.mozhell.fr/fr/news",
            "https://www.mozhell.fr.evil.example/fr/news",
            "https://www.mozhell.fr.evil.example/fr/",
            "https://www.mozhell.fr/other/news",
            "https://www.mozhell.fr/fr/../other",
            "https://www.mozhell.fr/fr/%2e%2e/other",
            "https://www.mozhell.fr/fr/news?url=evil",
            "https://www.mozhell.fr:444/fr/news",
            "https://username@www.mozhell.fr/fr/news",
        ):
            with self.subTest(unsafe=unsafe):
                self.assertFalse(valid(site, unsafe))

    def test_two_days_prove_two_archived_editions_without_inherited_fields(self):
        first = engine.run(
            self.folder, self.calendar, self.history, self.day1, self.fetch)
        self.assertEqual(first["privateCandidatesAdded"], 0)
        self.assertEqual(first["officialProofsEligible"], 2)
        self.assertFalse((self.folder / "patch-2026-11-18.json").exists())
        second = engine.run(
            self.folder, self.calendar, self.history, self.day2, self.fetch)
        self.assertEqual(second["privateCandidatesAdded"], 2)
        patch = json.loads((self.folder / "patch-2026-11-18.json").read_text())
        self.assertEqual(patch["additions"][0], self.patch["additions"][0])
        self.assertEqual(patch["updates"], self.patch["updates"])
        self.assertFalse(patch["safe_to_publish"])
        new = patch["additions"][1:]
        self.assertEqual({x["slug"] for x in new},
                         {"mozhell-open-air-2027", "festival-666-2027"})
        for proposal in new:
            self.assertEqual(proposal["proofMode"], ARCHIVED_HTML_PROOF_MODE)
            for key in ("city", "department", "region", "venue", "lat",
                        "lon", "price"):
                self.assertIsNone(proposal[key])
            self.assertFalse(proposal["showOnMap"])
            self.assertEqual(proposal["bands"], 0)
            self.assertEqual(proposal["lineup"], [])
            p = self.history["knownFestivals"][0 if proposal["originSlug"]
                                               == MOZ["slug"] else 1]
            expected_url = engine.PINNED_ARCHIVED_HTML_SOURCES[
                proposal["originSlug"]]["proofUrl"]
            self.assertIsNotNone(validate_archived_structured_edition(
                proposal, p, self.pages[expected_url],
                "2026-11-18", proof_mode=ARCHIVED_HTML_PROOF_MODE))
        self.assertTrue(all(registered and raw for _, registered, raw in self.visits))

    def test_rerun_cannot_duplicate_proposals(self):
        engine.run(self.folder, self.calendar, self.history,
                   self.day1, self.fetch)
        engine.run(self.folder, self.calendar, self.history,
                   self.day2, self.fetch)
        result = engine.run(self.folder, self.calendar, self.history,
                            self.day2, self.fetch)
        self.assertEqual(result["privateCandidatesAdded"], 0)
        patch = json.loads((self.folder / "patch-2026-11-18.json").read_text())
        self.assertEqual(len(patch["additions"]), 3)

    def test_unverified_or_hidden_2027_date_is_not_qualified(self):
        self.pages[engine.PINNED_ARCHIVED_HTML_SOURCES[
            "mozhell-open-air"]["proofUrl"]] = (
                "<html><body>MozHell Open Air "
                "<div hidden>23, 24 et 25 juillet 2027</div></body></html>")
        self.pages[engine.PINNED_ARCHIVED_HTML_SOURCES[
            "festival-666"]["proofUrl"]] = (
                "<html><body>Festival 666 annulé "
                "13 - 14 - 15 août 2027</body></html>")
        result = engine.run(self.folder, self.calendar, self.history,
                            self.day1, self.fetch)
        self.assertEqual(result["officialProofsEligible"], 0)

    def test_conflicting_dates_do_not_produce_partial_proposal(self):
        self.pages[engine.PINNED_ARCHIVED_HTML_SOURCES[
            "festival-666"]["proofUrl"]] += (
                '<p>Festival 666, 20 - 22 août 2027</p>')
        self.assertIsNone(engine.official_date(
            self.pages[engine.PINNED_ARCHIVED_HTML_SOURCES[
                "festival-666"]["proofUrl"]], SIX, 2027))

    def test_previous_year_or_different_parent_blocks(self):
        other = copy.deepcopy(self.history)
        other["knownFestivals"][0]["officialSite"] = "https://other.example/"
        other["knownFestivals"][1]["lastKnownYear"] = 2025
        result = engine.run(self.folder, self.calendar, other,
                            self.day1, self.fetch)
        self.assertEqual(result["officialProofsEligible"], 0)
        self.assertEqual(self.visits, [])

    def test_publisher_rechecks_only_pinned_page_not_patch_supplied_url(self):
        proposal = engine.candidate(
            MOZ, engine.PINNED_ARCHIVED_HTML_SOURCES["mozhell-open-air"],
            MOZHELL, self.day1)
        proposal["evidence"] = ["https://evil.example/danger"]
        urls = []
        def fetch(url, **kwargs):
            urls.append(url)
            return MOZHELL
        result = collect_registered_edition_sources(
            {"additions": [proposal]}, {}, fetcher=fetch,
            archived={"mozhell-open-air": MOZ})
        pinned = engine.PINNED_ARCHIVED_HTML_SOURCES[
            "mozhell-open-air"]["proofUrl"]
        self.assertEqual(urls, [pinned])
        self.assertEqual(result["registered-edition:"+proposal["slug"]], MOZHELL)
        self.assertEqual(result["registered-edition-proof-url:"+proposal["slug"]],
                         pinned)
        self.assertNotIn("evil.example", str(urls))

    def test_a_gap_in_daily_observation_resets_continuity(self):
        engine.run(self.folder, self.calendar, self.history,
                   self.day1, self.fetch)
        later = engine.run(self.folder, self.calendar, self.history,
                           date(2026, 11, 19), self.fetch)
        self.assertEqual(later["privateCandidatesAdded"], 0)

    def test_existing_public_row_not_reintroduced(self):
        self.calendar["festivals"].append({"slug":"mozhell-open-air-2027"})
        engine.run(self.folder, self.calendar, self.history,
                   self.day1, self.fetch)
        other = engine.run(self.folder, self.calendar, self.history,
                           self.day2, self.fetch)
        self.assertEqual(other["privateCandidatesAdded"], 1)
        patch = json.loads((self.folder / "patch-2026-11-18.json").read_text())
        self.assertNotIn("mozhell-open-air-2027",
                         [x["slug"] for x in patch["additions"]])


if __name__ == "__main__":
    unittest.main()
