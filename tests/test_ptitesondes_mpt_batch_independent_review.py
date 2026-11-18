"""Offline adversarial test of multiple independently reviewed municipal sessions."""
from datetime import date, timedelta
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ptitesondes_mpt_batch_independent_review import (
    review_official_listing_batch,
)
from ptitesondes_mpt_independent_geo_pilot import reviewed_pilot_records

TODAY = date(2026, 11, 18)
HOST = "https://mpt.montpellier.fr/evenement/"
LINKS = {
    "read": HOST + "bebes-lecteurs",
    "movement": HOST + "le-corps-le-jeu-atelier-de-motricite",
    "ambiguous": HOST + "melipitchouns-atelier-deveil-et-de-lecture",
    "art": HOST + "dans-la-foret",
}
LIST = ('<html><h1>Événements</h1>' +
        ''.join('<a href="' + v + '">Fiche</a>' for v in LINKS.values()) +
        '</html>')


def page(title, venue, street, postcode, date_txt, clock, *,
         blurb="Enfants et familles pour les enfants",
         fee="Sur inscription | Gratuit"):
    return f"""<html><head><title>Ville de Montpellier</title></head>
    <body><h1>{title}</h1><article>
    <p>{blurb}</p>
    <ul><li><p>{date_txt} - {clock} &gt; 12:30</p></li></ul>
    <p>{venue}<br/>{street}<br/>{postcode} Montpellier</p>
    <p>{fee}</p></article><h2>Autres événements</h2></body></html>"""


PAGES = {
    LINKS["read"]: page(
        "Bébés lecteurs", "Maison pour tous Frida Kahlo",
        "240 Rue Claude Levi-Strauss", "34000",
        "18 novembre 2026", "10:30",
        blurb="Les tout-petits et enfants en famille sont invités à la lecture."
    ),
    LINKS["movement"]: page(
        "Le corps ! Le jeu ! : atelier de motricité",
        "Maison pour tous Marie Curie",
        "13 Allée Antonin Chauliac", "34080",
        "19 novembre 2026", "10:30",
        blurb="Atelier de motricité ludique pour tout-petits et enfants."
    ),
    LINKS["ambiguous"]: page(
        "Méli'Pitchouns : atelier d'éveil et de lecture",
        "Maison pour tous Mélina Mercouri",
        "842 Rue de la Vieille Poste", "34000",
        "18 novembre 2026", "10:00",
        fee="Sur inscription | Gratuit | Carte MPT obligatoire"
    ),
    LINKS["art"]: page(
        "Dans la forêt", "Maison pour tous Albert Dubout",
        "2 Rue des Tourterelles", "34090",
        "25 novembre 2026", "10:00",
        blurb="Installation artistique pour les tout-petits en famille."
    ),
}


def catalogue():
    return json.loads(
        (ROOT / "docs/ptitesondes/sorties.json").read_text(encoding="utf-8"))


def geocoded(url):
    row = next(r for r in reviewed_pilot_records() if r["geo_source_url"] == url)
    return {"features": [{
        "properties": {
            "type": "housenumber", "score": 0.975,
            "label": row["address_label"], "postcode": row["postcode"],
            "city": "Montpellier",
        },
        "geometry": {
            "type": "Point", "coordinates": [row["lng"], row["lat"]]},
    }]}


def review(listing=LIST, *, htmls=PAGES, catalog=None, page_limit=24,
           geo=geocoded):
    return review_official_listing_batch(
        listing, catalogue() if catalog is None else catalog, TODAY,
        detail_get=lambda url: htmls[url] if url in htmls else (_ for _ in ()).throw(OSError("unavailable official detail")), geocoder_get=geo,
        page_limit=page_limit)


