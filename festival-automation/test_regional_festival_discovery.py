"""Non-publication, provenance, exact-host, dedup and rotation regression tests."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).parent))
from regional_festival_discovery import (load_indexes, candidate_links,
                                         select_indexes, scan_regional_indexes,
                                         SCHEMA, APPROVED, archive_hints,
                                         load_verified_archive_hints, ARCHIVE_SIGNAL,
                                         curated_count_pages)
LIMOGES="https://sortir.limoges.fr/agenda"
ANGERS="https://www.angers.fr/actualites-sorties/agenda/index.html"
TARGET="https://sortir.limoges.fr/agenda/shred-fest-2027"
A={"id":"na-limoges","region":"Nouvelle-Aquitaine","url":LIMOGES}
B={"id":"pdl-angers","region":"Pays de la Loire","url":ANGERS}
DAY="2026-11-05"
def page(label="Shred Fest 2027",target=TARGET):
    return '<div><a href="'+target+'">'+label+'</a></div>'
def report(day=DAY):
    return {"schema":"grossesondes.source-watch-report.v1","date":day}
class RegionalTests(unittest.TestCase):
    def test_semantic_heading_generic_link_and_year_are_private_only(self):
        from regional_festival_discovery import CARD_HEADING_PENDING_SIGNAL
        href = "/actualites-sorties/agenda/mordorfest"
        card_link = '<a href="' + href + '">En savoir plus</a>'
        cases = (
            '<article><h3>MordorFest</h3><p>Musique / Concert</p>'
            '<time>Les 25 et 26 juin 2027</time>' + card_link + '</article>',
            '<li><h2>MordorFest 2027</h2><span>Concerts / Musique</span>'
            + card_link + '</li>',
            '<div role="article"><div><h4>MordorFest</h4></div>'
            '<span>Musique / Concert — Édition 2027</span>'
            + card_link + '</div>',
        )
        for html in cases:
            with self.subTest(html=html):
                rows = candidate_links(html, ANGERS, "2026-11-20")
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["title"], "MordorFest 2027")
                self.assertEqual(rows[0]["signal"], CARD_HEADING_PENDING_SIGNAL)
                self.assertEqual(rows[0]["candidate_url"],
                                 "https://www.angers.fr" + href)
                self.assertIsNone(rows[0]["archive_slug"])
                self.assertNotIn("startDate", rows[0])
                self.assertNotIn("safe_to_publish", rows[0])

    def test_heading_is_not_borrowed_or_confused_with_generic_navigation(self):
        generic = '<a href="/actualites-sorties/agenda/mordorfest">En savoir plus</a>'
        cases = (
            '<h3>MordorFest 2027</h3><article><span>Musique / Concert</span>'
            + generic + '</article>',
            '<article><h3>MordorFest 2027</h3><span>Musique / Concert</span>'
            '</article><article>' + generic + '</article>',
            '<article><h3>MordorFest</h3><span>Musique / Concert</span>'
            + generic + '</article><span>Édition 2027</span>',
            '<article><h3>MordorFest</h3><span>Musique / Concert</span>'
            + generic + '</article>',
            '<article><h3 hidden>MordorFest 2027</h3>'
            '<span>Musique / Concert</span>' + generic + '</article>',
            '<article><h3 aria-hidden="true">MordorFest 2027</h3>'
            '<span>Musique / Concert</span>' + generic + '</article>',
            '<article><h3 style="display:none">MordorFest 2027</h3>'
            '<span>Musique / Concert</span>' + generic + '</article>',
            '<article><h3>MordorFest</h3><script>2027</script>'
            '<span>Musique / Concert</span>' + generic + '</article>',
            '<article><h3>MordorFest</h3><time datetime="2027-06-25">'
            'Juin</time><span>Musique / Concert</span>'
            + generic + '</article>',
            '<article><h3>MordorFest 2027</h3><h4>Autre évènement</h4>'
            '<span>Musique / Concert</span>' + generic + '</article>',
            '<article><h3>MordorFest 2027</h3><span>Musique / Concert</span>'
            + generic + '<a href="/autre">Autre</a></article>',
            '<article><h3>MordorFest 2027</h3>'
            '<article><span>Musique / Concert</span>' + generic
            + '</article></article>',
            '<article><h3>MordorFest 2027</h3>'
            + generic + '</article>',
            '<article><h3>MordorFest 2027</h3>'
            '<span>Culture / Loisirs</span>' + generic + '</article>',
            '<article><h3>Festival des plantes 2027</h3>'
            '<span>Musique / Concert</span>' + generic + '</article>',
            '<article><h3>Festivités du village 2027</h3>'
            '<span>Musique / Concert</span>' + generic + '</article>',
            '<article><h3>MordorFest 2027</h3>'
            '<span>Musique / Concert — Édition 2028</span>'
            + generic + '</article>',
            '<article><h3>MordorFest 2027</h3>'
            '<span>Musique / Concert</span>'
            '<a href="https://evil.example/mordorfest">En savoir plus</a>'
            '</article>',
            '<article><h3>MordorFest 2032</h3>'
            '<span>Musique / Concert</span>' + generic + '</article>',
        )
        for html in cases:
            with self.subTest(html=html):
                self.assertEqual(candidate_links(
                    html, ANGERS, "2026-11-20"), [])

    def test_heading_generic_link_next_day_and_no_publisher_bypass(self):
        from regional_festival_discovery import CARD_HEADING_PENDING_SIGNAL
        from national_discovery_queue import build_queue
        from national_detail_qualification import _eligible_sources, _seen_again
        from grossesondes_institutional_edition import (
            private_proposal, independently_fetch)
        today, tomorrow = "2026-11-20", "2026-11-21"
        url = "https://www.angers.fr/actualites-sorties/agenda/mordorfest"
        html = ('<article><h3>MordorFest</h3>'
                '<span>Concerts / Musique — Édition 2027</span>'
                '<a href="' + url + '">En savoir plus</a></article>')
        state = {"schema": "grossesondes.source-watch.v1",
                 "institutional_agenda_candidate_pages": {},
                 "secondary_source_candidates_private": {}}
        fetched = []
        result = scan_regional_indexes(
            {"schema": "grossesondes.source-watch-report.v1",
             "date": today, "source_reference_leads_review_only": []},
            state, [B], today,
            fetch=lambda url: fetched.append(url) or html, limit=1)
        self.assertEqual(fetched, [ANGERS])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["discovery_signal"],
                         CARD_HEADING_PENDING_SIGNAL)
        self.assertIs(result[0]["publication_authorized"], False)
        self.assertIs(result[0]["date_verified"], False)
        queue = build_queue(
            state, {"schema": "grossesondes.source-watch-report.v1",
                    "date": tomorrow, "source_reference_leads_review_only": []},
            [], tomorrow)
        self.assertEqual(queue["publications"], 0)
        self.assertEqual(queue["candidate_dossiers_count"], 1)
        candidates = _eligible_sources(state, queue, tomorrow, due_only=False)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["title"], "MordorFest 2027")
        self.assertTrue(_seen_again(html, candidates[0]))
        self.assertFalse(_seen_again(
            html.replace("</article>", '<a href="/other">Other</a></article>'),
            candidates[0]))
        self.assertFalse(_seen_again(
            html.replace("Édition 2027", "Édition 2028"), candidates[0]))
        proposal = private_proposal(
            candidates[0], ("2027-06-25", "2027-06-26"), tomorrow)
        self.assertIsNotNone(proposal)
        reads = []
        rejected = independently_fetch(
            proposal, tomorrow,
            fetch=lambda uri: reads.append(uri) or (
                html if uri == ANGERS
                else "<h1>MordorFest 2027</h1><p>Festival sans genre démontré</p>"
            ))
        self.assertIsNone(rejected)
        self.assertEqual(reads, [ANGERS, url])
        self.assertIs(queue["publication_authorized"], False)

    def test_visible_year_outside_single_link_is_strict_private_card_hint(self):
        from regional_festival_discovery import CARD_YEAR_PENDING_SIGNAL
        for title in ("Festibarock'in", "MordorFest", "Festival Rock des Forges"):
            href = "/actualites-sorties/agenda/" + (
                "festibarockin" if title == "Festibarock'in" else
                "mordorfest" if title == "MordorFest" else "festival-rock-forges"
            )
            anchor = '<h3><a href="' + href + '">' + title + '</a></h3>'
            cards = (
                '<article><p>Musique / Concert — Édition 2027</p>'
                + anchor + '</article>',
                '<li>' + anchor +
                '<time>25 et 26 juin 2027</time><span>Concerts / Musique</span></li>',
                '<div role="article"><p>Musique / Concert</p><div>' + anchor
                + '</div><p>Édition 2027</p></div>',
            )
            for html in cards:
                with self.subTest(title=title, html=html):
                    hits = candidate_links(html, ANGERS, "2026-11-20")
                    self.assertEqual(len(hits), 1)
                    self.assertEqual(hits[0]["title"], title + " 2027")
                    self.assertEqual(hits[0]["signal"], CARD_YEAR_PENDING_SIGNAL)
                    self.assertEqual(hits[0]["candidate_url"],
                                     "https://www.angers.fr" + href)
                    self.assertIsNone(hits[0]["archive_slug"])
                    self.assertNotIn("startDate", hits[0])
                    self.assertNotIn("edition_dates_verified", hits[0])
        # A same-card printed year without musical theme or festival
        # identity is not a discovery lead.
        self.assertEqual(candidate_links(
            '<article><p>Musique / Concert — Édition 2027</p>'
            '<a href="/actualites-sorties/agenda/solo">Concert solo</a>'
            '</article>', ANGERS, "2026-11-20"), [])

    def test_visible_card_year_cannot_leak_or_override_conflicts(self):
        anchor = '<a href="/actualites-sorties/agenda/mordorfest">MordorFest</a>'
        cases = [
            "<p>Édition 2027</p><article><p>Musique / Concert</p>"
            + anchor + "</article>",
            '<article><p>Musique / Concert</p>' + anchor +
            '</article><p>Édition 2027</p>',
            '<article><p>Musique / Concert</p>' + anchor
            + '<span hidden>2027</span></article>',
            '<article><p>Musique / Concert</p>' + anchor
            + '<span aria-hidden="true">2027</span></article>',
            '<article><p>Musique / Concert</p>' + anchor
            + '<script>document.write("2027")</script></article>',
            '<article><p>Musique / Concert</p>' + anchor
            + '<time datetime="2027-06-25">25 juin</time></article>',
            '<article><p>Musique / Concert</p>' + anchor
            + '<p>Édition 2027 / 2028</p></article>',
            '<article><p>Musique / Concert</p>' + anchor
            + '<p>Édition 2025</p></article>',
            '<article><p>Musique / Concert</p>' + anchor
            + '<p>Édition 2032</p></article>',
            '<article><p>Musique / Concert</p>' + anchor
            + '<a href="/autre">Autre</a><p>Édition 2027</p></article>',
            '<div role="article"><p>Musique / Concert</p>' + anchor
            + '<div role="article">Édition 2027</div></div>',
            '<article><p>Édition 2027</p><a href="https://evil.example/x">'
            'MordorFest</a><span>Musique / Concert</span></article>',
            '<article><p>Édition 2027</p><a href="/actualites-sorties/'
            'agenda/festivites">Festivités musicales</a>'
            '<span>Musique / Concert</span></article>',
            '<article><p>Édition 2027</p><a href="/actualites-sorties/'
            'agenda/festival-plantes">Festival des plantes</a>'
            '<span>Musique / Concert</span></article>',
            '<article><p>Édition 2027</p><a href="/actualites-sorties/'
            'agenda/plus">En savoir plus</a>'
            '<span>Musique / Concert</span></article>',
        ]
        for html in cases:
            with self.subTest(html=html):
                self.assertEqual(candidate_links(
                    html, ANGERS, "2026-11-20"), [])
        # A card's year must not overwrite a distinct explicit anchor year.
        explicit = ('<article><p>Édition 2027</p>'
                    '<span>Musique / Concert</span><a href="'
                    '/actualites-sorties/agenda/mordorfest-2026">'
                    'MordorFest 2026</a></article>')
        hits = candidate_links(explicit, ANGERS, "2026-11-20")
        self.assertTrue(all(x["title"] != "MordorFest 2027" for x in hits))

    def test_card_year_routes_through_next_day_private_recheck_only(self):
        from regional_festival_discovery import CARD_YEAR_PENDING_SIGNAL
        from national_discovery_queue import build_queue
        from national_detail_qualification import _eligible_sources, _seen_again
        from grossesondes_institutional_edition import (
            private_proposal, independently_fetch)
        today, tomorrow = "2026-11-20", "2026-11-21"
        target = "https://www.angers.fr/actualites-sorties/agenda/mordorfest"
        card = ('<article><p>Musique / Concert</p>'
                '<a href="' + target + '">MordorFest</a>'
                '<time>Édition 2027</time></article>')
        hits = candidate_links(card, ANGERS, today)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["signal"], CARD_YEAR_PENDING_SIGNAL)
        state = {"schema": "grossesondes.source-watch.v1",
                 "institutional_agenda_candidate_pages": {},
                 "secondary_source_candidates_private": {}}
        requested = []
        saved = scan_regional_indexes(
            {"schema": "grossesondes.source-watch-report.v1",
             "date": today, "source_reference_leads_review_only": []},
            state, [B], today,
            fetch=lambda url: requested.append(url) or card, limit=1)
        self.assertEqual(requested, [ANGERS])
        self.assertEqual(len(saved), 1)
        self.assertFalse(saved[0]["publication_authorized"])
        self.assertFalse(saved[0]["date_verified"])
        next_queue = build_queue(
            state, {"schema": "grossesondes.source-watch-report.v1",
                    "date": tomorrow, "source_reference_leads_review_only": []},
            [], tomorrow)
        self.assertEqual(next_queue["publications"], 0)
        self.assertEqual(next_queue["candidate_dossiers_count"], 1)
        ready = _eligible_sources(state, next_queue, tomorrow, due_only=False)
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0]["title"], "MordorFest 2027")
        self.assertTrue(_seen_again(card, ready[0]))
        multi_link = card.replace("</article>",
                                  '<a href="/other">Autre</a></article>')
        self.assertFalse(_seen_again(multi_link, ready[0]))
        self.assertFalse(_seen_again(card.replace("2027", "2028"), ready[0]))
        proposal = private_proposal(
            ready[0], ("2027-06-25", "2027-06-26"), tomorrow)
        self.assertIsNotNone(proposal)
        fetches = []
        self.assertIsNone(independently_fetch(
            proposal, tomorrow,
            fetch=lambda url: fetches.append(url) or (
                card if url == ANGERS
                else "<h1>MordorFest 2027</h1><p>Musique / Concert</p>"
            )))
        self.assertEqual(fetches, [ANGERS, target])
        self.assertFalse(next_queue["publication_authorized"])

    def test_semantic_list_and_role_article_cards_capture_visible_music_category(self):
        from regional_festival_discovery import MUSIC_CATEGORY_PENDING_SIGNAL
        title = "HelixFest 2027"
        link = ("/actualites-sorties/agenda/helixfest-2027")
        anchor = '<h3><a href="' + link + '">' + title + '</a></h3>'
        cases = [
            "<li><p>Musique / Concert</p>" + anchor + "</li>",
            '<li><span>Concerts / Musique</span>' + anchor + "</li>",
            '<div role="article"><div class="info">'
            '<span>Musique / Concert</span></div><div>' + anchor
            + "</div></div>",
            '<div role="article"><div>' + anchor + "</div>"
            "<p>Concerts / Musique</p></div>",
            # Ordinary lists inside an already-scoped article must not
            # erase its existing card attribution.
            "<article><ul><li>Musique / Concert</li></ul>" + anchor
            + "</article>",
        ]
        for html in cases:
            with self.subTest(html=html):
                found = candidate_links(html, ANGERS, DAY)
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0]["signal"], MUSIC_CATEGORY_PENDING_SIGNAL)
                self.assertEqual(found[0]["title"], title)
                self.assertEqual(found[0]["candidate_url"],
                                 "https://www.angers.fr" + link)
                self.assertIsNone(found[0]["archive_slug"])

    def test_semantic_card_scope_does_not_accept_hidden_or_ambiguous_siblings(self):
        title = "HelixFest 2027"
        anchor = '<a href="/actualites-sorties/agenda/helixfest-2027">' + title + '</a>'
        cases = [
            "<li><span>Musique / Concert</span></li><li>" + anchor + "</li>",
            '<div role="article"><span>Musique / Concert</span></div>'
            '<div role="article">' + anchor + '</div>',
            "<div><span>Musique / Concert</span></div><div>"
            + anchor + "</div>",
            '<li><span hidden>Musique / Concert</span>' + anchor + '</li>',
            '<div role="article"><span aria-hidden="true">'
            'Musique / Concert</span>' + anchor + '</div>',
            '<div role="article"><span style="display:none">'
            'Musique / Concert</span>' + anchor + '</div>',
            '<li><span>Musique / Concert</span>' + anchor
            + '<a href="/autre">Autre</a></li>',
            '<div role="article"><span>Musique / Concert</span>' + anchor
            + '<a href="/autre">Autre</a></div>',
            '<article><p>Musique / Concert</p>' + anchor
            + '<a href="/autre">Autre</a></article>',
            '<li><span>Musique / Concert</span>'
            '<li>' + anchor + '</li></li>',
            '<div role="article"><span>Musique / Concert</span>'
            '<div role="article">' + anchor + '</div></div>',
            '<li><span>Musique / Concert</span>'
            '<a href="https://evil.example/helixfest-2027">' + title
            + '</a></li>',
            '<li><span>Culture</span>' + anchor + '</li>',
            '<li><span>Musique / Concert</span>'
            '<a href="/actualites-sorties/agenda/helixfest">HelixFest</a></li>',
            '<li><span>Musique / Concert</span>'
            '<a href="/actualites-sorties/agenda/flower-2027">'
            'Festival des Fleurs 2027</a></li>',
        ]
        for html in cases:
            with self.subTest(html=html):
                self.assertEqual(candidate_links(html, ANGERS, DAY), [])

    def test_semantic_discovery_remains_private_and_never_authorizes_publisher(self):
        from regional_festival_discovery import MUSIC_CATEGORY_PENDING_SIGNAL
        from national_discovery_queue import build_queue
        from national_detail_qualification import _eligible_sources
        source = '<li><span>Concerts / Musique</span><a href="' \
                 '/actualites-sorties/agenda/festibarockin-2027">' \
                 "Festibarock'in 2027</a></li>"
        state = {"schema": "grossesondes.source-watch.v1",
                 "institutional_agenda_candidate_pages": {},
                 "secondary_source_candidates_private": {}}
        watched = []
        scan = scan_regional_indexes(
            report(), state, [B], DAY,
            fetch=lambda url: watched.append(url) or source, limit=1)
        self.assertEqual(watched, [ANGERS])
        self.assertEqual(len(scan), 1)
        self.assertEqual(scan[0]["discovery_signal"],
                         MUSIC_CATEGORY_PENDING_SIGNAL)
        self.assertIs(scan[0]["publication_authorized"], False)
        self.assertIs(scan[0]["date_verified"], False)
        tomorrow = "2026-11-06"
        review = build_queue(
            state, {"schema": "grossesondes.source-watch-report.v1",
                    "date": tomorrow, "source_reference_leads_review_only": []},
            [], tomorrow)
        self.assertEqual(review["candidate_dossiers_count"], 1)
        self.assertEqual(review["publications"], 0)
        self.assertIs(review["publication_authorized"], False)
        eligible = _eligible_sources(state, review, tomorrow, due_only=False)
        self.assertEqual(len(eligible), 1)
        self.assertEqual(eligible[0]["index_url"], ANGERS)
        self.assertIs(review["dossiers"][0]["publication_authorized"], False)

    def test_compound_festival_brand_music_category_is_discovery_only(self):
        from regional_festival_discovery import MUSIC_CATEGORY_PENDING_SIGNAL
        # The compound festival token nominates no event without an exact
        # future year, one uniquely attributed visible institutional card
        # and a general music category. It cannot prove rock/metal/punk.
        def card(title, category="Musique / Concert", hidden=False, extra=""):
            attribute = ' hidden' if hidden else ''
            return (
                '<article><p' + attribute + '>' + category + '</p>'
                '<h3><a href="/actualites-sorties/agenda/branded-2027">'
                + title + '</a></h3>' + extra + '</article>'
            )

        for title in ("HelixFest 2027", "MordorFest 2027",
                      "Festibarock'in 2027", "ProtoFest 2027"):
            with self.subTest(title=title):
                hits = candidate_links(card(title), ANGERS, DAY)
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0]["signal"], MUSIC_CATEGORY_PENDING_SIGNAL)
                self.assertIsNone(hits[0]["archive_slug"])
                self.assertEqual(hits[0]["title"], title)

        for title in ("HelixFest", "HelixFest 2032",
                      "Festivités musicales 2027", "Festin gourmand 2027",
                      "Festival des plantes 2027"):
            with self.subTest(title=title):
                self.assertEqual(candidate_links(card(title), ANGERS, DAY), [])
        self.assertEqual(candidate_links(card("HelixFest 2027", hidden=True),
                                         ANGERS, DAY), [])
        self.assertEqual(candidate_links(card("HelixFest 2027", category="Culture"),
                                         ANGERS, DAY), [])
        self.assertEqual(candidate_links(
            card("HelixFest 2027", extra='<a href="/other">Autre</a>'),
            ANGERS, DAY), [])
        # A neighbouring festival cannot borrow an adjacent card's label.
        adjacent = ('<article><p>Musique / Concert</p></article>'
                    '<article><h3><a href="/actualites-sorties/agenda/branded-2027">'
                    'HelixFest 2027</a></h3></article>')
        self.assertEqual(candidate_links(adjacent, ANGERS, DAY), [])

    def test_genreless_named_festival_in_visible_music_category_is_private_lead(self):
        from regional_festival_discovery import MUSIC_CATEGORY_PENDING_SIGNAL
        from national_discovery_queue import build_queue
        from national_detail_qualification import _eligible_sources
        title = "Festival des Rivages 2027"
        detail = "https://www.angers.fr/actualites-sorties/agenda/festival-des-rivages-2027"
        html = ('<article><div>Musique / Concert <a href="' + detail +
                '">' + title + '</a></div></article>')
        result = candidate_links(html, ANGERS, DAY)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["signal"], MUSIC_CATEGORY_PENDING_SIGNAL)
        self.assertEqual(result[0]["candidate_url"], detail)
        self.assertEqual(candidate_links(
            '<article><a href="' + detail + '">' + title + '</a></article>',
            ANGERS, DAY), [])
        for disallowed in ("Festival des plantes 2027",
                           "Festival des Rivages", "Festival des Rivages 2032"):
            with self.subTest(name=disallowed):
                self.assertEqual(candidate_links(
                    html.replace(title, disallowed), ANGERS, DAY), [])
        state = {"schema": "grossesondes.source-watch.v1",
                 "institutional_agenda_candidate_pages": {},
                 "secondary_source_candidates_private": {}}
        report = {"schema": "grossesondes.source-watch-report.v1",
                  "date": DAY, "source_reference_leads_review_only": []}
        seen = []
        rows = scan_regional_indexes(
            report, state, [B], DAY,
            fetch=lambda url: seen.append(url) or html, limit=1)
        self.assertEqual(seen, [ANGERS])
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["publication_authorized"])
        self.assertFalse(rows[0]["date_verified"])
        next_day = "2026-11-06"
        queue = build_queue(state, {
            "schema": "grossesondes.source-watch-report.v1",
            "date": next_day, "source_reference_leads_review_only": []
        }, [], next_day)
        self.assertEqual(queue["candidate_dossiers_count"], 1)
        sources = _eligible_sources(state, queue, next_day, due_only=False)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["url"], detail)
        self.assertEqual(queue["publications"], 0)


    def test_sibling_visible_category_in_single_article_is_private_only(self):
        from regional_festival_discovery import MUSIC_CATEGORY_PENDING_SIGNAL
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from grossesondes_institutional_edition import (
            independently_fetch, private_proposal)
        title = "Festival des Rivages 2027"
        url = ("https://www.angers.fr/actualites-sorties/agenda/"
               "festival-des-rivages-2027")
        separate_siblings = (
            '<article class="event-card"><p>Musique / Concert</p>'
            '<h3><a href="' + url + '">' + title + '</a></h3>'
            '</article>')
        found = candidate_links(separate_siblings, ANGERS, DAY)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["signal"], MUSIC_CATEGORY_PENDING_SIGNAL)
        self.assertEqual(found[0]["candidate_url"], url)
        self.assertEqual(found[0]["title"], title)
        self.assertEqual(found[0]["archive_slug"], None)
        # No independent metal/rock/punk proof on the official event detail.
        spec = {"index_url": ANGERS, "index_page": ANGERS,
                "url": url, "title": title, "year": 2027}
        proposal = private_proposal(
            spec, ("2027-06-04", "2027-06-05"), DAY)
        self.assertIsNotNone(proposal)
        seen = []
        def fetch(u):
            seen.append(u)
            if u == ANGERS:
                return separate_siblings
            self.assertEqual(u, url)
            return ('<h1>Festival des Rivages 2027</h1>'
                    '<p>Les 4 et 5 juin 2027.</p>')
        self.assertIsNone(independently_fetch(proposal, DAY, fetch=fetch))
        self.assertEqual(seen, [ANGERS, url])

    def test_article_category_cannot_leak_or_accept_hidden_or_ambiguous_cards(self):
        title = "Festival des Rivages 2027"
        url = "/actualites-sorties/agenda/festival-des-rivages-2027"
        anchor = '<h3><a href="' + url + '">' + title + '</a></h3>'
        cases = (
            # Category belongs to another article.
            "<article><p>Musique / Concert</p></article><article>" + anchor + "</article>",
            # Hidden category, script, or aria-hidden region is never evidence.
            '<article><p hidden>Musique / Concert</p>' + anchor + "</article>",
            '<article><p aria-hidden="true">Musique / Concert</p>' + anchor + "</article>",
            '<article><script>Musique / Concert</script>' + anchor + "</article>",
            '<article><div style="display:none">Musique / Concert</div>' + anchor + "</article>",
            # Two distinct visible links: ambiguous card ownership.
            '<article><p>Musique / Concert</p><a href="/autre">Autre</a>' + anchor + "</article>",
            # Multi-card parent may not attribute one child category to a sibling.
            '<article><p>Musique / Concert</p><article>' + anchor + "</article></article>",
            # Unrelated sibling DIV is still forbidden by the older local parser.
            '<div><p>Musique / Concert</p></div><div>' + anchor + "</div>",
            # Festival without exact edition year, and non-music festival.
            '<article><p>Musique / Concert</p><h3><a href="' + url +
            '">Festival des Rivages</a></h3></article>',
            '<article><p>Musique / Concert</p><h3><a href="' + url +
            '">Festival des fleurs 2027</a></h3></article>',
        )
        for html in cases:
            with self.subTest(html=html):
                self.assertEqual(candidate_links(html, ANGERS, DAY), [])


    def test_primary_name_crossmatch_finds_unusual_festival_on_approved_index_only(self):
        from regional_festival_discovery import (
            private_prior_primary_name_hints, PRIMARY_CROSS_SIGNAL)
        from national_discovery_queue import build_queue
        from national_detail_qualification import _eligible_sources
        primary = "https://www.festibarockin.fr/"
        name = "Festibarock'in"
        title = "Festibarock'in 2027"
        detail = ("https://www.angers.fr/actualites-sorties/agenda/"
                  "festibarock-in-2027")
        day1 = "2026-11-05"
        prior = {
            "schema": "grossesondes.national-festival-discovery-private.v1",
            "as_of": day1, "review_only": True, "safe_to_publish": False,
            "publication_authorized": False, "publications": 0,
            "dossiers": [{
                "id": "national-1234567890abcdef1234",
                "name_hint": name, "normalized_name": "festibarock in",
                "edition_year_hint": 2027, "region_hint": "Pays de la Loire",
                "safe_to_publish": False, "publication_authorized": False,
                "sources": [{
                    "kind": "CURATED_PRIMARY_CANDIDATE",
                    "url": primary, "discovered_via": primary,
                    "publication_authorized": False,
                }],
            }],
        }
        expected = frozenset({("festibarock in", 2027, "Pays de la Loire")})
        self.assertEqual(private_prior_primary_name_hints(prior, day1), expected)
        html = '<article><a href="' + detail + '">' + title + '</a></article>'
        self.assertEqual(candidate_links(html, ANGERS, day1), [])
        links = candidate_links(html, ANGERS, day1,
                                primary_name_hints=expected)
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["signal"], PRIMARY_CROSS_SIGNAL)
        state = {"schema": "grossesondes.source-watch.v1",
                 "institutional_agenda_candidate_pages": {},
                 "secondary_source_candidates_private": {}}
        report1 = {"schema": "grossesondes.source-watch-report.v1",
                   "date": day1, "source_reference_leads_review_only": []}
        recorded = scan_regional_indexes(
            report1, state, [B], day1,
            fetch=lambda url: html, limit=1, prior_primary_queue=prior)
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]["discovery_signal"], PRIMARY_CROSS_SIGNAL)
        self.assertFalse(recorded[0]["publication_authorized"])
        self.assertEqual(report1["regional_festival_primary_name_hints_review_only"], 1)
        self.assertEqual(report1["regional_festival_primary_matched_new_review_only"], 1)
        day2 = "2026-11-06"
        q = build_queue(state, {"schema": "grossesondes.source-watch-report.v1",
                                "date": day2, "source_reference_leads_review_only": []},
                        [], day2)
        self.assertEqual(q["candidate_dossiers_count"], 1)
        self.assertEqual(len(_eligible_sources(state, q, day2, due_only=False)), 1)
        self.assertFalse(q["dossiers"][0]["publication_authorized"])

    def test_prior_first_party_hint_fails_closed_for_stale_or_secondary_input(self):
        from regional_festival_discovery import private_prior_primary_name_hints
        good = {
            "schema": "grossesondes.national-festival-discovery-private.v1",
            "as_of": DAY, "review_only": True, "safe_to_publish": False,
            "publication_authorized": False, "publications": 0,
            "dossiers": [{
                "name_hint": "Festibarock'in",
                "normalized_name": "festibarock in",
                "edition_year_hint": 2027, "region_hint": "Pays de la Loire",
                "safe_to_publish": False, "publication_authorized": False,
                "sources": [{
                    "kind": "CURATED_PRIMARY_CANDIDATE",
                    "url": "https://www.festibarockin.fr/",
                    "discovered_via": "https://www.festibarockin.fr/",
                    "publication_authorized": False,
                }],
            }],
        }
        from copy import deepcopy
        variants = []
        for key, value in (
                ("safe_to_publish", True),
                ("publication_authorized", True),
                ("as_of", "2026-10-01")):
            altered = deepcopy(good)
            altered[key] = value
            variants.append(altered)
        for key, value in (
                ("region_hint", "Autre pays"),
                ("edition_year_hint", 2032),
                ("normalized_name", "another festival")):
            altered = deepcopy(good)
            altered["dossiers"][0][key] = value
            variants.append(altered)
        for key, value in (
                ("kind", "REGIONAL_INDEX_UNVERIFIED"),
                ("discovered_via", "https://evil.example/"),
                ("publication_authorized", True)):
            altered = deepcopy(good)
            altered["dossiers"][0]["sources"][0][key] = value
            variants.append(altered)
        for variant in variants:
            with self.subTest(case=variant):
                self.assertEqual(private_prior_primary_name_hints(
                    variant, DAY), frozenset())
        self.assertEqual(private_prior_primary_name_hints(
            good, "2026-11-07"), frozenset())

    def test_openagenda_compound_brand_exact_match_to_institution_stays_private(self):
        from national_openagenda_research import scan as scan_openagenda
        from regional_festival_discovery import (
            CROSS_SOURCE_SIGNAL, private_openagenda_name_hints)
        from national_discovery_queue import build_queue
        from national_detail_qualification import _eligible_sources
        from grossesondes_institutional_edition import (
            private_proposal, independently_fetch)
        today = "2026-11-20"
        tomorrow = "2026-11-21"
        title = "ForgeFest 2027"
        target = ("https://www.angers.fr/actualites-sorties/agenda/"
                  "forgefest-2027")
        html = '<a href="' + target + '">' + title + '</a>'
        event = {
            "title_fr": title,
            "canonicalurl": "https://openagenda.com/metal/events/forgefest-2027",
            "description_fr": "Festival de punk rock et thrash metal",
            "keywords_fr": ["thrash metal"],
            "location_countrycode": "FR",
            "location_region": "Pays de la Loire",
            "firstdate_begin": "2027-06-25T19:00:00+02:00",
            "lastdate_begin": "2027-06-26T23:00:00+02:00",
        }
        state = {"schema": "grossesondes.source-watch.v1",
                 "institutional_agenda_candidate_pages": {},
                 "secondary_source_candidates_private": {}}
        scan_openagenda(state, today, fetch=lambda _: {
            "total_count": 1, "results": [event]})
        hints = private_openagenda_name_hints(state, today)
        self.assertEqual(hints, frozenset({
            ("forgefest", 2027, "Pays de la Loire")}))
        self.assertEqual(candidate_links(html, ANGERS, today), [])
        found = candidate_links(html, ANGERS, today,
                                openagenda_name_hints=hints)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["candidate_url"], target)
        self.assertEqual(found[0]["signal"], CROSS_SOURCE_SIGNAL)
        self.assertEqual(candidate_links(html, LIMOGES, today,
                                         openagenda_name_hints=hints), [])
        no_year = html.replace("ForgeFest 2027", "ForgeFest")
        self.assertEqual(candidate_links(no_year, ANGERS, today,
                                         openagenda_name_hints=hints), [])
        visits = []
        recorded = scan_regional_indexes(
            {"schema": "grossesondes.source-watch-report.v1",
             "date": today, "source_reference_leads_review_only": []},
            state, [B], today, fetch=lambda url: visits.append(url) or html,
            limit=1)
        self.assertEqual(visits, [ANGERS])
        self.assertEqual(len(recorded), 1)
        self.assertFalse(recorded[0]["publication_authorized"])
        self.assertFalse(recorded[0]["date_verified"])
        queue = build_queue(
            state, {"schema": "grossesondes.source-watch-report.v1",
                    "date": tomorrow, "source_reference_leads_review_only": []},
            [], tomorrow)
        sources = _eligible_sources(state, queue, tomorrow, due_only=False)
        self.assertEqual(len(sources), 1)
        proposal = private_proposal(
            sources[0], ("2027-06-25", "2027-06-26"), tomorrow)
        self.assertIsNotNone(proposal)
        # An OpenAgenda genre is not independent evidence. The trusted
        # institution has not itself confirmed rock/punk/metal on its detail,
        # so the real publisher refuses admission.
        publisher_fetches = []
        self.assertIsNone(independently_fetch(
            proposal, tomorrow,
            fetch=lambda url: publisher_fetches.append(url) or html))
        self.assertEqual(publisher_fetches, [ANGERS, target])
        self.assertFalse(queue["publication_authorized"])

    def test_openagenda_name_plus_year_and_region_can_nominate_only_a_live_institutional_link(self):
        """A research clue can find a genre-less title, NEVER authorize publication."""
        from national_openagenda_research import scan as scan_openagenda
        from regional_festival_discovery import (
            private_openagenda_name_hints, CROSS_SOURCE_SIGNAL)
        from national_discovery_queue import build_queue
        from national_detail_qualification import _eligible_sources
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        from grossesondes_institutional_edition import (
            independently_fetch, private_proposal)
        source = ANGERS
        title = "Festival des Rivages 2027"
        detail = "https://www.angers.fr/actualites-sorties/agenda/festival-des-rivages-2027"
        event = {
            "title_fr": title,
            "canonicalurl": "https://openagenda.com/agenda-rock/events/festival-des-rivages-2027",
            "description_fr": "Festival rock et métal.",
            "keywords_fr": ["rock"],
            "location_countrycode": "FR",
            "location_region": "Pays de la Loire",
            "firstdate_begin": "2027-06-04T18:00:00+02:00",
            "lastdate_begin": "2027-06-05T23:00:00+02:00",
        }
        body = '<main><a href="' + detail + '">' + title + '</a></main>'
        today = "2026-11-05"
        self.assertEqual(candidate_links(body, source, today), [])
        state = {"schema": "grossesondes.source-watch.v1",
                 "institutional_agenda_candidate_pages": {},
                 "secondary_source_candidates_private": {}}
        research = scan_openagenda(
            state, today, fetch=lambda _: {"total_count": 1, "results": [event]})
        self.assertEqual(research["leads_count"], 1)
        hints = private_openagenda_name_hints(state, today)
        self.assertEqual(hints, frozenset({
            ("festival des rivages", 2027, "Pays de la Loire")}))
        direct = candidate_links(
            body, source, today, openagenda_name_hints=hints)
        self.assertEqual(len(direct), 1)
        self.assertEqual(direct[0]["candidate_url"], detail)
        self.assertEqual(direct[0]["signal"], CROSS_SOURCE_SIGNAL)
        self.assertEqual(direct[0]["archive_slug"], None)
        visits = []
        recorded = scan_regional_indexes(
            {"schema": "grossesondes.source-watch-report.v1",
             "date": today, "source_reference_leads_review_only": []},
            state, [B], today,
            fetch=lambda u: visits.append(u) or body, limit=1)
        self.assertEqual(visits, [source])  # No OpenAgenda/detail request.
        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]["discovery_signal"], CROSS_SOURCE_SIGNAL)
        self.assertIs(recorded[0]["publication_authorized"], False)
        self.assertIs(recorded[0]["date_verified"], False)
        self.assertEqual(recorded[0]["source_index"], source)
        report = {"schema": "grossesondes.source-watch-report.v1",
                  "date": "2026-11-06", "source_reference_leads_review_only": []}
        national = build_queue(state, report, [], "2026-11-06")
        self.assertEqual(national["candidate_dossiers_count"], 1)
        self.assertEqual(national["publications"], 0)
        self.assertFalse(national["dossiers"][0]["festival_verified"])
        self.assertFalse(national["dossiers"][0]["edition_dates_verified"])
        sources = _eligible_sources(state, national, "2026-11-06", due_only=False)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["url"], detail)
        self.assertEqual(sources[0]["index_url"], source)
        # No publisher admission from the research clue: an index-only
        # link without independent music context still fails publisher.
        proposal = private_proposal(sources[0],
                                    ("2027-06-04", "2027-06-05"),
                                    "2026-11-06")
        self.assertIsNotNone(proposal)
        checked = []
        self.assertIsNone(independently_fetch(
            proposal, "2026-11-06",
            fetch=lambda u: checked.append(u) or body))
        self.assertEqual(checked, [source, detail])  # #488 safely re-fetches same-host detail.
        self.assertEqual(national["publications"], 0)

    def test_openagenda_crossmatch_cannot_override_source_year_or_region(self):
        from national_openagenda_research import scan as scan_openagenda
        from regional_festival_discovery import private_openagenda_name_hints
        year = "2026-11-05"
        template = {
            "title_fr": "Festival des Rivages 2027",
            "canonicalurl": "https://openagenda.com/agenda-rock/events/festival-des-rivages-2027",
            "description_fr": "Festival metal et rock",
            "keywords_fr": ["metal"],
            "location_countrycode": "FR",
            "location_region": "Pays de la Loire",
            "firstdate_begin": "2027-06-04T18:00:00+02:00",
            "lastdate_begin": "2027-06-05T23:00:00+02:00",
        }
        state = {"schema": "grossesondes.source-watch.v1"}
        scan_openagenda(state, year, fetch=lambda _: {
            "total_count": 1, "results": [template]})
        hints = private_openagenda_name_hints(state, year)
        url = "https://www.angers.fr/actualites-sorties/agenda/festival-des-rivages-2027"
        variants = (
            ("Festival des Rivages 2028", url),
            ("Festival des Rivages 2026", url),
            ("Festival des Rivages 2027 Junior", url),
            ("Festival des Rivages 2027 / Spectacle", url),
            ("Festival des Rivages 2027", "https://evil.example/invalid"),
            ("Festival des Rivages 2027", "http://www.angers.fr/invalid"),
            ("Festival des Rivages 2027", "https://www.angers.fr/piece.pdf"),
        )
        for title, location in variants:
            with self.subTest(title=title, url=location):
                html = '<a href="' + location + '">' + title + '</a>'
                self.assertEqual(candidate_links(
                    html, ANGERS, year, openagenda_name_hints=hints), [])
        # The same title observed on a different reviewed REGION is not
        # a counterpart, and a yearless source may not borrow a year.
        limoges = (
            '<a href="/agenda/festival-des-rivages-2027">'
            'Festival des Rivages 2027</a>')
        self.assertEqual(candidate_links(
            limoges, LIMOGES, year, openagenda_name_hints=hints), [])
        self.assertEqual(candidate_links(
            '<a href="/actualites-sorties/agenda/festival-des-rivages">'
            'Festival des Rivages</a>',
            ANGERS, year, openagenda_name_hints=hints), [])
        # Poisoning a private research report cannot add an independent link.
        state["national_openagenda_research_private"]["publication_authorized"] = True
        self.assertEqual(private_openagenda_name_hints(state, year), frozenset())
        state["national_openagenda_research_private"]["publication_authorized"] = False
        state["national_openagenda_research_private"]["leads"][0]["source_url"] = (
            "https://127.0.0.1/admin")
        self.assertEqual(private_openagenda_name_hints(state, year), frozenset())

    def test_municipal_event_label_recovers_archive_identity_not_navigation(self):
        # Municipal agenda labels are longer than the event's real title.
        source = ANGERS
        label = "Plus d'information sur l'évènement : Hellfest 2027"
        html = '<a href="/actualites-sorties/agenda/hellfest-2027">' + label + '</a>'
        archive = {"hellfest": {"slug": "hellfest", "last_known_year": 2026}}
        found = candidate_links(html, source, "2026-11-06", archive)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["title"], "Hellfest 2027")
        self.assertEqual(found[0]["archive_slug"], "hellfest")
        self.assertEqual(found[0]["signal"], ARCHIVE_SIGNAL)
        self.assertEqual(found[0]["candidate_url"],
                         "https://www.angers.fr/actualites-sorties/agenda/hellfest-2027")
        self.assertNotIn("date_verified", found[0])

    def test_visible_generic_button_can_use_explicit_municipal_aria_label(self):
        html = (
            '<article><a href="/actualites-sorties/agenda/metal-fest-2027" '
            'aria-label="Plus d&#39;information sur l&#39;évènement : '
            'Metal Fest des Rives 2027">En savoir plus</a></article>')
        found = candidate_links(html, ANGERS, "2026-11-06")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["title"], "Metal Fest des Rives 2027")
        self.assertEqual(found[0]["signal"], "THEMATIC_NAME_ONLY")
        self.assertTrue(found[0]["candidate_url"].startswith("https://www.angers.fr/"))

    def test_municipal_accessibility_metadata_never_overrides_specific_visible_title(self):
        html = ('<a href="/actualites-sorties/agenda/visible-concert" '
                'aria-label="Plus d’information sur l’évènement : Metal Fest 2027">'
                'Concert de jazz 2027</a>')
        self.assertEqual(candidate_links(html, ANGERS, "2026-11-06"), [])

    def test_municipal_event_names_stay_private_and_reject_untrusted_links(self):
        source = ANGERS
        html = (
            '<div hidden><a href="/actualites-sorties/agenda/hidden" '
            'aria-label="Plus d’information sur l’évènement : Metal Fest 2027">'
            'En savoir plus</a></div>'
            '<script><a href="/actualites-sorties/agenda/script">'
            "Plus d'information sur l'évènement : Metal Fest 2027</a></script>"
            '<a href="https://evil.example/fest" '
            'aria-label="Plus d’information sur l’évènement : Metal Fest 2027">'
            'En savoir plus</a>'
            '<a href="/actualites-sorties/agenda/old-fest" '
            'aria-label="Plus d’information sur l’évènement : Metal Fest 2022">'
            'En savoir plus</a>'
            '<a href="/actualites-sorties/agenda/generic" '
            'aria-label="Plus d’information sur l’évènement : Festival des plantes 2027">'
            'En savoir plus</a>'
            '<a href="/actualites-sorties/agenda/ticket.pdf" '
            'aria-label="Plus d’information sur l’évènement : Metal Fest 2027">'
            'En savoir plus</a>'
            '<a href="/actualites-sorties/agenda/suspect" '
            'aria-label="Plus d’information sur l’évènement sans titre">'
            'En savoir plus</a>'
        )
        self.assertEqual(candidate_links(html, source, "2026-11-06"), [])

    def test_accessible_municipal_lead_is_never_approved_by_scan(self):
        html = ('<a href="/actualites-sorties/agenda/metal-fest-2027" '
                'aria-label="Plus d’information sur l’évènement : Metal Fest 2027">'
                'En savoir plus</a>')
        state = {}
        r = report("2026-11-06")
        found = scan_regional_indexes(
            r, state, [B], "2026-11-06", lambda _: html, limit=1)
        self.assertEqual(len(found), 1)
        self.assertIs(found[0]["publication_authorized"], False)
        self.assertEqual(r["regional_festival_publications"], 0)
        self.assertEqual(r["regional_festival_detail_pages_checked_review_only"], 0)

    def test_allowlist_never_accepts_dynamic_hosts_or_region_spoofs(self):
        self.assertEqual(load_indexes({"schema":SCHEMA,"indexes":[A]}),[A])
        for bad in (dict(A,url="https://127.0.0.1/agenda"),
                    dict(A,url="https://evil.fr/agenda"),
                    dict(A,region="Grand Est"),dict(A,url="http://sortir.limoges.fr/agenda")):
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                load_indexes({"schema":SCHEMA,"indexes":[bad]})
        with self.assertRaises(ValueError):
            load_indexes({"schema":SCHEMA,"indexes":[A,A]})
    def test_national_config_covers_overseas_and_only_curated_https(self):
        import json
        file = Path(__file__).with_name("regional_festival_indexes.json")
        source = json.loads(file.read_text(encoding="utf-8"))
        seeds = load_indexes(source)
        self.assertEqual(len(seeds), 25)
        self.assertEqual(len({s["region"] for s in seeds}), 20)
        self.assertEqual(len({s["url"] for s in seeds}), 25)
        self.assertEqual({
            "La Réunion", "Martinique", "Guadeloupe", "Nouvelle-Calédonie",
            "Guyane", "Mayotte", "Polynésie française"
        } - {s["region"] for s in seeds}, set())
        self.assertEqual(set(APPROVED), {s["url"] for s in seeds})
        for seed in seeds:
            self.assertTrue(seed["url"].startswith("https://"))
            if "?" in seed["url"]:
                self.assertIn(seed["url"], (
                    "https://sortir.limoges.fr/agenda?keys=rock",
                    "https://sortir.limoges.fr/agenda?keys=festival"))
        source["indexes"].append(dict(seeds[0], id="unapproved-copy"))
        with self.assertRaises(ValueError):
            load_indexes(source)

    def test_additional_overseas_indexes_never_authorize_a_festival(self):
        from regional_festival_discovery import MAX_INDEXES
        first_party_indexes = [
            {"id": "guy-trois-fleuves", "region": "Guyane",
             "url": "https://troisfleuves.fr/etn_category/concerts/"},
            {"id": "myt-departement-festivals", "region": "Mayotte",
             "url": "https://www.mayotte.fr/vie-locale/evenements/festivals"},
            {"id": "pyf-tahiti-tourisme", "region": "Polynésie française",
             "url": "https://tahititourisme.pf/agenda/"},
        ]
        self.assertEqual(load_indexes(
            {"schema": SCHEMA, "indexes": first_party_indexes}),
            first_party_indexes)
        self.assertLessEqual(len(first_party_indexes), MAX_INDEXES)
        for seed in first_party_indexes:
            with self.subTest(territory=seed["region"]):
                bad_region = dict(seed, region="Corse")
                bad_host = dict(seed, url="https://unapproved.example/agenda/")
                for mutated in (bad_region, bad_host):
                    with self.assertRaises(ValueError):
                        load_indexes({"schema": SCHEMA, "indexes": [mutated]})
                state = {}
                r = report("2026-11-06")
                html = (
                    '<article><a href="' + seed["url"].rstrip("/") +
                    '/metal-festival-2027">Rock Metal Festival 2027</a></article>'
                )
                scan_regional_indexes(
                    r, state, [seed], "2026-11-06",
                    lambda url: html, limit=1)
                self.assertEqual(r["regional_festival_publications"], 0)
                self.assertEqual(
                    r["regional_festival_detail_pages_checked_review_only"], 0)
                for item in state.get(
                        "regional_festival_candidates_review_only", {}).values():
                    self.assertIs(item["publication_authorized"], False)

    def test_overseas_seed_is_private_only_and_wrong_region_is_denied(self):
        site = "https://www.lesilesdeguadeloupe.com/agenda/"
        seed = {"id": "glp-tourisme", "region": "Guadeloupe", "url": site}
        self.assertEqual(load_indexes({"schema": SCHEMA, "indexes": [seed]}),
                         [seed])
        for unsafe in (dict(seed, region="Martinique"),
                       dict(seed, url="https://evil.example/agenda/"),
                       dict(seed, url="https://www.lesilesdeguadeloupe.com/agenda/?next=https://evil.example")):
            with self.subTest(unsafe=unsafe), self.assertRaises(ValueError):
                load_indexes({"schema": SCHEMA, "indexes": [unsafe]})
        html = ('<main><a href="/fete-manifestation/metal-fest-2027/">'
                'Metal Fest 2027</a></main>')
        state, r = {}, report("2026-11-06")
        found = scan_regional_indexes(r, state, [seed], "2026-11-06",
                                      lambda _: html, limit=1)
        self.assertEqual(len(found), 1)
        self.assertIs(found[0]["publication_authorized"], False)
        self.assertEqual(r["regional_festival_publications"], 0)
        self.assertEqual(r["regional_festival_detail_pages_checked_review_only"], 0)
        self.assertTrue(found[0]["candidate_url"].startswith(
            "https://www.lesilesdeguadeloupe.com/"))

    def test_region_metrics_distinguish_configured_attempted_scanned(self):
        r = report()
        state = {}
        scan_regional_indexes(r, state, [A,B], DAY,
                              lambda url: page() if url == LIMOGES else "",
                              limit=1)
        self.assertEqual(r["regional_festival_configured_sources_review_only"], 2)
        self.assertEqual(r["regional_festival_configured_regions_review_only"], 2)
        self.assertEqual(r["regional_festival_regions_attempted_review_only"], 1)
        self.assertEqual(r["regional_festival_scanned_this_pass_review_only"], 1)
        self.assertEqual(r["regional_festival_inaccessible_this_pass_review_only"], 0)
        r2 = report()
        scan_regional_indexes(r2, state, [A,B], DAY,
                              lambda _: (_ for _ in ()).throw(OSError("403")),
                              limit=1)
        self.assertEqual(r2["regional_festival_regions_attempted_review_only"], 2)
        self.assertEqual(r2["regional_festival_regions_this_pass_review_only"], 1)
        self.assertEqual(r2["regional_festival_scanned_this_pass_review_only"], 0)
        self.assertEqual(r2["regional_festival_inaccessible_this_pass_review_only"], 1)
        self.assertEqual(r2["regional_festival_publications"], 0)

    def test_visible_unmatched_vs_linkless_script_diagnostics_not_festival_proof(self):
        variants = (
            ("<html><script src='/app.js'></script><main>Chargement</main></html>",
             "NO_VISIBLE_LINKS", 1, 0, 1),
            ("<main><a href='/agenda/concert'>Concert de métal</a></main>",
             "VISIBLE_LINKS_NO_CANDIDATE", 0, 1, 0),
            ("<main><a href='/agenda/shred-fest-2027'>Shred Fest 2027</a></main>",
             "CANDIDATE_LINKS_REVIEW_ONLY", 0, 0, 0),
        )
        for html, diagnostic, linkless, unmatched, maybe_dynamic in variants:
            with self.subTest(diagnostic=diagnostic):
                r = report()
                state = {}
                scan_regional_indexes(r, state, [A], DAY,
                                      lambda _: html, limit=1)
                self.assertEqual(
                    r["regional_festival_indexes_review_only"][0]["page_diagnostic"],
                    diagnostic)
                self.assertEqual(
                    r["regional_festival_no_visible_links_review_only"], linkless)
                self.assertEqual(
                    r["regional_festival_visible_unmatched_review_only"], unmatched)
                self.assertEqual(
                    r["regional_festival_possible_dynamic_review_only"], maybe_dynamic)
                self.assertEqual(r["regional_festival_publications"], 0)

    def test_curated_search_pages_cannot_be_mutated_by_external_queries(self):
        config={"schema":SCHEMA, "indexes":[
            {"id":"na-rock-query", "region":"Nouvelle-Aquitaine",
             "url":"https://sortir.limoges.fr/agenda?keys=rock"}]}
        self.assertEqual(load_indexes(config),config["indexes"])
        for url in (
            "https://sortir.limoges.fr/agenda?keys=metal",
            "https://sortir.limoges.fr/agenda?keys=rock&page=999",
            "https://sortir.limoges.fr/agenda?keys=festival&next=http://127.0.0.1",
            "https://sortir.limoges.fr/agenda?keys=rock#foo",
            "https://sortir.limoges.fr/agenda?keys=festival&keys=rock",
        ):
            config["indexes"][0]["url"]=url
            with self.subTest(url=url), self.assertRaises(ValueError):
                load_indexes(config)
        # A pagination-only link on the same path is not a festival.
        source="https://sortir.limoges.fr/agenda?keys=festival"
        page='<a href="?keys=festival&page=1">Metal Fest 2027</a>'
        self.assertEqual(candidate_links(page,source,DAY),[])

    def test_curated_visible_result_counts_seed_only_delayed_private_pagination(self):
        rock = LIMOGES + "?keys=rock"
        first = rock + "&page=1"
        second = rock + "&page=2"
        html = "<main>Affichage des événements 1 à 9 sur 25 au total</main>"
        self.assertEqual(curated_count_pages(html, rock, rock), [first, second])
        seed = {"id": "na-rock-query", "region": "Nouvelle-Aquitaine",
                "url": rock}
        state, visits = {}, []
        def fetch(url):
            visits.append(url)
            return page() if url == first else html
        r = report()
        found = scan_regional_indexes(r, state, [seed], DAY, fetch, limit=1)
        self.assertEqual(found, [])
        self.assertEqual(visits, [rock])
        self.assertEqual(r["regional_festival_pagination_discovered_review_only"], 2)
        self.assertEqual(r["regional_festival_pagination_checked_review_only"], 0)
        self.assertEqual(set(state["regional_festival_page_queue_review_only"]),
                         {first, second})
        self.assertEqual(r["regional_festival_publications"], 0)
        visits.clear()
        following = "2026-11-06"
        r2 = report(following)
        found = scan_regional_indexes(r2, state, [seed], following, fetch, limit=2)
        self.assertIn(first, visits)
        self.assertEqual(len(visits), 2)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["candidate_url"], TARGET)
        self.assertEqual(found[0]["source_page"], first)
        self.assertEqual(found[0]["source_index"], rock)
        self.assertEqual(state["regional_festival_candidates_review_only"][TARGET]["source_page"], first)
        self.assertFalse(found[0]["publication_authorized"])
        self.assertEqual(r2["regional_festival_detail_pages_checked_review_only"], 0)
        self.assertEqual(r2["regional_festival_publications"], 0)

    def test_curated_page_counts_fail_closed_for_other_hosts_hidden_or_invalid(self):
        rock = LIMOGES + "?keys=rock"
        good = "<p>Affichage des événements 1 à 9 sur 25 au total</p>"
        self.assertEqual(curated_count_pages(good, LIMOGES, LIMOGES), [])
        self.assertEqual(curated_count_pages(good, ANGERS, ANGERS), [])
        self.assertEqual(curated_count_pages(good, rock + "&page=1", rock), [])
        self.assertEqual(curated_count_pages(good, LIMOGES + "?keys=metal",
                                             LIMOGES + "?keys=metal"), [])
        self.assertEqual(curated_count_pages("<script>" + good + "</script>",
                                             rock, rock), [])
        for bad in ("Affichage des événements 10 à 18 sur 25 au total",
                    "Affichage des événements 1 à 9 sur 9 au total",
                    "Affichage des événements 1 à 0 sur 25 au total",
                    "Affichage des événements 1 à 9 sur 9999 au total"):
            with self.subTest(bad=bad):
                self.assertEqual(curated_count_pages(bad, rock, rock), [])

    def test_independent_link_does_not_require_existing_catalogue_lead(self):
        self.assertEqual(candidate_links(page(),LIMOGES,DAY),
                         [{"candidate_url":TARGET,"title":"Shred Fest 2027",
                           "signal":"THEMATIC_NAME_ONLY","archive_slug":None}])
    def test_plain_rock_festivals_produce_only_private_candidates(self):
        for title in ("Festival Rock 2027", "Rock Festival 2027",
                      "La Sainte Rock Festival 2027", "Festival punk rock 2027"):
            with self.subTest(title=title):
                found = candidate_links(page(title), LIMOGES, DAY)
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0]["signal"], "THEMATIC_NAME_ONLY")
        for title in ("Concert de rock 2027", "Rock expo 2027",
                      "Festival du cinéma 2027", "Rock Festival 2029"):
            with self.subTest(title=title):
                self.assertEqual(candidate_links(page(title), LIMOGES, DAY), [])
        r = report()
        found = scan_regional_indexes(r, {}, [A], DAY,
                                      lambda _: page("Rock Festival 2027"),
                                      limit=1)
        self.assertEqual(len(found), 1)
        self.assertFalse(found[0]["publication_authorized"])
        self.assertFalse(found[0]["date_verified"])
        self.assertEqual(r["regional_festival_publications"], 0)

    def test_local_music_categories_reveal_private_candidates(self):
        cases = (
            ('<article><p>Genre : métal '
             '<a href="/agenda/festival-forges-2027">Festival des Forges 2027</a>'
             '</p></article>', "Festival des Forges 2027"),
            ('<li>Festival rock : '
             '<a href="/agenda/nuits-noires-2027">Les Nuits Noires 2027</a>'
             '</li>', "Les Nuits Noires 2027"),
            ('<p>Catégorie : punk '
             '<a href="/agenda/festival-des-lacs">Festival des Lacs</a>'
             '</p>', "Festival des Lacs"),
        )
        for html, title in cases:
            with self.subTest(title=title):
                found = candidate_links(html, LIMOGES, DAY)
                self.assertEqual(len(found), 1)
                self.assertEqual(found[0]["title"], title)
                self.assertEqual(found[0]["signal"], "MUSIC_CATEGORY_CONTEXT_ONLY")
        r = report()
        state = {}
        scan_regional_indexes(
            r, state, [A], DAY, lambda _: cases[0][0], limit=1)
        self.assertEqual(r["regional_festival_contextual_links_new_review_only"], 1)
        self.assertEqual(r["regional_festival_publications"], 0)
        row = next(iter(state["regional_festival_candidates_review_only"].values()))
        self.assertFalse(row["date_verified"])
        self.assertFalse(row["publication_authorized"])

    def test_context_is_not_global_hidden_or_unrelated(self):
        bad = (
            '<div>Genre : métal</div><div>'
            '<a href="/agenda/festival-des-forges">Festival des Forges</a></div>',
            '<div hidden>Genre : métal</div>'
            '<a href="/agenda/festival-des-forges">Festival des Forges</a>',
            '<p>Genre : métal <a href="/agenda/cinema">Festival du cinéma 2027</a></p>',
            '<p>Festival rock : <a href="/agenda/concert">Concert de punk 2027</a></p>',
            '<p>Festival rock : <a href="/agenda/details">En savoir plus</a></p>',
            '<p>Jazz : <a href="/agenda/festival-des-forges">Festival des Forges</a></p>',
        )
        for html in bad:
            with self.subTest(html=html):
                self.assertEqual(candidate_links(html, LIMOGES, DAY), [])

    def test_rotation_can_cover_four_distinct_regions_in_one_pass(self):
        indexes = [
            A, B,
            {"id": "occ-montpellier", "region": "Occitanie",
             "url": "https://agenda.montpellier.fr/"},
            {"id": "nor-tourisme", "region": "Normandie",
             "url": "https://www.normandie-tourisme.fr/agenda/"}
        ]
        state, visited = {}, []
        def fetch(url):
            visited.append(url)
            return "<p>Agenda consultable</p>"
        r = report()
        scan_regional_indexes(r, state, indexes, DAY, fetch, limit=4)
        self.assertEqual(len(visited), 4)
        self.assertEqual(r["regional_festival_regions_attempted_review_only"], 4)
        self.assertEqual(r["regional_festival_scanned_this_pass_review_only"], 4)
        self.assertEqual(r["regional_festival_publications"], 0)

    def test_rejects_generic_festivals_and_concerts(self):
        for name in ("Festival du cinéma", "Festival de la BD",
                     "Concert de metal", "Le festival des disques 2027",
                     "Festival metal 2025", "Metal Fest 2029"):
            with self.subTest(name=name):
                self.assertEqual(candidate_links(page(name),LIMOGES,DAY),[])
    def test_rejects_cross_host_http_ip_pdfs_years_and_hidden_links(self):
        bads = ("https://sortir.limoges.fr.evil.fr/agenda/shred-fest-2027",
                "https://127.0.0.1/agenda/shred-fest-2027",
                "http://sortir.limoges.fr/agenda/shred-fest-2027",
                "https://sortir.limoges.fr/affiche.pdf")
        for url in bads:
            with self.subTest(url=url):
                self.assertEqual(candidate_links(page(target=url),LIMOGES,DAY),[])
        for tag in ("<script>", "<noscript>", "<div hidden>",
                    '<div aria-hidden="true">', '<div style="display:none">'):
            closing="</"+tag.split()[0][1:].strip(">")+">"
            self.assertEqual(candidate_links(tag+page()+closing,LIMOGES,DAY),[])
    def test_rotation_across_regions_once_per_day(self):
        state={}
        self.assertEqual(select_indexes([A,B],state,DAY,limit=1),[A])
        state["regional_festival_index_last_checked"]={LIMOGES:DAY}
        self.assertEqual(select_indexes([A,B],state,DAY,limit=2),[B])
        self.assertEqual(select_indexes([A,B],state,"2026-11-06",limit=1),[B])
        state["regional_festival_index_last_checked"][LIMOGES]="2026-11-07"
        with self.assertRaises(ValueError):
            select_indexes([A,B],state,DAY,limit=2)
    def test_scan_private_one_new_not_published_next_call_deduplicated(self):
        state={}; visits=[]
        def fetch(url):
            visits.append(url);return page()
        r=report()
        found=scan_regional_indexes(r,state,[A],DAY,fetch,limit=1)
        self.assertEqual(len(found),1)
        self.assertEqual(visits,[LIMOGES])
        self.assertEqual(r["regional_festival_new_links_review_only"],1)
        self.assertEqual(r["regional_festival_publications"],0)
        self.assertEqual(r["regional_festival_detail_pages_checked_review_only"],0)
        self.assertFalse(found[0]["publication_authorized"])
        scan_regional_indexes(r,state,[A],DAY,fetch,limit=1)
        self.assertEqual(visits,[LIMOGES])
        self.assertEqual(r["regional_festival_new_links_review_only"],0)
        self.assertEqual(r["regional_festival_pending_links_review_only"],1)
        scan_regional_indexes(report("2026-11-06"),state,[A],"2026-11-06",fetch,limit=1)
        self.assertEqual(len(visits),2)
        self.assertEqual(state["regional_festival_candidates_review_only"][TARGET]["firstSeen"],DAY)
    def test_cross_pipeline_duplicate_is_not_a_new_regional_festival(self):
        state={"institutional_agenda_candidate_pages":{"older-edition":[{
            "candidate_url":TARGET,"source":"https://www.phalempin.fr/agenda",
            "lastSeen":DAY,"publication_authorized":False,
            "status":"UNVERIFIED_INDEX_LINK"}]}}
        r=report()
        hits=scan_regional_indexes(r,state,[A],DAY,lambda _:page(),limit=1)
        self.assertEqual(hits,[])
        self.assertEqual(r["regional_festival_existing_links_skipped_review_only"],1)
        self.assertEqual(r["regional_festival_pending_links_review_only"],0)
        self.assertEqual(r["regional_festival_publications"],0)

    def test_existing_catalogue_source_urls_are_skipped(self):
        r=report()
        r["source_reference_leads_review_only"]=[{"candidate_urls":[TARGET]}]
        found=scan_regional_indexes(r,{},[A],DAY,lambda _:page(),limit=1)
        self.assertEqual(found,[])
        self.assertEqual(r["regional_festival_existing_links_skipped_review_only"],1)

    def test_archive_consistency_fail_closed_no_extra_fetch_targets(self):
        archive={"schema":2,"knownFestivals":[
            {"slug":"motocultor-festival","name":"Motocultor Festival",
             "startDate":"2026-08-20","endDate":"2026-08-23","lastKnownYear":2026},
            {"slug":"unconfirmed-fest","name":"Unconfirmed Fest",
             "startDate":None,"endDate":None,"lastKnownYear":None}]}
        urls=[]
        def stable(url):
            urls.append(url)
            return archive
        hints,status,total=load_verified_archive_hints(DAY,stable)
        self.assertEqual(status,"CONSISTENT")
        self.assertEqual(total,2)
        self.assertEqual(len(hints),1)
        self.assertEqual(len(urls),2)
        self.assertTrue(all("festival-history.json" in u for u in urls))
        def changed(url):
            return dict(archive,updatedAt="divergent") if "github.io" in url else archive
        self.assertEqual(load_verified_archive_hints(DAY,changed)[1],"DIVERGENT")
        self.assertEqual(load_verified_archive_hints(
            DAY,lambda url: (_ for _ in ()).throw(OSError("403")))[1],
            "UNAVAILABLE_OR_INVALID")

    def test_archived_identity_future_year_is_private_hint_not_confirmed(self):
        hints={"motocultor festival":{"slug":"motocultor-festival",
                                      "last_known_year":2026}}
        url="https://sortir.limoges.fr/agenda/motocultor-festival-2027"
        page2027=page("Motocultor Festival 2027",url)
        found=candidate_links(page2027,LIMOGES,DAY,hints)
        self.assertEqual(len(found),1)
        self.assertEqual(found[0]["signal"],ARCHIVE_SIGNAL)
        self.assertEqual(found[0]["archive_slug"],"motocultor-festival")
        for name in ("Motocultor Festival 2026", "Motocultor Festival 2025",
                     "Motocultor Festival Junior 2027",
                     "Motocultor Festival 2027 et 2028",
                     "Motocultor Festival"):
            with self.subTest(name=name):
                self.assertEqual(candidate_links(page(name,url),LIMOGES,DAY,hints),[])
        self.assertEqual(candidate_links(page2027,LIMOGES,DAY),[])
        state={}
        r=report()
        recorded=scan_regional_indexes(
            r,state,[A],DAY,lambda _:page2027,limit=1,
            historical_hints=hints,archive_status="CONSISTENT",archive_total=173)
        self.assertEqual(len(recorded),1)
        self.assertEqual(recorded[0]["historical_name_slug"],"motocultor-festival")
        self.assertFalse(recorded[0]["date_verified"])
        self.assertFalse(recorded[0]["publication_authorized"])
        self.assertEqual(r["regional_festival_archive_links_new_review_only"],1)
        self.assertEqual(r["regional_festival_publications"],0)
        self.assertEqual(r["regional_festival_detail_pages_checked_review_only"],0)

    def test_undated_and_future_archive_rows_never_seed_discovery(self):
        document={"schema":2,"knownFestivals":[
            {"slug":"festival-first","name":"Festival First",
             "startDate":None,"endDate":None,"lastKnownYear":None},
            {"slug":"festival-next","name":"Festival Next",
             "startDate":"2027-01-01","endDate":"2027-01-02",
             "lastKnownYear":2027}]}
        self.assertEqual(archive_hints(document,DAY),{})
        with self.assertRaises(ValueError):
            archive_hints(dict(document,schema=1),DAY)
        with self.assertRaises(ValueError):
            archive_hints(dict(document,knownFestivals=document["knownFestivals"]*2),DAY)

    def test_eight_distinct_regional_index_checks_remain_private(self):
        # The increased bound improves geographic breadth without trusting
        # a newly discovered domain, changing admissions, or writing a patch.
        indexes = []
        seen = set()
        for url, region in APPROVED.items():
            if region in seen:
                continue
            seen.add(region)
            indexes.append({"id": "eight-" + str(len(indexes)),
                            "region": region, "url": url})
            if len(indexes) == 8:
                break
        self.assertEqual(len(indexes), 8)
        self.assertEqual(len(select_indexes(indexes, {}, DAY, limit=8)), 8)
        with self.assertRaises(ValueError):
            select_indexes(indexes, {}, DAY, limit=9)
        checked = []
        result = report()
        observed = scan_regional_indexes(
            result, {}, indexes, DAY,
            fetch=lambda url: checked.append(url) or "<main>Aucun festival métal</main>",
            limit=8)
        self.assertEqual(len(checked), 8)
        self.assertEqual(observed, [])
        self.assertEqual(result["regional_festival_publications"], 0)

    def test_inaccessible_is_not_public_or_confirmed(self):
        def down(_):
            raise OSError("403")
        r=report()
        scan_regional_indexes(r,{},[A],DAY,down,limit=1)
        self.assertEqual(r["regional_festival_indexes_review_only"][0]["status"],"INACCESSIBLE")
        self.assertEqual(r["regional_festival_new_links_review_only"],0)
        self.assertEqual(r["regional_festival_publications"],0)
    def test_poisoned_private_state_pruned_and_never_fetched(self):
        state={"regional_festival_candidates_review_only":{
            "https://127.0.0.1/event":{"source_index":LIMOGES,"status":"UNVERIFIED_THEME_LINK",
              "lastSeen":DAY,"publication_authorized":False},
            TARGET:{"source_index":LIMOGES,"status":"VERIFIED",
                    "lastSeen":DAY,"publication_authorized":True}
        }}
        r=report()
        scan_regional_indexes(r,state,[A],DAY,lambda _: "<p>no events</p>",limit=1)
        self.assertEqual(state["regional_festival_candidates_review_only"],{})
        self.assertEqual(r["regional_festival_publications"],0)
if __name__=="__main__":
    unittest.main()
