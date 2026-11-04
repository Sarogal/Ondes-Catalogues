"""End-to-end regression for independent typed festival proof collection.

No real announcement, private token, external request, or published JSON is
needed: the official HTML is a controlled fixture injected into the fetcher.
"""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from grossesondes_cloud_sync import collect_registered_update_sources
from grossesondes_stage import stage
from test_grosses_stage import fixtures

TODAY = "2026-11-04"
URL = "https://festival.example.org/official"
ORIGINAL = {
    "slug": "winter-rising-fest-2026",
    "name": "Winter Rising Fest 2026",
    "startDate": "2026-12-18",
    "endDate": "2026-12-19",
    "lineup": ["Old Band"],
    "bands": 1,
    "lastVerified": "2026-10-01",
    "officialSite": URL,
    "status": "Confirmé",
}
GOOD_HTML = '<script type="application/ld+json">' + json.dumps({
    "@context": "https://schema.org",
    "@type": "MusicEvent",
    "name": "Winter Rising Fest 2026",
    "startDate": "2026-12-18",
    "endDate": "2026-12-19",
    "performer": [
        {"@type": "MusicGroup", "name": "Old Band"},
        {"@type": "MusicGroup", "name": "New Band"},
    ],
}) + "</script>"


def typed_update():
    return {
        "slug": ORIGINAL["slug"],
        "proofMode": "structured-roster.v1",
        "changes": [
            {"field": "lineup", "before": ["Old Band"],
             "after": ["Old Band", "New Band"]},
            {"field": "bands", "before": 1, "after": 2},
            {"field": "lastVerified", "before": "2026-10-01",
             "after": TODAY},
        ],
        "verified_at": TODAY,
        "evidence": [URL],
    }


class RegisteredFestivalProofTests(unittest.TestCase):
    def test_known_festival_typed_patch_can_reach_stage(self):
        c, h, patch = fixtures()
        c["festivals"][3] = dict(ORIGINAL)
        patch["additions"] = []
        patch["updates"] = [typed_update()]
        calls = []

        def fetch(url, *, registered, raw):
            calls.append((url, registered, raw))
            return GOOD_HTML

        source = collect_registered_update_sources(
            patch, {ORIGINAL["slug"]: ORIGINAL}, fetch)
        self.assertEqual(calls, [(URL, True, True)])
        out, report = stage(c, h, patch, source, TODAY)
        self.assertEqual(report["accepted_updates"][0]["slug"], ORIGINAL["slug"])
        self.assertEqual(out["festivals"][3]["lineup"],
                         ["Old Band", "New Band"])
        self.assertEqual(out["festivals"][3]["bands"], 2)
        self.assertEqual(len(out["festivals"]), len(c["festivals"]))
        self.assertEqual(c["festivals"][3]["lineup"], ["Old Band"])
        self.assertFalse(report["automatic_publication"])

    def test_private_patch_cannot_redirect_official_fetch(self):
        modified = typed_update()
        modified["evidence"] = ["https://untrusted.example.org/fake"]
        calls = []
        sources = collect_registered_update_sources(
            {"updates": [modified]}, {ORIGINAL["slug"]: ORIGINAL},
            lambda url, *, registered, raw:
                calls.append(url) or GOOD_HTML)
        self.assertEqual(calls, [URL])
        self.assertIn("registered-schema:" + ORIGINAL["slug"], sources)
        c, h, patch = fixtures()
        c["festivals"][3] = dict(ORIGINAL)
        patch["updates"] = [modified]
        patch["additions"] = []
        out, report = stage(c, h, patch, sources, TODAY)
        self.assertEqual(report["accepted_updates"], [])
        self.assertEqual(out["festivals"][3], ORIGINAL)

    def test_shared_official_site_is_fetched_once_but_both_get_proof(self):
        second = dict(ORIGINAL, slug="same-site-second-2026")
        p = {"updates": [typed_update(),
                         dict(typed_update(), slug=second["slug"])]}
        calls = []
        proofs = collect_registered_update_sources(
            p, {ORIGINAL["slug"]: ORIGINAL, second["slug"]: second},
            lambda url, *, registered, raw:
                calls.append((url, raw)) or GOOD_HTML)
        self.assertEqual(calls, [(URL, True)])
        self.assertEqual(proofs["registered-schema:" + ORIGINAL["slug"]], GOOD_HTML)
        self.assertEqual(proofs["registered-schema:" + second["slug"]], GOOD_HTML)

    def test_error_fails_closed_for_all_sharing_site(self):
        second = dict(ORIGINAL, slug="same-site-second-2026")
        p = {"updates": [typed_update(),
                         dict(typed_update(), slug=second["slug"])]}
        calls = []

        def broken(url, *, registered, raw):
            calls.append(url)
            raise OSError("source unavailable")

        proofs = collect_registered_update_sources(
            p, {ORIGINAL["slug"]: ORIGINAL, second["slug"]: second}, broken)
        self.assertEqual(calls, [URL])
        self.assertEqual(list(proofs.values()), ["", ""])

    def test_legacy_known_and_unknown_mode_do_not_fetch(self):
        updates = [dict(typed_update(), proofMode="unknown.v2"),
                   {"slug": ORIGINAL["slug"], "changes": []}]
        proofs = collect_registered_update_sources(
            {"updates": updates}, {ORIGINAL["slug"]: ORIGINAL},
            lambda *args, **kwargs: self.fail("unexpected network fetch"))
        self.assertEqual(proofs, {})

    def test_limit_stays_at_first_fifteen_updates(self):
        rows = {}
        updates = []
        for i in range(16):
            slug = f"test-{i}"
            rows[slug] = dict(ORIGINAL, slug=slug, officialSite=f"https://site{i}.example.org")
            updates.append(dict(typed_update(), slug=slug))
        calls = []
        collect_registered_update_sources(
            {"updates": updates}, rows,
            lambda url, *, registered, raw: calls.append(url) or GOOD_HTML)
        self.assertEqual(len(calls), 15)


if __name__ == "__main__":
    unittest.main()
