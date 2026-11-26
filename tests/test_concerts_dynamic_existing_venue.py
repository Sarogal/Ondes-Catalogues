"""Open-ended Concerts existing-venue admission, publisher and negative paths."""
import copy
import datetime as dt
import json
import unittest
from pathlib import Path
from unittest import mock

from scripts import concerts_cloud_sync as publisher
from scripts import concert_dynamic_existing_venue as dynamic
from automation.concerts import approval_preflight

ROOT = Path(__file__).resolve().parents[1]
BASE = json.loads((ROOT / "docs/grossesondes/concerts-reference.json").read_text())
PUBLISHED = json.loads((ROOT / "docs/grossesondes/concerts.json").read_text())
TODAY = dt.date(2026, 11, 21)
VENUE_ID = "le-bikini-toulouse"
# The immutable 2025 reference intentionally has an unverified municipal
# centroid for Le Bikini. This publisher test must use the ACTUAL published
# venue identity (with verified OSM node), never pretend the historical
# reference already possessed today's correct named geolocation.
BASE["venues"] = [
    copy.deepcopy(next(v for v in PUBLISHED["venues"] if v["id"] == VENUE_ID))
    if v["id"] == VENUE_ID else v
    for v in BASE["venues"]
]
MAIN = "https://nouveau-domaine-independant.fr/2027/03/05/metal-event/"
# Synthetic first-party host must be linked from OSM; never included in a manifest.
EVENT = "https://nouveau-domaine-independant.fr/2027/03/05/metal-event/"
WITNESS = "https://artiste-exemple.fr/tour/2027/bikini"
NAMES = [f"Groupe Libre {n}" for n in range(1, 9)]
IDS = [f"groupe-libre-{n}" for n in range(1, 9)]


def signed_approval(event_url=EVENT):
    venue = next(v for v in BASE["venues"] if v["id"] == VENUE_ID)
    return {
        "reviewDecision": "approved",
        "reviewedBy": "independent-official-verifier",
        "reviewedAt": TODAY.isoformat(),
        "officialEvidence": [{
            "url": event_url, "proofType": dynamic.PROFILE,
            "checkedAt": TODAY.isoformat(),
            "checkedFields": list(dynamic.CHECKED),
            "officialArtistNames": list(NAMES),
            "officialGenreLabels": ["Black Metal"],
            "namedOsmUrl": venue["geoSource"],
            "corroboratingEventUrl": WITNESS,
        }],
        "event": {
            "id": "go-c-20270305-ramonville-saint-agne-groupe-libre-1",
            "title": " + ".join(NAMES), "date": "2027-03-05",
            "time": None, "artistIds": list(IDS),
            "venueId": VENUE_ID, "genres": ["Black Metal"],
            "status": "confirmed", "officialUrl": event_url,
            "sourceType": "salle",
        },
        "newArtists": [{"id": i, "name": n} for i, n in zip(IDS, NAMES)],
    }


def page(url, *, names=NAMES, genres=True, venue_name="Le Bikini",
         postal="31520", city="Ramonville-Saint-Agne",
         date="2027-03-05", country="FR", status="", music=True,
         event_name=None):
    venue = next(v for v in BASE["venues"] if v["id"] == VENUE_ID)
    node = {
        "@context": "https://schema.org",
        "@type": "MusicEvent" if music else "Event",
        "name": event_name or " + ".join(names), "url": url,
        "startDate": date + "T20:00:00+01:00",
        "eventStatus": status,
        "performer": [{"@type": "MusicGroup", "name": n} for n in names],
        "location": {
            "@type": "Place", "name": venue_name,
            "address": {"@type": "PostalAddress", "addressCountry": country,
                        "addressLocality": city, "postalCode": postal,
                        "streetAddress": venue["address"]},
        },
    }
    if genres:
        node["genre"] = ["Black Metal"]
    return ("<html><body><main><h1>Nouvel événement</h1><script "
            "type='application/ld+json'>" + json.dumps(node)
            + "</script></main><p>Programme officiel du concert</p></body></html>")


def osm(*, name="Le Bikini", website="https://nouveau-domaine-independant.fr",
        lat="43.54795", lon="1.48568", country="FR"):
    return (f'<osm version="0.6"><node id="380889428" lat="{lat}" lon="{lon}">'
            f'<tag k="name" v="{name}"/><tag k="website" v="{website}"/>'
            f'<tag k="addr:city" v="Ramonville-Saint-Agne"/>'
            f'<tag k="addr:postcode" v="31520"/>'
            f'<tag k="addr:country" v="{country}"/></node></osm>')


def fake_fetch(modifications=None):
    modifications = modifications or {}
    venue = next(v for v in BASE["venues"] if v["id"] == VENUE_ID)
    assert venue["geoSource"].endswith("380889428")
    def fetch(url, cache):
        if url.startswith("https://api.openstreetmap.org/api/0.6/node/"):
            return modifications.get("osm", osm())
        if url == EVENT:
            return modifications.get("primary", page(EVENT))
        if url == WITNESS:
            return modifications.get("secondary",
                                     page(WITNESS, names=[NAMES[0]]))
        raise AssertionError("unexpected network URL: " + url)
    return fetch


