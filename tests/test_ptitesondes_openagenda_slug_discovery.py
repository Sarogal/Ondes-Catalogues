"""No-network tests: exact public OpenAgenda agenda slug -> immutable UID.

Public API metadata is an UNVERIFIED source identity; never organizer trust.
"""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_openagenda_slug_discovery import (
    SCHEMA, MAX_BYTES, lookup_agenda_by_slug,
)

KEY = "oa_pk_testpublicread123"
SLUG = "mediatheques-de-la-haute-deule"


class FakeResponse:
    def __init__(self, url, raw, *, status=200, redirect=None):
        self.url, self.raw = url, raw
        self.status = status
        self.redirect = redirect

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def geturl(self):
        return self.redirect or self.url

    def read(self, limit):
        return self.raw[:limit]


def lookup(data=None, *, status=200, redirect=None, key=KEY,
           slug=SLUG, raw=None, capture=None):
    if data is None:
        data = {"total": 1, "agendas": [
            {"uid": 228811, "slug": slug, "official": True,
             "url": "https://self-asserted-not-a-source.example"},
        ]}
    def open_fake(request, timeout):
        if capture is not None:
            capture.append((request.full_url,
                            request.get_header("Key"), timeout))
        return FakeResponse(request.full_url,
                            json.dumps(data).encode() if raw is None else raw,
                            status=status, redirect=redirect)
    return lookup_agenda_by_slug(slug, key, opener=open_fake)


class DynamicAgendaSlugDiscoveryTests(unittest.TestCase):
    def test_exact_public_slug_resolution_is_only_research(self):
        calls = []
        result = lookup(capture=calls)
        self.assertEqual(result["schema"], SCHEMA)
        self.assertEqual(result["uid"], 228811)
        self.assertEqual(result["slug"], SLUG)
        self.assertEqual(result["status"],
                         "public_uid_slug_only_independent_ownership_pending")
        self.assertEqual(len(calls), 1)
        url, header, timeout = calls[0]
        self.assertEqual(
            url, "https://api.openagenda.com/v2/agendas?"
            "slug=mediatheques-de-la-haute-deule&size=2")
        self.assertEqual(header, KEY)
        self.assertEqual(timeout, 18)
        self.assertNotIn(KEY, url)
        for flag in ("organizer_verified", "independent_ownership_verified",
                     "rights_reviewed", "publication_ready",
                     "approval_granted", "publisher_connected"):
            self.assertIs(result[flag], False)
        self.assertEqual(result["public_writes"], 0)
        self.assertNotIn("url", result)
        self.assertNotIn("permissions", result)

    def test_untrusted_agenda_official_true_and_url_are_never_permissions(self):
        self.assertFalse(lookup()["independent_ownership_verified"])
        self.assertFalse(lookup()["approval_granted"])
        self.assertFalse(lookup()["rights_reviewed"])

    def test_slug_and_public_read_key_must_be_strict_and_header_only(self):
        for value in ("", "../localhost", "a?uid=1", "a#fragment",
                      "a&size=100", "foo.bar", "AGENDA", "a" * 102,
                      None, "coeur de flandre"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                lookup(slug=value)
        for key in ("", "oa_sk_secret12345678", "not-a-key",
                    "oa_pk_short", "oa_pk_test\nHeader: injected",
                    "oa_pk_test\r\nHost: malicious"):
            with self.subTest(key=key), self.assertRaises(ValueError):
                lookup(key=key)

    def test_nonunique_missing_or_unrelated_search_never_selects_a_winner(self):
        for data in (
            {"total": 0, "agendas": []},
            {"total": 2, "agendas": [
                {"uid": 1, "slug": SLUG}, {"uid": 2, "slug": SLUG}]},
            {"total": 1, "agendas": []},
            {"total": 1, "agendas": [{"uid": 1, "slug": "other"}]},
            {"total": 1, "agendas": [{"uid": 0, "slug": SLUG}]},
            {"total": 1, "agendas": [{"uid": True, "slug": SLUG}]},
            {"total": 1, "agendas": [{"uid": "1", "slug": SLUG}]},
            {"total": True, "agendas": [{"uid": 1, "slug": SLUG}]},
            {"total": 1, "agendas": [{"uid": 10**13, "slug": SLUG}]},
            {"agendas": [{"uid": 100, "slug": SLUG}]},
            ["malformed"],
        ):
            with self.subTest(data=data), self.assertRaises(ValueError):
                lookup(data=data)

    def test_redirect_bad_status_oversize_json_and_network_unavailable(self):
        with self.assertRaises(ValueError):
            lookup(redirect="https://evil.test/redirect")
        with self.assertRaises(ValueError):
            lookup(status=301)
        with self.assertRaises(ValueError):
            lookup(raw=b"a" * (MAX_BYTES + 1))
        with self.assertRaises(ValueError):
            lookup(raw=b"{broken")
        with self.assertRaises(ValueError):
            lookup_agenda_by_slug(
                SLUG, KEY, opener=lambda request, timeout: (
                    _ for _ in ()).throw(TimeoutError("read-only offline")))


if __name__ == "__main__":
    unittest.main()
