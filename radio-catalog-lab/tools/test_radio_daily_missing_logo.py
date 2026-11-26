import hashlib
import json
import unittest
from radio_daily_missing_logo import build, candidates
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
            return ('<title>Iron Radio</title><meta property="og:title" content="Iron Radio"><meta property="og:image" content="'+url+'">').encode()
        r=run(og("https://radio.example.org/logo.png"))
        self.assertEqual(r["records"][0]["sourceKind"],"named_page_og_image")
        r=run(og(URL),fetch_image=lambda u,h:self.fail("cross-host OG"))
        self.assertEqual(r["counts"],{"image_held":1})

    def test_og_title_alone_cannot_confirm_identity(self):
        body=b'<meta property="og:title" content="Iron Radio"><meta property="og:image" content="https://radio.example.org/logo.png">'
        r=run(body,fetch_image=lambda u,h:self.fail("OG self corroboration"))
        self.assertEqual(r["counts"],{"no_bound_image":1})

    def test_shared_network_logo_held(self):
        body=typed()+typed(name="Another Station")
        r=run(body,fetch_image=lambda u,h:self.fail("network artwork"))
        self.assertEqual(r["counts"],{"no_bound_image":1})

    def test_distinct_day_stability_and_changed_image(self):
        r=run(typed())
        self.assertEqual(r["records"][0]["confirmationStatus"],"await_distinct_day")
        r=run(typed(),prior=r,day="2026-11-27")
        self.assertEqual(r["records"][0]["confirmationStatus"],"stable_typed_logo_review")
        self.assertEqual(r["records"][0]["logoEvidenceDates"],[DAY,"2026-11-27"])
        self.assertFalse(r["records"][0]["logoApproved"])
        r=run(typed(),prior=r,day="2026-12-04",fetch_image=lambda u,h:(b"changed bytes","image/png"))
        self.assertEqual(r["records"][0]["logoEvidenceDates"],["2026-12-04"])
        self.assertEqual(r["records"][0]["confirmationStatus"],"await_distinct_day")

    def test_typed_illustration_not_qualified(self):
        body=typed().replace(b'"logo"',b'"image"')
        r=run(body)
        self.assertEqual(r["records"][0]["confirmationStatus"],"illustration_review_only")
        self.assertEqual(r["records"][0]["logoEvidenceDates"],[])

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

    def html_logo(self, *, alt="Iron Radio logo", title="Iron Radio", player=None, extra="", src="/logo.png"):
        raw,_=setup()
        station=json.loads(raw)["stations"][0]
        url=player or station["streams"][0]["url"]
        body=('<title>'+title+'</title><img alt="'+alt+'" src="'+src+'">'
              +'<audio src="'+url+'"></audio>'+extra).encode()
        return station,body

    def test_named_visible_logo_and_registered_player(self):
        station,body=self.html_logo()
        self.assertEqual(candidates(station,PAGE,body),
                         {"https://radio.example.org/logo.png":"named_player_html_logo"})
        r=run(body)
        self.assertEqual(r["records"][0]["confirmationStatus"],"await_distinct_day")
        r=run(body,prior=r,day="2026-11-27")
        self.assertEqual(r["records"][0]["confirmationStatus"],"stable_typed_logo_review")

    def test_html_logo_rejects_unbound_player_or_generic_label(self):
        for kwargs in ({"alt":"logo"},{"title":"Network"},{"player":"https://unrelated.example.org/live"},
                       {"extra":'<audio src="https://other.example.org/live"></audio>'},
                       {"src":"https://cdn.example.org/logo.png"}):
            station,body=self.html_logo(**kwargs)
            self.assertEqual(candidates(station,PAGE,body),{})

    def test_html_logo_ambiguous_multiple_images(self):
        station,body=self.html_logo(extra='<img alt="Iron Radio logo" src="/other.png">')
        self.assertEqual(len(candidates(station,PAGE,body)),2)
        self.assertEqual(run(body,fetch_image=lambda u,h:self.fail("ambiguous"))["counts"],{"ambiguous_images":1})

    def test_html_logo_ignored_template(self):
        station,body=self.html_logo(alt="generic",extra='<template><img alt="Iron Radio logo" src="/hidden.png"></template>')
        self.assertEqual(candidates(station,PAGE,body),{})

if __name__=="__main__":
    unittest.main()
