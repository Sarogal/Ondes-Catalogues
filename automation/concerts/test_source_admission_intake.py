"""Source discovery must be open-ended, private and non-authoritative."""
from __future__ import annotations

import copy
import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import source_admission_intake as intake

TODAY = dt.date(2026, 11, 21)
CATALOGUE = {"schemaVersion": 1, "events": [], "artists": [], "venues": []}
ORGANIZERS = [{
    "host": "trusted-organizer.fr", "enabled": True,
}]
VENUES = {
    "known-hall": {"host": "trusted-venue.fr"},
}


def lead(host="unknown-bar.fr", *, event=None, source=None, title="NEW BAND",
         name="New Bar", city="Poitiers", date="2027-03-01",
         bucket="genre_tag_review", stable=2, possible=False, detail=True):
    url = event or f"https://{host}/agenda/new-band/"
    return {
        "status": "pending_review", "stableObservations": stable,
        "candidate": {
            "candidateId": f"{host}|{date}|{title}",
            "source": source or "agenda_officiel_new_detail_review",
            "sourceUrl": url,
            "sourcePage": f"https://{host}/agenda/",
            "eventDetailUrl": url,
            "name": title, "venue": name, "city": city,
            "date": date, "reviewBucket": bucket,
            "officialDetailFound": detail,
            "possibleExistingConcert": possible,
            "publicationAllowed": False, "reviewRequired": True,
        },
    }


def registry(*items):
    return {
        "schema": "grossesondes.concert.intake.v1",
        "items": {f"item{i}": row for i, row in enumerate(items)},
    }


def run(data):
    return intake.build(
        data, CATALOGUE, TODAY,
        organizer_sources=ORGANIZERS, reviewed_venues=VENUES)


