"""Official institution index discovery: candidates never become trusted pins."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_oa2_official_index_discovery import (
    discover_pinned_official_index, discover_from_live_official_index,
    redacted_discovery_counts,
)

PIN = {"approved_host": "mediatheque-test.fr",
       "exact_index_url": "https://mediatheque-test.fr/agenda"}
META = [{"uid": 12345678, "slug": "mediatheque-test"}]
ROOT = "https://openagenda.com/mediatheque-test"
UNKNOWN = "https://openagenda.com/autre-agenda"


def page(links):
    return {"url": PIN["exact_index_url"],
            "html": "<html><body><main><h1>Agenda culturel de la ville</h1>"
                    + links + "</main></body></html>"}


def anchor(href, text="Agenda jeunesse"):
    return '<a href="' + href + '">' + text + '</a>'


class _PageGet:
    def __init__(self, markup, redirected=False, status=200):
        self.markup = markup
        self.redirected = redirected
        self.status = status
        self.request = None

    def __call__(self, request, timeout):
        self.request = request
        self.url = request.full_url
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self):
        return self.url + "/redirect" if self.redirected else self.url

    @property
    def headers(self):
        return {"Content-Type": "text/html"}

    def read(self, size):
        return self.markup.encode("utf-8")


class OfficialIndexDiscoveryTests(unittest.TestCase):
    def test_known_and_unknown_root_links_enter_review_queue_only(self):
        html = anchor(ROOT) + anchor(UNKNOWN, "Programme culturel")
        out = discover_pinned_official_index(PIN, page(html), META)
        self.assertEqual(out["counts"]["observed_unique_roots"], 2)
        self.assertEqual(out["counts"]["matched_listed_api_metadata"], 1)
        self.assertEqual(out["counts"]["unlisted_slug_for_api_resolution"], 1)
        self.assertEqual(len(out["private_review_queue"]), 2)
        by_slug = {x["observed_agenda_slug"]: x
                   for x in out["private_review_queue"]}
        self.assertEqual(by_slug["mediatheque-test"]["listed_agenda_uid"], "12345678")
        self.assertIsNone(by_slug["autre-agenda"]["listed_agenda_uid"])
        for item in by_slug.values():
            self.assertFalse(item["approved"])
            self.assertTrue(item["review_required"])
            self.assertIsNone(item["timezone"])
            self.assertNotIn("exact_page_url", item)
            self.assertNotIn("agenda_slug", item)
        self.assertFalse(out["institution_ownership_attested"])
        self.assertFalse(out["trusted_registry_mutated"])
        self.assertFalse(out["approval_granted"])

    def test_unlisted_agenda_does_not_require_per_event_hardcoding(self):
        out = discover_pinned_official_index(
            PIN, page(anchor(UNKNOWN)), [])
        self.assertEqual(out["counts"]["unlisted_slug_for_api_resolution"], 1)
        self.assertEqual(out["private_review_queue"][0]["status"],
                         "agenda_uid_unresolved")
        self.assertEqual(out["public_writes"], 0)

    def test_duplicate_metadata_is_held_not_picked_by_first(self):
        out = discover_pinned_official_index(
            PIN, page(anchor(ROOT)),
            META + [{"uid": 87654321, "slug": "mediatheque-test"}])
        self.assertEqual(out["counts"]["ambiguous_api_metadata_held"], 1)
        self.assertIsNone(out["private_review_queue"][0]["listed_agenda_uid"])
        self.assertFalse(out["approval_granted"])

    def test_malicious_hidden_nonroot_and_wrong_label_are_ignored(self):
        sources = (
            anchor("https://openagenda.com.evil.example/mediatheque-test")
            + anchor(ROOT + "/events/12345678_titre")
            + anchor(ROOT + "?redirect=evil.example")
            + anchor(ROOT + "#fake")
            + anchor("http://openagenda.com/mediatheque-test")
            + anchor("https://openagenda.com@evil.example/mediatheque-test")
            + '<a hidden href="' + ROOT + '">Agenda caché</a>'
            + '<span style="display:none">' + anchor(ROOT) + '</span>'
            + anchor(ROOT, "Cliquez ici")
        )
        out = discover_pinned_official_index(PIN, page(sources), META)
        self.assertEqual(out["counts"]["observed_unique_roots"], 0)
        self.assertEqual(out["private_review_queue"], [])

    def test_valid_locale_prefix_and_duplicate_links_deduplicate(self):
        source = anchor("https://openagenda.com/fr/mediatheque-test")
        source += anchor(ROOT, "Programmation")
        source += anchor("https://openagenda.com/en/mediatheque-test", "Calendrier")
        out = discover_pinned_official_index(PIN, page(source), META)
        self.assertEqual(out["counts"]["observed_unique_roots"], 1)

    def test_wrong_pinned_host_or_url_never_discover(self):
        invalid = dict(PIN, approved_host="autre.fr")
        out = discover_pinned_official_index(
            invalid, page(anchor(ROOT)), META)
        self.assertEqual(out["reason"], "unreviewed_institutional_index")
        self.assertEqual(out["private_review_queue"], [])
        other_page = dict(page(anchor(ROOT)), url="https://fake.example/agenda")
        out = discover_pinned_official_index(PIN, other_page, META)
        self.assertEqual(out["counts"]["observed_unique_roots"], 0)

    def test_invalid_metadata_or_unbounded_html_fail_closed(self):
        for metadata in (
            [{"uid": "invalid", "slug": "mediatheque-test"}],
            [{"uid": 12345678, "slug": "../invalid"}],
            [{"uid": 12345678, "slug": "mediatheque-test", "verified": True}],
            [None],
        ):
            out = discover_pinned_official_index(
                PIN, page(anchor(ROOT)), metadata)
            self.assertEqual(out["reason"], "invalid_index_or_metadata")
            self.assertEqual(out["private_review_queue"], [])
        oversized = page("x" * 350001)
        out = discover_pinned_official_index(PIN, oversized, META)
        self.assertEqual(out["reason"], "institutional_index_unavailable")

    def test_real_page_reader_contract_rejects_redirect(self):
        markup = page(anchor(ROOT))["html"]
        reader = _PageGet(markup)
        out = discover_from_live_official_index(PIN, META, opener=reader)
        self.assertEqual(out["counts"]["matched_listed_api_metadata"], 1)
        self.assertEqual(reader.url, PIN["exact_index_url"])
        self.assertEqual(reader.request.get_method(), "GET")
        redirected = _PageGet(markup, redirected=True)
        out = discover_from_live_official_index(PIN, META, opener=redirected)
        self.assertEqual(out["reason"], "institutional_index_unavailable")
        self.assertEqual(out["private_review_queue"], [])

    def test_redacted_aggregate_cannot_leak_source_details(self):
        result = discover_pinned_official_index(
            PIN, page(anchor(ROOT) + anchor(UNKNOWN)), META)
        sanitized = redacted_discovery_counts(result)
        raw = json.dumps(sanitized)
        for secret in (PIN["approved_host"], PIN["exact_index_url"],
                       "mediatheque-test", "autre-agenda", "12345678", ROOT):
            self.assertNotIn(secret, raw)
        self.assertFalse(sanitized["approval_granted"])
        self.assertFalse(sanitized["contains_private_identifiers"])
        self.assertEqual(sanitized["public_writes"], 0)
        forged = redacted_discovery_counts({
            "schema": result["schema"],
            "counts": {"observed_unique_roots": -10,
                       "matched_listed_api_metadata": "SECRET",
                       "unlisted_slug_for_api_resolution": 99999,
                       "ambiguous_api_metadata_held": True},
            "private_review_queue": [{"password": "SECRET"}],
        })
        self.assertEqual(set(forged["counts"].values()), {0})
        self.assertNotIn("SECRET", json.dumps(forged))


if __name__ == "__main__":
    unittest.main()
