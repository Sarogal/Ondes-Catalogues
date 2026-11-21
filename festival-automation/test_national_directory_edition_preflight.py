"""Synthetic unknown festival discovery: no source URL trust or public writes."""
import sys
from copy import deepcopy
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from national_directory_edition_preflight import (
    eligible, examine, stable_private_proposals, append_private_proposals,
    proof_digest, STATE_KEY, SCHEMA,
)
from grossesondes_generic_directory_edition import directory_url, PROOF_MODE

FIRST = "2026-11-20"
SECOND = "2026-11-21"
TITLE = "Festival Foudre Imaginaire 2027"
BASE = "Festival Foudre Imaginaire"
SITE = "https://www.foudre-festival.fr/"
DURL = "https://www.festivalenfrance.com/festival/festivalfoudreimaginaire"
DATES = ("2027-06-25", "2027-06-26")
INDEX = (f"<main><h1>{BASE}</h1><p>Festival de metal</p>"
         f'<p>Site web : <a href="{SITE}">www.foudre-festival.fr</a></p>'
         "</main>")
HOMEPAGE = (f"<main><h1>{TITLE}</h1>"
            "<p>Notre festival de rock : 25 et 26 juin 2027</p></main>")


def discovery(day=FIRST, source="https://127.0.0.1/should-never-be-fetched"):
    return {
        "schema": "grossesondes.national-festival-discovery-private.v1",
        "as_of": day, "review_only": True,
        "safe_to_publish": False, "publication_authorized": False,
        "dossiers": [{
            "id": "national-unique-foudre-2027",
            "name_hint": BASE, "edition_year_hint": 2027,
            "status": "DISCOVERED_REVIEW_REQUIRED",
            "review_only": True, "safe_to_publish": False,
            "publication_authorized": False,
            "sources": [{
                "kind": "OPENAGENDA_PUBLIC_RESEARCH_ONLY",
                "url": source, "publication_authorized": False,
            }],
        }],
    }


def state():
    return {"schema": "grossesondes.source-watch.v1"}


def catalog():
    return {"schema": 1, "festivals": []}