class UnknownSourcesIntakeTests(unittest.TestCase):
    def test_unknown_venue_and_unknown_artists_enter_private_queue(self):
        item = lead()
        before = copy.deepcopy(item)
        result = run(registry(item))
        self.assertEqual(result["candidateSourceHosts"], 1)
        self.assertEqual(result["previouslyUnreviewedHosts"], 1)
        self.assertEqual(result["stableUnreviewedSourceHosts"], 1)
        self.assertFalse(result["publicationAllowed"])
        self.assertFalse(result["automaticTrustGranted"])
        host = result["reviewQueue"][0]
        self.assertEqual(host["host"], "unknown-bar.fr")
        self.assertEqual(host["eventLeads"], 1)
        self.assertEqual(host["stableOnDistinctDays"], 1)
        self.assertEqual(host["sameHostEventLeads"], 1)
        self.assertFalse(host["independentCorroborationVerified"])
        self.assertFalse(host["networkChecked"])
        self.assertFalse(host["automaticTrustGranted"])
        self.assertEqual(item, before)

    def test_not_tied_to_a_list_or_count_of_bands_venues_organizers(self):
        rows = [lead(host=f"source{i:03d}.fr", title=f"NEW ARTIST {i:03d}")
                for i in range(215)]
        result = run(registry(*rows))
        self.assertEqual(result["previouslyUnreviewedHosts"], 215)
        self.assertEqual(result["stableUnreviewedSourceHosts"], 215)
        self.assertEqual(len(result["reviewQueue"]), 215)
        self.assertTrue(all(not row["automaticTrustGranted"]
                            for row in result["reviewQueue"]))

    def test_two_different_domains_only_signal_a_corroboration_hint(self):
        result = run(registry(lead("source-a.fr"), lead("source-b.fr")))
        self.assertEqual(result["crossHostIdentityHints"], 1)
        self.assertEqual(result["previouslyUnreviewedHosts"], 2)
        self.assertFalse(result["automaticTrustGranted"])
        self.assertTrue(all(not row["independentCorroborationVerified"]
                            for row in result["reviewQueue"]))
        unrelated = run(registry(lead("source-a.fr"),
                                 lead("source-b.fr", title="OTHER BAND")))
        self.assertEqual(unrelated["crossHostIdentityHints"], 0)

    def test_reviewed_organizer_or_venue_never_counts_as_new_authority(self):
        out = run(registry(lead("trusted-venue.fr"),
                           lead("trusted-organizer.fr"),
                           lead("fresh-domain.fr")))
        self.assertEqual(out["candidateSourceHosts"], 3)
        self.assertEqual(out["previouslyUnreviewedHosts"], 1)
        self.assertEqual(out["reviewQueue"][0]["host"], "fresh-domain.fr")

    def test_offsite_billet_link_is_only_an_untrusted_clue(self):
        row = lead(
            "new-town-hall.fr",
            event="https://tickets.example.org/checkout/metal/")
        out = run(registry(row))
        self.assertEqual(out["reviewQueue"][0]["offsiteEventLinks"], 1)
        self.assertEqual(out["reviewQueue"][0]["sameHostEventLeads"], 0)
        self.assertFalse(out["reviewQueue"][0]["automaticTrustGranted"])

    def test_invalid_origins_are_never_admitted(self):
        for source_url in (
            "http://new-bar.fr/agenda/",
            "https://127.0.0.1/agenda/",
            "https://localhost/agenda/",
            "https://new-bar.local/agenda/",
            "https://new-bar.fr:444/agenda/",
            "https://name:pass@new-bar.fr/agenda/",
            "https://new-bar.fr.evil.example/agenda/",
            "https://new-bar.fr/agenda/#event",
        ):
            with self.subTest(source_url=source_url):
                row = lead()
                row["candidate"]["sourcePage"] = source_url
                result = run(registry(row))
                self.assertEqual(result["candidateSourceHosts"], 0)
                self.assertEqual(result["skipped"]["invalid_https_origin_or_event"], 1)
        for source_url in ("https://evil.example.org/agenda/",):
            row = lead()
            row["candidate"]["sourcePage"] = source_url
            result = run(registry(row))
            self.assertEqual(result["reviewQueue"][0]["host"], "evil.example.org")
            self.assertFalse(result["automaticTrustGranted"])

    def test_ics_ticketing_expired_festival_duplicates_and_published_are_held(self):
        items = [
            lead(source="agenda_ics"),
            lead(source="billetterie_brin_de_zinc_a_recouper"),
            lead(bucket="festival_overlap_review"),
            lead(possible=True),
            lead(date="2026-10-01"),
        ]
        result = run(registry(*items))
        self.assertEqual(result["candidateSourceHosts"], 0)
        self.assertEqual(result["skipped"]["not_first_party_claim"], 2)
        self.assertEqual(result["skipped"]["excluded_or_duplicate"], 2)
        self.assertEqual(result["skipped"]["expired"], 1)

        match = lead()
        catalogue = copy.deepcopy(CATALOGUE)
        catalogue["events"].append({
            "officialUrl": match["candidate"]["sourceUrl"],
            "date": match["candidate"]["date"],
        })
        result = intake.build(
            registry(match), catalogue, TODAY,
            organizer_sources=ORGANIZERS, reviewed_venues=VENUES)
        self.assertEqual(result["skipped"]["already_published_exact"], 1)

    def test_a_first_day_is_detected_without_pretending_stability(self):
        result = run(registry(lead(stable=1)))
        self.assertEqual(result["candidateSourceHosts"], 1)
        self.assertEqual(result["stableUnreviewedSourceHosts"], 0)
        self.assertEqual(result["reviewQueue"][0]["stableOnDistinctDays"], 0)

    def test_invalid_inputs_fail_closed(self):
        for bad in ({}, {"schema": "wrong", "items": {}},
                    {"schema": "grossesondes.concert.intake.v1",
                     "items": []}):
            with self.assertRaises(ValueError):
                run(bad)
        with self.assertRaises(ValueError):
            intake.build(registry(), CATALOGUE, "2026-11-21",
                         organizer_sources=ORGANIZERS,
                         reviewed_venues=VENUES)


if __name__ == "__main__":
    unittest.main()
