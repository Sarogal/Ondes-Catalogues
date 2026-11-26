from copy import deepcopy
from datetime import date, timedelta
import json
import unittest
from unittest.mock import Mock

from ptitesondes_catalogue_geo_correction_preview import (
    preview, structured_event_identity, GEO_FIELDS,
)
from ptitesondes_catalogue_geo_research import research_queue
from ptitesondes_catalogue_geo_rotation import identity, SCHEMA

DAY = date(2026, 11, 26)
EVENT = dict(id="historic-theatre", title="Les comptines", city="Ville",
             venue="Théâtre des enfants", department="Test (01)", region="Test",
             date_start="2026-12-12", date_end="2026-12-12",
             category="lecture-jeunesse", source_url="https://venue.example/event")
NODE = {"@type": "Event", "name": EVENT["title"], "startDate": "2026-12-12T10:00:00",
        "endDate": "2026-12-12T11:00:00", "eventStatus": "https://schema.org/EventScheduled",
        "location": {"@type": "Place", "name": EVENT["venue"],
                     "address": {"addressLocality": EVENT["city"]}}}


def page(node=None):
    return '<script type="application/ld+json">' + json.dumps(NODE if node is None else node) + '</script>'


def fixture():
    doc = dict(version=3, updated_at="2026-11-26", events=[
        deepcopy(EVENT), dict(EVENT, id="already-valid", lat=44.5, lng=2.25),
        dict(EVENT, id="expired", date_start="2026-10-01", date_end="2026-10-01")])
    group = research_queue(doc, DAY)["research_groups"][0]
    proof = dict(city=group["city"], venue=group["venue"],
                 status="independent_venue_point_found", publication_ready=False,
                 event_identity_recheck_required=True,
                 venue_point=dict(lat=44.5, lng=2.25,
                     official="https://venue.example/contact", geo_source="Independent BAN"))
    state = dict(schema=SCHEMA, latest={identity(group): dict(day=DAY.isoformat(), result=proof)})
    return doc, state, proof


class HistoricalCorrectionPreviewTests(unittest.TestCase):
    def test_fresh_research_and_source_allow_geo_only_preview(self):
        doc, state, proof = fixture()
        before = deepcopy(doc)
        researcher, reader = Mock(return_value=proof), Mock(return_value=page())
        corrected, audit = preview(doc, DAY, state, researcher=researcher, source_reader=reader)
        self.assertEqual(doc, before)
        self.assertEqual(audit["proposed_count"], 1)
        self.assertEqual(audit["public_writes"], 0)
        self.assertFalse(audit["publication_ready"])
        self.assertEqual(corrected["events"][0]["lat"], 44.5)
        self.assertEqual(corrected["events"][0]["geo_verified_at"], DAY.isoformat())
        self.assertEqual(corrected["events"][1:], before["events"][1:])
        self.assertEqual(set(corrected["events"][0])-set(EVENT), GEO_FIELDS)
        researcher.assert_called_once()
        reader.assert_called_once_with(EVENT["source_url"])

    def test_checkpoint_is_not_a_proof(self):
        doc, state, proof = fixture()
        bad = deepcopy(proof)
        bad["venue_point"]["lat"] = 45
        for fresh in (None, bad, dict(proof, city="Other")):
            reader = Mock(side_effect=AssertionError("no event fetch"))
            out, audit = preview(doc, DAY, state, researcher=lambda *_: fresh, source_reader=reader)
            self.assertEqual(out, doc)
            self.assertEqual(audit["proposed_count"], 0)
            reader.assert_not_called()
        next(iter(state["latest"].values()))["day"] = (DAY-timedelta(days=8)).isoformat()
        out, audit = preview(doc, DAY, state, researcher=Mock(side_effect=AssertionError()))
        self.assertEqual(audit["examined_groups"], 0)

    def test_moved_cancelled_wrong_date_or_duplicate_event_not_identity(self):
        for key, value in (("name", "Other"), ("startDate", "2026-12-13"),
                           ("eventStatus", "https://schema.org/EventCancelled"),
                           ("location", {"name": EVENT["venue"], "address": {"addressLocality": "Other"}})):
            node = dict(NODE, **{key: value})
            self.assertFalse(structured_event_identity(EVENT, page(node)))
        self.assertFalse(structured_event_identity(EVENT, page([NODE, NODE])))
        doc, state, proof = fixture()
        corrected, audit = preview(doc, DAY, state, researcher=lambda *_: proof,
            source_reader=lambda _: page(dict(NODE, eventStatus="EventCancelled")))
        self.assertEqual(corrected, doc)
        self.assertEqual(audit["reasons"]["event_identity_unconfirmed"], 1)

    def test_persistent_fairness_groups_and_sessions_after_failures(self):
        doc, state, proof = fixture()
        doc["events"] = [dict(EVENT, id="a-%02d" % i) for i in range(15)]
        doc["events"] += [dict(EVENT, id="other-%d" % i, venue="Salle %d" % i)
                          for i in range(1, 5)]
        groups = research_queue(doc, DAY)["research_groups"]
        proofs = {g["venue"]: dict(proof, venue=g["venue"]) for g in groups}
        state["latest"] = {identity(g): dict(day=DAY.isoformat(), result=proofs[g["venue"]])
                           for g in groups}
        seen_groups = []
        def researcher(g, _):
            seen_groups.append(g["venue"])
            return proofs[g["venue"]]
        progress = None
        seen = set()
        for _ in range(8):
            _, audit = preview(doc, DAY, state, progress=progress, researcher=researcher,
                               source_reader=lambda _: "<html>unavailable</html>")
            self.assertLessEqual(audit["source_reads"], 12)
            self.assertLessEqual(audit["examined_groups"], 3)
            progress = audit["progress"]
            key = identity(groups[0])
            seen.add(progress["events"][key][0])
            self.assertEqual(audit["proposed_count"], 0)
        self.assertEqual(set(seen_groups), set(proofs))
        self.assertGreaterEqual(len(seen), 4)
        self.assertEqual(set(progress["events"][identity(groups[0])]),
                         set(groups[0]["missing_ids"]))

    def test_repeated_preview_does_not_repair_existing_valid_point(self):
        doc, state, proof = fixture()
        corrected, _ = preview(doc, DAY, state, researcher=lambda *_: proof, source_reader=lambda _: page())
        after, audit = preview(corrected, DAY, state, researcher=Mock(side_effect=AssertionError()))
        self.assertEqual(after, corrected)
        self.assertEqual(audit["proposed_count"], 0)
