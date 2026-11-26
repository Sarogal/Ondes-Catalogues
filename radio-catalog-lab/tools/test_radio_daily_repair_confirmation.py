import json
import unittest
from radio_daily_repair_confirmation import build
from radio_daily_repair_preview import build as repair
from test_radio_daily_repair_preview import fixture,candidate,DAY,NEXT,PAGE
from radio_daily_maintenance_preview import digest

def inputs():
    raw,sha,m,d=fixture()
    r=repair(raw,m,d,expected=sha,limit=1,search=lambda n:[candidate()])
    return raw,sha,r

def page(url):
    return PAGE, ('<script type="application/ld+json">'+json.dumps({"@type":"RadioStation","name":"Iron Radio","streamUrl":NEXT})+'</script>').encode()

def audio(url):
    return {"streamSha256":digest(url),"verdict":"audio_sample_ok","frameChain":"mp3"}

def run(prior=None,fetch=page,search=lambda n:[candidate()],probe=audio,day=DAY,hls=None,continuity=None):
    raw,sha,r=inputs()
    r["scanDate"]=day
    return build(raw,r,expected=sha,prior=prior,limit=1,search=search,fetch=fetch,probe=probe,
                 hls_probe=hls,continuity_probe=continuity)

class ConfirmationTests(unittest.TestCase):
    def test_typed_broadcaster_and_two_days(self):
        r=run()
        self.assertEqual(r["counts"],{"audio_hint":1})
        r=run(prior=r,day="2026-11-27")
        self.assertEqual(r["counts"],{"repeated_audio_review":1})
        self.assertFalse(r["records"][0]["approved"])
        self.assertNotIn("secret",json.dumps(r))

    def test_same_day_no_repetition(self):
        r=run()
        r=run(prior=r,search=lambda n:self.fail("same day"))
        self.assertEqual(r["attemptedCount"],0)

    def test_changed_directory_not_probed(self):
        r=run(search=lambda n:[candidate(url_resolved="https://radio.example.org/new2")],
              probe=lambda u:self.fail("changed digest"))
        self.assertEqual(r["counts"],{"directory_changed":1})

    def test_generic_page_and_multiple_players_held(self):
        for body in (b'<h1>Iron Radio</h1>', ('<h1>Iron Radio</h1><audio src="'+NEXT+'"></audio><audio src="https://radio.example.org/other"></audio>').encode()):
            r=run(fetch=lambda p:(PAGE,body),probe=lambda u:self.fail("unbound"))
            self.assertEqual(r["counts"],{"broadcaster_unlinked":1})

    def test_exact_single_player(self):
        r=run(fetch=lambda p:(PAGE,('<h1>Iron Radio</h1><audio src="'+NEXT+'"></audio>').encode()))
        self.assertEqual(r["records"][0]["observations"][0]["declaration"],"unique_named_player")

    def test_redirect_to_different_station_held(self):
        r=run(fetch=lambda p:("https://radio.example.org/other",page(p)[1]),probe=lambda u:self.fail("redirect"))
        self.assertEqual(r["counts"],{"broadcaster_held":1})

    def test_linked_named_player_page(self):
        child="https://radio.example.org/listen"
        def fetch(p):
            if p==PAGE:
                return PAGE,b'<h1>Iron Radio</h1><a href="/listen">Listen live</a>'
            self.assertEqual(p,child)
            return child,('<h1>Iron Radio</h1><audio src="'+NEXT+'"></audio>').encode()
        r=run(fetch=fetch)
        o=r["records"][0]["observations"][0]
        self.assertEqual(o["declaration"],"linked_unique_named_player")
        self.assertIsNotNone(o["rootPageSha256"])

    def test_generic_root_cannot_follow_player(self):
        def fetch(p):
            self.assertEqual(p,PAGE)
            return PAGE,b'<h1>Radio Network</h1><a href="/listen">Listen live</a>'
        r=run(fetch=fetch,probe=lambda u:self.fail("unbound"))
        self.assertEqual(r["counts"],{"broadcaster_unlinked":1})

    def test_hls_manifest_only_and_audio_continuity(self):
        def playlist(u):return {"streamSha256":digest(u),"verdict":"playlist_pending"}
        r=run(probe=playlist,hls=lambda u:{"verdict":"advancing_hls_manifest_only"})
        self.assertEqual(r["counts"],{"inconclusive":1})
        def hls(u):return {"verdict":"advancing_hls_audio_frame_indication","frameCodec":"aac"}
        r=run(probe=playlist,hls=hls)
        r=run(prior=r,day="2026-11-27",probe=playlist,hls=hls)
        self.assertEqual(r["counts"],{"repeated_continuity_review":1})
        self.assertEqual(len(r["records"][0]["continuityDates"]),2)

    def test_direct_samples_not_continuity(self):
        r=run(continuity=lambda u:{"verdict":"continuous_icy_frame_indication"})
        r=run(prior=r,day="2026-11-27",continuity=lambda u:{"verdict":"finite_response_review"})
        self.assertEqual(r["counts"],{"repeated_audio_review":1})
        self.assertEqual(r["records"][0]["continuityDates"],[])

    def test_old_analyzer_unlinked_revisited_without_duplicate_day(self):
        r=run(fetch=lambda p:(PAGE,b'<h1>Iron Radio</h1>'))
        o=r["records"][0]["observations"][0]
        o.pop("analyzerVersion")
        r=run(prior=r)
        self.assertEqual(r["attemptedCount"],1)
        self.assertEqual(len(r["records"][0]["observations"]),1)
        self.assertEqual(r["counts"],{"audio_hint":1})

    def test_negative_breaks_positive_streak(self):
        r=run()
        r=run(prior=r,day="2026-11-27",probe=lambda u:{"streamSha256":digest(u),"verdict":"needs_review","reason":"http_not_successful"})
        self.assertEqual(r["records"][0]["positiveDates"],[])
        self.assertEqual(r["counts"],{"unavailable_hint":1})

if __name__=="__main__":
    unittest.main()
