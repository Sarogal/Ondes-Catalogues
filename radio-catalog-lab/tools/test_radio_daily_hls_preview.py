import unittest
from radio_daily_hls_preview import parse_manifest, observe, collect, MAX_MANIFEST, MAX_SEGMENT
from radio_daily_qualification_dossiers import safe_digest

URL="https://radio.example.org/live.m3u8"
A="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
DAY="2026-11-25"


def manifest(seq=10,end=False):
    return (f"#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXT-X-MEDIA-SEQUENCE:{seq}\n"
            f"#EXTINF:4,\n{seq}.aac\n#EXTINF:4,\n{seq+1}.aac\n"+("#EXT-X-ENDLIST\n" if end else "")).encode()


class HLSTests(unittest.TestCase):
    def test_media_and_vod(self):
        self.assertEqual(parse_manifest(manifest(),URL)["sequence"],10)
        self.assertTrue(parse_manifest(manifest(end=True),URL)["finite"])

    def test_ordinary_playlist(self):
        self.assertEqual(parse_manifest(b"#EXTM3U\nhttps://radio.example.org/live\n",URL)["kind"],"ordinary_playlist")

    def test_prefer_audio_variant(self):
        body=b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=100000,CODECS="avc1.4d,mp4a.40.2"\nvideo.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=64000,CODECS="mp4a.40.2"\naudio.m3u8\n'
        self.assertEqual(parse_manifest(body,URL)["variant"],"https://radio.example.org/audio.m3u8")

    def test_no_downgrade_or_private_target(self):
        for target in ("http://radio.example.org/a","https://127.0.0.1/a"):
            body=b"#EXTM3U\n#EXT-X-TARGETDURATION:4\n#EXTINF:4,\n"+target.encode()
            with self.assertRaises(ValueError):
                parse_manifest(body,URL)

    def test_unsupported_key_map_or_range(self):
        for tag in ('#EXT-X-KEY:METHOD=AES-128,URI="key"', '#EXT-X-MAP:URI="init"', '#EXT-X-BYTERANGE:100@0'):
            self.assertEqual(parse_manifest(manifest()+tag.encode(),URL)["kind"],"unsupported_hls_features")

    def test_advancing_with_audio_frames(self):
        frame=b"\xff\xfb\x90\x00"+b"\0"*413
        responses=iter([(URL,manifest(10)),(URL,manifest(11)),("https://radio.example.org/12.aac",frame*9)])
        calls=[]
        def fetch(url,cap):
            calls.append((url,cap))
            return next(responses)
        result=observe(URL,fetch=fetch,sleep=lambda s:None)
        self.assertEqual(result["verdict"],"advancing_hls_audio_frame_indication")
        self.assertEqual(calls[-1][1],MAX_SEGMENT)

    def test_uri_churn_without_sequence_progress_not_live(self):
        responses=iter([(URL,manifest()),(URL,manifest().replace(b".aac",b".aac?token=new"))])
        self.assertEqual(observe(URL,fetch=lambda u,n:next(responses),sleep=lambda s:None)["verdict"],"manifest_not_advanced")

    def test_vod_never_fetches_segments(self):
        calls=[]
        def fetch(u,n):
            calls.append(u)
            return u,manifest(end=True)
        self.assertEqual(observe(URL,fetch=fetch,sleep=lambda s:self.fail("sleep"))["verdict"],"finite_hls_review")
        self.assertEqual(len(calls),1)

    def test_collect_cache_and_no_approval(self):
        d={"schemaVersion":1,"scanDate":DAY,"publicationAllowed":False,
           "candidates":[{"stationuuid":A,"streamUrl":URL}]}
        r={"schemaVersion":1,"scanDate":DAY,"automaticAdmissionAllowed":False,"catalogChanged":False,
           "candidates":[{"stationuuid":A,"classification":"unmapped_candidate"}]}
        a={"schemaVersion":1,"observationDate":DAY,"publicationAllowed":False,"technicallyQualifiedCount":0,
           "records":[{"stationuuid":A,"streamSha256":safe_digest(URL),"lastVerdict":"playlist_pending",
                       "technicalQualified":False,"publicationAllowed":False}]}
        first=collect(d,r,a,limit=1,probe=lambda u:{"verdict":"advancing_hls_manifest_only"})
        self.assertEqual(first["advancingManifestCount"],1)
        self.assertEqual(first["technicallyQualifiedCount"],0)
        second=collect(d,r,a,previous=first,limit=1,probe=lambda u:self.fail("cache"))
        self.assertEqual(second["attemptedCount"],0)

if __name__=="__main__":
    unittest.main()
