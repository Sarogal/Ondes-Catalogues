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
