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
