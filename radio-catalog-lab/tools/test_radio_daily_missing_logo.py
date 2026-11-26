import hashlib
import json
import unittest
from radio_daily_missing_logo import build
from radio_daily_v9_generator import encode
from test_radio_daily_repair_plan import fixture,PAGE

DAY="2026-11-26"
URL="https://cdn.example.org/iron.png"
DATA=b"image bytes"

def setup(synthetic=False):
    raw,*_=fixture()
    doc=json.loads(raw)
    s=doc["stations"][0]
    s["logo"]=None
    if synthetic:
        s["status"].update(state="quarantined",reason_code="synthetic_diagnostic_not_for_playback")
    raw=encode(doc)
    return raw,hashlib.sha256(raw).hexdigest()

def typed(name="Iron Radio",logo=URL):
    return ('<script type="application/ld+json">'+json.dumps({"@type":"RadioStation","name":name,"logo":logo})+'</script>').encode()

def run(body,prior=None,synthetic=False,fetch_image=lambda u,h:(DATA,"image/png"),day=DAY):
    raw,sha=setup(synthetic)
    return build(raw,day,expected=sha,prior=prior,limit=4,fetch_page=lambda u:(PAGE,body),
                 fetch_image=fetch_image,decode=lambda b:("image/png",128,128))

class MissingLogoTests(unittest.TestCase):
    def test_typed_station_cdn_digest_only(self):
        r=run(typed())
        self.assertEqual(r["counts"],{"decoded_review":1})
        self.assertEqual(r["records"][0]["sourceKind"],"typed_station_logo")
        self.assertFalse(r["records"][0]["logoApproved"])
        self.assertNotIn(URL,json.dumps(r))

    def test_other_station_and_favicon_ignored(self):
        for body in (typed(name="Another Station"),b'<title>Iron Radio</title><link rel="icon" href="/favicon.png">'):
            r=run(body,fetch_image=lambda u,h:self.fail("unbound image"))
            self.assertEqual(r["counts"],{"no_bound_image":1})

    def test_conflicting_declared_logos_held(self):
        r=run(typed(logo=[URL,"https://cdn.example.org/other.png"]),fetch_image=lambda u,h:self.fail("ambiguous"))
        self.assertEqual(r["counts"],{"ambiguous_images":1})

    def test_named_page_og_same_host_only(self):
        def og(url):
            return ('<meta property="og:title" content="Iron Radio"><meta property="og:image" content="'+url+'">').encode()
        r=run(og("https://radio.example.org/logo.png"))
        self.assertEqual(r["records"][0]["sourceKind"],"named_page_og_image")
        r=run(og(URL),fetch_image=lambda u,h:self.fail("cross-host OG"))
        self.assertEqual(r["counts"],{"image_held":1})

    def test_synthetic_never_searched(self):
        r=run(typed(),synthetic=True,fetch_image=lambda u,h:self.fail("synthetic"))
        self.assertEqual(r["attemptedStationCount"],0)
        self.assertEqual(r["counts"],{"synthetic_held":1})

    def test_query_held(self):
        r=run(typed(logo=URL+"?token=secret"),fetch_image=lambda u,h:self.fail("query"))
        self.assertEqual(r["counts"],{"image_held":1})
        self.assertNotIn("secret",json.dumps(r))

    def test_cache_and_prior_validation(self):
        r=run(typed())
        r=run(typed(),prior=r,fetch_image=lambda u,h:self.fail("same day"))
        self.assertEqual(r["attemptedStationCount"],0)
        r["records"][0]["image"]["width"]=0
        with self.assertRaises(ValueError):
            run(typed(),prior=r)

if __name__=="__main__":
    unittest.main()
