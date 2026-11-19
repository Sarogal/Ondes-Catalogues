"""Offline national archived-organizer discovery, no secrets or publication."""
from __future__ import annotations

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


def archive(slug, name, site):
    return {
        "slug": slug, "name": name, "officialSite": site,
        "startDate": "2026-06-04", "endDate": "2026-06-06",
        "lastKnownYear": 2026,
        "venue": "Historic only", "lat": 46.0, "lon": 5.0,
        "lineup": ["Historic Artist"], "price": "Historic price",
    }


FIRST = archive("north-fire-2026", "North Fire Fest", "https://northfire.example/")
SECOND = archive("delta-riff", "Delta Riff Open Air", "https://deltariff.example/")
HTML_FIRST = "<html><body><main><h1>North Fire Fest</h1><p>Les 12 et 13 juin 2027.</p></main></body></html>"
HTML_SECOND = "<html><body><h1>Delta Riff Open Air</h1><p>10 et 11 juillet 2027</p></body></html>"


class GenericArchivedOrganizerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.today = date(2026, 11, 17)
        self.nextday = date(2026, 11, 18)
        self.history = {"schema": 2, "knownFestivals": [FIRST, SECOND]}
        self.public = {"schema": 1, "generatedAt": "2026-11-16", "festivals": []}
        self.patch = {
            "schema": "grossesondes.patch.v1", "generated_at": "2026-11-17",
            "safe_to_publish": False,
            "source": {"festivals": {
                "url": "https://grosses-ondes.fr/data/festivals.json",
                "generatedAt": "2026-11-01", "count": 123,
            }},
            "additions": [], "updates": [], "deferred": [],
            "history_additions": [], "history_updates": [],
        }
        (self.root / "patch-2026-11-17.json").write_text(json.dumps(self.patch))
        (self.root / "source-watch-state.json").write_text(
            json.dumps({"schema": "grossesondes.source-watch.v1"}))
        self.pages = {FIRST["officialSite"]: HTML_FIRST,
                      SECOND["officialSite"]: HTML_SECOND}
        self.visited = []

    def fetch(self, url, *, registered=False, raw=False):
        self.visited.append((url, registered, raw))
        return self.pages[url]

    def test_dynamically_discovered_archived_sources_are_rechecked_on_two_days(self):
        before = engine.run(self.root, self.public, self.history, self.today, self.fetch)
        self.assertEqual(before["officialProofsEligible"], 2)
        self.assertEqual(before["privateCandidatesAdded"], 0)
        # Only a later-day observation may create a quarantined private patch.
        after = engine.run(self.root, self.public, self.history, self.nextday, self.fetch)
        self.assertEqual(after["officialProofsEligible"], 2)
        self.assertEqual(after["privateCandidatesAdded"], 2)
        approved_patch = json.loads(
            (self.root / "patch-2026-11-18.json").read_text())
        self.assertEqual(
            {x["slug"] for x in approved_patch["additions"]},
            {"north-fire-2027", "delta-riff-2027"})
        self.assertFalse(approved_patch["safe_to_publish"])
        for p in approved_patch["additions"]:
            self.assertEqual(p["proofMode"], ARCHIVED_HTML_PROOF_MODE)
            self.assertEqual(p["lineup"], [])
            self.assertEqual(p["bands"], 0)
            self.assertFalse(p["showOnMap"])
            for key in ("venue", "lat", "lon", "city", "department", "region", "price"):
                self.assertIsNone(p[key])
            origin = next(x for x in self.history["knownFestivals"]
                          if x["slug"] == p["originSlug"])
            self.assertIsNotNone(validate_archived_structured_edition(
                p, origin, self.pages[origin["officialSite"]],
                self.nextday.isoformat(), proof_mode=ARCHIVED_HTML_PROOF_MODE))
        self.assertTrue(all(reg and raw for _, reg, raw in self.visited))

    def test_publisher_freshly_fetches_signed_parent_not_proposal_url(self):
        p = engine.candidate(
            FIRST, {"officialSite": FIRST["officialSite"],
                    "proofUrl": FIRST["officialSite"], "year": 2027},
            HTML_FIRST, self.today)
        self.assertIsNotNone(p)
        p["evidence"] = ["https://forged.example/"]
        urls = []
        def fetch(url, **_kwargs):
            urls.append(url)
            return HTML_FIRST
        result = collect_registered_edition_sources(
            {"additions": [p]}, {}, fetcher=fetch,
            archived={FIRST["slug"]: FIRST})
        self.assertEqual(urls, [FIRST["officialSite"]])
        self.assertEqual(result["registered-edition:" + p["slug"]], HTML_FIRST)

    def test_private_national_hints_prioritize_only_signed_matching_archives(self):
        # Thirty safe archives; one exact private name+region/year matches.
        sources = {
            "hint-" + str(i): archive(
                "hint-" + str(i), "Festival " + str(i) + " Steel",
                "https://festival" + str(i) + ".example/")
            for i in range(30)
        }
        sources["hint-29"]["region"] = "Occitanie"
        review = {
            "schema": engine.NATIONAL_REVIEW_SCHEMA,
            "as_of": "2026-11-17",
            "review_only": True, "safe_to_publish": False,
            "publication_authorized": False,
            "dossiers": [
                {"status": "DISCOVERED_REVIEW_REQUIRED",
                 "archive_slug_hint": "hint-29",
                 "name_hint": "Festival 29 Steel", "region_hint": "Occitanie",
                 "edition_year_hint": 2027, "safe_to_publish": False,
                 "publication_authorized": False},
                {"status": "DISCOVERED_REVIEW_REQUIRED",
                 "archive_slug_hint": "evil-external",
                 "name_hint": "Arbitrary Fest", "region_hint": "Occitanie",
                 "edition_year_hint": 2027, "safe_to_publish": False,
                 "publication_authorized": False},
                {"status": "DISCOVERED_REVIEW_REQUIRED",
                 "archive_slug_hint": "hint-28",
                 "name_hint": "Forged Event", "region_hint": "Other Region",
                 "edition_year_hint": 2027, "safe_to_publish": False,
                 "publication_authorized": False},
            ],
        }
        (self.root / "national-festival-discovery-review.json").write_text(
            json.dumps(review))
        priority = engine.national_archived_priority(
            self.root, sources, self.today)
        self.assertEqual(priority, {"hint-29"})
        chosen = engine.generic_rotating_sources(
            sources, set(), set(), {}, self.today, priority_slugs=priority)
        self.assertEqual(len(chosen), 10)
        self.assertIn("hint-29", chosen)
        self.assertEqual(chosen["hint-29"]["proofUrl"],
                         sources["hint-29"]["officialSite"])

    def test_priority_is_only_hint_and_does_not_starve_rotation(self):
        sources = {
            "group-" + str(i): archive(
                "group-" + str(i), "Metal Group " + str(i),
                "https://group" + str(i) + ".example/")
            for i in range(30)
        }
        state = {}
        visits = []
        for _ in range(4):
            chosen = engine.generic_rotating_sources(
                sources, set(), set(), state, self.today,
                priority_slugs={"group-29", "group-28", "group-27"})
            self.assertLessEqual(len(chosen), 10)
            visits.extend(chosen)
        self.assertEqual(len(set(visits)), 30)

    def test_stale_private_review_and_mismatched_year_never_prioritize(self):
        historic = archive("steel-2025", "Steel Reunion",
                           "https://steel.example/")
        historic["region"] = "Occitanie"
        historic.update(startDate="2025-06-04", endDate="2025-06-06",
                        lastKnownYear=2025)
        record = {"schema": engine.NATIONAL_REVIEW_SCHEMA,
                  "as_of": "2026-11-12", "review_only": True,
                  "safe_to_publish": False, "publication_authorized": False,
                  "dossiers": [{"status": "DISCOVERED_REVIEW_REQUIRED",
                                "archive_slug_hint": historic["slug"],
                                "name_hint": historic["name"],
                                "region_hint": historic["region"],
                                "edition_year_hint": 2026,
                                "safe_to_publish": False,
                                "publication_authorized": False}]}
        path = self.root / "national-festival-discovery-review.json"
        path.write_text(json.dumps(record))
        self.assertEqual(engine.national_archived_priority(
            self.root, {historic["slug"]: historic}, self.today), set())
        record["as_of"] = "2026-11-17"
        path.write_text(json.dumps(record))
        self.assertEqual(engine.national_archived_priority(
            self.root, {historic["slug"]: historic}, self.today), set())
        record["dossiers"][0]["edition_year_hint"] = 2027
        path.write_text(json.dumps(record))
        self.assertEqual(engine.national_archived_priority(
            self.root, {historic["slug"]: historic}, self.today),
            {historic["slug"]})

    def test_bounded_rotation_scans_more_than_two_festivals_without_manual_ids(self):
        sources = {
            "new-" + str(i): archive(
                "new-" + str(i), "Festival " + str(i) + " Steel",
                "https://festival" + str(i) + ".example/")
            for i in range(30)
        }
        state = {}
        a = engine.generic_rotating_sources(
            sources, set(), set(), state, self.today)
        b = engine.generic_rotating_sources(
            sources, set(), set(), state, self.today)
        c = engine.generic_rotating_sources(
            sources, set(), set(), state, self.today)
        self.assertEqual((len(a), len(b), len(c)), (10, 10, 10))
        self.assertEqual(len(set(a) | set(b) | set(c)), 30)
        self.assertLessEqual(engine.GENERIC_MAX_PER_RUN, 10)

    def test_historical_2025_last_seen_can_prove_2027_without_inventing_2026(self):
        # Historical coverage must not disappear merely because the previous
        # edition was missing or the last archived year was 2025.
        revived = archive("returning-ash-2025", "Returning Ash Fest",
                          "https://returningash.example/")
        revived.update(startDate="2025-07-10", endDate="2025-07-11",
                       lastKnownYear=2025)
        html = ("<html><body><main><h1>Returning Ash Fest</h1>"
                "<p>Les 21 et 22 août 2027.</p></main></body></html>")
        self.history["knownFestivals"].append(revived)
        self.pages[revived["officialSite"]] = html
        watched = engine.generic_rotating_sources(
            {revived["slug"]: revived}, set(), set(), {}, self.today)
        self.assertEqual(watched[revived["slug"]]["year"], 2027)
        day1 = engine.run(self.root, self.public, self.history,
                          self.today, self.fetch)
        day2 = engine.run(self.root, self.public, self.history,
                          self.nextday, self.fetch)
        self.assertEqual(day1["privateCandidatesAdded"], 0)
        self.assertEqual(day2["privateCandidatesAdded"], 3)
        patch = json.loads((self.root / "patch-2026-11-18.json").read_text())
        proposal = next(r for r in patch["additions"]
                        if r["slug"] == "returning-ash-2027")
        self.assertEqual(proposal["startDate"], "2027-08-21")
        self.assertIsNone(proposal["venue"])
        self.assertIsNone(proposal["lat"])
        self.assertFalse(proposal["showOnMap"])
        # The publisher still independently validates the HTML first-party
        # claim. Ordinary published-parent admission stays consecutive-year.
        self.assertIsNotNone(validate_archived_structured_edition(
            proposal, revived, html, self.nextday.isoformat(),
            proof_mode=ARCHIVED_HTML_PROOF_MODE))
        from grossesondes_structured_edition import (
            HTML_PROOF_MODE, validate_structured_edition)
        self.assertIsNone(validate_structured_edition(
            dict(proposal, proofMode=HTML_PROOF_MODE), revived, html,
            self.nextday.isoformat(), proof_mode=HTML_PROOF_MODE))

    def test_historical_gap_does_not_approve_wrong_year_or_missing_dates(self):
        old = archive("returning-ash-2025", "Returning Ash Fest",
                      "https://returningash.example/")
        old.update(startDate="2025-07-10", endDate="2025-07-11",
                   lastKnownYear=2025)
        target = {"officialSite": old["officialSite"],
                  "proofUrl": old["officialSite"], "year": 2027}
        self.assertIsNone(engine.candidate(
            old, target, "<html><body>Returning Ash Fest 2026</body></html>",
            self.today))
        self.assertIsNone(engine.candidate(
            old, target,
            "<html><body>Returning Ash Fest 21 et 22 août 2026</body></html>",
            self.today))
        self.assertIsNone(engine.candidate(
            old, dict(target, year=2029),
            "<html><body>Returning Ash Fest 21 et 22 août 2029</body></html>",
            self.today))

    def test_only_first_party_https_from_signed_archive_is_allowed(self):
        for site in (
            "http://organizer.example/", "https://127.0.0.1/",
            "https://localhost/", "https://evil.local/",
            "https://www.facebook.com/festival", "https://linktr.ee/fest",
            "https://www.instagram.com/fest", "https://helloasso.com/fest",
            "https://organizer.example:8080/",
            "https://user:pass@organizer.example/",
            "https://organizer.example/?token=secret",
            "https://organizer.example/fr/../admin",
            "https://organizer.example/fr/%2e%2e/admin",
        ):
            with self.subTest(site=site):
                self.assertFalse(engine.organizer_homepage(site))
        self.assertTrue(engine.organizer_homepage(FIRST["officialSite"]))

    def test_unproved_or_cancelled_official_page_never_adds(self):
        self.pages[FIRST["officialSite"]] = (
            "<html><body><p>North Fire Fest reporté 12 et 13 juin 2027</p></body></html>")
        self.pages[SECOND["officialSite"]] = (
            "<html><body>Delta Riff Open Air <span hidden>10 et 11 juillet 2027</span></body></html>")
        out = engine.run(self.root, self.public, self.history, self.today, self.fetch)
        self.assertEqual(out["officialProofsEligible"], 0)
        self.assertEqual(out["privateCandidatesAdded"], 0)

    def test_yearless_published_edition_is_not_recollected_as_new_suffix(self):
        # Actual Cernunnos failure shape: published slug lacks year, but the
        # signed current edition already has the exact festival/year.
        self.public["festivals"] = [{
            "slug": "delta-riff", "name": "Delta Riff Open Air",
            "startDate": "2027-07-10", "endDate": "2027-07-11",
        }]
        first = engine.run(self.root, self.public, self.history,
                           self.today, self.fetch)
        self.assertEqual(first["officialProofsEligible"], 1)
        self.assertNotIn(SECOND["officialSite"],
                         [url for url, _, _ in self.visited])
        after = engine.run(self.root, self.public, self.history,
                           self.nextday, self.fetch)
        self.assertEqual(after["privateCandidatesAdded"], 1)
        stored = json.loads((self.root / "source-watch-state.json").read_text())
        self.assertNotIn("delta-riff-2027",
                         stored["archived_html_edition_observations"])
        patch = json.loads((self.root / "patch-2026-11-18.json").read_text())
        self.assertEqual([row["slug"] for row in patch["additions"]],
                         ["north-fire-2027"])

    def test_previous_year_with_same_yearless_slug_is_not_excluded(self):
        self.public["festivals"] = [{
            "slug": "delta-riff", "name": "Delta Riff Open Air",
            "startDate": "2026-07-10", "endDate": "2026-07-11",
        }]
        result = engine.run(self.root, self.public, self.history,
                            self.today, self.fetch)
        self.assertEqual(result["officialProofsEligible"], 2)
        self.assertIn(SECOND["officialSite"],
                      [url for url, _, _ in self.visited])

    def test_skip_existing_public_edition_no_duplicate(self):
        self.public["festivals"] = [{"slug": "north-fire-2027"}]
        engine.run(self.root, self.public, self.history, self.today, self.fetch)
        res = engine.run(self.root, self.public, self.history, self.nextday, self.fetch)
        self.assertEqual(res["privateCandidatesAdded"], 1)
        r = json.loads((self.root / "patch-2026-11-18.json").read_text())
        self.assertEqual([x["slug"] for x in r["additions"]], ["delta-riff-2027"])


if __name__ == "__main__":
    unittest.main()
