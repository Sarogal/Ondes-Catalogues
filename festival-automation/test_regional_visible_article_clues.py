"""Fail-closed observations from visible event cards lacking ordinary hyperlinks."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parent))

from regional_visible_article_clues import (
    visible_article_clues, update_private_articles)
from regional_festival_discovery import (
    scan_regional_indexes, APPROVED)

DAY = "2026-11-06"
BASE = "https://sortir.limoges.fr/agenda"
SEED = {"url": BASE, "region": "Nouvelle-Aquitaine", "id": "na-limoges"}


def report():
    return {"schema": "grossesondes.source-watch-report.v1", "date": DAY}


class ArticleClueTests(unittest.TestCase):
    def test_plain_visible_articles_without_links_create_private_hints(self):
        html = """
        <main>
          <article><h2>Metal Fest 2027</h2>
          <p>Festival metal, les 12 et 13 juin 2027</p></article>
          <article><h3>Les Nuits Noires 2027</h3>
          <p>Festival punk rock. Programmation en préparation.</p></article>
          <article><h2>Festival des Forges</h2>
          <p>Catégorie : metal</p></article>
        </main>"""
        clues, count = visible_article_clues(html, DAY)
        self.assertEqual(count, 3)
        self.assertEqual(len(clues), 3)
        self.assertEqual(clues[0]["edition_year_hint"], 2027)
        self.assertIsNone(clues[2]["edition_year_hint"])
        for item in clues:
            self.assertFalse(item["publication_authorized"])
            self.assertFalse(item["date_verified"])
            self.assertFalse(item["fetch_eligible"])
            self.assertNotIn("candidate_url", item)

    def test_global_context_hidden_markup_and_regular_links_are_not_promoted(self):
        html = """
        <p>Festival metal 2027</p>
        <article><h2>Festival de la BD 2027</h2><p>Metal</p></article>
        <article hidden><h2>Metal Fest 2027</h2></article>
        <article aria-hidden="true"><h2>Rock Festival 2027</h2></article>
        <article><script type="application/ld+json">
        {"@type":"MusicEvent","name":"Metal Fest 2027",
        "url":"https://127.0.0.1/"}</script><h2>Festival des Lacs</h2></article>
        <article><h2>Concert de metal 2027</h2><p>Concert uniquement</p></article>
        <article><h2>Rock Festival 2027</h2><a href="/unsafe">Détails</a></article>
        """
        clues, _ = visible_article_clues(html, DAY)
        self.assertEqual(clues, [])

    def test_historical_identity_requires_explicit_new_year(self):
        hints = {"les foudres": {"slug": "les-foudres", "last_known_year": 2026}}
        html = ("<article><h2>Les Foudres 2027</h2><p>Musique live</p></article>"
                "<article><h2>Les Foudres</h2><p>Musique live</p></article>")
        clues, _ = visible_article_clues(html, DAY, hints)
        self.assertEqual(len(clues), 1)
        self.assertEqual(clues[0]["historical_name_slug"], "les-foudres")
        self.assertEqual(clues[0]["signal"], "VISIBLE_ARTICLE_HISTORICAL_NAME_ONLY")

    def test_private_persistence_is_stable_and_not_visit_eligible(self):
        html = "<article><h2>Metal Fest 2027</h2><p>Festival metal</p></article>"
        clue, _ = visible_article_clues(html, DAY)
        state = {}
        new, pending = update_private_articles(
            state, BASE, "Nouvelle-Aquitaine", clue, DAY, APPROVED)
        self.assertEqual((len(new), pending), (1, 1))
        keys = list(state["regional_festival_article_clues_review_only"])
        more, pending = update_private_articles(
            state, BASE, "Nouvelle-Aquitaine", clue, DAY, APPROVED)
        self.assertEqual((len(more), pending), (0, 1))
        self.assertEqual(list(state["regional_festival_article_clues_review_only"]), keys)
        self.assertFalse(new[0]["fetch_eligible"])
        self.assertFalse(new[0]["publication_authorized"])

    def test_poisoned_private_state_cannot_authorize_publication_or_fetches(self):
        html = "<article><h2>Metal Fest 2027</h2><p>Festival metal</p></article>"
        clue, _ = visible_article_clues(html, DAY)
        state = {"regional_festival_article_clues_review_only": {
            "0123456789abcdef0123": {
                "source_index": ["https://127.0.0.1/"],
                "region": "Nouvelle-Aquitaine", "status": "UNVERIFIED_VISIBLE_ARTICLE",
                "publication_authorized": False, "fetch_eligible": False,
                "firstSeen": DAY, "lastSeen": DAY},
            "1234567890abcdef0123": {
                "source_index": BASE, "region": "Nouvelle-Aquitaine",
                "status": "UNVERIFIED_VISIBLE_ARTICLE",
                "publication_authorized": True, "fetch_eligible": True,
                "firstSeen": DAY, "lastSeen": DAY}
        }}
        added, pending = update_private_articles(
            state, BASE, "Nouvelle-Aquitaine", clue, DAY, APPROVED)
        self.assertEqual((len(added), pending), (1, 1))
        self.assertTrue(all(
            not row["publication_authorized"] and not row["fetch_eligible"]
            for row in state["regional_festival_article_clues_review_only"].values()))

    def test_regional_watch_preserves_private_card_hints_without_network_targets(self):
        html = """
        <article><h2>Metal Fest 2027</h2>
        <p>Festival metal à Limoges</p></article>"""
        visits = []
        def fetch(url):
            visits.append(url)
            return html
        state = {}
        r = report()
        found = scan_regional_indexes(
            r, state, [SEED], DAY, fetch=fetch, limit=1)
        self.assertEqual(visits, [BASE])
        self.assertEqual(found, [])
        self.assertEqual(r["regional_festival_article_clues_new_review_only"], 1)
        self.assertEqual(r["regional_festival_article_clues_pending_review_only"], 1)
        self.assertEqual(r["regional_festival_visible_articles_review_only"], 1)
        self.assertEqual(r["regional_festival_new_links_review_only"], 0)
        self.assertEqual(r["regional_festival_detail_pages_checked_review_only"], 0)
        self.assertEqual(r["regional_festival_publications"], 0)
        self.assertEqual(len(state["regional_festival_article_clues_review_only"]), 1)

    def test_script_only_festivals_not_observed(self):
        html = """<script type="application/ld+json">
        {"@type":"MusicEvent","name":"Rock Festival 2027",
        "url":"https://www.evil.fr/festival"}</script>"""
        self.assertEqual(visible_article_clues(html, DAY), ([], 0))


if __name__ == "__main__":
    unittest.main()
