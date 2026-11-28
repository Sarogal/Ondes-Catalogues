import unittest
from xml.sax.saxutils import escape

from official_programme_sitemap import discover_programme_urls, programme_urls, MAX_XML

SITE = "https://festival-exemple.fr/"


def sitemap(*urls):
    return ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            + "".join("<url><loc>" + escape(url) + "</loc></url>" for url in urls)
            + "</urlset>").encode("utf-8")


class ProgrammeSitemapTests(unittest.TestCase):
    def test_only_same_origin_current_programme_routes(self):
        data = sitemap(SITE + "en/lineup", SITE + "fr/programmation",
                       SITE + "2026/lineup", SITE + "2027/news",
                       "https://other.fr/lineup", SITE + "lineup?token=secret",
                       SITE + "a/../lineup", SITE + "%66r/lineup",
                       SITE + "en/lineup")
        self.assertEqual(programme_urls(SITE, data),
                         [SITE + "en/lineup", SITE + "fr/programmation"])

    def test_reject_entities_index_oversize_and_non_utf8(self):
        for raw in (b'<!DOCTYPE a [<!ENTITY x "test">]><a>&x;</a>',
                    b'<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"/>',
                    b"x" * (MAX_XML + 1), b"\xff", b"<broken"):
            self.assertEqual(programme_urls(SITE, raw), [])

    def test_one_fixed_endpoint_never_follows_candidate_urls(self):
        calls = []
        def fetch(url):
            calls.append(url)
            return sitemap(SITE + "lineup")
        self.assertEqual(discover_programme_urls(SITE + "fr/", fetch=fetch),
                         [SITE + "lineup"])
        self.assertEqual(calls, [SITE + "sitemap.xml"])
        self.assertEqual(discover_programme_urls("http://festival-exemple.fr/", fetch=fetch), [])
        self.assertEqual(len(calls), 1)


    def test_index_child_rotation_is_bounded_and_stays_same_host(self):
        def index(*urls):
            return ('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    + "".join("<sitemap><loc>" + escape(u) + "</loc></sitemap>" for u in urls)
                    + "</sitemapindex>").encode("utf-8")
        first, second = SITE + "pages.xml", SITE + "posts.xml"
        root = SITE + "sitemap.xml"
        data = index(first, second, root, "https://other.fr/child.xml",
                     SITE + "a/../child.xml", SITE + "secret.xml?token=x",
                     SITE + "%63hild.xml", SITE + "child.html")
        pages = {root: data, first: sitemap(SITE + "en/lineup"),
                 second: sitemap(SITE + "fr/programmation")}
        calls = []
        def fetch(url):
            calls.append(url)
            return pages[url]
        self.assertEqual(discover_programme_urls(SITE, fetch=fetch, tick=0),
                         [SITE + "en/lineup"])
        self.assertEqual(calls, [root, first])
        calls.clear()
        self.assertEqual(discover_programme_urls(SITE, fetch=fetch, tick=1),
                         [SITE + "fr/programmation"])
        self.assertEqual(calls, [root, second])
        calls.clear()
        pages[first] = index(second)
        self.assertEqual(discover_programme_urls(SITE, fetch=fetch, tick=0), [])
        self.assertEqual(calls, [root, first])

    def test_discovery_outcomes_expose_only_counts_and_fixed_codes(self):
        root = SITE + "sitemap.xml"
        child = SITE + "pages.xml"
        index = ('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                 '<sitemap><loc>' + child + '</loc></sitemap></sitemapindex>').encode()
        for raw, child_raw, expected, reads, children in (
                (None, None, "ROOT_UNAVAILABLE", 1, 0),
                (b"<broken", None, "ROOT_XML_REJECTED", 1, 0),
                (sitemap(SITE + "news"), None, "DIRECT_NO_ROUTES", 1, 0),
                (sitemap(SITE + "lineup"), None, "DIRECT_ROUTES_FOUND", 1, 0),
                (index, None, "CHILD_UNAVAILABLE", 2, 1),
                (index, index, "CHILD_XML_REJECTED", 2, 1),
                (index, sitemap(SITE + "news"), "INDEX_NO_ROUTES", 2, 1),
                (index, sitemap(SITE + "lineup"), "INDEX_ROUTES_FOUND", 2, 1)):
            with self.subTest(expected=expected):
                diagnostic = {}
                calls = []
                def fetch(url):
                    calls.append(url)
                    return {root: raw, child: child_raw}[url]
                discover_programme_urls(SITE, fetch=fetch, diagnostic=diagnostic)
                self.assertEqual(diagnostic, {"outcome": expected,
                    "index_children": children, "xml_reads": reads})
                self.assertEqual(len(calls), reads)
                self.assertNotIn(child, str(diagnostic))
