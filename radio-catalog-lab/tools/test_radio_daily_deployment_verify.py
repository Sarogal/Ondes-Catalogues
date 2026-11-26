"""Independent synthetic public endpoint and deployment acceptance tests."""
import unittest
from dataclasses import replace

import test_radio_daily_git_lab_transfer as fixture
from radio_daily_baseline_verify import strict_json
from radio_daily_deployment_verify import PublicResponse, ROOT, POINTER_URL, verify_deployment
from radio_daily_publication_simulator import inventory
from radio_daily_v9_generator import digest


class DeploymentVerifyTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.GitLabTransferTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.commit = self.f.advance()
        self.f.successor(self.commit)
        self.store = self.f.store
        self.pointer = self.store.current()
        p = strict_json(self.pointer)
        self.catalog_url = ROOT + p["content_path"]
        body = self.store.get(p["content_path"])
        self.responses = {
            POINTER_URL: PublicResponse(200, POINTER_URL, "application/json", self.pointer),
            self.catalog_url: PublicResponse(200, self.catalog_url, "application/json; charset=utf-8", body),
        }
        for logo, _ in inventory(strict_json(body)):
            url = logo["url"]
            self.responses[url] = PublicResponse(200, url, logo["mime_type"], self.store.logo(url))
        self.logo_urls = set(self.responses) - {POINTER_URL, self.catalog_url}
        self.calls = []
        signer = self.f.f.f.f.signer
        self.args = dict(expected_commit=self.commit, deployment_commit=self.commit,
                         deployment_status="success", bootstrap_sha=self.f.old_sha,
                         expected_sha=self.f.old_sha, expected_sequence=8,
                         public_key=signer.public_key, key_id=signer.key_id)

    def fetch(self, url, limit):
        self.calls.append((url, limit))
        return self.responses[url]

    def verify(self, **kw):
        args = dict(self.args, fetch=self.fetch)
        args.update(kw)
        return verify_deployment(self.f.receiver, **args)

    def test_exact_deployment_independent_readback(self):
        report = self.verify()
        self.assertTrue(report["deploymentVerified"])
        self.assertTrue(report["simulated"])
        self.assertFalse(report["publicationAllowed"])
        self.assertEqual(report["selectedSequence"], 9)
        self.assertEqual(report["selectedSha256"], self.f.new_sha)
        self.assertEqual(report["verifiedLogoUrls"], len(self.logo_urls))
        self.assertEqual(self.calls[0][0], POINTER_URL)
        self.assertEqual(self.calls[-1][0], POINTER_URL)
        self.assertEqual(set(url for url, _ in self.calls), set(self.responses))

    def test_git_success_is_not_deployment_success(self):
        for args in (dict(deployment_status="pending"), dict(deployment_status="failure"),
                     dict(deployment_commit=self.f.base)):
            with self.subTest(args=args), self.assertRaisesRegex(ValueError, "deployment"):
                self.verify(**args)
        self.assertEqual(self.calls, [])

    def test_stale_public_pointer_refused(self):
        self.responses[POINTER_URL] = replace(self.responses[POINTER_URL],
            body=self.store.historical(8)[0])
        with self.assertRaisesRegex(ValueError, "public pointer differs"):
            self.verify()
        self.assertEqual(len(self.calls), 1)

    def test_public_catalogue_corruption_refused(self):
        item = self.responses[self.catalog_url]
        self.responses[self.catalog_url] = replace(item, body=b"x"*len(item.body))
        with self.assertRaisesRegex(ValueError, "public catalogue differs"):
            self.verify()

    def test_missing_logo_and_wrong_mime_refused(self):
        url = next(iter(self.logo_urls))
        original = self.responses[url]
        self.responses[url] = replace(original, status=404)
        with self.assertRaisesRegex(ValueError, "unavailable"):
            self.verify()
        self.responses[url] = replace(original, content_type="text/html")
        with self.assertRaisesRegex(ValueError, "content type"):
            self.verify()

    def test_redirect_and_oversized_response_refused(self):
        url = next(iter(self.logo_urls))
        original = self.responses[url]
        self.responses[url] = replace(original, effective_url="https://untrusted.example.invalid/")
        with self.assertRaisesRegex(ValueError, "redirected"):
            self.verify()
        self.responses[url] = replace(original, body=original.body+b"x")
        with self.assertRaisesRegex(ValueError, "resource size"):
            self.verify()

    def test_changed_pointer_during_public_readback_refused(self):
        seen = 0
        def moving(url, limit):
            nonlocal seen
            response = self.fetch(url, limit)
            if url == POINTER_URL:
                seen += 1
                if seen == 2:
                    return replace(response, body=self.store.historical(8)[0])
            return response
        with self.assertRaisesRegex(ValueError, "changed during"):
            self.verify(fetch=moving)

    def test_logo_same_size_corruption_refused(self):
        url = next(iter(self.logo_urls))
        original = self.responses[url]
        self.responses[url] = replace(original, body=b"x"*len(original.body))
        with self.assertRaisesRegex(ValueError, "logo digest"):
            self.verify()
