"""Live institutional pagination never trusts privately suggested links."""
import unittest

from national_live_index_recheck import live_index_for_exact_link

ORIGIN = "https://sortir.limoges.fr/agenda?keys=festival"
PAGE = ORIGIN + "&page=1"
OTHER = ORIGIN + "&page=2"
EVENT = "https://sortir.limoges.fr/agenda/festival-des-nuits-de-fer-2027"
SOURCE = {
    "index_url": ORIGIN, "index_page": ORIGIN, "url": EVENT,
    "title": "Festival des Nuits de Fer 2027", "year": 2027,
}


class LiveIndexPaginationTests(unittest.TestCase):
    def test_exact_title_discovered_on_visible_linked_page(self):
        root = ('<main><a href="?keys=festival&page=1">'
                '1</a></main>')
        page = ('<main><a href="/agenda/festival-des-nuits-de-fer-2027">'
                'Festival des Nuits de Fer 2027</a></main>')
        fetched = []
        def fetch(url):
            fetched.append(url)
            return {ORIGIN: root, PAGE: page}[url]
        self.assertEqual(live_index_for_exact_link(SOURCE, fetch), page)
        self.assertEqual(fetched, [ORIGIN, PAGE])

    def test_no_unreviewed_host_or_query_is_downloaded(self):
        root = ('<a href="https://127.0.0.1/private">2</a>'
                '<a href="?keys=festival&page=999">999</a>'
                '<a href="?keys=rock&page=1">1</a>')
        fetched = []
        result = live_index_for_exact_link(
            SOURCE, lambda url: (fetched.append(url) or root))
        self.assertIsNone(result)
        self.assertEqual(fetched, [ORIGIN])

    def test_unlisted_detail_link_cannot_be_substituted(self):
        root = ('<a href="/agenda/another-festival-2027">'
                'Festival des Nuits de Fer 2027</a>')
        self.assertIsNone(live_index_for_exact_link(
            SOURCE, lambda url: root))

    def test_page_four_touring_concert_remains_discoverable(self):
        # A named dated tour may be on the fourth page of the municipality's
        # approved agenda. The 2-page research quota cannot be a reproof cap.
        pages = [ORIGIN + "&page=" + str(n) for n in (1, 2, 3, 4)]
        root = "<main>" + "".join(
            '<a href="?keys=festival&page=' + str(n) + '">' +
            str(n) + "</a>" for n in (1, 2, 3, 4)) + "</main>"
        detail = ('<main><a href="/agenda/festival-des-nuits-de-fer-2027">'
                  'Festival des Nuits de Fer 2027</a></main>')
        html = {ORIGIN: root, **{p: "<main>Aucun résultat pertinent</main>"
                                 for p in pages}, pages[3]: detail}
        visited = []
        def fetch(url):
            visited.append(url)
            return html[url]
        self.assertEqual(live_index_for_exact_link(SOURCE, fetch), detail)
        self.assertEqual(visited, [ORIGIN] + pages)

    def test_page_six_outside_fetch_budget_is_not_forced(self):
        root = "<main>" + "".join(
            '<a href="?keys=festival&page=' + str(n) + '">' +
            str(n) + "</a>" for n in (1, 2, 3, 4, 5, 6)) + "</main>"
        visited = []
        result = live_index_for_exact_link(
            SOURCE, lambda url: visited.append(url) or root)
        self.assertIsNone(result)
        self.assertEqual(len(visited), 6)
        self.assertEqual(visited, [ORIGIN] + [
            ORIGIN + "&page=" + str(n) for n in (1, 2, 3, 4, 5)])
        self.assertNotIn(ORIGIN + "&page=6", visited)

    def test_malformed_private_index_pages_fail_without_network(self):
        for page in ("http://sortir.limoges.fr/agenda",
                     "https://127.0.0.1/private",
                     ORIGIN + "&page=99",
                     ORIGIN + "&other=admin",
                     "https://sortir.limoges.fr/agenda?page=1"):
            spec = dict(SOURCE, index_page=page)
            with self.subTest(page=page):
                self.assertIsNone(live_index_for_exact_link(
                    spec, lambda url: self.fail("untrusted index fetch")))

    def test_fixed_fetch_budget_and_old_page_rechecks_root(self):
        spec = dict(SOURCE, index_page=PAGE)
        root = ('<a href="?keys=festival&page=2">2</a>')
        old_page = '<main>La liste a changé</main>'
        new_page = ('<a href="/agenda/festival-des-nuits-de-fer-2027">'
                    'Festival des Nuits de Fer 2027</a>')
        calls = []
        def fetch(url):
            calls.append(url)
            return {PAGE: old_page, ORIGIN: root, OTHER: new_page}[url]
        self.assertEqual(live_index_for_exact_link(spec, fetch), new_page)
        self.assertEqual(calls, [PAGE, ORIGIN, OTHER])

if __name__ == "__main__":
    unittest.main()
