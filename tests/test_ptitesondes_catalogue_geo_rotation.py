from datetime import date
import unittest
from unittest.mock import Mock
from tempfile import TemporaryDirectory
from pathlib import Path
import json

from ptitesondes_catalogue_geo_rotation import rotate, write_state, identity
from ptitesondes_catalogue_geo_research import research_queue

DAY = date(2026, 11, 25)


def doc(names):
    return dict(events=[dict(id=name, city="Ville", venue=name,
                             date_start="2027-01-01") for name in names])


class RotationTests(unittest.TestCase):
    def test_fairness_after_insertion_and_removal(self):
        seen = []
        def reader(group, day):
            seen.append(group["venue"])
            return dict(status="held", publication_ready=False)
        state, summary = rotate(doc("ABCDE"), DAY, researcher=reader)
        self.assertEqual(seen, list("ABC"))
        self.assertEqual(summary["never_examined"], 2)
        # D disappears; new name sorts before all old names. E still runs first.
        state, summary = rotate(doc(["0", "A", "B", "C", "E"]), DAY, state, researcher=reader)
        self.assertEqual(seen[3:], list("EAB"))
        self.assertEqual(summary["never_examined"], 1)
        state, summary = rotate(doc(["0", "A", "B", "C", "E"]), DAY, state, researcher=reader)
        self.assertIn("0", seen[6:])
        self.assertEqual(summary["never_examined"], 0)
        self.assertEqual(len(state["pending"]), 5)

    def test_temporary_failure_keeps_place_in_rotation(self):
        reader = Mock(side_effect=TimeoutError())
        state, summary = rotate(doc("ABCD"), DAY, researcher=reader)
        self.assertEqual(summary["examined"], 3)
        self.assertEqual(len(state["pending"]), 4)
        self.assertTrue(all(x["result"]["status"] == "research_retry_later"
                            for x in state["latest"].values()))
        self.assertEqual(summary["public_writes"], 0)

    def test_invalid_state_refused(self):
        with self.assertRaises(ValueError):
            rotate(doc("A"), DAY, {"schema": "other"})

    def test_atomic_state_file(self):
        with TemporaryDirectory() as root:
            path = Path(root) / "state.json"
            state, _ = rotate(doc("A"), DAY, researcher=lambda *a:
                              dict(status="held", publication_ready=False))
            write_state(path, state)
            self.assertEqual(json.loads(path.read_text()), state)
            self.assertFalse(path.with_name("state.json.tmp").exists())


    def test_hint_priority_preserves_fifo_and_no_starvation(self):
        catalogue = doc("ABCDEFGH")
        groups = research_queue(catalogue, DAY)["research_groups"]
        keys = {g["venue"]: identity(g) for g in groups}
        seen = []
        def reader(group, day):
            seen.append(group["venue"])
            return dict(status="held", publication_ready=False)
        priority = {keys["H"], keys["G"], "f" * 64}
        state, summary = rotate(catalogue, DAY, researcher=reader, priority_keys=priority)
        self.assertEqual(seen, list("ABG"))
        self.assertEqual(summary["accelerated_hints"], 1)
        self.assertEqual(summary["examined"], 3)
        self.assertEqual(len(state["pending"]), 8)
        self.assertEqual(len(set(state["pending"])), 8)
        state, summary = rotate(catalogue, DAY, state, researcher=reader, priority_keys=priority)
        self.assertEqual(seen[3:], list("CDH"))
        state, summary = rotate(catalogue, DAY, state, researcher=reader, priority_keys=priority)
        self.assertEqual(seen[6:8], list("EF"))
        self.assertEqual(summary["never_examined"], 0)
        self.assertEqual(summary["public_writes"], 0)

    def test_unknown_or_already_selected_hint_does_not_reorder(self):
        catalogue = doc("ABCDE")
        keys = {g["venue"]: identity(g) for g in research_queue(catalogue, DAY)["research_groups"]}
        seen = []
        def reader(group, day):
            seen.append(group["venue"])
            return dict(status="held", publication_ready=False)
        _, summary = rotate(catalogue, DAY, researcher=reader,
                            priority_keys={keys["C"], keys["E"]})
        self.assertEqual(seen, list("ABC"))
        self.assertEqual(summary["accelerated_hints"], 0)
