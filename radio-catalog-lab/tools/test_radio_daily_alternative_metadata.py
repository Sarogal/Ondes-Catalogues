import unittest
from radio_daily_alternative_metadata import (
    advertised_endpoints, json_hints, observe_alternative, page_hints, Page, embedded_hints,
)
from radio_daily_qualification_dossiers import safe_digest

STREAM = "https://radio.example.org:8443/metal"
OTHER = "https://radio.example.org:8443/pop"
HOME = "https://station.example.org/"
API = "https://radio.example.org:8443/status-json.xsl"
STATION = {"name": "Metal Example", "homepage": HOME}


def page(html):
    p = Page()
    p.feed(html)
    return p


class AlternativeMetadataTests(unittest.TestCase):
    def test_icecast_exact_mount_not_other_station(self):
        data = {"icestats": {"source": [
            {"listenurl": OTHER, "title": "Pop Band - Other Song"},
            {"listenurl": STREAM, "title": "AC/DC - Thunderstruck"},
        ]}}
        hints = json_hints(data, STREAM, API)
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]["artistHint"], "AC/DC")
        self.assertEqual(hints[0]["titleSha256"], safe_digest("Thunderstruck"))
        self.assertEqual(hints[0]["method"], "icecast_json")

    def test_single_source_separate_artist_title(self):
        data = {"icestats": {"source": {"listenurl": STREAM, "artist": "A & B", "title": "Song - Live"}}}
        self.assertEqual(json_hints(data, STREAM, API)[0]["titleHint"], "Song - Live")

    def test_missing_or_ambiguous_mount_rejected(self):
        for rows in ([{"listenurl": OTHER, "title": "Band - Song"}],
                     [{"title": "Band - Song"}],
                     [{"listenurl": STREAM, "title": "Band - Song"}]*2):
            self.assertEqual(json_hints({"icestats": {"source": rows}}, STREAM, API), [])

    def test_shoutcast_requires_exact_stream_identity(self):
        for url in (OTHER, HOME, None):
            self.assertEqual(json_hints({"streamurl": url, "songtitle": "Band - Song"}, STREAM, API), [])
        self.assertEqual(json_hints({"streamurl": STREAM, "songtitle": "Band - Song"}, STREAM, API)[0]["method"],
                         "shoutcast_json")

    def test_links_are_declared_https_same_stream_origin_only(self):
        html = f'<a href="{API}">status</a><a href="https://other.example.org/status-json.xsl">wrong</a>'
        html += '<a href="http://radio.example.org:8443/status-json.xsl">insecure</a>'
        html += '<a href="https://radio.example.org:8443/stats?token=secret">secret</a>'
        html += '<a href="https://127.0.0.1/status-json.xsl">local</a>'
        self.assertEqual(advertised_endpoints(page(html), HOME, STREAM), [API])

    def test_no_guessed_api(self):
        self.assertEqual(observe_alternative(STREAM, STATION, fetch_page=lambda u: (u, b"<h1>Radio</h1>"),
                                           fetch_api=lambda u: self.fail("guessed URL")), [])

    def test_advertised_api_and_source_digest(self):
        result = observe_alternative(STREAM, STATION,
            fetch_page=lambda u: (u, f'<a href="{API}">status</a>'.encode()),
            fetch_api=lambda u: {"icestats": {"source": {"listenurl": STREAM, "title": "Band - Song"}}})
        self.assertEqual(result[0]["sourceSha256"], safe_digest(API))

    def test_jsonld_requires_typed_exact_station_and_stream(self):
        import json
        node = {"@type": "RadioStation", "name": STATION["name"], "streamUrl": STREAM,
                "nowPlaying": {"byArtist": {"name": "Band"}, "name": "Song"}}
        def inspect(value):
            return page_hints(page('<script type="application/ld+json">'+json.dumps(value)+'</script>'),
                              STATION["name"], STREAM, HOME)
        self.assertEqual(inspect(node)[0]["method"], "station_jsonld")
        for change in ({"streamUrl": OTHER}, {"name": "Other Station"}, {"@type": "MusicRecording"}):
            self.assertEqual(inspect(dict(node, **change)), [])
        self.assertEqual(inspect([node, node]), [])

    def test_network_failure_is_no_hint(self):
        def unavailable(url):
            raise TimeoutError()
        self.assertEqual(observe_alternative(STREAM, STATION, fetch_page=unavailable), [])

    def test_unparseable_or_unsafe_metadata(self):
        for title in ("Radio slogan", "Band - https://example.org", "Band - A - B"):
            self.assertEqual(json_hints({"icestats": {"source": {"listenurl": STREAM, "title": title}}}, STREAM, API), [])



    def test_generic_now_playing_multi_station(self):
        data = [
            {"station": {"listen_url": OTHER}, "now_playing": {"song": {"artist": "Pop Band", "title": "Other"}}},
            {"station": {"listen_url": STREAM}, "now_playing": {"song": {"artist": "A & B", "title": "Metal Song"}}},
        ]
        hints = json_hints(data, STREAM, API)
        self.assertEqual(hints[0]["artistHint"], "A & B")
        self.assertEqual(hints[0]["method"], "station_now_playing_json")
        self.assertEqual(json_hints(data + [data[1]], STREAM, API), [])

    def test_generic_never_joins_siblings_or_history(self):
        for data in (
            {"stations": [{"streamUrl": STREAM}, {"nowPlaying": {"artist": "Band", "title": "Song"}}]},
            {"streamUrl": STREAM, "song_history": [{"song": {"artist": "Band", "title": "Song"}}]},
            {"station": {"listen_url": OTHER}, "now_playing": {"song": {"artist": "Band", "title": "Song"}}},
            {"streamUrl": STREAM, "nowPlaying": {"artist": "Band", "title": "Song"},
             "currentTrack": {"artist": "Other", "title": "Other"}},
        ):
            self.assertEqual(json_hints(data, STREAM, API), [])

    def test_homepage_origin_api_requires_exact_stream(self):
        url = HOME + "api/nowplaying/metal"
        html = f'<a href="{url}">Now playing</a>'
        self.assertEqual(advertised_endpoints(page(html), HOME, STREAM), [url])
        result = observe_alternative(STREAM, STATION, fetch_page=lambda u: (u, html.encode()),
            fetch_api=lambda u: {"station": {"listen_url": STREAM},
                "now_playing": {"song": {"artist": "Band", "title": "Song"}}})
        self.assertEqual(result[0]["sourceSha256"], safe_digest(url))

    def test_embedded_json_never_executes_scripts(self):
        import json
        data = {"props": {"pageProps": {"stations": [{"streamUrl": STREAM,
                    "currentTrack": {"artist": "Band", "title": "Song"}}]}}}
        payload = json.dumps(data)
        result = embedded_hints(f'<script type="application/json">{payload}</script>'.encode(), STREAM, HOME)
        self.assertEqual(result[0]["method"], "station_embedded_json")
        self.assertEqual(embedded_hints(f'<script>var state={payload}</script>'.encode(), STREAM, HOME), [])

    def test_scoped_html_only(self):
        html = f'<div data-stream-url="{STREAM}" data-now-playing-artist="Band" data-now-playing-title="Song"></div>'
        self.assertEqual(embedded_hints(html.encode(), STREAM, HOME)[0]["method"], "station_html")
        self.assertEqual(embedded_hints(html.replace(STREAM, OTHER).encode(), STREAM, HOME), [])
        self.assertEqual(embedded_hints(b'<div data-now-playing-artist="Band" data-now-playing-title="Song"></div>', STREAM, HOME), [])

    def test_conflicting_embedded_observations_are_ambiguous(self):
        html = f'<div data-stream-url="{STREAM}" data-now-playing-artist="Band" data-now-playing-title="Song"></div>'
        self.assertEqual(embedded_hints((html + html.replace("Song", "Different")).encode(), STREAM, HOME), [])

if __name__ == "__main__":
    unittest.main()
