"""Network-free regression: open-ended OSM first-party venue discovery."""
import datetime as dt
import json
import unittest

from automation.concerts import venue_osm_self_discovery as discover_osm

TODAY=dt.date(2026,11,21)
HOME="https://radio-metal-concert.fr/"
DETAIL="https://radio-metal-concert.fr/programmation/liste-des-groupes-2027"
NODE_ID="380889428"
ARTISTS=[f"Groupe de test {x}" for x in range(1,9)]


def venue():
    return {
        "id":"bikini-test", "name":"Le Bikini",
        "address":"Rue Théodore Monod",
        "city":"Ramonville-Saint-Agne","department":"31",
        "postalCode":"31520","region":"Occitanie",
        "latitude":43.54795,"longitude":1.48568,
        "geoSource":f"https://www.openstreetmap.org/node/{NODE_ID}",
        "geoPrecision":"named OSM point",
    }


def catalogue():
    return {"schemaVersion":1,"events":[],"artists":[],"venues":[venue()]}


def osm(name="Le Bikini",city="Ramonville-Saint-Agne",lat="43.54795",
        website=HOME):
    return (f'<osm version="0.6"><node id="{NODE_ID}" lat="{lat}" lon="1.48568">'
            f'<tag k="name" v="{name}"/>'
            f'<tag k="addr:city" v="{city}"/>'
            f'<tag k="addr:postcode" v="31520"/>'
            f'<tag k="addr:country" v="FR"/>'
            f'<tag k="website" v="{website}"/>'
            f'</node></osm>')


def event_page(*, music=True, date="2027-05-02", name="Nuit des métaux",
               genres=None, room="Le Bikini"):
    data={
        "@context":"https://schema.org",
        "@type":"MusicEvent" if music else "Event",
        "name":name,"url":DETAIL,"startDate":date+"T20:00:00+02:00",
        "eventStatus":"https://schema.org/EventScheduled",
        "performer":[{"@type":"MusicGroup","name":n} for n in ARTISTS],
        "location":{"@type":"Place","name":room,"address":{
            "@type":"PostalAddress","addressCountry":"FR",
            "addressLocality":"Ramonville-Saint-Agne","postalCode":"31520",
            "streetAddress":"Rue Théodore Monod"}},
        "genre":genres if genres is not None else ["Black Metal"],
    }
    return "<html><script type='application/ld+json'>"+json.dumps(data)+"</script></html>"


def fake_fetch(*,node=None,home=None,detail=None):
    replies={
        "https://api.openstreetmap.org/api/0.6/node/"+NODE_ID:
            node if node is not None else osm(),
        HOME:home if home is not None else (
            '<html><a href="/programmation/liste-des-groupes-2027">'
            'Programmation concerts 2027</a>'
            '<a href="https://evil.fr/private">Externe</a></html>'),
        DETAIL:detail if detail is not None else event_page(),
    }
    def fetch(url,cache):
        assert url in replies,"Unexpected network request: "+url
        return replies[url]
    return fetch


