"""Keep Pages upload and deployment names distinct across rerun attempts."""
from pathlib import Path
import unittest

YAML = (Path(__file__).resolve().parents[1] /
        ".github/workflows/grossesondes-concerts-cloud-sync.yml").read_text(
            encoding="utf-8")


class PagesAttemptArtifactTests(unittest.TestCase):
    def test_matching_attempt_specific_pages_artifacts(self):
        self.assertIn("uses: actions/upload-pages-artifact@v5", YAML)
        self.assertIn("uses: actions/deploy-pages@v5", YAML)
        name = "github-pages-${{ github.run_attempt }}"
        self.assertIn("name: " + name, YAML)
        self.assertIn("artifact_name: " + name, YAML)

    def test_approval_security_is_unchanged(self):
        self.assertIn("GROSSES_ONDES_INTAKE_READ_TOKEN:", YAML)
        self.assertIn("GROSSES_ONDES_CONCERTS_CLOUD_SYNC", YAML)
        self.assertIn("concurrency:", YAML)
        self.assertIn("cancel-in-progress: false", YAML)
        self.assertIn("path: docs/", YAML)
        self.assertIn("needs: prepare", YAML)


if __name__=="__main__":
    unittest.main()
