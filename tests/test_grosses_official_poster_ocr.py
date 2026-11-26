"""Offline security and cache regressions for official poster OCR."""
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "festival-automation"))

from grossesondes_official_poster_ocr import (
    MAX_BYTES, qualified_url, parse_tsv, read_official_poster,
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
