"""Regression: dynamic Concert approvals must consume this run's evidence.

The cross-domain stages run with the SAME private-source runner workspace as
official_recheck, never on PR code with secrets. Historical reports remain in
the private Git archive for analysis, not authorization.
"""
from pathlib import Path
import unittest


WORKFLOW = (
    Path(__file__).resolve().parents[2]
    / ".github/workflows/grossesondes-concerts-private-intake-on-public-runners.yml"
)
CROSS_PATH = '"$RUNNER_TEMP/concerts-cross-domain-current.json"'
FRESH_PATH = '"$RUNNER_TEMP/concerts-cross-domain-fresh-current.json"'
PRIVATE_CROSS = "confidential/automation/concerts/intake/source-cross-domain-corroboration.json"
PRIVATE_FRESH = "confidential/automation/concerts/intake/source-cross-domain-fresh-evidence.json"


def steps():
    text = WORKFLOW.read_text(encoding="utf-8")
    result = {}
    for part in text.split("      - name: ")[1:]:
        name = part.splitlines()[0].strip()
        if name in result:
            raise AssertionError("Duplicate GitHub Action step: " + name)
        result[name] = part
    return text, result


class SameRunConcertEvidenceWorkflowTests(unittest.TestCase):
    def test_current_run_corroboration_precedes_approval_and_publisher(self):
        document, stage = steps()
        names = (
            "Archiver les découvertes et les tournées Festivals dans le registre privé",
            "Croiser les annonces officielles de domaines différents (privé seul)",
            "Revérifier les mêmes concerts sur deux domaines officiels distincts (privé)",
            "Revérifier et approuver uniquement si le verrou existant le permet",
            "Qualifier les domaines officiels inconnus et proposer leurs concerts (privé)",
            "Produire des paires concert + nouveau lieu depuis deux preuves fraîches (privé)",
            "Prévalider chaque nouvelle approbation avec le vrai moteur de publication",
        )
        self.assertTrue(all(name in stage for name in names))
        indices = [document.index("      - name: " + name) for name in names]
        self.assertEqual(indices, sorted(indices))

    def test_no_cached_private_report_can_reenter_dynamic_publisher(self):
        _, stage = steps()
        for name in (
            "Qualifier les domaines officiels inconnus et proposer leurs concerts (privé)",
            "Produire des paires concert + nouveau lieu depuis deux preuves fraîches (privé)",
        ):
            block = stage[name]
            self.assertIn("CROSS=" + FRESH_PATH, block)
            self.assertIn('if [ -s "$CROSS" ]; then', block)
            self.assertNotIn("CROSS=" + PRIVATE_FRESH, block)
            self.assertIn('--cross "$CROSS"', block)

    def test_fresh_corroboration_is_generated_and_archived_only_on_success(self):
        _, stage = steps()
        block = stage[
            "Croiser les annonces officielles de domaines différents (privé seul)"
        ]
        self.assertIn("--output " + CROSS_PATH, block)
        self.assertIn("rm -f " + CROSS_PATH, block)
        self.assertIn("cp " + CROSS_PATH + " " + PRIVATE_CROSS, block)
        self.assertNotIn("--output " + PRIVATE_CROSS, block)

    def test_fresh_independent_recheck_depends_on_fresh_corroboration(self):
        _, stage = steps()
        block = stage[
            "Revérifier les mêmes concerts sur deux domaines officiels distincts (privé)"
        ]
        self.assertIn("if [ -s " + CROSS_PATH + " ]; then", block)
        self.assertIn("--input " + CROSS_PATH, block)
        self.assertIn("--output " + FRESH_PATH, block)
        self.assertIn("rm -f " + FRESH_PATH, block)
        self.assertIn("cp " + FRESH_PATH + " " + PRIVATE_FRESH, block)
        self.assertNotIn("--input " + PRIVATE_CROSS, block)
        self.assertNotIn("--output " + PRIVATE_FRESH, block)

    def test_pipeline_keeps_private_runner_gate_and_autoreview_gate(self):
        text, stage = steps()
        for name in (
            "Croiser les annonces officielles de domaines différents (privé seul)",
            "Revérifier les mêmes concerts sur deux domaines officiels distincts (privé)",
            "Qualifier les domaines officiels inconnus et proposer leurs concerts (privé)",
        ):
            self.assertIn("if: steps.access.outputs.ready == 'true'", stage[name])
        self.assertIn("GROSSES_ONDES_CONCERTS_AUTOREVIEW", text)
        self.assertIn("approval_preflight.py", text)


if __name__ == "__main__":
    unittest.main()
