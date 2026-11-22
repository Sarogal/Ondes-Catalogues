"""Ensure national private Publisher batches cannot be monopolised by an agenda."""
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ptitesondes_open_world_private_dossier_intake import fair_dossier_order, MAX_DOSSIERS


def item(agenda_uid, event_uid, day, venue="new"):
    return {
        "date_start": f"2026-12-{day:02d}",
        "lead": {"agenda_uid": agenda_uid, "event_uid": event_uid},
        "official_event_url": f"https://openagenda.com/source-{agenda_uid}/events/{event_uid}",
        "official_venue_url": f"https://openagenda.com/source-{agenda_uid}/events/{event_uid}",
    }


class FairNationalDossiersTests(unittest.TestCase):
    def test_busy_calendar_cannot_monopolize_first_eighty(self):
        source = []
        for event_uid in range(100, 140):
            for day in range(1, 10):
                source.append(item(1, event_uid, day))
        for event_uid in range(200, 220):
            source.append(item(2, event_uid, 15))
        for event_uid in range(300, 310):
            source.append(item(3, event_uid, 16))
        result = fair_dossier_order(source)
        self.assertEqual(len(result), len(source))
        first = result[:MAX_DOSSIERS]
        self.assertEqual({x["lead"]["agenda_uid"] for x in first}, {1, 2, 3})
        self.assertEqual(len({x["lead"]["event_uid"] for x in first
                              if x["lead"]["agenda_uid"] == 1}), 40)
        self.assertCountEqual(
            [repr(x) for x in result], [repr(x) for x in source])

    def test_thirty_six_representations_never_dropped(self):
        source = [item(7, 777, ((k % 25) + 1)) for k in range(36)]
        source += [item(8, 888, 4)]
        sorted_rows = fair_dossier_order(source)
        self.assertEqual(len(sorted_rows), len(source))
        self.assertEqual(
            sum(x["lead"]["event_uid"] == 777 for x in sorted_rows), 36)
        self.assertEqual(sorted_rows[1]["lead"]["agenda_uid"], 8)

    def test_one_busy_program_does_not_hide_other_programs_same_agenda(self):
        source = [item(10, 1, (i % 25)+1) for i in range(140)]
        source += [item(10, 2, 2), item(10, 3, 3)]
        ordered = fair_dossier_order(source)
        self.assertEqual([x["lead"]["event_uid"] for x in ordered[:5]],
                         [1, 2, 3, 1, 1])
        self.assertEqual(len(ordered), 142)

    def test_deterministic_even_if_inventory_changes_order(self):
        data = [item(a, uid, d) for a in range(1, 5)
                for uid in range(a*10, a*10+4) for d in range(1, 8)]
        expected = fair_dossier_order(data)
        self.assertEqual(expected, fair_dossier_order(list(reversed(data))))
        self.assertEqual(
            expected, fair_dossier_order(data[::2]+data[1::2]))

    def test_disjoint_first_four_batches_and_future_waves(self):
        source = [item(a, a*1000+k, (k % 25)+1)
                  for a in range(1, 5) for k in range(112)]
        ordered = fair_dossier_order(source)
        first_wave = [
            ordered[i*MAX_DOSSIERS:(i+1)*MAX_DOSSIERS] for i in range(4)]
        self.assertEqual(len(first_wave[0]), MAX_DOSSIERS)
        self.assertEqual(len(set(map(id, sum(first_wave, [])))), 320)
        self.assertEqual(len(ordered[320:]), 128)
        self.assertCountEqual(
            [repr(x) for x in ordered], [repr(x) for x in source])

    def test_empty_and_single_event(self):
        self.assertEqual(fair_dossier_order([]), [])
        self.assertEqual(fair_dossier_order([item(1, 2, 3)]),
                         [item(1, 2, 3)])


if __name__ == "__main__":
    unittest.main()
