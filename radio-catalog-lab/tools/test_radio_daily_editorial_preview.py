import unittest
from radio_daily_editorial_preview import homepage_url, inspect_page, collect

A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
DAY = "2026-11-25"
URL = "https://radio.example.org/"
HTML = b'<title>Iron Test Radio</title><meta name="description" content="Heavy metal and punk radio"><meta property="og:image" content="/logo.png">'


def inputs():
    d = {"schemaVersion": 1, "publicationAllowed": False, "scanDate": DAY, "candidates": [
        {"stationuuid": uid, "name": "Iron Test Radio" if uid == A else "Other Radio", "homepage": URL}
        for uid in (A,B)]}
    r = {"schemaVersion": 1, "automaticAdmissionAllowed": False, "catalogChanged": False,
         "scanDate": DAY, "candidates": [{"stationuuid": uid, "classification": "unmapped_candidate"} for uid in (A,B)]}
    return d,r


class EditorialPreviewTests(unittest.TestCase):
    def test_url_policy(self):
        self.assertEqual(homepage_url("http://radio.example.org"), URL)
        for url in ("https://127.0.0.1/", "https://localhost/", "https://radcap.ru/",
                    "https://radio.example.org/?token=x", "https://user@radio.example.org/",
                    "https://radio.example.org:8080/"):
            self.assertIsNone(homepage_url(url))

    def test_identity_bound_signal_and_logo_hint(self):
        a = inspect_page("Iron Test Radio", URL, HTML)
        self.assertEqual(a["signal"], "identity_and_target_indication")
        self.assertEqual(len(a["imageHintSha256"]), 1)
        self.assertEqual(inspect_page("Other Radio", URL, HTML)["signal"], "unbound_target_indication")

    def test_mixed_and_script_only(self):
        self.assertEqual(inspect_page("Iron Test Radio", URL,
            b"<title>Iron Test Radio: punk and techno</title>")["signal"], "mixed_programme_indication")
        self.assertEqual(inspect_page("Iron Test Radio", URL,
            b"<title>Iron Test Radio</title><script>metal punk</script>")["signal"], "no_format_evidence")

    def test_shared_page_one_fetch_not_shared_identity(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return url, HTML
        result = collect(*inputs(), limit=1, fetch=fetch)
        self.assertEqual(calls, [URL])
        self.assertEqual(result["identityTargetCount"], 1)
        self.assertEqual(result["htmlObservedCount"], 2)
        self.assertEqual(result["editoriallyApprovedCount"], 0)

    def test_retention_and_same_day_backoff(self):
        first = collect(*inputs(), limit=1, fetch=lambda url: (url, HTML))
        d,r = inputs()
        d["candidates"] = d["candidates"][1:]
        r["candidates"] = r["candidates"][1:]
        again = collect(d,r,limit=1,previous=first,fetch=lambda url: self.fail("cache"))
        self.assertFalse(again["records"][0]["observedInScan"])
        self.assertEqual(again["identityTargetCount"], 1)
        self.assertEqual(again["attemptedPageCount"], 0)

    def test_failed_page_is_not_retried_same_day(self):
        first = collect(*inputs(), limit=1, fetch=lambda url: (url,b""))
        again = collect(*inputs(), limit=1, previous=first, fetch=lambda url: self.fail("backoff"))
        self.assertEqual(again["attemptedPageCount"], 0)
        self.assertEqual(again["htmlObservedCount"], 0)

    def test_offline_default_and_external_redirect(self):
        self.assertEqual(collect(*inputs(), fetch=lambda url: self.fail("network"))["attemptedPageCount"], 0)
        result = collect(*inputs(), limit=1, fetch=lambda url: ("https://other.example.org/", HTML))
        self.assertEqual(result["htmlObservedCount"], 0)


if __name__ == "__main__":
    unittest.main()
