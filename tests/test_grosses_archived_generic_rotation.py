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

    def test_skip_existing_public_edition_no_duplicate(self):
        self.public["festivals"] = [{"slug": "north-fire-2027"}]
        engine.run(self.root, self.public, self.history, self.today, self.fetch)
        res = engine.run(self.root, self.public, self.history, self.nextday, self.fetch)
        self.assertEqual(res["privateCandidatesAdded"], 1)
        r = json.loads((self.root / "patch-2026-11-18.json").read_text())
        self.assertEqual([x["slug"] for x in r["additions"]], ["delta-riff-2027"])


if __name__ == "__main__":
    unittest.main()
