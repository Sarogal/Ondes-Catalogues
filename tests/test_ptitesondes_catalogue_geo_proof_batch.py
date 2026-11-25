import unittest
from unittest.mock import Mock
from datetime import date
from ptitesondes_catalogue_geo_proof_batch import research_group, run_batch
from test_ptitesondes_shared_venue_location_evidence import directory, html, ban, GROUP, URL

DAY = date(2026, 11, 25)


def group(**kw):
    return dict(GROUP, active_ids=["event-1"], missing_ids=["event-1"],
                source_urls=[URL], **kw)


class CatalogueGeoProofTests(unittest.TestCase):
    def test_independent_proof_not_event_approval(self):
        result = research_group(group(), DAY, directory_get=lambda _: directory(),
                                html_get=lambda _: html(), ign_get=lambda _: ban())
        self.assertEqual(result["status"], "independent_venue_point_found")
        self.assertTrue(result["event_identity_recheck_required"])
        self.assertFalse(result["publication_ready"])
        self.assertEqual(result["venue_point"]["lat"], 44.5)

    def test_no_fetch_on_unverified_domain(self):
        read = Mock(side_effect=AssertionError("unexpected HTML read"))
        result = research_group(group(), DAY, directory_get=lambda _: {},
                                html_get=read, ign_get=Mock())
        self.assertEqual(result["status"], "municipality_not_independently_identified")
        read.assert_not_called()

    def test_wrong_name_no_point(self):
        result = research_group(group(), DAY, directory_get=lambda _: directory(),
                                html_get=lambda _: html("Other place"),
                                ign_get=lambda _: ban())
        self.assertNotIn("venue_point", result)

    def test_batch_bound_and_rotation(self):
        doc = dict(events=[dict(id=str(i), city="Ville", venue="Salle "+str(i),
                                date_start="2026-12-01") for i in range(5)])
        reader = Mock(return_value=dict(status="held"))
        first = run_batch(doc, DAY, researcher=reader)
        self.assertEqual(first["next_offset"], 3)
        self.assertEqual(reader.call_count, 3)
        last = run_batch(doc, DAY, first["next_offset"], researcher=reader)
        self.assertEqual(last["next_offset"], 0)
        self.assertEqual(reader.call_count, 5)
        self.assertEqual(last["public_writes"], 0)
