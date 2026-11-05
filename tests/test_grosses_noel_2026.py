"""Field-level Festival de Noël approval: immutable sessions and anti-publication guards."""
from copy import deepcopy
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from grossesondes_noel_2026 import (
    PROOF_MODE, SLUG, GROUPS, NOTE, STATUS, FIELDS,
    PROOF_SOURCES, MUNICIPAL_URLS, TICKET_URLS, ORGANIZER_URL,
    noel_2026_update, expected_sources,
)
from grossesondes_stage import stage
from grossesondes_cloud_sync import collect_noel_independent_sources
from urllib.error import HTTPError
from test_grosses_stage import fixtures


def original_row():
    return json.loads((ROOT / "tests/fixtures/noel-2026-reference.json").read_text(encoding="utf-8"))


def proposal(row, date_verified="2026-11-05"):
    target = {
        "officialSite": ORGANIZER_URL,
        "notes": NOTE,
        "verificationStatus": STATUS,
        "auditSources": expected_sources(row),
        "lastVerified": date_verified,
    }
    return {
        "slug": SLUG, "proofMode": PROOF_MODE,
        "evidence": list(PROOF_SOURCES.values()) + list(TICKET_URLS.values()),
        "changes": [
            {"field": field, "before": deepcopy(row[field]), "after": deepcopy(target[field])}
            for field in sorted(FIELDS)
        ],
    }


def independent_sources():
    sources = {"noel_organizer":
               "<html><main>Execution Management. Notre 34° Festival de Noël 2026 "
               "au CCM John Lennon à Limoges avec 4 soirées en décembre 2026.</main>"
               + ("Programme association " * 10) + "</html>"}
    for i, (day, groups) in enumerate(GROUPS.items(), start=1):
        date_part = str(int(day[-2:])) + " déc"
        sources["noel_city_" + day] = (
            "<html><h1>Festival de Noël # XXXIV</h1>"
            f"<h2>Jour {i}</h2><p>Du {date_part} 2026 au CCM John-Lennon "
            "Publié par Centres Culturels Limoges. "
            + " / ".join(groups) +
            "</p><a href='https://execution-mgt.fr/'>Proposé par Execution MGT</a>"
            + ("Une soirée festival officielle. " * 6) + "</html>"
        )
    return sources