class NationalDirectoryAutonomyTests(TestCase):
    def test_new_name_only_produces_safe_directory_lookup(self):
        sources = eligible(discovery(), catalog(), FIRST)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["directory_url"], DURL)
        self.assertNotIn("http://127.0.0.1", str(sources))
        self.assertEqual(directory_url(TITLE), DURL)

    def test_two_calendar_days_and_private_only_proposal(self):
        s, visited = state(), []
        def read_directory(url):
            visited.append(url)
            self.assertEqual(url, DURL)
            return INDEX
        def read_site(url):
            visited.append(url)
            self.assertEqual(url, SITE)
            return HOMEPAGE
        with patch("national_directory_edition_preflight.verify_primary",
                   return_value=DATES):
            first = examine(s, discovery(), catalog(), FIRST,
                            directory_fetch=read_directory,
                            organizer_fetch=read_site, limit=1)
            self.assertEqual(first["rows"][0]["status"],
                             "FIRST_DAY_DIRECTORY_FIRST_PARTY_PRIVATE")
            self.assertEqual(first["two_day_count"], 0)
            self.assertEqual(stable_private_proposals(
                s, discovery(), catalog(), first, FIRST), [])
            second = examine(s, discovery(SECOND), catalog(), SECOND,
                             directory_fetch=read_directory,
                             organizer_fetch=read_site, limit=1)
            self.assertEqual(second["rows"][0]["status"],
                             "TWO_DAY_DIRECTORY_FIRST_PARTY_PRIVATE")
            self.assertEqual(second["two_day_count"], 1)
            self.assertFalse(second["publication_authorized"])
            proposals = stable_private_proposals(
                s, discovery(SECOND), catalog(), second, SECOND)
        self.assertEqual(visited, [DURL, SITE, DURL, SITE])
        self.assertEqual(len(proposals), 1)
        p = proposals[0]
        self.assertEqual(p["proofMode"], PROOF_MODE)
        self.assertFalse(p["showOnMap"])
        self.assertIsNone(p["city"])
        self.assertEqual(p["lineup"], [])
        self.assertFalse(p["source"].startswith("https://127.0.0.1"))

    def test_hyphenated_directory_alias_stays_bound_across_two_days(self):
        # Directory aliases are derived from the exact dossier name, NEVER
        # from its untrusted candidate source URL.
        alternate = DURL.replace(
            "/festival/festivalfoudreimaginaire",
            "/festival/festival-foudre-imaginaire")
        visited, state_store = [], state()
        def directory(url):
            visited.append(url)
            if url == DURL:
                raise OSError("compact alias 404")
            self.assertEqual(url, alternate)
            return INDEX
        def primary(url):
            visited.append(url)
            self.assertEqual(url, SITE)
            return HOMEPAGE
        with patch("national_directory_edition_preflight.verify_primary",
                   return_value=DATES):
            first = examine(state_store, discovery(FIRST), catalog(), FIRST,
                            directory_fetch=directory,
                            organizer_fetch=primary, limit=1)
            second = examine(state_store, discovery(SECOND), catalog(), SECOND,
                             directory_fetch=directory,
                             organizer_fetch=primary, limit=1)
            ready = stable_private_proposals(
                state_store, discovery(SECOND), catalog(), second, SECOND)
        self.assertEqual(first["two_day_count"], 0)
        self.assertEqual(second["two_day_count"], 1)
        self.assertEqual(second["rows"][0]["directory_ref_review_only"],
                         alternate)
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0]["originSlug"], alternate)
        self.assertEqual(ready[0]["evidence"], [alternate, SITE])
        self.assertEqual(visited, [DURL, alternate, SITE,
                                   DURL, alternate, SITE])
        forged = deepcopy(second)
        forged["rows"][0]["directory_ref_review_only"] = DURL
        self.assertEqual(stable_private_proposals(
            state_store, discovery(SECOND), catalog(), forged, SECOND), [])
        forged["rows"][0]["directory_ref_review_only"] = "https://evil.example/"
        self.assertEqual(stable_private_proposals(
            state_store, discovery(SECOND), catalog(), forged, SECOND), [])

    def test_missing_directory_attribution_never_probes_candidate_url(self):
        s, calls = state(), []
        def directory(url):
            calls.append(url)
            return "<main><h1>Other festival</h1><p>Site web</p></main>"
        result = examine(s, discovery(), catalog(), FIRST,
                         directory_fetch=directory,
                         organizer_fetch=lambda u: self.fail(
                             "Unknown organizer domain must never be fetched"),
                         limit=1)
        self.assertEqual(calls, [
            DURL, DURL.replace("/festival/festivalfoudreimaginaire",
                               "/festival/festival-foudre-imaginaire")])
        self.assertEqual(result["rows"][0]["status"],
                         "DIRECTORY_OFFICIAL_LINK_UNPROVEN")
        self.assertNotIn("digest", s[STATE_KEY][
            "national-unique-foudre-2027"])

    def test_directories_cannot_bypass_genre_rechecks(self):
        s, calls = state(), []
        result = examine(s, discovery(), catalog(), FIRST,
                         directory_fetch=lambda u: INDEX,
                         organizer_fetch=lambda u: calls.append(u) or
                         "<h1>Other 2027</h1><p>festival jazz uniquement</p>",
                         limit=1)
        self.assertEqual(calls, [SITE])
        self.assertEqual(result["rows"][0]["status"],
                         "OFFICIAL_CURRENT_EDITION_NOT_PROVEN")
        self.assertEqual(result["two_day_count"], 0)

    def test_report_poison_and_duplicate_are_not_publication_permission(self):
        s = state()
        q = discovery(SECOND)
        base = eligible(q, catalog(), SECOND)[0]
        s[STATE_KEY] = {base["dossier_id"]: {
            "firstSeen": FIRST, "lastSeen": SECOND,
            "lastChecked": SECOND, "stable": True,
            "digest": proof_digest(base, SITE, DATES),
            "directoryRef": DURL,
        }}
        review = {
            "schema": SCHEMA, "as_of": SECOND, "review_only": True,
            "safe_to_publish": False, "publication_authorized": False,
            "publications": 0,
            "rows": [{
                "dossier_id": base["dossier_id"],
                "status": "TWO_DAY_DIRECTORY_FIRST_PARTY_PRIVATE",
                "publication_authorized": False,
                "two_day_observation": True,
                "directory_ref_review_only": DURL,
                "site_review_only": SITE, "start_date_hint": DATES[0],
                "end_date_hint": DATES[1],
            }],
        }
        good = stable_private_proposals(s, q, catalog(), review, SECOND)
        self.assertEqual(len(good), 1)
        for changed in (
            lambda x: x["rows"][0].update(start_date_hint="2027-06-24"),
            lambda x: x["rows"][0].update(publication_authorized=True),
            lambda x: x.update(safe_to_publish=True),
        ):
            with self.subTest(changed=changed):
                faulty = deepcopy(review)
                changed(faulty)
                if faulty.get("safe_to_publish") is True:
                    with self.assertRaises(ValueError):
                        stable_private_proposals(
                            s, q, catalog(), faulty, SECOND)
                else:
                    self.assertEqual(stable_private_proposals(
                        s, q, catalog(), faulty, SECOND), [])
        published = {"schema": 1, "festivals": [{
            "slug": good[0]["slug"], "name": TITLE,
            "startDate": DATES[0]}]}
        self.assertEqual(eligible(q, published, SECOND), [])
        self.assertEqual(stable_private_proposals(
            s, q, published, review, SECOND), [])

    def test_no_patch_io_when_not_stable(self):
        report = {
            "schema": SCHEMA, "as_of": FIRST, "review_only": True,
            "safe_to_publish": False, "publication_authorized": False,
            "publications": 0, "rows": [],
        }
        with patch("national_directory_edition_preflight.latest_patch") as read:
            count = append_private_proposals(
                Path("/does-not-exist"), catalog(),
                {"schema": 2, "knownFestivals": []},
                state(), discovery(), report, FIRST)
        self.assertEqual(count, 0)
        read.assert_not_called()


if __name__ == "__main__":
    main()
