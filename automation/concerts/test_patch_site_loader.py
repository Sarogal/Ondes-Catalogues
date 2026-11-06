"""Test ciblé du correctif JS; sans accès WebFTP ni déploiement."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import patch_site_loader as p


class SitePatchTests(unittest.TestCase):
    def test_patch_is_exact_and_keeps_rest(self):
        original = "'use strict';\n" + p.ORIGINAL + "\nwindow.addEventListener('load',init);"
        edited = p.patch_js(original)
        self.assertIn(p.CLOUD, edited)
        self.assertNotIn(p.ORIGINAL, edited)
        self.assertIn("window.addEventListener('load',init);", edited)
        self.assertIn("data.events.length<127", edited)
        self.assertIn("'catalogue.json'", edited)

    def test_refuses_double_patch(self):
        original = p.ORIGINAL
        once = p.patch_js(original)
        with self.assertRaises(ValueError):
            p.patch_js(once)

    def test_unknown_js_refused(self):
        with self.assertRaises(ValueError):
            p.patch_js("async function init(){try{const data=await fetch('x');}}")

    def test_html_revision_is_targeted(self):
        text = '<script defer src="app.js?v=0.3.0"></script><script defer src="map.js?v=0.2"></script>'
        new = p.patch_index(text)
        self.assertIn('src="app.js?v=cloud-2026-11-01"',new)
        self.assertIn('src="map.js?v=0.2"',new)

    def test_unknown_html_refused(self):
        with self.assertRaises(ValueError):
            p.patch_index('<script src="alternate.js"></script>')


if __name__ == "__main__":
    unittest.main()