class MptBatchSourceGeoTests(unittest.TestCase):
    def test_multiple_sources_one_generic_pipeline_not_event_adapters(self):
        r = review()
        self.assertEqual(r["discovered_occurrences"], 4)
        self.assertEqual(r["classified_family_occurrences"], 4)
        self.assertEqual(r["selected_for_independent_review"], 4)
        self.assertEqual(r["venue_points_external_ign_rechecked"], 4)
        # "Bébés lecteurs" and "Le corps! Le jeu!" have clear access;
        # the MPT-card and misleading "forêt" rows must remain held.
        self.assertEqual(r["independent_source_cues_passed"], 2)
        self.assertIn("unresolved_access_contradiction",
                      r["held_in_independent_checks"])
        self.assertIn("art_installation_requires_editorial_review",
                      r["held_before_independent_checks"])
        self.assertTrue(r["catalogue_unchanged"])
        self.assertFalse(r["publication_ready"])
        self.assertEqual(r["published_events"], 0)
        self.assertEqual(r["public_writes"], 0)

    def test_no_leads_returns_zero_and_never_raises_to_publish(self):
        listing = '<html><a href="/evenement/adult-only">Adult</a></html>'
        htmls = {HOST + "adult-only": page(
            "Peinture réservée aux adultes",
            "Maison pour tous Marie Curie",
            "13 Allée Antonin Chauliac", "34080",
            "19 novembre 2026", "10:30",
            blurb="Atelier réservé aux adultes seulement.")}
        r = review(listing, htmls=htmls)
        self.assertEqual(r["discovered_occurrences"], 0)
        self.assertEqual(r["independent_source_cues_passed"], 0)
        self.assertEqual(r["public_writes"], 0)

    def test_incomplete_official_detail_fails_whole_batch_closed(self):
        pages = dict(PAGES)
        pages.pop(LINKS["art"])
        r = review(htmls=pages)
        self.assertEqual(r["unreadable_detail_pages_held"], 1)
        self.assertEqual(r["selected_for_independent_review"], 0)
        self.assertEqual(r["independent_source_cues_passed"], 0)
        self.assertEqual(r["held_before_independent_checks"][
            "discovery_incomplete_no_review"], 3)

    def test_bad_ign_disables_place_evidence_not_other_valid_events(self):
        reviewed = reviewed_pilot_records()
        row = next(x for x in reviewed if "frida-kahlo" in x["venue_key"])
        def geo_with_street(url):
            result = geocoded(url)
            if url == row["geo_source_url"]:
                result["features"][0]["properties"]["type"] = "street"
            return result
        r = review(geo=geo_with_street)
        self.assertEqual(r["independent_source_cues_passed"], 1)
        self.assertIn("independent_geo_not_currently_verified",
                      r["held_before_independent_checks"])

    def test_page_limit_is_explicitly_sample_only(self):
        r = review(page_limit=2)
        self.assertEqual(r["detail_pages_selected"], 2)
        self.assertEqual(r["selected_for_independent_review"], 2)
        self.assertTrue(r["sample_only_not_full_agenda"])
        self.assertEqual(r["public_writes"], 0)

    def test_no_raw_official_names_urls_html_in_public_report(self):
        j = json.dumps(review(), ensure_ascii=False)
        for forbidden in (
                "Frida Kahlo", "Marie Curie", "Mélina Mercouri",
                "mpt.montpellier.fr", "Bébés lecteurs", "Dans la forêt",
                "event_title", "<article>", "source_url"):
            self.assertNotIn(forbidden, j)

    def test_bounded_overflow_is_held_not_silently_discarded(self):
        base = PAGES[LINKS["read"]]
        occurrences = []
        for n in range(26):
            d = TODAY + timedelta(days=n)
            months = {
                11: "novembre", 12: "décembre"
            }
            occurrences.append(f"<li><p>{d.day} {months[d.month]} {d.year} - "
                               "10:30 &gt; 12:30</p></li>")
        expanded = base.replace(
            "<li><p>18 novembre 2026 - 10:30 &gt; 12:30</p></li>",
            "".join(occurrences))
        r = review(
            listing='<html><a href="/evenement/bebes-lecteurs">'
                    'Bébés lecteurs</a></html>',
            htmls={LINKS["read"]: expanded})
        self.assertEqual(r["discovered_occurrences"], 26)
        self.assertEqual(r["selected_for_independent_review"], 24)
        self.assertEqual(r["held_by_source_batch_limit"], 2)
        self.assertEqual(r["public_writes"], 0)

    def test_malicious_untrusted_link_never_fetched(self):
        listing = (
            '<html><h1>Événements</h1>'
            '<a href="https://evil.test/evenement/something">Danger</a>'
            '<a href="https://mpt.montpellier.fr.evil.test/evenement/x">'
            'Fake</a></html>')
        r = review(listing, htmls={})
        self.assertEqual(r["detail_pages_selected"], 0)
        self.assertEqual(r["independent_source_cues_passed"], 0)
        self.assertEqual(r["public_writes"], 0)


if __name__ == "__main__":
    unittest.main()
