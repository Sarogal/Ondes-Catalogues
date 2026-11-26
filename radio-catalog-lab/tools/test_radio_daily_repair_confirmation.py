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

def run(prior=None,fetch=page,search=lambda n:[candidate()],probe=audio,day=DAY):
    raw,sha,r=inputs()
    r["scanDate"]=day
    return build(raw,r,expected=sha,prior=prior,limit=1,search=search,fetch=fetch,probe=probe)

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

    def test_negative_breaks_positive_streak(self):
        r=run()
        r=run(prior=r,day="2026-11-27",probe=lambda u:{"streamSha256":digest(u),"verdict":"needs_review","reason":"http_not_successful"})
        self.assertEqual(r["records"][0]["positiveDates"],[])
        self.assertEqual(r["counts"],{"unavailable_hint":1})

if __name__=="__main__":
    unittest.main()