class NoelOfficialApprovalTests(unittest.TestCase):
    def test_pinned_reference_exactly_matches_sessions_and_preserves_17(self):
        row = original_row()
        self.assertEqual(row["lineupByDate"], GROUPS)
        self.assertEqual(len(row["lineup"]), 17)
        self.assertEqual(row["officialSite"], None)
        self.assertEqual(row["sessionDates"], list(GROUPS))

    def test_independent_reproof_changes_only_five_approved_fields(self):
        original = original_row()
        result = noel_2026_update(
            original, proposal(original), independent_sources(), "2026-11-05")
        self.assertIsNotNone(result)
        changed, fields, uncorroborated = result
        self.assertEqual(set(fields), FIELDS)
        self.assertEqual(uncorroborated, [])
        self.assertEqual(changed["officialSite"], ORGANIZER_URL)
        self.assertEqual(changed["lineupByDate"], original["lineupByDate"])
        self.assertEqual(changed["lineup"], original["lineup"])
        self.assertEqual(changed["sessionDates"], original["sessionDates"])
        self.assertEqual(changed["bands"], 17)
        self.assertNotIn("ticketAvailability", changed)
        self.assertEqual({k for k in changed if changed[k] != original[k]}, FIELDS)
        self.assertIn("Red Gordon", changed["notes"])

    def test_fail_closed_when_one_independent_source_is_missing_or_wrong(self):
        row, update, sources = original_row(), None, independent_sources()
        update = proposal(row)
        self.assertIsNone(noel_2026_update(row, update, {}, "2026-11-05"))
        for day in GROUPS:
            with self.subTest(day=day):
                s = dict(sources, **{"noel_city_" + day: ""})
                self.assertIsNone(noel_2026_update(row, update, s, "2026-11-05"))
                s = dict(sources, **{"noel_city_" + day:
                    sources["noel_city_" + day].replace("Festival de Noël # XXXIV", "Autre festival")})
                self.assertIsNone(noel_2026_update(row, update, s, "2026-11-05"))
                s = dict(sources, **{"noel_city_" + day:
                    sources["noel_city_" + day].replace(GROUPS[day][0], "Groupe inventé")})
                self.assertIsNone(noel_2026_update(row, update, s, "2026-11-05"))
        s = dict(sources, noel_organizer="<main>Un autre festival hors saison.</main>")
        self.assertIsNone(noel_2026_update(row, update, s, "2026-11-05"))

    def test_ticketing_is_not_stock_evidence_and_patch_cannot_extend_roster(self):
        row, src = original_row(), independent_sources()
        for mutation in (
            lambda up: up.update(evidence=["https://evil.fr/"]),
            lambda up: up["changes"].append(
                {"field":"lineup", "before":row["lineup"],
                 "after":row["lineup"] + ["Red Gordon"]}),
            lambda up: next(c for c in up["changes"] if c["field"] == "officialSite")
                      .update(after="https://www.helloasso.com/"),
            lambda up: next(c for c in up["changes"] if c["field"] == "notes")
                      .update(after="Tous les billets épuisés !"),
            lambda up: next(c for c in up["changes"] if c["field"] == "auditSources")
                      .update(after=["https://evil.fr/"]),
        ):
            with self.subTest(mutation=str(mutation)):
                up = proposal(row)
                mutation(up)
                self.assertIsNone(noel_2026_update(row, up, src, "2026-11-05"))
        self.assertIsNone(noel_2026_update(row, proposal(row, "2026-11-06"),
                                           src, "2026-11-05"))
        altered = dict(row, lineupByDate={**row["lineupByDate"],
                                         "2026-12-19":row["lineupByDate"]["2026-12-19"] +
                                                      ["Red Gordon"]})
        self.assertIsNone(noel_2026_update(altered, proposal(altered),
                                           src, "2026-11-05"))

    def test_cloud_retry_only_transient_http_not_403(self):
        row = original_row()
        patch = {"updates": [proposal(row)]}
        first_url = ORGANIZER_URL
        calls, sleeps = [], []
        def fetch(url):
            calls.append(url)
            if url == first_url and calls.count(url) == 1:
                raise HTTPError(url, 503, "Service Unavailable", None, None)
            if url == MUNICIPAL_URLS["2026-12-12"]:
                raise HTTPError(url, 403, "Forbidden", None, None)
            return "Sources indépendantes accessibles"
        collected = collect_noel_independent_sources(
            patch, fetcher=fetch, sleeper=sleeps.append)
        self.assertEqual(calls.count(first_url), 2)
        self.assertEqual(calls.count(MUNICIPAL_URLS["2026-12-12"]), 1)
        self.assertEqual(sleeps, [1])
        self.assertEqual(collected["noel_organizer"],
                         "Sources indépendantes accessibles")
        self.assertEqual(collected["noel_city_2026-12-12"], "")
        self.assertEqual(set(collected), set(PROOF_SOURCES))

    def test_cloud_sources_ignore_patch_urls_and_absent_mode(self):
        self.assertEqual(collect_noel_independent_sources(
            {"updates": []}, fetcher=lambda url: self.fail(url)), {})
        patch = {"updates": [proposal(original_row())]}
        patch["updates"][0]["evidence"] = ["https://evil.fr/"]
        visited = []
        collected = collect_noel_independent_sources(
            patch,
            fetcher=lambda url: visited.append(url) or "preuve",
            sleeper=lambda _: self.fail("unexpected sleep"))
        self.assertEqual(set(visited), set(PROOF_SOURCES.values()))
        self.assertNotIn("https://evil.fr/", visited)
        self.assertEqual(len(collected), 5)

    def test_stage_holds_without_sources_then_accepts_when_independently_proven(self):
        c, h, p = fixtures()
        row = original_row()
        c["festivals"][5] = deepcopy(row)
        p["additions"] = []
        p["updates"] = [proposal(row)]
        p["generated_at"] = "2026-11-05"
        unverified, withheld = stage(c, h, p, {}, "2026-11-05")
        self.assertNotIn(SLUG, [x["slug"] for x in withheld["accepted_updates"]])
        self.assertEqual(unverified["festivals"][5], row)
        accepted, rep = stage(c, h, p, independent_sources(), "2026-11-05")
        self.assertIn(SLUG, [x["slug"] for x in rep["accepted_updates"]])
        changed = next(r for r in accepted["festivals"] if r["slug"] == SLUG)
        self.assertEqual(changed["officialSite"], ORGANIZER_URL)
        self.assertEqual(len(changed["lineup"]), 17)
        self.assertEqual(len(h["knownFestivals"]), 170)
        self.assertFalse(rep["automatic_publication"])


if __name__ == "__main__":
    unittest.main()
