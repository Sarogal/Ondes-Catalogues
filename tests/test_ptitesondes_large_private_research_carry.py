"""1.6 MiB private research must survive carry-forward and dossier handoff.

The 1.5 MiB input caps prevented all national source processing once a
bounded 80-item private patch accumulated evidence; this test exercises both
real CLIs offline without permission to write public catalogue files.
"""
from contextlib import redirect_stdout
from datetime import date
from io import StringIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ptitesondes_private_research_carry_forward as carry
import ptitesondes_open_world_private_dossier_intake as dossier
from private_intake import MAX_PRIVATE_PATCH

DAY = date(2026, 11, 23)
NEXT = "2026-12-05"
PUBLIC_ORIGIN = "https://ptitesondes.fr/config/sorties.json"


def patch_document(*, queue=True, padding=True):
    doc = {
        "schema": "ptitesondes.patch.v1",
        "generated_at": DAY.isoformat(),
        "safe_to_publish": False,
        "source": {
            "url": PUBLIC_ORIGIN,
            "version": 3,
            "updated_at": "2026-11-23T06:18:39+01:00",
            "events_count": 664,
        },
        "checks": {"ids_unique": True, "official_sources_verified": True,
                   "no_production_changes": True},
        "additions": [], "updates": [], "deferred": [],
    }
    if queue:
        doc["open_world_research"] = [{
            "lead": {
                "agenda_uid": 123456,
                "agenda_slug": "unknown-public-agenda",
                "event_uid": 987654321,
                "city_unverified": "Ville inconnue",
                "venue_unverified": "Salle nouvelle",
            },
            "date_start": NEXT,
            "official_event_url":
                "https://openagenda.com/unknown-public-agenda/events/987654321",
            "official_venue_url":
                "https://openagenda.com/unknown-public-agenda/events/987654321",
        }]
    if padding:
        doc["test_only_padding"] = "x" * 1_600_000
    return doc


class LargePrivateResearchCarryTests(unittest.TestCase):
    def test_both_private_clis_process_over_1_5mb_without_approval(self):
        self.assertEqual(dossier.MAX_PRIVATE_PATCH_BYTES, MAX_PRIVATE_PATCH)
        with TemporaryDirectory() as temp:
            root = Path(temp)
            existing = root / "existing.json"
            fresh = root / "fresh.json"
            carried = root / "carried.json"
            updated = root / "updated.json"
            observation = root / "observation"
            research = root / "research"
            observation.mkdir()
            research.mkdir()
            existing.write_text(
                json.dumps(patch_document(), ensure_ascii=False),
                encoding="utf-8",
            )
            fresh.write_text(
                json.dumps(patch_document(queue=False), ensure_ascii=False),
                encoding="utf-8",
            )
            self.assertGreater(existing.stat().st_size, 1_500_000)
            self.assertLess(existing.stat().st_size, MAX_PRIVATE_PATCH)
            with patch.object(sys, "argv", [
                "carry", "--existing", str(existing), "--fresh", str(fresh),
                "--output", str(carried), "--day", DAY.isoformat(),
            ]), redirect_stdout(StringIO()):
                carry.main()
            original = json.loads(carried.read_text(encoding="utf-8"))
            self.assertEqual(len(original["open_world_research"]), 1)
            self.assertFalse(original["safe_to_publish"])

            with patch.object(sys, "argv", [
                "dossiers", "--observation-root", str(observation),
                "--research-root", str(research),
                "--patch-file", str(carried),
                "--output-file", str(updated),
                "--day", DAY.isoformat(),
            ]), redirect_stdout(StringIO()):
                dossier.main()
            next_patch = json.loads(updated.read_text(encoding="utf-8"))
            self.assertEqual(next_patch["open_world_research"],
                             original["open_world_research"])
            self.assertFalse(next_patch["safe_to_publish"])
            self.assertEqual(next_patch["additions"], [])
            self.assertEqual(next_patch["updates"], [])

    def test_input_greater_than_shared_five_megabyte_cap_fails_closed(self):
        from ptitesondes_national_backlog_bridge import _read
        with TemporaryDirectory() as temp:
            file = Path(temp) / "oversized.json"
            file.write_bytes(b" " * (dossier.MAX_PRIVATE_PATCH_BYTES + 1))
            with self.assertRaisesRegex(ValueError, "invalid_private_bridge_input"):
                _read(file, dossier.MAX_PRIVATE_PATCH_BYTES)


if __name__ == "__main__":
    unittest.main()
