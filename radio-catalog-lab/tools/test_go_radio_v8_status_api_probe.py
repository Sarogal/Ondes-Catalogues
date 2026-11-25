import unittest

from go_radio_v8_status_api_probe import icecast_records, azuracast_records, match, same_mount


class StatusApiTests(unittest.TestCase):
    def test_icecast_single_source_and_exact_mount(self):
        data = {"icestats": {"source": {"listenurl": "https://example.org/metal",
                 "artist": "Artist", "title": "Song"}}}
        rows = icecast_records(data)
        self.assertEqual(match(rows, "https://example.org/metal", "Radio")["kind"],
                         "explicit_artist_title")
        self.assertIsNone(match(rows, "https://example.org/rock", "Radio"))
        self.assertIsNone(match(rows, "https://other.example/metal", "Radio"))

    def test_icecast_combined_and_station_label(self):
        rows = icecast_records({"icestats": {"source": [
            {"listenurl": "https://example.org/a", "title": "Artist - Song"},
            {"listenurl": "https://example.org/b", "title": "Radio - Metal"}
        ]}})
        self.assertEqual(match(rows, "https://example.org/a", "Radio")["kind"],
                         "combined_title_candidate")
        self.assertIsNone(match(rows, "https://example.org/b", "Radio - Metal"))

    def test_ambiguous_mount_is_rejected(self):
        rows = icecast_records({"icestats": {"source": [
            {"listenurl": "https://example.org/a", "artist": "A", "title": "X"},
            {"listenurl": "https://example.org/a", "artist": "B", "title": "Y"}
        ]}})
        self.assertIsNone(match(rows, "https://example.org/a", "Radio"))

    def test_azuracast_online_mount(self):
        data = [{"station": {"listen_url": "https://example.org/listen/metal/radio.mp3",
                  "mounts": [{"url": "https://example.org/listen/metal/alternate.mp3"}]},
                 "is_online": True, "now_playing": {"played_at": 123, "duration": 200,
                  "song": {"artist": "Artist", "title": "Song"}}}]
        rows = azuracast_records(data)
        self.assertEqual(match(rows, "https://example.org/listen/metal/alternate.mp3", "Radio")["played_at"], 123)
        data[0]["is_online"] = False
        self.assertEqual(azuracast_records(data), [])

    def test_no_cross_origin_or_subpath(self):
        self.assertFalse(same_mount("http://example.org/metal", "https://example.org/metal"))
        self.assertFalse(same_mount("https://example.org/metal", "https://example.org/metal2"))
        self.assertFalse(same_mount("https://example.org/metal", "https://example.org:8080/metal"))
        self.assertTrue(same_mount("https://example.org/metal?x=1", "https://example.org/metal"))


if __name__ == "__main__":
    unittest.main()
