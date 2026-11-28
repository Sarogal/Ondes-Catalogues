import sys
from pathlib import Path
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from grossesondes_external_poster_review import candidates, raster_url, scan

SITE = "https://festival-exemple.fr/"
ROW = {"slug": "festival-exemple-2027", "name": "Festival Exemple 2027",
       "startDate": "2027-08-13", "endDate": "2027-08-15",
       "officialSite": SITE, "lineup": []}
CAT = {"schema": 1, "festivals": [ROW]}
URL = "https://cdn.public.fr/public/exemple-2027-infos.png?enable-io=true&enable=upscale&crop=0.75%3A1&width=800"


class ExternalRasterTests(unittest.TestCase):
    def test_only_explicit_current_visible_named_raster(self):
        self.assertTrue(raster_url(URL))
        html = '<main><img src="' + URL.replace("&", "&amp;") + '"></main>'
        self.assertEqual(candidates(html, SITE, ROW), [URL])
        for bad in (html.replace("<img", "<img hidden"), html.replace("2027", "2026"),
                    html.replace("exemple", "autre"), html.replace("cdn.public.fr", "festival-exemple.fr"),
                    html.replace("<main>", "<nav>").replace("</main>", "</nav>")):
            self.assertEqual(candidates(bad, SITE, ROW), [])
        for bad in (URL.replace("https:", "http:"), URL.replace("cdn.public.fr", "127.0.0.1"),
                    URL.replace("cdn.public.fr", "user@cdn.public.fr"), URL.replace("width=800", "width=8000"),
                    URL.replace("width=800", "url=https://other.fr/"), URL + "&width=800",
                    URL.replace("public/", "public/../"), URL.replace(".png", ".svg"), URL + "#x"):
            self.assertFalse(raster_url(bad), bad)

    def test_fresh_signed_root_and_no_publication(self):
        html = ('<main><h1>Festival Exemple 2027</h1><p>Festival Exemple du 13 au 15 août 2027</p>'
                '<img src="' + URL.replace("&", "&amp;") + '"></main>')
        read = Mock(return_value=("image/png", b"fake"))
        report = scan(CAT, "2026-11-28", fetch=lambda _: html, read=read,
                      recognize=Mock(return_value=[]))
        read.assert_called_once_with(URL)
        self.assertFalse(report["publication_authorized"])
        self.assertNotIn(URL, str(report))
        read.reset_mock()
        scan(CAT, "2026-11-28", fetch=lambda _: html.replace("août 2027", "août 2026"),
             read=read, recognize=Mock(return_value=[]))
        read.assert_not_called()
        for wrong in (html.replace("13 au 15 août", "14 au 16 août"),
                      html.replace("</main>", "<p>20 août 2027</p></main>")):
            scan(CAT, "2026-11-28", fetch=lambda _: wrong,
                 read=read, recognize=Mock(return_value=[]))
            read.assert_not_called()

    def test_root_rejections_are_visible_without_reading_images(self):
        from unittest.mock import patch
        html = ('<main><h1>Festival Exemple 2027</h1><p>Festival Exemple du 13 au 15 août 2027</p>'
                '<img src="' + URL.replace("&", "&amp;") + '"></main>')
        read = Mock()
        for fetch, expected in (
            (Mock(side_effect=OSError("private diagnostic detail")), "ROOT_UNAVAILABLE"),
            (Mock(return_value=html), "ROOT_EDITION_UNCONFIRMED"),
            (Mock(return_value=html.replace("13 au 15 août", "14 au 16 août")), "ROOT_DATES_UNCONFIRMED"),
        ):
            with self.subTest(expected=expected), patch(
                "grossesondes_external_poster_review.home_matches_edition",
                return_value=expected != "ROOT_EDITION_UNCONFIRMED"
            ):
                report = scan(CAT, "2026-11-28", fetch=fetch, read=read)
                self.assertEqual(report["rows"], [{"slug": ROW["slug"], "candidates": 0,
                                                  "outcome": expected}])
                self.assertFalse(report["publication_authorized"])
                self.assertNotIn("private diagnostic detail", str(report))
        read.assert_not_called()

    def test_exact_title_and_future_announcement(self):
        from grossesondes_external_poster_review import page, titled_future_announcement
        row = dict(ROW, name="Exemple Sonore 2027", startDate="2027-09-11",
                   endDate="2027-09-11")
        html = ("<html><head><title>Exemple Sonore</title></head><body><main>"
                "<p>Merci pour cette édition 2026. Préparez-vous pour le 11 septembre 2027 !</p>"
                "</main></body></html>")
        self.assertTrue(titled_future_announcement(html, page(html), row))
        for bad in (html.replace("Exemple Sonore", "Autre Sonore"),
                    html.replace("Exemple Sonore", "Exemple Sonore 2026"),
                    html.replace("Préparez-vous pour le", "Photos prises le"),
                    html.replace("11 septembre", "12 septembre"),
                    html.replace("<p>", "<p hidden>"),
                    html.replace("</main>", "<p>Festival annulé</p></main>")):
            self.assertFalse(titled_future_announcement(bad, page(bad), row), bad)
        from grossesondes_external_poster_review import exact_root_dates
        conflict = html.replace("</main>", "<p>12 septembre 2027</p></main>")
        self.assertFalse(exact_root_dates(page(conflict), row))
