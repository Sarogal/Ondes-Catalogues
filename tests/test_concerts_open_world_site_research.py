"""Network-free integration checks for generic unlisted concert-site research."""
import datetime as dt
import json
import unittest

from automation.concerts import open_world_site_research as research
from automation.concerts import open_world_frontier as frontier

DAY = dt.date(2026, 11, 24)


def catalogue():
    return {"schemaVersion": 1, "events": [], "artists": [], "venues": []}


def queue(venue=True, artist=False):
    return {
        "schema": frontier.SCHEMA, "publicationAllowed": False,
        "venueResearch": ([{
            "name": "New Room", "city": "Lyon", "department": "69",
            "key": "venue:unlisted", "researchOnly": True,
            "firstSeen": "private_lead",
        }] if venue else []),
        "artistResearch": ([{
            "name": "New Act", "key": "artist:unlisted",
            "researchOnly": True, "firstSeen": "private_lead",
        }] if artist else []),
    }


def registry(leads):
    return {"schema": "grossesondes.concert.intake.v1",
            "items": {str(i): {
                "status": "pending_review", "candidate": lead,
            } for i, lead in enumerate(leads)}}


def lead(source="agenda_officiel_structuré",
         source_page="https://newroom.example.org/agenda"):
    return {
        "source": source, "sourcePage": source_page, "sourceUrl": source_page,
        "date": "2027-03-12", "venue": "New Room", "city": "Lyon",
        "department": "69", "name": "New Act", "leadArtist": "New Act",
        "publicationAllowed": False, "reviewRequired": True,
    }


def music_event(url, room="New Room", artist="New Act", city="Lyon"):
    return json.dumps({
        "@context": "https://schema.org", "@type": "MusicEvent",
        "url": url, "name": artist + " live", "startDate": "2027-03-12",
        "genre": ["Thrash Metal"],
        "performer": [{"@type": "MusicGroup", "name": artist}],
        "location": {
            "@type": "Place", "name": room,
            "address": {"@type": "PostalAddress",
                        "addressLocality": city, "addressCountry": "FR",
                        "postalCode": "69001"},
        },
    })


class OpenWorldSiteResearchTests(unittest.TestCase):
    def test_unlisted_venue_produces_structured_lead_without_host_manifest(self):
        url = "https://newroom.example.org/agenda"
        html = '<script type="application/ld+json">' + music_event(url) + '</script>'
        calls = []
        def fetch(request, cache):
            calls.append(request)
            self.assertEqual(request, url)
            return html
        result = research.scan(
            catalogue(), registry([lead()]), queue(), DAY,
            max_details=1, fetch=fetch)
        self.assertEqual(calls, [url])
        self.assertEqual(result["sitesConsidered"], 1)
        self.assertEqual(len(result["candidates"]), 1)
        found = result["candidates"][0]
        self.assertEqual(found["leadArtist"], "New Act")
        self.assertEqual(found["venue"], "New Room")
        self.assertIsNone(found["venueCatalogueId"])
        self.assertFalse(found["publicationAllowed"])
        self.assertFalse(found["sourceAuthorityVerified"])
        self.assertTrue(found["reviewRequired"])

    def test_unknown_artist_tour_reveals_another_city_and_venue(self):
        url = "https://newact.example.org/tour"
        page = '<script type="application/ld+json">' + music_event(
            url, room="Fresh Hall", city="Nantes") + '</script>'
        candidate = lead("artist_official_tour", url)
        result = research.scan(
            catalogue(), registry([candidate]),
            queue(venue=False, artist=True), DAY,
            max_details=1, fetch=lambda req, cache: page)
        self.assertEqual(len(result["candidates"]), 1)
        row = result["candidates"][0]
        self.assertEqual(row["venue"], "Fresh Hall")
        self.assertEqual(row["city"], "Nantes")
        self.assertTrue(row["newVenueToReview"])
        self.assertEqual(row["source"], "open_world_artist_tour_research")
        self.assertFalse(row["sourceAuthorityVerified"])
        self.assertFalse(row["publicationAllowed"])

    def test_untrusted_aggregators_unsafe_urls_and_nonmatching_rooms_are_ignored(self):
        mixed = [
            lead(source_page="http://169.254.169.254/latest"),
            lead(source_page="https://openagenda.com/agenda"),
            lead(source_page="https://newroom.example.org/agenda"),
            dict(lead(source_page="https://bad.example.org/"),
                 venue="Other Room"),
            dict(lead(source_page="https://newroom.example.org/"),
                 date="2025-02-01"),
        ]
        selected = research.select_sources(queue(), registry(mixed), DAY)
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["url"],
                         "https://newroom.example.org/agenda")
        self.assertFalse(selected[0]["claimedOfficial"])

    def test_venue_link_navigation_does_not_cross_host(self):
        homepage = "https://newroom.example.org/agenda"
        detail = "https://newroom.example.org/events/new-act"
        pages = {
            homepage: '<a href="/events/new-act">Concert</a>'
                      '<a href="https://evil.example.net/x">No</a>',
            detail: '<script type="application/ld+json">' +
                    music_event(detail) + '</script>',
        }
        calls = []
        def fetch(url, cache):
            calls.append(url)
            return pages[url]
        out = research.scan(
            catalogue(), registry([lead()]), queue(), DAY,
            max_details=2, fetch=fetch)
        self.assertIn(detail, calls)
        self.assertEqual(set(calls), {homepage, detail})
        self.assertEqual(len(out["candidates"]), 1)

    def test_unverified_html_visible_bill_is_review_only(self):
        url = "https://newroom.example.org/agenda"
        page = ('<h1>New Act</h1><strong>12 mars 2027</strong>'
                '<p>New Room, Lyon</p>'
                '<h4>► New Act – Thrash Metal</h4>')
        out = research.scan(
            catalogue(), registry([lead()]), queue(), DAY,
            max_details=1, fetch=lambda u, c: page)
        self.assertEqual(len(out["candidates"]), 1)
        row = out["candidates"][0]
        self.assertEqual(row["source"], "open_world_visible_research")
        self.assertEqual(row["officialArtistNames"], ["New Act"])
        self.assertFalse(row["sourceAuthorityVerified"])
        self.assertFalse(row["publicationAllowed"])

    def test_invalid_or_fake_frontier_cannot_approve_a_source(self):
        q = queue()
        q["publicationAllowed"] = True
        with self.assertRaises(ValueError):
            research.select_sources(q, registry([lead()]), DAY)
        self.assertIsNone(research.safe_page(
            "https://127.0.0.1/admin"))
        self.assertIsNone(research.safe_page(
            "https://room.example.org:8443/show"))
        self.assertIsNone(research.safe_page(
            "https://room.example.org/show#fragment"))


if __name__ == "__main__":
    unittest.main()
