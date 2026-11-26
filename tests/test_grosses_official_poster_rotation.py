import sys
from pathlib import Path
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from grossesondes_official_poster_rotation import scan

SITE = "https://festival-exemple.fr/"
ROW = {"slug": "festival-exemple-2027", "name": "Festival Exemple 2027",
       "startDate": "2027-08-13", "endDate": "2027-08-15",
       "officialSite": SITE, "lineup": []}
CAT = {"schema": 1, "festivals": [ROW]}
HTML = '<main><img src="/exemple-2027.jpg"><img src="/poster-2027.jpg"><img src="/affiche-2027.jpg"></main>'


class RotationTests(unittest.TestCase):
    def test_only_discovered_same_host_and_bounded_no_publish(self):
        from copy import deepcopy
        original = deepcopy(CAT)
        reader = Mock(return_value={"status": "review_only", "review_only": True, "words": []})
        report = scan(CAT, "2026-11-26", tick=0, fetch=lambda _: HTML, reader=reader)
        self.assertEqual(report["images_read"], 2)
        self.assertTrue(all(call.args[0] == SITE and call.args[1].startswith(SITE)
                            for call in reader.call_args_list))
        self.assertFalse(report["publication_authorized"])
        self.assertEqual(CAT, original)

    def test_rate_limit_stops_remaining_images_on_host(self):
        reader = Mock(return_value={"status": "rate_limited"})
        report = scan(CAT, "2026-11-26", tick=0, fetch=lambda _: HTML, reader=reader)
        self.assertEqual(report["images_read"], 1)
        reader.assert_called_once()

    def test_unknown_slug_or_external_img_never_read(self):
        reader = Mock()
        fetch = Mock(return_value='<main><img src="https://external.fr/poster-2027.jpg"></main>')
        scan(CAT, "2026-11-26", slug="unknown", fetch=fetch, reader=reader)
        fetch.assert_not_called()
        scan(CAT, "2026-11-26", slug=ROW["slug"], fetch=fetch, reader=reader)
        reader.assert_not_called()
