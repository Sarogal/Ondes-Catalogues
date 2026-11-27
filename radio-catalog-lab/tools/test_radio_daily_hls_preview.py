import unittest
from radio_daily_hls_preview import parse_manifest, observe, collect, MAX_MANIFEST, MAX_SEGMENT, packed_id3
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


def sync_bytes(n):
    return bytes((n >> shift) & 127 for shift in (21,14,7,0))


def id3(frames, version=4):
    body=b""
    for name, payload in frames:
        size=sync_bytes(len(payload)) if version==4 else len(payload).to_bytes(4,"big")
        body+=name+size+b"\0\0"+payload
    return b"ID3"+bytes([version,0,0])+sync_bytes(len(body))+body


class ID3Tests(unittest.TestCase):
    def test_v23_and_v24_artist_title(self):
        for version, marker in ((3,b"\0"),(4,b"\3")):
            tag=id3([(b"TPE1",marker+b"AC/DC"),(b"TIT2",marker+b"Song")],version)
            offset,hints=packed_id3(tag+b"audio",URL)
            self.assertEqual(offset,len(tag))
            self.assertEqual(hints[0]["artistHint"],"AC/DC")
            self.assertEqual(hints[0]["titleSha256"],safe_digest("Song"))
            self.assertEqual(hints[0]["method"],"hls_packed_id3")

    def test_timestamp_only_is_not_music(self):
        tag=id3([(b"PRIV",b"com.apple.streaming.transportStreamTimestamp\0"+b"\0"*8)])
        self.assertEqual(packed_id3(tag,URL),(len(tag),[]))

    def test_truncated_and_duplicate_frames_rejected(self):
        tag=id3([(b"TPE1",b"\3Band"),(b"TIT2",b"\3Song")])
        self.assertEqual(packed_id3(tag[:-1],URL),(0,[]))
        duplicate=id3([(b"TPE1",b"\3Band"),(b"TPE1",b"\3Other"),(b"TIT2",b"\3Song")])
        self.assertEqual(packed_id3(duplicate,URL),(0,[]))
        self.assertEqual(packed_id3(b"audio"+tag,URL),(0,[]))

    def test_id3_requires_advancing_manifest_and_audio(self):
        tag=id3([(b"TPE1",b"\3Band"),(b"TIT2",b"\3Song")])
        frame=b"\xff\xfb\x90\x00"+b"\0"*413
        for audio, expected in ((frame*8,"hls_id3_artist_title_hint"),(b"not audio","hls_no_parseable_id3")):
            responses=iter([(URL,manifest(10)),(URL,manifest(11)),("https://radio.example.org/12.aac",tag+audio)])
            r=observe(URL,fetch=lambda u,n:next(responses),sleep=lambda s:None,metadata=True)
            self.assertEqual(r["verdict"],expected)
            self.assertEqual(bool(r["titleHints"]),bool(audio==frame*8))
        responses=iter([(URL,manifest(10)),(URL,manifest(10))])
        r=observe(URL,fetch=lambda u,n:next(responses),sleep=lambda s:None,metadata=True)
        self.assertNotIn("titleHints",r)

if __name__=="__main__":
    unittest.main()
