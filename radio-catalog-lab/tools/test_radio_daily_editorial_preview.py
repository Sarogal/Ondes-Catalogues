import unittest
from radio_daily_editorial_preview import homepage_url, inspect_page, collect, followup_links

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


    def test_name_alone_is_not_programme_evidence(self):
        result = inspect_page("Azuracast Metal", URL, b"<title>Azuracast Metal</title>")
        self.assertEqual(result["signal"], "no_format_evidence")
        self.assertNotIn("azuracast metal", result["primaryTargetTerms"])

    def test_typed_jsonld_binds_genre_to_station(self):
        body = b'<script type="application/ld+json">{"@graph":[{"@type":"RadioStation","name":"Iron Test Radio","genre":["heavy metal","punk"]},{"@type":"RadioStation","name":"Other Radio","genre":"techno"}]}</script>'
        result = inspect_page("Iron Test Radio", URL, body)
        self.assertTrue(result["structuredProgrammeEvidence"])
        self.assertEqual(result["signal"], "identity_and_target_indication")
        self.assertEqual(inspect_page("Other Radio", URL, body)["signal"], "electronic_indication")

    def test_unrelated_jsonld_not_genre_evidence(self):
        body = b'<script type="application/ld+json">{"@type":"MusicAlbum","name":"Iron Test Radio","genre":"metal"}</script>'
        self.assertEqual(inspect_page("Iron Test Radio", URL, body)["signal"], "no_format_evidence")

    def test_declared_stream_link_matches_exact_url(self):
        body = b'<audio src="/live"></audio>'
        self.assertTrue(inspect_page("Iron Test Radio", URL, body, URL+"live")["declaredStreamLinked"])
        self.assertFalse(inspect_page("Iron Test Radio", URL, body, URL+"other")["declaredStreamLinked"])

    def test_old_analyzer_evidence_requires_refresh(self):
        first = collect(*inputs(), limit=1, fetch=lambda url: (url, HTML))
        for row in first["records"]:
            row.pop("analyzerVersion")
        again = collect(*inputs(), limit=0, previous=first)
        self.assertEqual(again["identityTargetCount"], 0)
        self.assertEqual(again["records"][0]["signal"], "stale_analyzer_or_stream_review")

    def test_changed_stream_does_not_reuse_link(self):
        d,r = inputs()
        d["candidates"][0]["streamUrl"] = URL+"live"
        first = collect(d,r,limit=1,fetch=lambda url:(url,b'<audio src="/live"></audio>'))
        self.assertEqual(first["declaredStreamLinkedCount"], 1)
        d["candidates"][0]["streamUrl"] = URL+"new"
        again = collect(d,r,limit=0,previous=first)
        self.assertEqual(again["declaredStreamLinkedCount"], 0)


    def test_plain_html_scope_without_jsonld(self):
        body=b'<h1>Iron Test Radio</h1><p>Iron Test Radio plays heavy metal 24/7.</p><audio src="/live"></audio>'
        row=inspect_page("Iron Test Radio",URL,body,URL+"live")
        self.assertTrue(row["programmeScopeEvidence"])
        self.assertFalse(row["structuredProgrammeEvidence"])
        self.assertTrue(row["declaredStreamLinked"])
        self.assertEqual(row["programmeScopeSources"],["explicit_html_station_scope"])

    def test_weekly_show_and_mixed_formats_not_scope(self):
        for text in ("Iron Test Radio has a weekly show dedicated to metal",
                     "Iron Test Radio plays metal and indie 24/7",
                     "Iron Test Radio is not dedicated to metal"):
            row=inspect_page("Iron Test Radio",URL,("<h1>Iron Test Radio</h1><p>"+text+"</p>").encode())
            self.assertFalse(row["programmeScopeEvidence"])

    def test_typed_genre_and_exact_station_stream(self):
        body=b'<script type="application/ld+json">{"@type":"RadioStation","name":"Iron Test Radio","genre":"metal","contentUrl":"/live"}</script>'
        row=inspect_page("Iron Test Radio",URL,body,URL+"live")
        self.assertTrue(row["programmeScopeEvidence"])
        self.assertTrue(row["declaredStreamLinked"])
        self.assertFalse(inspect_page("Other Radio",URL,body,URL+"live")["declaredStreamLinked"])

    def test_typed_audio_links_not_generic_video(self):
        for html,expected in ((b'<a type="audio/mpeg" href="/live">Listen</a>',True),
                              (b'<button data-stream-url="/live">Listen</button>',True),
                              (b'<video><source src="/live"></video>',False),
                              (b'<a href="/live">Random link</a>',False)):
            self.assertEqual(inspect_page("Iron Test Radio",URL,html,URL+"live")["declaredStreamLinked"],expected)

    def test_description_of_one_show_not_structured_scope(self):
        body=b'<script type="application/ld+json">{"@type":"RadioStation","name":"Iron Test Radio","description":"weekly metal show"}</script>'
        row=inspect_page("Iron Test Radio",URL,body)
        self.assertTrue(row["structuredProgrammeEvidence"])
        self.assertFalse(row["programmeScopeEvidence"])


    def test_bounded_followup_programme_and_player(self):
        d,r = inputs()
        d["candidates"][0]["streamUrl"] = URL+"live"
        calls = []
        pages = {
            URL: b'<h1>Iron Test Radio</h1><a href="/about">About us</a><a href="/player">Listen live</a><a href="/schedule">Schedule</a>',
            URL+"about": b'<h1>Iron Test Radio</h1><p>Iron Test Radio plays heavy metal 24/7.</p><a href="/extra">Programming</a>',
            URL+"player": b'<h1>Iron Test Radio</h1><audio src="/live"></audio>'
        }
        def fetch(url):
            calls.append(url)
            return url, pages[url]
        report = collect(d,r,limit=1,fetch=fetch)
        self.assertEqual(calls,[URL,URL+"about",URL+"player"])
        self.assertEqual(report["linkedPagesFetched"],2)
        a,b = report["records"]
        self.assertTrue(a["programmeScopeEvidence"])
        self.assertTrue(a["declaredStreamLinked"])
        self.assertEqual(len(a["linkedPageEvidence"]),2)
        self.assertFalse(b["programmeScopeEvidence"])
        self.assertFalse(b["declaredStreamLinked"])

    def test_followup_links_exclude_unsafe_and_irrelevant_targets(self):
        html = b'<a href="https://other.example.org/about">About</a><a href="http://radio.example.org/about">About</a><a href="/about?token=x">About</a><a href="/about.pdf">About</a><a href="/podcast">Programming</a><a href="/about">About</a><a href="/about">About</a>'
        self.assertEqual(followup_links(URL,html),[URL+"about"])

    def test_child_wrong_identity_not_merged(self):
        def fetch(url):
            if url == URL:
                return url,b'<h1>Iron Test Radio</h1><a href="/about">About</a>'
            return url,b'<h1>Different Radio</h1><p>Different Radio plays metal 24/7.</p><audio src="/live"></audio>'
        d,r=inputs()
        d["candidates"][0]["streamUrl"]=URL+"live"
        row=collect(d,r,limit=1,fetch=fetch)["records"][0]
        self.assertFalse(row["programmeScopeEvidence"])
        self.assertFalse(row["declaredStreamLinked"])
        self.assertEqual(row["linkedPageEvidence"],[])

    def test_child_external_redirect_not_merged(self):
        def fetch(url):
            if url == URL:
                return url,b'<h1>Iron Test Radio</h1><a href="/about">About</a>'
            return "https://other.example.org/about", b'<h1>Iron Test Radio</h1><p>Iron Test Radio plays metal 24/7.</p>'
        report=collect(*inputs(),limit=1,fetch=fetch)
        self.assertEqual(report["linkedPagesFetched"],0)
        self.assertFalse(report["records"][0]["programmeScopeEvidence"])

    def test_conflicting_child_programme_blocks_scope(self):
        def fetch(url):
            if url == URL:
                return url,b'<h1>Iron Test Radio</h1><p>Iron Test Radio plays metal 24/7.</p><a href="/about">About</a>'
            return url,b'<h1>Iron Test Radio: metal and techno</h1>'
        row=collect(*inputs(),limit=1,fetch=fetch)["records"][0]
        self.assertFalse(row["programmeScopeEvidence"])
        self.assertEqual(row["signal"],"mixed_programme_indication")

    def test_failed_child_preserves_homepage(self):
        def fetch(url):
            if url == URL:
                return url,b'<h1>Iron Test Radio</h1><p>Iron Test Radio plays metal 24/7.</p><a href="/about">About</a>'
            raise TimeoutError()
        row=collect(*inputs(),limit=1,fetch=fetch)["records"][0]
        self.assertTrue(row["programmeScopeEvidence"])
        self.assertEqual(row["retrieval"],"html_observed")

if __name__ == "__main__":
    unittest.main()
