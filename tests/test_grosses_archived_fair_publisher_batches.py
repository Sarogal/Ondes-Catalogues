"""Publisher fairness: arbitrary validated festival count, bounded proof per run.

Nothing is signed by this test. No network, secrets or public writes.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from grossesondes_cloud_sync import collect_registered_edition_sources
from grossesondes_structured_edition import ARCHIVED_HTML_PROOF_MODE


def data(size=31):
    archive = {
        "old-" + str(i): {"officialSite": "https://festival" + str(i) + ".example/"}
        for i in range(size)
    }
    proposals = [{
        "slug": "festival" + str(i) + "-2027",
        "originSlug": "old-" + str(i),
        "proofMode": ARCHIVED_HTML_PROOF_MODE,
        "startDate": "2027-07-22", "endDate": "2027-07-24",
    } for i in range(size)]
    return proposals, archive


class FestivalFairPublisherBatchesTests(unittest.TestCase):
    def test_ten_fresh_editions_per_run_then_next_ten(self):
        proposals, archive = data()
        calls = []
        def fake_fetch(url, **kwargs):
            calls.append(url)
            self.assertTrue(kwargs["registered"])
            self.assertTrue(kwargs["raw"])
            return "<html>fake first-party content used only for routing</html>"
        signed = set()
        all_seen = set()
        for expected in (10, 10, 10, 1):
            before = len(calls)
            sources = collect_registered_edition_sources(
                {"additions": proposals}, {}, fake_fetch,
                archived=archive, published_slugs=signed)
            current = {p["slug"] for p in proposals
                       if "registered-edition:" + p["slug"] in sources}
            self.assertEqual(len(current), expected)
            self.assertEqual(len(calls) - before, expected)
            self.assertFalse(current & signed)
            all_seen.update(current)
            signed.update(current)
        self.assertEqual(len(all_seen), 31)
        self.assertEqual(signed, {p["slug"] for p in proposals})

    def test_existing_published_and_nonproof_modes_do_not_consume_the_budget(self):
        proposed, archive = data(18)
        proposed.insert(0, {"slug": "legacy-unknown", "proofMode": None})
        visited = []
        signed = {p["slug"] for p in proposed[1:6]}
        result = collect_registered_edition_sources(
            {"additions": proposed}, {}, lambda url, **_: visited.append(url) or "<html/>",
            archived=archive, published_slugs=signed)
        self.assertEqual(len(visited), 10)
        self.assertFalse(any("registered-edition:" + slug in result for slug in signed))
        self.assertNotIn("registered-edition:legacy-unknown", result)
        self.assertIn("registered-edition:festival5-2027", result)
        self.assertIn("registered-edition:festival14-2027", result)

    def test_untrusted_published_set_fails_closed(self):
        proposals, archive = data(1)
        for corrupt in (["festival0-2027"], {"festival0-2027": True}, {None},
                        {"festival0-2027", 42}):
            with self.subTest(corrupt=str(corrupt)), self.assertRaises(ValueError):
                collect_registered_edition_sources(
                    {"additions": proposals}, {}, lambda u, **kw: "", archived=archive,
                    published_slugs=corrupt)

    def test_never_take_a_fetch_url_from_private_proposal(self):
        proposals, archive = data(1)
        proposals[0]["sourceUrl"] = "https://evil.test/private"
        proposed = []
        def fetch(url, **kwargs):
            proposed.append(url)
            return "<html/>"
        result = collect_registered_edition_sources(
            {"additions": proposals}, {}, fetch, archived=archive,
            published_slugs=set())
        self.assertEqual(proposed, ["https://festival0.example/"])
        self.assertNotIn("evil.test", str(result))

    def test_no_identity_spoof_when_no_approved_parent(self):
        proposals, archive = data(1)
        result = collect_registered_edition_sources(
            {"additions": proposals}, {}, lambda *_args, **_kw: "<html/>",
            archived={}, published_slugs=set())
        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
