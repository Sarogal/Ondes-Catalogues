import hashlib
import json
import unittest
from radio_daily_missing_logo import build, candidates, discover_page, ANALYZER_VERSION
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

    def test_failed_legacy_record_reexamined_once_same_day(self):
        prior=run(b"<title>Iron Radio</title>")
        prior["records"][0].pop("analyzerVersion")
        current=run(typed(),prior=prior)
        self.assertEqual(current["attemptedStationCount"],1)
        self.assertEqual(current["records"][0]["analyzerVersion"],ANALYZER_VERSION)
        self.assertEqual(current["records"][0]["logoEvidenceDates"],[DAY])
        self.assertEqual(run(typed(),prior=current)["attemptedStationCount"],0)

    def test_named_same_host_link_with_exact_player(self):
        station,body=self.html_logo()
        child="https://radio.example.org/station/iron"
        root=b'<a href="/station/iron">Iron Radio</a>'
        final,content,found=discover_page(station,lambda u:(u,body if u==child else root))
        self.assertEqual(final,child)
        self.assertEqual(found,{"https://radio.example.org/logo.png":"named_player_html_logo"})

    def test_alternate_typed_logo_needs_registered_player(self):
        station,_=self.html_logo()
        child="https://radio.example.org/station/iron"
        self.assertEqual(candidates(station,child,typed()),{})
        player=('<audio src="'+station["streams"][0]["url"]+'"></audio>').encode()
        self.assertEqual(candidates(station,child,typed()+player),{URL:"typed_station_logo"})

    def test_dead_station_path_recovers_from_official_root(self):
        station,body=self.html_logo()
        root="https://radio.example.org/"
        child="https://radio.example.org/station/iron"
        calls=[]
        def fetch(u):
            calls.append(u)
            if u==PAGE:
                raise ValueError("old page unavailable")
            if u==root:
                return u,b'<a href="/station/iron">Iron Radio</a>'
            self.assertEqual(u,child)
            return u,body
        final,_,found=discover_page(station,fetch)
        self.assertEqual(calls,[PAGE,root,child])
        self.assertEqual(final,child)
        self.assertEqual(found,{"https://radio.example.org/logo.png":"named_player_html_logo"})

    def test_root_fallback_cannot_accept_unbound_network_logo(self):
        station,_=self.html_logo()
        def fetch(u):
            if u==PAGE:
                raise OSError("old page unavailable")
            return u,typed()
        self.assertEqual(discover_page(station,fetch)[2],{})

    def test_already_root_failure_does_not_retry(self):
        station,_=self.html_logo()
        station["homepage"]="https://radio.example.org/"
        calls=[]
        def fetch(u):
            calls.append(u)
            raise OSError("offline")
        with self.assertRaises(OSError):
            discover_page(station,fetch)
        self.assertEqual(calls,[station["homepage"]])

    def test_expanded_station_budget_is_bounded(self):
        raw,sha=setup()
        report=build(raw,DAY,expected=sha,limit=8,fetch_page=lambda u:(PAGE,typed()),
                     fetch_image=lambda u,h:(DATA,"image/png"),decode=lambda b:("image/png",128,128))
        self.assertEqual(report["attemptedStationCount"],1)
        with self.assertRaises(ValueError):
            build(raw,DAY,expected=sha,limit=9)

    def test_alternate_structured_logo_and_exact_stream_same_node(self):
        station,_=self.html_logo()
        child="https://radio.example.org/station/iron"
        node={"@type":"RadioStation","name":"Iron Radio","logo":URL,
              "streamUrl":station["streams"][0]["url"]}
        def page(*nodes):
            return ('<script type="application/ld+json">'+json.dumps(list(nodes))+'</script>').encode()
        self.assertEqual(candidates(station,child,page(node)),{URL:"typed_station_logo"})
        node["streamUrl"]="https://wrong.example.org/stream"
        self.assertEqual(candidates(station,child,page(node)),{})

    def test_alternate_structured_stream_cannot_be_borrowed(self):
        station,_=self.html_logo()
        child="https://radio.example.org/station/iron"
        nodes=[{"@type":"RadioStation","name":"Iron Radio","logo":URL},
               {"@type":"RadioStation","name":"Other Radio","streamUrl":station["streams"][0]["url"]}]
        def page():
            return ('<script type="application/ld+json">'+json.dumps(nodes)+'</script>').encode()
        self.assertEqual(candidates(station,child,page()),{})
        nodes[1]["name"]="Iron Radio"
        self.assertEqual(candidates(station,child,page()),{})

    def test_alternate_structured_stream_conflicting_html_player_held(self):
        station,_=self.html_logo()
        child="https://radio.example.org/station/iron"
        node={"@type":"RadioStation","name":"Iron Radio","logo":URL,
              "contentUrl":station["streams"][0]["url"]}
        body=('<script type="application/ld+json">'+json.dumps(node)+'</script>'
              '<audio src="https://wrong.example.org/stream"></audio>').encode()
        self.assertEqual(candidates(station,child,body),{})

    def test_external_link_not_followed(self):
        station,_=self.html_logo()
        root=b'<a href="https://other.example.org/station/iron">Iron Radio</a>'
        def fetch(u):
            self.assertEqual(u,PAGE)
            return u,root
        self.assertEqual(discover_page(station,fetch)[2],{})

    def test_html_logo_ignored_template(self):
        station,body=self.html_logo(alt="generic",extra='<template><img alt="Iron Radio logo" src="/hidden.png"></template>')
        self.assertEqual(candidates(station,PAGE,body),{})

if __name__=="__main__":
    unittest.main()
