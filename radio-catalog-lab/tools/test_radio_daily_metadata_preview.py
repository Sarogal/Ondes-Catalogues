import io
import unittest
from radio_daily_continuity_preview import read_icy_titles
from radio_daily_metadata_preview import collect
from radio_daily_qualification_dossiers import safe_digest

UID="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
URL="https://radio.example.org/live"
SHA=safe_digest(URL)
DAY="2026-11-25"

def block(text):
    b=text.encode("utf-8")
    n=(len(b)+15)//16
    return b"abcd"+bytes([n])+b.ljust(n*16,b"\0")

def reports(day=DAY,url=URL):
    sha=safe_digest(url)
    common={"schemaVersion":1,"scanDate":day,"publicationAllowed":False}
    return (dict(common,candidates=[{"stationuuid":UID,"streamUrl":url}]),
            dict(common,automaticAdmissionAllowed=False,catalogChanged=False,
                 candidates=[{"stationuuid":UID,"classification":"unmapped_candidate"}]),
            dict(common,technicallyQualifiedCount=0,records=[{"stationuuid":UID,"streamSha256":sha,
                "verdict":"continuous_icy_frame_indication","technicalQualified":False,"publicationAllowed":False}]),
            dict(common,approvedCount=0,records=[{"stationuuid":UID,"streamSha256":sha,
                "decision":"advanced_candidate","approved":False,"publicationAllowed":False}]))

def sample(url):
    return {"verdict":"icy_artist_title_hint","titleHints":[{"artistHint":"Iron Band","titleSha256":safe_digest("Song")}]}

class MetadataTests(unittest.TestCase):
    def test_icy_framing_and_deduplication(self):
        data=block("StreamTitle='Iron Band - Song';")+block("StreamTitle='Iron Band - Song';")+block("StreamTitle='Other Band - Second';")
        result=read_icy_titles(io.BytesIO(data),"4",10,lambda:0)
        self.assertEqual([x["artistHint"] for x in result["titleHints"]],["Iron Band","Other Band"])
        self.assertNotIn("Song",str(result))

    def test_empty_and_malformed_blocks_not_artist(self):
        data=b"abcd\0"+block("StreamTitle='station slogan';")+block("StreamTitle='https://example.org - Song';")
        self.assertEqual(read_icy_titles(io.BytesIO(data),"4",10,lambda:0)["titleHints"],[])

    def test_invalid_interval_and_deadline(self):
        for interval in ("0","999999","-1",None):
            self.assertEqual(read_icy_titles(io.BytesIO(b""),interval,10,lambda:0)["titleHints"],[])
        self.assertEqual(read_icy_titles(io.BytesIO(block("StreamTitle='Iron Band - Song';")),"4",0,lambda:0)["titleHints"],[])

    def test_cross_day_and_backoff(self):
        first=collect(*reports(),limit=1,observe=sample)
        same=collect(*reports(),previous=first,limit=1,observe=lambda u:self.fail("same day"))
        self.assertEqual(same["attemptedCount"],0)
        second=collect(*reports("2026-11-26"),previous=first,limit=1,observe=sample)
        self.assertEqual(len(second["records"][0]["observations"]),2)
        self.assertEqual(second["approvedCount"],0)

    def test_changed_stream_never_reuses_old_hints(self):
        first=collect(*reports(),limit=1,observe=sample)
        result=collect(*reports(url=URL+"2"),previous=first,limit=1,
                       observe=lambda u:{"verdict":"metadata_not_advertised","titleHints":[]})
        self.assertEqual(result["records"][0]["observations"],[])

    def test_offline_default_and_duplicate_review(self):
        self.assertEqual(collect(*reports(),observe=lambda u:self.fail("network"))["attemptedCount"],0)
        d,r,c,q=reports()
        r["candidates"][0]["classification"]="possible_variant_or_duplicate"
        self.assertEqual(collect(d,r,c,q,limit=1,observe=lambda u:self.fail("duplicate"))["attemptedCount"],0)

if __name__=="__main__":
    unittest.main()
