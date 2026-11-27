from datetime import date
import unittest
from ptitesondes_open_world_permanent_place_research import directory_cycle
from test_ptitesondes_open_world_permanent_place_research import report, row

DAY = date(2026, 11, 27)

def lead(name):
    return {"city": "Les Bois", "venue": name, "status": "not_inspected_yet",
            "observed_at": None, "public_eligible": False,
            "gps_verified": False, "official_site_verified": False}

def page(n, *records):
    return {"schema": "ptitesondes.cultural_directory_private_page.v1",
            "next_page": n, "rows_examined": 20, "records": list(records),
            "publication_ready": False, "public_writes": 0}

def offline(*args):
    raise OSError("offline")

def run(base, old, scan, **kwargs):
    return directory_cycle(base, old, DAY, directory_scan=scan,
        osm_fetch=lambda *_: {"elements": []}, **kwargs)

class DirectoryQueueTests(unittest.TestCase):
    def test_migration_cursor_and_outage_preserve_leads(self):
        base = report(row())
        old, _ = run(base, None, offline)
        old.pop("directory")
        a, first = run(base, old, lambda n: page(n+1, lead("Ludothèque A")))
        self.assertEqual(first["directory_leads_added"], 1)
        self.assertEqual(a["directory"]["next_page"], 2)
        self.assertEqual(len(a["records"]), 2)
        b, second = run(base, a, offline)
        self.assertEqual(second["directory_unavailable"], 1)
        self.assertEqual(b["directory"], a["directory"])
        self.assertEqual(len(b["records"]), 2)
        c, third = run(base, b, lambda n: page(n+1, lead("Ludothèque A"), lead("Ludothèque B")))
        self.assertEqual(third["directory_leads_added"], 1)
        self.assertEqual(c["directory"]["next_page"], 3)
        self.assertEqual(len(c["records"]), 3)

    def test_untrusted_permission_cannot_enter_queue(self):
        a, summary = run(report(row()), None,
                         lambda n: page(n+1, dict(lead("Ludothèque A"), public_eligible=True)))
        self.assertEqual(summary["directory_unavailable"], 1)
        self.assertEqual(a["directory"]["next_page"], 1)
        self.assertEqual(a["directory"]["records"], [])

    def test_retry_and_new_lead_both_receive_work(self):
        base = report(row())
        old, _ = run(base, None, offline, limit=2)
        a, summary = run(base, old, lambda n: page(n+1, lead("Ludothèque A"), lead("Ludothèque B")), limit=2)
        self.assertEqual(summary["examined"], 2)
        self.assertEqual(summary["unattempted"], 1)
        self.assertEqual(len(a["records"]), 2)
        self.assertEqual(len(a["directory"]["records"]), 2)

if __name__ == "__main__":
    unittest.main()
