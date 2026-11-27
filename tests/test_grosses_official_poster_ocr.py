"""Offline security and cache regressions for official poster OCR."""
import sys
import io
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "festival-automation"))

from grossesondes_official_poster_ocr import (
    MAX_BYTES, qualified_url, parse_tsv, read_official_poster,
    load_ocr_cache, save_ocr_cache, recognize_poster, poster_review_claims,
    _choose_ocr_pass, poster_known_artist_candidates, structured_poster_candidates,
)
from dns_pinned_https import OfficialHTTPStatusError

SITE = "https://festival-example.fr/"
POSTER = SITE + "images/poster.jpg"
HEADER = "level\tleft\ttop\twidth\theight\tconf\ttext\n"


class PosterOCRTests(unittest.TestCase):
    def test_url_rejects_untrusted_origins_and_nonraster(self):
        self.assertTrue(qualified_url(SITE, POSTER))
        for url in ("http://festival-example.fr/poster.jpg",
                    "https://outside.fr/poster.jpg", SITE + "poster.svg",
                    POSTER + "?token=1", SITE + "a/../poster.jpg",
                    SITE + "%2e%2e/poster.jpg"):
            fetch = Mock()
            self.assertEqual(read_official_poster(SITE, url, cache={}, fetch=fetch)["status"],
                             "unqualified")
            fetch.assert_not_called()

    def test_confidence_is_preserved_not_authority(self):
        words = parse_tsv(HEADER + "5\t1\t2\t40\t12\t31.4\tUnknown\n")
        self.assertEqual(words, [{"text": "Unknown", "confidence": 31.4,
                                  "box": [1, 2, 40, 12], "review_only": True}])
        for confidence in ("nan", "101", "-1"):
            with self.assertRaises(ValueError):
                parse_tsv(HEADER + "5\t1\t2\t40\t12\t" + confidence + "\tName\n")

    def test_hash_cache_detects_changed_content_even_at_same_url(self):
        cache = {}
        fetch = Mock(side_effect=[("image/jpeg", b"first"), ("image/jpeg", b"first"),
                                  ("image/jpeg", b"new")])
        recognize = Mock(return_value=[])
        a, b, c = [read_official_poster(SITE, POSTER, cache=cache, fetch=fetch,
                                        recognize=recognize) for _ in range(3)]
        self.assertEqual(a["sha256"], b["sha256"])
        self.assertNotEqual(a["sha256"], c["sha256"])
        self.assertFalse(a["cache_hit"])
        self.assertTrue(b["cache_hit"])
        self.assertFalse(c["cache_hit"])
        self.assertEqual(recognize.call_count, 2)
        self.assertTrue(all(row["review_only"] for row in (a, b, c)))

    def test_rate_limit_and_invalid_payload_never_call_ocr(self):
        cache = {}
        recognize = Mock()
        fetch = Mock(side_effect=OfficialHTTPStatusError(429))
        result = read_official_poster(SITE, POSTER, cache=cache, fetch=fetch,
                                      recognize=recognize)
        self.assertEqual(result["status"], "rate_limited")
        fetch.assert_called_once()
        for value in (("text/html", b"not an image"), ("image/jpeg", b""),
                      ("image/jpeg", b"x" * (MAX_BYTES + 1))):
            result = read_official_poster(SITE, POSTER, cache=cache,
                                          fetch=lambda *_: value, recognize=recognize)
            self.assertEqual(result["status"], "image_or_ocr_unavailable")
        recognize.assert_not_called()
        self.assertEqual(cache, {})

    def test_persistent_cache_roundtrip_and_changed_poster(self):
        words = parse_tsv(HEADER + "5\t1\t2\t40\t12\t97\tExample\n")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private-cache.json"
            cache = {}
            recognize = Mock(return_value=words)
            read_official_poster(SITE, POSTER, cache=cache,
                                 fetch=lambda *_: ("image/jpeg", b"first"), recognize=recognize)
            save_ocr_cache(path, cache)
            restored = load_ocr_cache(path)
            self.assertEqual(restored, cache)
            hit = read_official_poster(SITE, POSTER, cache=restored,
                                       fetch=lambda *_: ("image/jpeg", b"first"), recognize=recognize)
            self.assertTrue(hit["cache_hit"])
            miss = read_official_poster(SITE, POSTER, cache=restored,
                                        fetch=lambda *_: ("image/jpeg", b"changed"), recognize=recognize)
            self.assertFalse(miss["cache_hit"])
            self.assertEqual(recognize.call_count, 2)
            path.write_text('{"profile":"old","entries":{}}')
            self.assertEqual(load_ocr_cache(path), {})
            path.write_text("not json")
            self.assertEqual(load_ocr_cache(path), {})

    @unittest.skipUnless(os.environ.get("GO_REAL_POSTER_OCR") == "1",
                         "Dedicated real OCR runner only")
    def test_real_tesseract_reads_generated_raster(self):
        from PIL import Image, ImageDraw, ImageFont
        image = Image.new("RGB", (1400, 500), "white")
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 80)
        draw.text((30, 30), "FESTIVAL EXEMPLE", font=font, fill="black")
        draw.text((30, 180), "13 AOÛT 2027", font=font, fill="black")
        draw.text((30, 330), "PASS 45 EUROS", font=font, fill="black")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        words = recognize_poster("image/png", buffer.getvalue())
        text = " ".join(word["text"] for word in words).upper()
        for expected in ("FESTIVAL", "EXEMPLE", "2027", "45"):
            self.assertIn(expected, text)
        self.assertTrue(all(word["review_only"] for word in words))

    def test_poster_claims_bind_exact_edition_and_explicit_fields(self):
        row = {"name": "Festival Exemple 2027", "startDate": "2027-08-13",
               "endDate": "2027-08-15"}
        def reading(lines, confidence=96):
            words = []
            for y, line in enumerate(lines):
                x = 20
                for token in line.split():
                    width = len(token) * 10
                    words.append({"text": token, "confidence": confidence,
                                  "box": [x, 40*y, width, 25], "review_only": True})
                    x += width + 8
            return {"status": "review_only", "review_only": True, "words": words}
        lines = ["FESTIVAL EXEMPLE", "13 au 15 août 2027", "Artistes : Alpha, Beta",
                 "Ville : Exempleville", "Pass : 45 €", "Sponsor Gamma"]
        result = poster_review_claims(row, reading(lines))
        self.assertEqual(result["status"], "edition_matches_review_only")
        self.assertTrue(result["diagnostics"]["brand_matches"])
        self.assertTrue(result["diagnostics"]["strong_exact_dates"])
        self.assertFalse(result["diagnostics"]["contradictory_dates"])
        self.assertEqual(result["claims"]["artist_labels"], ["Artistes : Alpha, Beta"])
        self.assertEqual(result["claims"]["location_labels"], ["Ville : Exempleville"])
        self.assertEqual(result["claims"]["price_labels"], ["Pass : 45 €"])
        self.assertFalse(result["publication_authorized"])
        for changed in (["FESTIVAL AUTRE"] + lines[1:],
                        lines[:1] + ["13 au 16 août 2027"] + lines[2:],
                        lines + ["Archives 2026"], lines + ["Annulé"],
                        lines + ["14 au 16 août 2027"]):
            self.assertEqual(poster_review_claims(row, reading(changed))["claims"], {})
        self.assertEqual(poster_review_claims(row, reading(lines, confidence=40))["claims"], {})
        result = poster_review_claims(row, reading(lines[:2] + ["ALPHA BETA", "45 €"]))
        self.assertEqual(set(result["claims"]), {"dates"})

    def test_contrast_pass_prefers_complete_stronger_geometry_without_mixing(self):
        def words(*tokens):
            return [{"text": token, "confidence": confidence,
                     "box": [i * 60, 0, 50, 20], "review_only": True}
                    for i, (token, confidence) in enumerate(tokens)]
        original = words(("2027", 96), ("Exemple", 35))
        better = words(("2027", 98), ("Exemple", 97), ("Alpha", 95))
        self.assertIs(_choose_ocr_pass(original, better), better)
        self.assertIs(_choose_ocr_pass(better, original), better)
        for unsafe in (words(("2026", 99), ("Exemple", 99), ("Alpha", 99)),
                       words(("2027", 99), ("Annulé", 99), ("Alpha", 99)),
                       words(("Exemple", 99), ("Alpha", 99), ("Beta", 99))):
            self.assertIs(_choose_ocr_pass(original, unsafe), original)
        dates = words(("2027", 96), ("13", 96), ("au", 96),
                      ("15", 96), ("août", 96))
        different = words(("2027", 99), ("13", 99), ("au", 99),
                          ("16", 99), ("août", 99), ("Alpha", 99))
        self.assertIs(_choose_ocr_pass(dates, different), dates)

    def test_artist_hints_require_complete_confident_geometric_segments(self):
        words = []
        def line(tokens, y, confidence=98):
            x = 20
            for token in tokens.split():
                width = len(token) * 10
                words.append({"text": token, "confidence": confidence,
                              "box": [x, y, width, 20], "review_only": True})
                x += width + 5
        line("ALPHA BETA", 0)
        line("Sponsor Gamma", 40)
        line("Delta", 80, 40)
        line("Omega Records", 120)
        line("New Artist", 160)
        line("Rival", 200)
        reading = {"status": "review_only", "review_only": True, "words": words}
        known = ["Alpha Beta", "Alpha", "Gamma", "Sponsor Gamma", "Delta",
                 "Omega", "Rival", "RIVAL"]
        self.assertEqual(poster_known_artist_candidates(reading, known), ["Alpha Beta"])
        self.assertEqual(poster_known_artist_candidates(dict(reading, review_only=False), known), [])

    def test_structured_fields_require_exact_edition_and_high_confidence(self):
        row = {"name": "Festival Exemple 2027", "startDate": "2027-08-13",
               "endDate": "2027-08-15"}
        def reading(lines, confidence=98):
            words = []
            for y, line in enumerate(lines):
                x = 20
                for token in line.split():
                    width = len(token) * 10
                    words.append({"text": token, "confidence": confidence,
                                  "box": [x, 40*y, width, 25], "review_only": True})
                    x += width + 8
            return {"status": "review_only", "review_only": True, "words": words}
        base = ["FESTIVAL EXEMPLE", "13 au 15 août 2027"]
        lines = base + ["Artistes : Alpha, New Artist", "Pass 3 jours : 75,50 €",
                        "Pass 1J : 30 EUR", "Pass 4J : 99 €",
                        "Sponsor Gamma", "45 €"]
        result = structured_poster_candidates(row, reading(lines))
        self.assertEqual(result["artists"], ["Alpha", "New Artist"])
        self.assertEqual(result["passes"], {"1": "30", "3": "75,50"})
        self.assertFalse(result["publication_authorized"])
        conflict = structured_poster_candidates(
            row, reading(lines + ["Pass 3J : 90 €", "Artistes : Rival"]))
        self.assertEqual(conflict["artists"], [])
        self.assertEqual(conflict["passes"], {"1": "30"})
        for altered, confidence in ((lines + ["Archives 2026"], 98),
                                    (lines, 90),
                                    (base + ["Artistes : Alpha, Sponsor Gamma",
                                             "Pass 3J : 75 € en vente"], 98)):
            result = structured_poster_candidates(row, reading(altered, confidence))
            self.assertEqual(result["artists"], [])
            self.assertEqual(result["passes"], {})

    def test_stacked_calendar_dates_require_adjacent_aligned_date_only_lines(self):
        row = {"name": "Festival Exemple 2027", "startDate": "2027-08-13",
               "endDate": "2027-08-15"}
        def reading(segments):
            words = []
            for phrase, x, y, confidence in segments:
                for token in phrase.split():
                    width = len(token) * 10
                    words.append({"text": token, "confidence": confidence,
                                  "box": [x, y, width, 25], "review_only": True})
                    x += width + 8
            return {"status": "review_only", "review_only": True, "words": words}
        base = [("FESTIVAL EXEMPLE", 20, 0, 98)]
        fields = [("Artistes : Alpha, Beta", 20, 200, 98), ("Pass 3J : 75 €", 20, 240, 98)]
        dates = [("13 au 15", 40, 40, 98), ("août 2027", 40, 80, 98)]
        result = structured_poster_candidates(row, reading(base + dates + fields))
        self.assertEqual(result["artists"], ["Alpha", "Beta"])
        self.assertEqual(result["passes"], {"3": "75"})
        three = [("13 au 15", 40, 40, 98), ("août", 60, 80, 98), ("2027", 60, 120, 98)]
        self.assertEqual(structured_poster_candidates(row, reading(base + three + fields))["artists"],
                         ["Alpha", "Beta"])
        for wrong in (
            [dates[0], ("août 2027", 400, 80, 98)],
            [dates[0], ("août 2027", 40, 140, 98)],
            [dates[0], ("août 2027", 40, 80, 40)],
            [dates[0], ("Sponsor août 2027", 40, 80, 98)],
            [dates[0], ("août", 40, 80, 98)],
            [dates[0], ("août 2027", 40, 80, 98),
             ("14 au 16", 40, 120, 40), ("août 2027", 40, 160, 40)],
        ):
            with self.subTest(wrong=wrong):
                result = structured_poster_candidates(row, reading(base + wrong + fields))
                self.assertEqual(result["artists"], [])
                self.assertEqual(result["passes"], {})

    def test_stacked_fields_require_confident_unambiguous_adjacent_labels(self):
        row = {"name": "Festival Exemple 2027", "startDate": "2027-08-13",
               "endDate": "2027-08-15"}
        def reading(segments):
            words = []
            for phrase, x, y, confidence in segments:
                for token in phrase.split():
                    width = len(token) * 10
                    words.append({"text": token, "confidence": confidence,
                                  "box": [x, y, width, 25], "review_only": True})
                    x += width + 8
            return {"status": "review_only", "review_only": True, "words": words}
        base = [("FESTIVAL EXEMPLE", 20, 0, 98),
                ("13 au 15 août 2027", 20, 40, 98)]
        roster = [("Artistes :", 20, 80, 98), ("Alpha, Beta", 20, 120, 98)]
        price = [("Pass 3J", 20, 160, 98), ("75 €", 20, 200, 98)]
        result = structured_poster_candidates(row, reading(base + roster + price))
        self.assertEqual(result["artists"], ["Alpha", "Beta"])
        self.assertEqual(result["passes"], {"3": "75"})
        self.assertFalse(result["publication_authorized"])
        for wrong in (
            [roster[0], ("Alpha, Beta", 400, 120, 98)],
            [roster[0], ("Alpha, Beta", 20, 150, 98)],
            [roster[0], ("Alpha, Beta", 20, 120, 94)],
            [roster[0], ("Alpha, Beta", 20, 120, 98), ("Gamma", 400, 120, 98)],
            [("Sponsors :", 20, 80, 98), roster[1]],
            [roster[0], ("Alpha", 20, 120, 98)],
        ):
            self.assertEqual(structured_poster_candidates(row, reading(base + wrong))["artists"], [])
        for wrong in (
            [price[0], ("75 €", 400, 200, 98)],
            [price[0], ("75 €", 20, 240, 98)],
            [price[0], ("75 €", 20, 200, 94)],
            [price[0], price[1], ("50 €", 400, 200, 98)],
        ):
            self.assertEqual(structured_poster_candidates(row, reading(base + wrong))["passes"], {})
        conflict = base + price + [("Pass 3J : 90 €", 20, 240, 98)]
        self.assertEqual(structured_poster_candidates(row, reading(conflict))["passes"], {})

    def test_ambiguous_vertical_geometry_requires_unique_horizontal_neighbour(self):
        from grossesondes_official_poster_ocr import poster_word_lines
        def word(text, x, y, w, h):
            return {"text": text, "confidence": 98,
                    "box": [x, y, w, h], "review_only": True}
        # Different word heights create two possible vertical matches
        # for a later word, but only one local horizontal neighbour.
        first = word("Alpha", 20, 10, 50, 40)   # centre 30
        second = word("Gamma", 300, 30, 50, 10) # centre 35
        third = word("Beta", 78, 17, 40, 40)    # centre 37
        lines = poster_word_lines([first, second, third])
        self.assertIsNotNone(lines)
        self.assertIn(["Alpha", "Beta"], [[w["text"] for w in line] for line in lines])
        self.assertIn(["Gamma"], [[w["text"] for w in line] for line in lines])
        # Two adjacent candidates or no adjacent candidate stay ambiguous.
        nearby = word("Gamma", 125, 30, 50, 10)
        self.assertIsNone(poster_word_lines([first, nearby, third]))
        remote = word("Beta", 600, 17, 40, 40)
        self.assertIsNone(poster_word_lines([first, second, remote]))

    def test_failed_recognition_not_cached(self):
        cache = {}
        recognize = Mock(side_effect=FileNotFoundError())
        result = read_official_poster(SITE, POSTER, cache=cache,
                                      fetch=lambda *_: ("image/jpeg", b"image"),
                                      recognize=recognize)
        self.assertEqual(result["status"], "image_or_ocr_unavailable")
        self.assertEqual(cache, {})


if __name__ == "__main__":
    unittest.main()