class OpenEndedOSMDiscoveryTests(unittest.TestCase):
    def test_unlisted_origin_eight_unknown_bands_are_quarantined(self):
        observed=[]
        fetch=fake_fetch()
        def visitor(url,cache):
            observed.append(url)
            return fetch(url,cache)
        report=discover_osm.scan(catalogue(),TODAY,max_venues=1,
                                 max_details=2,fetch=visitor)
        self.assertFalse(report["publicationAllowed"])
        self.assertFalse(report["automaticPublication"])
        self.assertEqual(sum(report["triageCounts"].values()),1)
        self.assertEqual(len(report["candidates"]),1)
        candidate=report["candidates"][0]
        self.assertTrue(candidate["newlyDiscoveredFirstPartySource"])
        self.assertFalse(candidate["sourceAuthorityVerified"])
        self.assertFalse(candidate["publicationAllowed"])
        self.assertTrue(candidate["reviewRequired"])
        self.assertEqual(candidate["sourceUrl"],DETAIL)
        self.assertEqual(candidate["classification"],["Black Metal"])
        self.assertIn("Groupe de test 8",candidate["leadArtist"])
        self.assertEqual(candidate["reviewBucket"],"genre_tag_review")
        self.assertEqual(len(observed),3)
        self.assertNotIn("https://evil.fr/private",observed)

    def test_official_agenda_then_individual_detail_with_bounded_fetches(self):
        agenda="https://radio-metal-concert.fr/agenda"
        pages={
            "https://api.openstreetmap.org/api/0.6/node/"+NODE_ID:osm(),
            HOME:'<html><a href="/agenda">Agenda officiel</a></html>',
            agenda:('<html><a href="/programmation/liste-des-groupes-2027">'
                    '<time datetime="2027-05-02">2 mai</time>'
                    'Concert métal huit artistes</a></html>'),
            DETAIL:event_page(),
        }
        calls=[]
        def fetch(url,cache):
            calls.append(url)
            if url not in pages:
                raise AssertionError("Unexpected external page: "+url)
            return pages[url]
        report=discover_osm.scan(catalogue(),TODAY,max_venues=1,
                                 max_details=2,fetch=fetch)
        self.assertEqual(len(report["candidates"]),1)
        self.assertEqual(report["sourceChecks"]["detailPagesRead"],2)
        self.assertEqual(
            calls,["https://api.openstreetmap.org/api/0.6/node/"+NODE_ID,
                   HOME,agenda,DETAIL])
        self.assertFalse(report["candidates"][0]["publicationAllowed"])

    def test_false_source_owner_and_venue_provenance_are_not_used(self):
        cases={
            "missing-website":osm(website="http://evil.fr"),
            "wrong-owner-city":osm(city="Nantes"),
            "wrong-room":osm(name="Unrelated Room"),
            "wrong-coordinates":osm(lat="44.0"),
        }
        for name,xml in cases.items():
            with self.subTest(name=name):
                report=discover_osm.scan(
                    catalogue(),TODAY,max_venues=1,max_details=2,
                    fetch=fake_fetch(node=xml))
                self.assertEqual(report["candidates"],[])
                self.assertEqual(report["sourceChecks"]["sourcesHeld"],1)

    def test_festival_nonmusic_offsite_and_past_dates_remain_held(self):
        cases={
            "festival":event_page(name="Festival des métaux 2027"),
            "nonmusic":event_page(music=False),
            "past":event_page(date="2026-01-01"),
        }
        for name,html in cases.items():
            with self.subTest(name=name):
                report=discover_osm.scan(catalogue(),TODAY,max_venues=1,
                    max_details=2,fetch=fake_fetch(detail=html))
                self.assertEqual(report["candidates"],[])
                self.assertFalse(report["publicationAllowed"])

    def test_offsite_new_venue_is_research_not_rejection_or_approval(self):
        report=discover_osm.scan(catalogue(),TODAY,max_venues=1,
                                 max_details=2,fetch=fake_fetch(
                                     detail=event_page(room="Une autre salle")))
        self.assertEqual(len(report["candidates"]),1)
        row=report["candidates"][0]
        self.assertTrue(row["venueOutsideSource"])
        self.assertTrue(row["newVenueToReview"])
        self.assertIsNone(row["venueCatalogueId"])
        self.assertEqual(row["venue"],"Une autre salle")
        self.assertFalse(row["publicationAllowed"])
        self.assertTrue(row["reviewRequired"])
        self.assertFalse(row["sourceAuthorityVerified"])

    def test_discovery_enters_private_registry_without_domain_approval(self):
        from automation.concerts import intake_archive
        from automation.concerts import source_admission_intake as admission
        catalog=catalogue()
        report=discover_osm.scan(catalog,TODAY,max_venues=1,
                                 max_details=2,fetch=fake_fetch())
        first,stats=intake_archive.merge(
            None,report,"2026-11-21T10:00:00Z")
        self.assertEqual(stats["added"],1)
        self.assertEqual(first["total"],1)
        queued=admission.build(
            first,catalog,TODAY,organizer_sources=[],reviewed_venues={})
        self.assertEqual(queued["candidateSourceHosts"],1)
        self.assertEqual(queued["previouslyUnreviewedHosts"],1)
        self.assertFalse(queued["automaticTrustGranted"])
        self.assertFalse(queued["publicationAllowed"])
        self.assertFalse(queued["reviewQueue"][0]["alreadyReviewedAuthority"])
        second,stats2=intake_archive.merge(
            first,report,"2026-11-22T09:00:00Z")
        self.assertEqual(stats2["stableReobservedOnNewDay"],1)
        followup=admission.build(
            second,catalog,TODAY,organizer_sources=[],reviewed_venues={})
        self.assertEqual(followup["stableUnreviewedSourceHosts"],1)
        self.assertFalse(followup["automaticTrustGranted"])

    def test_rotation_covers_venues_without_fixed_list(self):
        sites=[{"id":f"place-{n}"} for n in range(23)]
        visited=set()
        for day in range(8):
            for slot in range(3):
                sample=discover_osm.select(
                    sites,TODAY+dt.timedelta(days=day),slot,5)
                self.assertLessEqual(len(sample),5)
                visited.update(r["id"] for r in sample)
        self.assertEqual(visited,{r["id"] for r in sites})


if __name__=="__main__":
    unittest.main()