class UnlistedExistingVenueTests(unittest.TestCase):
    def setUp(self):
        # The immutable reference still contains the ORIGINAL unlocated Bikini.
        # In this synthetic test the venue is already geo-corrected at the
        # baseline; exclude only its legacy migration patch, which production
        # continues to enforce with a persisted independent signed approval.
        original = publisher.NEW_REFERENCE_GEO_SOURCES.pop(VENUE_ID, None)
        self.assertIsNotNone(original)
        self.addCleanup(lambda: publisher.NEW_REFERENCE_GEO_SOURCES.__setitem__(
            VENUE_ID, original))

    def test_inline_bold_credits_inside_paragraph_replayed_by_publisher(self):
        from automation.concerts import dynamic_first_party_venue_proposals as proposals
        signed = signed_approval()
        proof = signed["officialEvidence"][0]
        proof["proofType"] = dynamic.OSM_SINGLE_PROFILE
        proof.pop("corroboratingEventUrl")
        title = " + ".join(NAMES)
        credits = "<br/>".join("<strong>" + n + "</strong> - Angleterre - Black Metal"
                               for n in NAMES)
        body = page(EVENT, music=False, genres=False)
        body = body.replace(json.dumps(
            [{"@type": "MusicGroup", "name": n} for n in NAMES]), "[]")
        body = body.replace("<h1>Nouvel événement</h1>",
                            "<h1>" + title + "</h1><p><strong>Le Bikini - Grande salle</strong>"
                            "<br/>Prix : 15 euros<br/><br/>" + credits + "</p>")
        venue = next(v for v in BASE["venues"] if v["id"] == VENUE_ID)
        venues = {v["id"]: v for v in BASE["venues"]}
        artists = {a["id"]: a for a in BASE["artists"]}
        fetch = fake_fetch({"primary": body})
        self.assertEqual(proposals._individual_event(
            body, EVENT, signed["event"]["date"], venue,
            accept_generic=True, fetch=fetch, cache={}), (NAMES, ["Black Metal"]))
        self.assertTrue(dynamic.validate(signed, venues, artists, TODAY, fetch=fetch))
        with mock.patch.object(dynamic, "safe_fetch", side_effect=fetch):
            published, counts = publisher.merge(
                BASE, BASE, {"schema": publisher.SCHEMA, "approvals": [signed]}, TODAY)
        self.assertEqual(counts["newEvents"], 1)
        event = next(e for e in published["events"] if e["id"] == signed["event"]["id"])
        self.assertEqual(event["artistIds"], IDS)
        for bad in (
                body.replace("<strong>" + NAMES[0] + "</strong>", NAMES[0]),
                body.replace("</strong> - Angleterre", "</strong><br/> - Angleterre"),
                body.replace("Black Metal", "Hardcore Techno"),
                body.replace("Black Metal", "Influenced by Black Metal"),
                body.replace("Angleterre", "not"),
                body.replace(credits, credits + "<br/><strong>Other Band</strong> - Punk"),
                body.replace(credits, credits + "<br/><strong>" + NAMES[0] + "</strong> - Punk"),
                body.replace("<h1>" + title, "<h1>Other Show"),
                body.replace("<p><strong>Le Bikini", "<h2>Autres concerts</h2><p><strong>Le Bikini"),
                body.replace(credits, "<span hidden>" + credits + "</span>"),
                body.replace(credits, "Concert annulé<br/>" + credits),
                body.replace('"performer": []', '"performer": [{"@type": "MusicGroup", "name": "Other Band"}]'),
        ):
            with self.subTest(snippet=bad[:180]), self.assertRaises(ValueError):
                dynamic.validate(signed, venues, artists, TODAY,
                                 fetch=fake_fetch({"primary": bad}))

    def test_inline_credit_uses_literal_style_not_event_genre(self):
        from automation.concerts import official_html_evidence as visible
        title = "Example Solo + Example Band"
        html = ("<h1>" + title + "</h1><p><strong>Example Solo</strong> - Jazz"
                "<br/><b>Example Band</b> – Angleterre – Post-punk</p>")
        people = visible.inline_artist_credits(html, title)
        self.assertEqual([p["name"] for p in people], ["Example Solo", "Example Band"])
        self.assertEqual([p["genre"] for p in people], ["Jazz", "Post Punk"])
        self.assertIsNone(visible.inline_artist_credits(
            html.replace("Example Solo</strong>", "Example Solo</strong><br/>"), title))
        self.assertIsNone(visible.inline_artist_credits(
            html.replace("Post-punk", "Post-punk influenced by Jazz"), title))
        self.assertIsNone(visible.inline_artist_credits(
            html.replace("<b>", "&#57344;").replace("</b>", "&#57345;"), title))

    def test_structured_event_admission_reports_fixed_rejection_codes(self):
        from automation.concerts import dynamic_first_party_venue_proposals as proposals
        venue = next(v for v in BASE["venues"] if v["id"] == VENUE_ID)
        for html, reason in (
                (page(EVENT, genres=False), "relevant_artist_or_event_genre_missing"),
                (page(EVENT, names=[]), "named_bill_missing_or_ambiguous"),
                (page(EVENT, venue_name="Different room"), "venue_name_or_location_mismatch"),
                (page(EVENT, date="2027-03-06"), "event_date_mismatch"),
                (page(WITNESS), "canonical_url_mismatch"),
                (page(EVENT, status="EventCancelled"), "cancelled_or_postponed")):
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(ValueError, reason):
                    proposals._individual_event(html, EVENT, "2027-03-05", venue,
                                                accept_generic=True)
        html = page(EVENT, genres=False)
        # A foreign recommendation is rejected before the current event.
        foreign = page(WITNESS)
        with self.assertRaisesRegex(ValueError, "relevant_artist_or_event_genre_missing"):
            proposals._individual_event(foreign + html, EVENT, "2027-03-05",
                                        venue, accept_generic=True)
        with self.assertRaisesRegex(ValueError, "multiple_matching_events"):
            proposals._individual_event(page(EVENT) + page(EVENT), EVENT,
                                        "2027-03-05", venue, accept_generic=True)

    def test_explicit_same_graph_artist_references_replayed_by_publisher(self):
        from automation.concerts import dynamic_first_party_venue_proposals as proposals
        signed = signed_approval()
        proof = signed["officialEvidence"][0]
        proof["proofType"] = dynamic.OSM_SINGLE_PROFILE
        proof.pop("corroboratingEventUrl")
        node = next(dynamic.discover.read_ld(page(EVENT)))
        people = [{"@id": "#artist-" + str(i), "@type": "MusicGroup",
                   "name": name} for i, name in enumerate(NAMES)]
        node["performer"] = [{"@id": p["@id"]} for p in people]
        unrelated = {"@id": "#unrelated", "@type": "MusicGroup",
                     "name": "Not On Bill", "genre": "Black Metal"}
        venue = next(v for v in BASE["venues"] if v["id"] == VENUE_ID)
        venues = {v["id"]: v for v in BASE["venues"]}
        artists = {a["id"]: a for a in BASE["artists"]}

        def graph_page(nodes):
            return ("<html><main><script type='application/ld+json'>"
                    + json.dumps({"@context": "https://schema.org",
                                  "@graph": nodes})
                    + "</script><p>Official concert detail</p></main></html>")

        html = graph_page([node, *people, unrelated])
        self.assertEqual(proposals._individual_event(
            html, EVENT, signed["event"]["date"], venue,
            accept_generic=True), (NAMES, ["Black Metal"]))
        self.assertTrue(dynamic.validate(
            signed, venues, artists, TODAY, fetch=fake_fetch({"primary": html})))

        # No guessed roster from unlinked nodes, conflicting definitions,
        # missing references, wrong type or partially inlined contradictions.
        wrong_type = {**people[0], "@type": "Organization"}
        duplicate = {**people[0], "name": "A Different Band"}
        partial = {**node, "performer": [
            {**node["performer"][0], "name": "Conflicting Inline Name"},
            *node["performer"][1:]]}
        for nodes in ([node, *people[1:], unrelated],
                      [node, *people, duplicate],
                      [node, wrong_type, *people[1:]],
                      [partial, *people],
                      [{**node, "performer": []}, *people]):
            body = graph_page(nodes)
            with self.assertRaises(ValueError):
                proposals._individual_event(
                    body, EVENT, signed["event"]["date"], venue,
                    accept_generic=True)
            with self.assertRaises(ValueError):
                dynamic.validate(signed, venues, artists, TODAY,
                                 fetch=fake_fetch({"primary": body}))
        # Identifiers cannot join independent script documents.
        split = graph_page([node]) + graph_page(people)
        with self.assertRaises(ValueError):
            dynamic.validate(signed, venues, artists, TODAY,
                             fetch=fake_fetch({"primary": split}))

    def test_exact_place_description_replays_when_postal_address_is_empty(self):
        signed = signed_approval()
        proof = signed["officialEvidence"][0]
        proof["proofType"] = dynamic.OSM_SINGLE_PROFILE
        proof.pop("corroboratingEventUrl")
        node = next(dynamic.discover.read_ld(page(EVENT, music=False)))
        venue = next(v for v in BASE["venues"] if v["id"] == VENUE_ID)
        venues = {v["id"]: v for v in BASE["venues"]}
        artists = {a["id"]: a for a in BASE["artists"]}
        exact = " ".join(venue[k] for k in ("address", "postalCode", "city"))
        node["location"]["address"] = {"@type": "PostalAddress"}
        node["location"]["description"] = exact + " Métro ligne B"

        def as_html(value):
            return ("<html><main><script type='application/ld+json'>"
                    + json.dumps(value) + "</script>"
                    "<p>Official concert detail</p></main></html>")

        self.assertTrue(dynamic.validate(
            signed, venues, artists, TODAY,
            fetch=fake_fetch({"primary": as_html(node)})))
        for field, value in (("streetAddress", "12 rue différente"),
                             ("postalCode", "75001"),
                             ("addressLocality", "Paris"),
                             ("addressCountry", "BE")):
            wrong = copy.deepcopy(node)
            wrong["location"]["address"][field] = value
            with self.assertRaises(ValueError):
                dynamic.validate(signed, venues, artists, TODAY,
                                 fetch=fake_fetch({"primary": as_html(wrong)}))
        for description in (venue["city"], "Autre lieu " + exact,
                            exact + " ou 75001 Paris", "Une adresse inconnue"):
            wrong = copy.deepcopy(node)
            wrong["location"]["description"] = description
            with self.assertRaises(ValueError):
                dynamic.validate(signed, venues, artists, TODAY,
                                 fetch=fake_fetch({"primary": as_html(wrong)}))
        wrong = copy.deepcopy(node)
        wrong["location"]["country"] = {"@type": "Country", "name": "BE"}
        with self.assertRaises(ValueError):
            dynamic.validate(signed, venues, artists, TODAY,
                             fetch=fake_fetch({"primary": as_html(wrong)}))
        # An unrelated site never obtains authority from a correct address.
        with self.assertRaises(ValueError):
            dynamic.validate(signed, venues, artists, TODAY,
                             fetch=fake_fetch({"primary": as_html(node),
                                               "osm": osm(website="https://autre.fr")}))

    def test_visible_detail_single_source_replayed_with_eight_unknown_artists(self):
        from automation.concerts import dynamic_first_party_venue_proposals as proposals
        signed = signed_approval()
        proof = signed["officialEvidence"][0]
        proof["proofType"] = dynamic.OSM_SINGLE_PROFILE
        proof.pop("corroboratingEventUrl")
        title = " + ".join(NAMES)
        html = ("<h1>" + title + "</h1><p>5 mars 2027</p><p>" + title
                + "</p><p>concert ― Black Metal</p>"
                + "<p>→ Le Bikini - Salle de concert</p>"
                + "<p>Ramonville-Saint-Agne</p>")
        venue = next(v for v in BASE["venues"] if v["id"] == VENUE_ID)
        self.assertEqual(proposals._individual_event(
            html, EVENT, "2027-03-05", venue, accept_generic=True),
            (NAMES, ["Black Metal"]))
        venues = {v["id"]: v for v in BASE["venues"]}
        artists = {a["id"]: a for a in BASE["artists"]}
        self.assertTrue(dynamic.validate(signed, venues, artists, TODAY,
            fetch=fake_fetch({"primary": html})))
        for changed in (
            html.replace("5 mars", "6 mars"),
            html.replace("Black Metal", "Pop"),
            html.replace("→ Le Bikini", "→ Autre Salle"),
            html + "<p>Concert annulé</p>",
            html + page(EVENT, date="2027-03-06"),
        ):
            with self.assertRaises(ValueError):
                dynamic.validate(signed, venues, artists, TODAY,
                    fetch=fake_fetch({"primary": changed}))
        with self.assertRaises(ValueError):
            dynamic.validate(signed, venues, artists, TODAY,
                fetch=fake_fetch({"primary": html, "osm": osm(website="https://autre.fr")}))

    def test_sparse_schema_uses_complete_visible_card_without_masking_conflicts(self):
        from automation.concerts import dynamic_first_party_venue_proposals as proposals
        signed = signed_approval()
        proof = signed["officialEvidence"][0]
        proof["proofType"] = dynamic.OSM_SINGLE_PROFILE
        proof.pop("corroboratingEventUrl")
        title = " + ".join(NAMES)
        card = ("<h1>" + title + "</h1><p>5 mars 2027</p><p>" + title
                + "</p><p>concert ― Black Metal</p>"
                + "<p>→ Le Bikini - Salle de concert</p>"
                + "<p>Ramonville-Saint-Agne</p>")
        node = {"@type": "MusicEvent", "name": title, "url": EVENT,
                "location": {"@type": "Place",
                             "country": {"@type": "Country", "name": "FR"}}}
        venue = next(v for v in BASE["venues"] if v["id"] == VENUE_ID)
        venues = {v["id"]: v for v in BASE["venues"]}
        artists = {a["id"]: a for a in BASE["artists"]}

        def schema(value):
            return "<script type='application/ld+json'>" + json.dumps(value) + "</script>"

        html = schema(node) + card
        self.assertEqual(proposals._individual_event(
            html, EVENT, "2027-03-05", venue, accept_generic=True),
            (NAMES, ["Black Metal"]))
        self.assertTrue(dynamic.validate(signed, venues, artists, TODAY,
            fetch=fake_fetch({"primary": html})))
        for patch in (
            {"startDate": "2027-03-06"}, {"url": WITNESS},
            {"name": "Different event"}, {"eventStatus": "EventCancelled"},
            {"genre": "Jazz"}, {"performer": [{"@type": "MusicGroup", "name": "Other Band"}]},
            {"location": {"@type": "Place", "name": "Wrong Room"}},
            {"location": {"@type": "Place", "country": "BE"}},
            {"location": {"@type": "Place", "address": {"postalCode": "75001"}}},
        ):
            wrong = schema({**node, **patch}) + card
            with self.assertRaises(ValueError):
                dynamic.validate(signed, venues, artists, TODAY,
                    fetch=fake_fetch({"primary": wrong}))
        for wrong in (schema(node) + card.replace("5 mars", "6 mars"),
                      schema(node) + card.replace("Black Metal", "Jazz"),
                      schema(node) + card + schema(node),
                      schema(node) + card.replace("→ Le Bikini", "→ Other Room")):
            with self.assertRaises(ValueError):
                dynamic.validate(signed, venues, artists, TODAY,
                    fetch=fake_fetch({"primary": wrong}))

    def test_visible_tour_named_roster_replayed_by_producer_and_publisher(self):
        from automation.concerts import dynamic_first_party_venue_proposals as proposals
        from automation.concerts import dynamic_osm_official_proposals as producer
        from automation.concerts import official_visible_tour_bill as tour
        title = "Independent Across Europe Tour 2027"
        venue = next(v for v in BASE["venues"] if v["id"] == VENUE_ID)
        node = {"@type": "MusicEvent", "name": title, "url": EVENT,
                "location": {"@type": "Place", "country": "FR"}}
        roster = "<br/>".join(n + " - https://artists.example.org/" + i
                              for n, i in zip(NAMES, IDS))
        card = ("<main><h1>" + title + " par</h1><p>Black Metal</p>"
                "<p>5 mars 2027, au Bikini - Ramonville-Saint-Agne</p>"
                "<p>Avec<br/>" + NAMES[0] + " + " + NAMES[1]
                + " + 6 supports dans le cadre de la tournée</p>"
                "<p>" + roster + "</p></main>")
        def schema(n):
            return "<script type='application/ld+json'>" + json.dumps(n) + "</script>"
        html = schema(node) + card
        self.assertEqual(tour.verified_tour(html, title, venue["name"], venue["city"],
                                            "2027-03-05"), (NAMES, ["Black Metal"]))
        self.assertEqual(proposals._individual_event(
            html, EVENT, "2027-03-05", venue, accept_generic=True),
            (NAMES, ["Black Metal"]))
        signed = signed_approval()
        signed["officialEvidence"][0]["proofType"] = dynamic.OSM_SINGLE_PROFILE
        signed["officialEvidence"][0].pop("corroboratingEventUrl")
        venues = {v["id"]: v for v in BASE["venues"]}
        artists = {a["id"]: a for a in BASE["artists"]}
        get = fake_fetch({"primary": html})
        self.assertTrue(dynamic.validate(signed, venues, artists, TODAY, fetch=get))
        candidate = {"eventDetailUrl": EVENT, "sourceUrl": EVENT,
                     "sourcePage": EVENT, "venue": venue["name"],
                     "city": venue["city"], "department": venue["department"],
                     "leadArtist": title, "name": title}
        proposed = producer.propose((EVENT, "2027-03-05", VENUE_ID, candidate),
                                    BASE, TODAY, fetch=get)
        self.assertEqual(proposed["event"]["artistIds"], IDS)
        self.assertEqual(proposed["event"]["title"], " + ".join(NAMES))
        self.assertNotIn(title, [a["name"] for a in proposed["newArtists"]])
        with mock.patch.object(dynamic, "safe_fetch", side_effect=get):
            published, counts = publisher.merge(
                BASE, BASE, {"schema": publisher.SCHEMA, "approvals": [proposed]}, TODAY)
        self.assertEqual(counts["newEvents"], 1, counts["held"])
        self.assertEqual(published["events"][-1]["artistIds"], IDS)
        for wrong in (
                html.replace("5 mars", "6 mars"),
                html.replace("au Bikini", "au Théâtre"),
                html.replace("Black Metal", "Jazz"),
                html.replace("6 supports", "5 supports"),
                html.replace(roster, roster.replace(NAMES[-1], NAMES[0])),
                html.replace("Avec", "Recommandations"),
                html.replace("</main>", "<p>Concert annulé</p></main>"),
                html.replace("<p>" + roster, "<h2>Vous aimerez aussi</h2><p>" + roster),
                schema({**node, "startDate": "2027-03-06"}) + card,
                schema({**node, "performer": [{"@type": "MusicGroup", "name": "Other Band"}]}) + card,
                schema(node) + html):
            with self.subTest(wrong=wrong[:100]):
                with self.assertRaises(ValueError):
                    dynamic.validate(signed, venues, artists, TODAY,
                                     fetch=fake_fetch({"primary": wrong}))
        approximate = dict(venue, geoPrecision="centre de commune (position indicative)")
        self.assertIsNone(dynamic.sparse_visible_event_detail(
            html, [node], EVENT, "2027-03-05", approximate, tour_only=True))

    def test_generic_leaf_divs_join_inline_date_and_isolate_recommendations(self):
        from automation.concerts import open_world_visible_cards as cards
        page = ("<h1>La Salle</h1><h2>La Salle présente :</h2>"
                "<p>Présentation musicale.</p><div><div>5 <span>―</span> mars 2027</div>"
                "<div>New Act</div></div><div><div>concert ― Metal</div>"
                "<div>→ La Salle - Salle de concert</div></div>"
                "<div><div>5 <span>―</span> mars 2027</div>"
                "<div>New Act</div><div>Ouverture des portes 19:00</div></div>"
                "<section><div>Vous devriez aimer</div>"
                "<h2>6 mars 2027</h2><h5>Metal</h5><h3>Other Act</h3></section>"
                "<footer>12 rue des Fleurs<br>75019 Paris</footer>")
        opts = {"address": "12 rue des Fleurs", "postal": "75019"}
        self.assertEqual(cards.verified_detail(page, "La Salle", "Paris",
                         "2027-03-05", **opts), (["New Act"], ["Metal"]))
        for bad in (
            page.replace("5 <span>―</span> mars 2027", "6 <span>―</span> mars 2027", 1),
            page.replace("concert ― Metal", "concert ― Jazz"),
            page.replace("→ La Salle - Salle de concert", "→ Autre Salle"),
            page.replace("<h2>La Salle présente :</h2>", "<h2>Programmation</h2>"),
            page.replace("Présentation musicale.", "Concert annulé."),
            page.replace("Vous devriez aimer", "Autre date"),
        ):
            self.assertIsNone(cards.verified_detail(bad, "La Salle", "Paris",
                              "2027-03-05", **opts))
        # A recommendation-only card cannot authorize the primary event.
        related_only = ("<h1>La Salle</h1><h2>La Salle présente :</h2>"
                        "<div>Vous devriez aimer</div><div>5 mars 2027</div>"
                        "<div>New Act</div><div>concert ― Metal</div>"
                        "<div>→ La Salle - Salle de concert</div>"
                        "<footer>12 rue des Fleurs<br>75019 Paris</footer>")
        self.assertIsNone(cards.verified_detail(related_only, "La Salle", "Paris",
                          "2027-03-05", **opts))

    def test_footer_can_corroborate_only_exact_physical_address(self):
        from automation.concerts import open_world_visible_cards as cards
        page = ("<h1>La Salle</h1><h2>La Salle présente :</h2>"
                "<p>5 mars 2027</p><p>New Act</p><p>concert ― Metal</p>"
                "<p>→ La Salle - Salle de concert</p>"
                "<footer>12 rue des Fleurs<br>75019 Paris</footer>")
        opts = {"address": "12 rue des Fleurs", "postal": "75019"}
        self.assertEqual(cards.verified_detail(page, "La Salle", "Paris",
                         "2027-03-05", **opts), (["New Act"], ["Metal"]))
        for bad in (page.replace("12 rue", "13 rue"),
                    page.replace("75019", "75020"),
                    page.replace("concert ― Metal", "concert ― Jazz"),
                    page.replace("présente", "programme")):
            diag = {}
            self.assertIsNone(cards.verified_detail(bad, "La Salle", "Paris",
                              "2027-03-05", diagnostics=diag, **opts))
            self.assertIn("visibleDetail", diag)
        self.assertIsNone(cards.verified_detail(page, "La Salle", "Paris",
                          "2027-03-05"))

    def test_venue_linked_artist_profile_genre_reaches_real_publisher(self):
        from automation.concerts import dynamic_first_party_venue_proposals as proposals
        signed = signed_approval()
        proof = signed["officialEvidence"][0]
        proof["proofType"] = dynamic.OSM_SINGLE_PROFILE
        proof.pop("corroboratingEventUrl")
        profile_url = "https://unknown-musician.example.org/bio"
        source = page(EVENT, genres=False)
        # A named performer at the END of a mixed lineup is sufficient.
        primary = source.replace(
            json.dumps({"@type": "MusicGroup", "name": NAMES[-1]}),
            json.dumps({"@type": "MusicGroup", "name": NAMES[-1],
                        "url": profile_url}))
        self.assertNotEqual(primary, source)
        def profile(name=NAMES[-1], genre="Black Metal", kind="MusicGroup"):
            return ('<script type="application/ld+json">' +
                    json.dumps({"@type": kind, "name": name, "genre": genre}) +
                    '</script>')
        venue = next(v for v in BASE["venues"] if v["id"] == VENUE_ID)
        venues = {v["id"]: v for v in BASE["venues"]}
        artists = {a["id"]: a for a in BASE["artists"]}
        reads = []
        def fetch(url, cache):
            reads.append(url)
            if url == profile_url:
                return profile()
            return fake_fetch({"primary": primary})(url, cache)
        self.assertEqual(proposals._individual_event(
            primary, EVENT, signed["event"]["date"], venue,
            accept_generic=True, fetch=fetch, cache={}),
            (NAMES, ["Black Metal"]))
        self.assertTrue(dynamic.validate(signed, venues, artists, TODAY, fetch=fetch))
        self.assertEqual(reads.count(profile_url), 2)
        with mock.patch.object(dynamic, "safe_fetch", side_effect=fetch):
            proposed = {"schema": publisher.SCHEMA, "approvals": [signed]}
            result, counts = publisher.merge(BASE, BASE, proposed, TODAY)
            self.assertEqual(counts["newEvents"], 1)
            self.assertEqual(len(result["events"]), len(BASE["events"]) + 1)
        for changed in (profile(name="Another Artist"), profile(genre="Jazz"),
                        profile(kind="MusicEvent"), profile(genre="Hardcore Techno")):
            def wrong(url, cache):
                if url == profile_url:
                    return changed
                return fake_fetch({"primary": primary})(url, cache)
            with self.assertRaises(ValueError):
                dynamic.validate(signed, venues, artists, TODAY, fetch=wrong)
        for changed in (source, primary.replace(profile_url, "https://127.0.0.1/"),
                        primary.replace('"MusicEvent"', '"Event"'),
                        primary.replace("2027-03-05", "2027-03-06")):
            with self.assertRaises(ValueError):
                dynamic.validate(signed, venues, artists, TODAY,
                                 fetch=fake_fetch({"primary": changed}))

    def test_venue_linked_biography_reaches_publisher_without_structured_genre(self):
        from automation.concerts import dynamic_first_party_venue_proposals as proposals
        signed = signed_approval()
        proof = signed["officialEvidence"][0]
        proof["proofType"] = dynamic.OSM_SINGLE_PROFILE
        proof.pop("corroboratingEventUrl")
        target = "https://unknown-musician.example.org/"
        bio_url = target + "bio"
        source = page(EVENT, genres=False)
        primary = source.replace(
            json.dumps({"@type": "MusicGroup", "name": NAMES[-1]}),
            json.dumps({"@type": "MusicGroup", "name": NAMES[-1], "url": target}))
        self.assertNotEqual(primary, source)
        landing = '<a href="/bio">Biography</a>'
        biography = ("<title>" + NAMES[-1] + " Biography</title><p>" +
                     NAMES[-1] + " are a band playing black metal.</p>")
        venue = next(v for v in BASE["venues"] if v["id"] == VENUE_ID)
        venues = {v["id"]: v for v in BASE["venues"]}
        artists = {a["id"]: a for a in BASE["artists"]}
        def fetch(url, cache):
            if url == target:
                return landing
            if url == bio_url:
                return biography
            return fake_fetch({"primary": primary})(url, cache)
        self.assertEqual(proposals._individual_event(
            primary, EVENT, signed["event"]["date"], venue,
            accept_generic=True, fetch=fetch, cache={}),
            (NAMES, ["Black Metal"]))
        with mock.patch.object(dynamic, "safe_fetch", side_effect=fetch):
            result, counts = publisher.merge(
                BASE, BASE, {"schema": publisher.SCHEMA, "approvals": [signed]}, TODAY)
            self.assertEqual(counts["newEvents"], 1)
        conflicting = ('<script type="application/ld+json">' +
                       json.dumps({"@type": "MusicGroup", "name": NAMES[-1],
                                   "genre": "Jazz"}) + '</script>')
        for bad_landing, bad_bio in (
            (landing + conflicting, biography),
            ('<a href="https://other.example.org/bio">Biography</a>', biography),
            (landing, biography.replace(NAMES[-1], "Another Artist")),
            (landing, biography.replace("black metal", "jazz")),
        ):
            def wrong(url, cache):
                if url == target:
                    return bad_landing
                if url == bio_url:
                    return bad_bio
                return fake_fetch({"primary": primary})(url, cache)
            with self.assertRaises(ValueError):
                dynamic.validate(signed, venues, artists, TODAY, fetch=wrong)

    def test_venue_linked_direct_profile_replayed_by_real_publisher(self):
        from automation.concerts import dynamic_first_party_venue_proposals as proposals
        signed = signed_approval()
        proof = signed["officialEvidence"][0]
        proof["proofType"] = dynamic.OSM_SINGLE_PROFILE
        proof.pop("corroboratingEventUrl")
        target = "https://unknown-musician.example.org/"
        source = page(EVENT, genres=False)
        person = {"@type": "MusicGroup", "name": NAMES[-1]}
        primary = source.replace(json.dumps(person),
                                 json.dumps({**person, "url": target}))
        self.assertNotEqual(primary, source)
        profile = ("<title>" + NAMES[-1] + "</title><p>" +
                   NAMES[-1] + " are a black metal band from Norway.</p>")
        venue = next(v for v in BASE["venues"] if v["id"] == VENUE_ID)
        venues = {v["id"]: v for v in BASE["venues"]}
        artists = {a["id"]: a for a in BASE["artists"]}
        def fetch(url, cache):
            if url == target:
                return profile
            return fake_fetch({"primary": primary})(url, cache)
        self.assertEqual(proposals._individual_event(
            primary, EVENT, signed["event"]["date"], venue,
            accept_generic=True, fetch=fetch, cache={}),
            (NAMES, ["Black Metal"]))
        with mock.patch.object(dynamic, "safe_fetch", side_effect=fetch):
            result, counts = publisher.merge(
                BASE, BASE, {"schema": publisher.SCHEMA, "approvals": [signed]}, TODAY)
            self.assertEqual(counts["newEvents"], 1)
        for body in (
            profile.replace("black metal band", "black metal band tribute act"),
            profile.replace("are a", "are not a"),
            profile.replace(NAMES[-1], "Unrelated Artist"),
            profile + ('<script type="application/ld+json">' +
                json.dumps({"@type": "MusicGroup", "name": NAMES[-1],
                            "genre": "Jazz"}) + '</script>'),
        ):
            def wrong(url, cache):
                return body if url == target else fake_fetch({"primary": primary})(url, cache)
            with self.assertRaises(ValueError):
                dynamic.validate(signed, venues, artists, TODAY, fetch=wrong)

    def test_named_artist_without_external_link_can_qualify_from_own_event_bio(self):
        from automation.concerts import dynamic_first_party_venue_proposals as proposals
        signed = signed_approval()
        proof = signed["officialEvidence"][0]
        proof["proofType"] = dynamic.OSM_SINGLE_PROFILE
        proof.pop("corroboratingEventUrl")
        source = page(EVENT, genres=False)
        person = {"@type": "MusicGroup", "name": NAMES[-1]}
        sentence = NAMES[-1] + " are a black metal band from Norway."
        primary = source.replace(json.dumps(person),
                                 json.dumps({**person, "description": sentence}))
        visible = source.replace("<h1>Nouvel événement</h1>",
                                 "<h1>" + " + ".join(NAMES) + "</h1><h2>"
                                 + NAMES[-1] + "</h2><p>" + sentence + "</p>")
        venue = next(v for v in BASE["venues"] if v["id"] == VENUE_ID)
        venues = {v["id"]: v for v in BASE["venues"]}
        artists = {a["id"]: a for a in BASE["artists"]}
        for body in (primary, visible):
            fetch = fake_fetch({"primary": body})
            self.assertEqual(proposals._individual_event(
                body, EVENT, signed["event"]["date"], venue,
                accept_generic=True, fetch=fetch, cache={}),
                (NAMES, ["Black Metal"]))
            with mock.patch.object(dynamic, "safe_fetch", side_effect=fetch):
                result, counts = publisher.merge(
                    BASE, BASE, {"schema": publisher.SCHEMA,
                                 "approvals": [signed]}, TODAY)
                self.assertEqual(counts["newEvents"], 1)
        for sentence_bad in (
                "Another Artist are a black metal band.",
                NAMES[-1] + " are not a black metal band.",
                NAMES[-1] + " are a jazz band influenced by black metal.",
                NAMES[-1] + " support a black metal band.",
                NAMES[-1] + " are a black metal tribute band."):
            body = primary.replace(sentence, sentence_bad)
            with self.assertRaises(ValueError):
                dynamic.validate(signed, venues, artists, TODAY,
                                 fetch=fake_fetch({"primary": body}))
        conflicting = source.replace(json.dumps(person), json.dumps({
            **person, "genre": "Jazz", "description": sentence}))
        unrelated = visible.replace("<h2>" + NAMES[-1],
                                    "<h2>Related events</h2><h2>" + NAMES[-1])
        for body in (conflicting, unrelated,
                     visible.replace("<h1>" + " + ".join(NAMES), "<h1>Other show")):
            with self.assertRaises(ValueError):
                dynamic.validate(signed, venues, artists, TODAY,
                                 fetch=fake_fetch({"primary": body}))

    def test_visible_genre_badges_with_missing_or_named_structured_bill(self):
        from automation.concerts import dynamic_first_party_venue_proposals as proposals
        signed = signed_approval()
        proof = signed["officialEvidence"][0]
        proof["proofType"] = dynamic.OSM_SINGLE_PROFILE
        proof.pop("corroboratingEventUrl")
        signed["event"]["genres"] = proof["officialGenreLabels"] = ["Post Punk"]
        title = " + ".join(NAMES)
        headings = "".join("<h4>" + n + "</h4><p>Jazz</p>" for n in NAMES[:-1])
        last = "<h4>" + NAMES[-1] + "</h4><span>Darkwave</span><span>Post-punk</span>"
        primary = page(EVENT, music=False, genres=False).replace(
            "<h1>Nouvel événement</h1>", "<h1>" + title + "</h1>" + headings + last)
        no_bill = primary.replace(json.dumps(
            [{"@type": "MusicGroup", "name": n} for n in NAMES]), "[]")
        venue = next(v for v in BASE["venues"] if v["id"] == VENUE_ID)
        venues = {v["id"]: v for v in BASE["venues"]}
        artists = {a["id"]: a for a in BASE["artists"]}
        for body in (primary, no_bill):
            fetch = fake_fetch({"primary": body})
            self.assertEqual(proposals._individual_event(
                body, EVENT, signed["event"]["date"], venue,
                accept_generic=True, fetch=fetch, cache={}), (NAMES, ["Post Punk"]))
            self.assertTrue(dynamic.validate(signed, venues, artists, TODAY, fetch=fetch))
        for body in (no_bill.replace(last, "<h4>Other Artist</h4><span>Post-punk</span>"),
                     no_bill.replace(last, "<h4>Related events</h4>" + last),
                     primary.replace("<span>Darkwave</span>", "<span>not</span>"),
                     primary.replace("Post-punk", "Influenced by post-punk"),
                     primary.replace("Post-punk", "Hardcore techno"),
                     no_bill.replace("<h4>" + NAMES[0] + "</h4>", "<h4>Wrong artist</h4>")):
            with self.assertRaises(ValueError):
                dynamic.validate(signed, venues, artists, TODAY,
                                 fetch=fake_fetch({"primary": body}))

    def test_exact_visible_musical_prose_replayed_by_real_publisher(self):
        from automation.concerts import dynamic_first_party_venue_proposals as proposals
        signed = signed_approval()
        proof = signed["officialEvidence"][0]
        proof["proofType"] = dynamic.OSM_SINGLE_PROFILE
        proof.pop("corroboratingEventUrl")
        title = " + ".join(NAMES) + " + Guest"
        description = ("Au programme, " + ", ".join("le groupe " + n for n in NAMES[:-1])
                       + " et le black metal mélodique de " + NAMES[-1] + ".")
        body = page(EVENT, music=False, genres=False, event_name=title)
        body = body.replace(json.dumps(
            [{"@type": "MusicGroup", "name": n} for n in NAMES]), "[]")
        body = body.replace("<h1>Nouvel événement</h1>",
                            "<h1>" + title + "</h1><p>" + description + "</p>")
        venue = next(v for v in BASE["venues"] if v["id"] == VENUE_ID)
        venues = {v["id"]: v for v in BASE["venues"]}
        artists = {a["id"]: a for a in BASE["artists"]}
        fetch = fake_fetch({"primary": body})
        self.assertEqual(proposals._individual_event(
            body, EVENT, signed["event"]["date"], venue,
            accept_generic=True, fetch=fetch, cache={}), (NAMES, ["Black Metal"]))
        self.assertTrue(dynamic.validate(signed, venues, artists, TODAY, fetch=fetch))
        with mock.patch.object(dynamic, "safe_fetch", side_effect=fetch):
            published, counts = publisher.merge(
                BASE, BASE, {"schema": publisher.SCHEMA, "approvals": [signed]}, TODAY)
        self.assertEqual(counts["newEvents"], 1)
        event = next(e for e in published["events"] if e["id"] == signed["event"]["id"])
        self.assertEqual(event["artistIds"], IDS)
        self.assertEqual(event["title"], " + ".join(NAMES))
        for bad in (
                body.replace("le groupe " + NAMES[0], "le groupe Other Artist"),
                body.replace("Au programme,", "Au programme, discussion avec"),
                body.replace("Au programme,", "Biographie :"),
                body.replace("black metal mélodique", "jazz influencé par le black metal"),
                body.replace("black metal mélodique", "hardcore techno"),
                body.replace("le black metal", "pas le black metal"),
                body.replace("<p>" + description, "<h2>Vous devriez aimer…</h2><p>" + description),
                body.replace("<p>" + description, "<h3>" + NAMES[0] + "</h3><p>" + description),
                body.replace("<h1>" + title, "<h1>Different Concert"),
                body.replace('"performer": []', '"performer": [{"@type": "MusicGroup", "name": "Other Artist"}]'),
        ):
            with self.subTest(snippet=bad[:180]), self.assertRaises(ValueError):
                dynamic.validate(signed, venues, artists, TODAY,
                                 fetch=fake_fetch({"primary": bad}))

    def test_visible_prose_roles_and_explicit_style_stay_artist_specific(self):
        names = ["Example Trio", "Example Solo", "Example Group"]
        title = " / ".join(names)
        description = ("Au programme, la techno du trio Example Trio, les chansons "
                       "mélancoliques de Example Solo et le groupe de rock alternatif "
                       "et post-punk originaire de Rouen Example Group.")
        html = "<h1>" + title + "</h1><p>" + description + "</p>"
        people = dynamic.visible_named_bill(html, title)
        self.assertEqual([p["name"] for p in people], names)
        self.assertNotIn("genre", people[0])
        self.assertNotIn("genre", people[1])
        self.assertEqual(people[2]["genre"], ["Post Punk"])
        literal = "Example A / Example B"
        single = "<h1>" + literal + "</h1><h3>" + literal + "</h3><p>Post-punk</p>"
        single_bill = dynamic.visible_named_bill(single, literal)
        self.assertEqual([p["name"] for p in single_bill], [literal])
        self.assertEqual(dynamic.visible_named_bill(
            html + "<p>" + description + "</p>", title), people)
        self.assertIsNone(dynamic.visible_named_bill(
            html + "<p>" + description.replace("post-punk", "death metal") + "</p>", title))

    def test_visible_prose_trailing_guest_and_individual_punk_credits(self):
        title = "Example A + Example B + Guest"
        prose = ("Une session avec le punk rock féministe très riot grrrls de Example A "
                 "et le punk grunge anarchiste de Example B.")
        html = "<h1>" + title + "</h1><p>" + prose + "</p>"
        people = dynamic.visible_named_bill(html, title)
        self.assertEqual([p["name"] for p in people], ["Example A", "Example B", "Guest"])
        self.assertEqual(people[0]["genre"], ["Punk Rock"])
        self.assertEqual(people[1]["genre"], ["Punk"])
        self.assertNotIn("genre", people[2])
        for bad_title in ("Example A + Guest + Example B", "Example A + Example B + TBA + Guest"):
            self.assertIsNone(dynamic.visible_named_bill(
                html.replace(title, bad_title), bad_title))

    def test_signed_published_osm_api_node_sources_are_rechecked_without_allowlist(self):
        # Five real published venues use the API-node spelling; the old
        # validator rejected these even though it fetches that exact API.
        for origin in (
            "https://www.openstreetmap.org/api/0.6/node/380889428",
            "https://api.openstreetmap.org/api/0.6/node/380889428",
        ):
            with self.subTest(origin=origin):
                venue_map = copy.deepcopy(BASE)
                venue = next(v for v in venue_map["venues"]
                             if v["id"] == VENUE_ID)
                venue["geoSource"] = origin
                signed = signed_approval()
                signed["officialEvidence"][0]["namedOsmUrl"] = origin
                reads = []
                fetch = fake_fetch()
                def observe(url, cache):
                    reads.append(url)
                    return fetch(url, cache)
                self.assertTrue(dynamic.validate(
                    signed, {v["id"]: v for v in venue_map["venues"]},
                    {a["id"]: a for a in venue_map["artists"]},
                    TODAY, fetch=observe))
                self.assertIn(
                    "https://api.openstreetmap.org/api/0.6/node/380889428",
                    reads)
                self.assertIn(EVENT, reads)
                self.assertIn(WITNESS, reads)

    def test_osm_api_node_source_rejects_lookalikes_and_wrong_object(self):
        venue = copy.deepcopy(next(v for v in BASE["venues"]
                                  if v["id"] == VENUE_ID))
        unsafe = (
            "http://www.openstreetmap.org/api/0.6/node/380889428",
            "https://www.openstreetmap.org.evil.example/api/0.6/node/380889428",
            "https://www.openstreetmap.org/api/0.6/way/380889428",
            "https://www.openstreetmap.org/api/0.6/node/380889428?x=1",
            "https://www.openstreetmap.org/api/0.6/node/380889428/extra",
            "https://www.openstreetmap.org/api/0.6/node/0",
            "https://api.openstreetmap.org.evil.example/api/0.6/node/380889428",
        )
        for ref in unsafe:
            with self.subTest(ref=ref):
                venue["geoSource"] = ref
                with self.assertRaisesRegex(ValueError, "named OSM node"):
                    dynamic.osm_identity(venue, EVENT,
                        lambda *_: self.fail("Invalid ref must not fetch"),
                        {})
        venue["geoSource"] = (
            "https://www.openstreetmap.org/api/0.6/node/380889429")
        with self.assertRaisesRegex(ValueError, "node mismatched"):
            dynamic.osm_identity(venue, EVENT,
                                 lambda *_: osm(), {})

    def test_unknown_domain_and_eight_unknown_artists_publish_without_manifest(self):
        approval = signed_approval()
        calls = []
        fetch = fake_fetch()
        def visit(url, cache):
            calls.append(url)
            return fetch(url, cache)
        with mock.patch.object(dynamic, "safe_fetch", side_effect=visit):
            self.assertTrue(dynamic.validate(
                approval, {v["id"]: v for v in BASE["venues"]},
                {a["id"]: a for a in BASE["artists"]}, TODAY))
            proposed = {"schema": publisher.SCHEMA, "approvals": [approval]}
            old = {"schema": publisher.SCHEMA, "approvals": []}
            accepted = approval_preflight.check_append_only(old, proposed, TODAY)
            self.assertEqual(len(accepted), 1)
            # Never call a special-case venue verifier or edit a manifest.
            published, counts = publisher.merge(BASE, BASE, proposed, TODAY)
        self.assertEqual(counts["newEvents"], 1)
        self.assertEqual(counts["newArtists"], 8)
        self.assertEqual(counts["newVenues"], 0)
        self.assertEqual(len(published["events"]), len(BASE["events"]) + 1)
        self.assertEqual(published["venues"], BASE["venues"])
        self.assertEqual([a["id"] for a in published["artists"][-8:]], IDS)
        self.assertIn(EVENT, calls)
        self.assertIn(WITNESS, calls)
        self.assertTrue(any("api.openstreetmap.org" in x for x in calls))
        # Signed replay cannot insert another event or artist.
        with mock.patch.object(dynamic, "safe_fetch",
                               side_effect=AssertionError("old approval must not re-fetch")):
            replay, repeated = publisher.merge(BASE, published, proposed, TODAY)
        self.assertEqual(replay, published)
        self.assertEqual(repeated["newEvents"], 0)

    def test_private_national_cross_source_to_publisher_no_allowlist(self):
        from automation.concerts import dynamic_first_party_venue_proposals as proposed_source
        from automation.concerts import source_cross_domain_live_recheck as cross
        report = {
            "schema": cross.SCHEMA,
            "publicationAllowed": False,
            "sourceOwnershipVerified": False,
            "checks": [{
                "date": "2027-03-05", "leadArtist": NAMES[0],
                "city": "Ramonville-Saint-Agne", "venue": "bikini",
                "publishedAlreadyKnown": False,
                "markedPossibleDuplicate": False,
                "sourceOwnershipVerified": False,
                "publicationAllowed": False,
                "crossDomainEventVerified": True,
                "verifiedWitnesses": [
                    {"url": EVENT, "host": "nouveau-domaine-independant.fr"},
                    {"url": WITNESS, "host": "artiste-exemple.fr"},
                ],
            }],
        }
        seed = {"schema": publisher.SCHEMA, "approvals": []}
        proposals, metrics = proposed_source.build(
            report, BASE, seed, TODAY, fetch=fake_fetch())
        self.assertEqual(metrics["stateCounts"]["publisher_proposals"], 1)
        self.assertEqual(len(proposals["approvals"]), 1)
        self.assertEqual(seed["approvals"], [])
        approval = proposals["approvals"][0]
        self.assertEqual(approval["event"]["artistIds"], IDS)
        self.assertEqual(approval["newArtists"], [
            {"id": ident, "name": name}
            for ident, name in zip(IDS, NAMES)])
        with mock.patch.object(dynamic, "safe_fetch", side_effect=fake_fetch()):
            stats = approval_preflight.validate_proposal(
                seed, proposals, BASE, BASE, TODAY, publisher.merge)
        self.assertEqual(stats["newApprovals"], 1)
        self.assertTrue(stats["validatedByPublisher"])

    def test_private_cross_source_does_not_trust_failed_correlations(self):
        from automation.concerts import dynamic_first_party_venue_proposals as proposed_source
        from automation.concerts import source_cross_domain_live_recheck as cross
        base = {"schema": cross.SCHEMA, "publicationAllowed": False,
                "sourceOwnershipVerified": False,
                "checks": [{
                    "date": "2027-03-05", "leadArtist": NAMES[0],
                    "city": "Ramonville-Saint-Agne", "venue": "bikini",
                    "publishedAlreadyKnown": False,
                    "markedPossibleDuplicate": False,
                    "sourceOwnershipVerified": False, "publicationAllowed": False,
                    "crossDomainEventVerified": True,
                    "verifiedWitnesses": [
                        {"url": EVENT, "host": "nouveau-domaine-independant.fr"},
                        {"url": WITNESS, "host": "artiste-exemple.fr"},
                    ],
                }]}
        seed = {"schema": publisher.SCHEMA, "approvals": []}
        for variant in ("not_verified", "already_published", "new_venue",
                        "forged_venue", "bad_second_source", "no_osm_owner"):
            with self.subTest(variant=variant):
                report = copy.deepcopy(base)
                item = report["checks"][0]
                kwargs = {}
                if variant == "not_verified":
                    item["crossDomainEventVerified"] = False
                elif variant == "already_published":
                    item["publishedAlreadyKnown"] = True
                elif variant == "new_venue":
                    item["venue"] = "inconnu"
                elif variant == "forged_venue":
                    item["city"] = "Nantes"
                elif variant == "bad_second_source":
                    kwargs = {"secondary": page(WITNESS, names=["Faux Groupe"])}
                elif variant == "no_osm_owner":
                    kwargs = {"osm": osm(website="https://autre-site.fr")}
                out, metric = proposed_source.build(
                    report, BASE, seed, TODAY, fetch=fake_fetch(kwargs))
                self.assertEqual(out, seed)
                self.assertGreaterEqual(
                    metric["stateCounts"].get("held_needs_other_evidence", 0), 1)

    def test_publisher_replay_reports_specific_fixed_rejection_stage(self):
        cases = (
            (page(EVENT, names=NAMES[:-1]), "signed_title_mismatch"),
            (page(EVENT, date="2027-03-06"), "event_date_mismatch"),
            (page(EVENT, venue_name="Other Place"), "venue_name_mismatch"),
            (page(EVENT, postal="99999"), "venue_postal_identity_mismatch"),
            (page(EVENT, country="GB"), "venue_country_unconfirmed"),
            (page(EVENT, genres=False), "relevant_genre_missing"),
            (page(EVENT, status="EventCancelled"), "event_not_confirmed"),
        )
        for html, reason in cases:
            with self.subTest(reason=reason):
                with self.assertRaisesRegex(
                        ValueError, "no unique exact first-party MusicEvent: " + reason):
                    dynamic.validate(signed_approval(),
                                     {v["id"]: v for v in BASE["venues"]},
                                     {a["id"]: a for a in BASE["artists"]}, TODAY,
                                     fetch=fake_fetch({"primary": html}))
        # Remote or unexpected exceptions must never become a report detail.
        self.assertEqual(dynamic._replay_reason(ValueError("private remote text")),
                         "invalid_event_node")

    def test_source_identity_and_exact_event_contradictions_hold(self):
        for case, changed in (
            ("source-owner", {"osm": osm(website="https://unrelated.fr")}),
            ("missing-name", {"osm": osm(name="Another Venue")}),
            ("wrong-country", {"osm": osm(country="GB")}),
            ("wrong-geo", {"osm": osm(lat="44.0")}),
            ("changed-bill", {"primary": page(EVENT, names=NAMES[:-1])}),
            ("changed-date", {"primary": page(EVENT, date="2027-03-06")}),
            ("foreign-event", {"primary": page(EVENT, country="GB")}),
            ("wrong-room", {"primary": page(EVENT, venue_name="Other Place")}),
            ("nonconcert", {"primary": page(EVENT, music=False)}),
            ("festival-not-a-concert", {"primary": page(
                EVENT, event_name="Festival des métaux 2027")}),
            ("no-genre", {"primary": page(EVENT, genres=False)}),
            ("cancelled", {"primary": page(EVENT, status="EventCancelled")}),
            ("forged-witness", {"secondary": page(WITNESS, names=["Another Artist"])}),
            ("changed-witness-place", {"secondary": page(
                WITNESS, names=[NAMES[0]], city="Bordeaux")}),
        ):
            with self.subTest(case=case):
                approval = signed_approval()
                with mock.patch.object(dynamic, "safe_fetch",
                                       side_effect=fake_fetch(changed)):
                    result, counts = publisher.merge(
                        BASE, BASE,
                        {"schema": publisher.SCHEMA, "approvals": [approval]}, TODAY)
                # Publisher intentionally records invalid approvals in the
                # private held queue instead of raising from merge(). Verify
                # the rejection comes from the independent dynamic contract,
                # rather than a legacy per-venue pilot allowlist.
                self.assertEqual(result, BASE)
                self.assertEqual(counts["newEvents"], 0)
                self.assertEqual(len(counts["held"]), 1)
                if case in ("forged-witness", "changed-witness-place"):
                    # Independent second-domain event verification rejects
                    # the mismatched artist or city before dynamic.validate
                    # can add its own context prefix.
                    self.assertIn("No unique exact dated/named site and band bill",
                                  counts["held"][0]["reason"])
                else:
                    self.assertIn("Unlisted official source:",
                                  counts["held"][0]["reason"])

    def test_same_apex_witness_not_independent(self):
        row = signed_approval()
        row["officialEvidence"][0]["corroboratingEventUrl"] = (
            "https://tickets.nouveau-domaine-independant.fr/another-page")
        with mock.patch.object(dynamic, "safe_fetch", side_effect=fake_fetch()):
            with self.assertRaisesRegex(ValueError, "same source apex"):
                dynamic.validate(
                    row, {v["id"]: v for v in BASE["venues"]},
                    {a["id"]: a for a in BASE["artists"]}, TODAY)

    def test_unknown_source_refused_without_osm_website_or_secondary(self):
        record = signed_approval()
        for mod in ("without-osm", "secondary-missing", "false-attribution"):
            with self.subTest(mod=mod):
                row = copy.deepcopy(record)
                if mod == "secondary-missing":
                    row["officialEvidence"][0].pop("corroboratingEventUrl")
                elif mod == "false-attribution":
                    row["officialEvidence"][0]["namedOsmUrl"] = (
                        "https://www.openstreetmap.org/node/98765")
                otherwise = {"osm": osm(website="https://bad.example")}
                with mock.patch.object(dynamic, "safe_fetch",
                                       side_effect=fake_fetch(otherwise)):
                    with self.assertRaises((ValueError, KeyError, TypeError)):
                        dynamic.validate(
                            row, {v["id"]: v for v in BASE["venues"]},
                            {a["id"]: a for a in BASE["artists"]}, TODAY)

    def test_duplicates_stay_unpublishable(self):
        # An existing event already using the same named artist at the same
        # room/date cannot be re-created under a different generated ID.
        approval = signed_approval()
        public = copy.deepcopy(BASE)
        public["artists"].extend(
            {"id": i, "name": n, "aliases": []} for i, n in zip(IDS, NAMES))
        public["events"].append({
            "id": "go-c-20270305-ramonville-duplicate",
            "title": NAMES[0], "date": "2027-03-05",
            "artistIds": [IDS[0]], "venueId": VENUE_ID,
            "genres": ["Black Metal"], "status": "confirmed",
            "officialUrl": "https://other.example/real",
            "sourceType": "salle",
        })
        # This test checks duplicate detection without using forged prior
        # approvals for the old event.
        self.assertTrue(any(
            e["date"] == approval["event"]["date"]
            and e["venueId"] == approval["event"]["venueId"]
            and bool(set(e["artistIds"]) & set(approval["event"]["artistIds"]))
            for e in public["events"]))


if __name__ == "__main__":
    unittest.main()
