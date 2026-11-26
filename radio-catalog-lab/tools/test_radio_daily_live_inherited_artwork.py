import copy
import unittest
from unittest.mock import Mock
from radio_daily_live_inherited_artwork import recover_inherited, ArtworkUnavailable
from radio_daily_v9_generator import digest
from test_radio_daily_logo_plan import DATA, OLD, URL


def doc(url=URL):
    return {"stations":[{"logo":dict(url=url, sha256=digest(DATA),
        byte_size=len(DATA), mime_type="image/png", width=128, height=128)}]}


class InheritedArtworkTests(unittest.TestCase):
    def test_exact_bytes_fetched_only_once(self):
        old = doc()
        new = copy.deepcopy(old)
        new["stations"].append(copy.deepcopy(old["stations"][0]))
        fetch = Mock(return_value=(DATA, "image/png"))
        self.assertEqual(recover_inherited(old, new, fetch=fetch), {URL:DATA})
        fetch.assert_called_once_with(URL, "radio.example.org")

    def test_changed_bytes_held(self):
        with self.assertRaises(ArtworkUnavailable):
            recover_inherited(doc(), doc(), fetch=lambda u,h:(OLD,"image/png"))

    def test_missing_predecessor_object_held_even_if_replaced(self):
        with self.assertRaises(ArtworkUnavailable):
            recover_inherited(doc(), {"stations":[]}, fetch=Mock(side_effect=OSError("down")))

    def test_wrong_mime_held(self):
        with self.assertRaises(ArtworkUnavailable):
            recover_inherited(doc(), doc(), fetch=lambda u,h:(DATA,"image/jpeg"))

    def test_inconsistent_url_descriptor_held_before_network(self):
        new = doc()
        new["stations"][0]["logo"]["sha256"] = digest(OLD)
        fetch = Mock()
        with self.assertRaises(ArtworkUnavailable):
            recover_inherited(doc(), new, fetch=fetch)
        fetch.assert_not_called()

    def test_budget_deadline_held_before_network(self):
        fetch = Mock()
        clock = Mock(side_effect=[0, 151])
        with self.assertRaises(ArtworkUnavailable):
            recover_inherited(doc(), doc(), fetch=fetch, clock=clock)
        fetch.assert_not_called()
