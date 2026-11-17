"""Adversarial, network-free municipal append-only rehearsal on real 548-event input."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import json
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))

from ptitesondes_municipal_appendonly_dryrun import SCHEMA, rehearse, canonical_sha256, _event_from_proposal
from merge_policy import valid
from ptitesondes_nonmusic_release_contract import TYPES
from ptitesondes_municipal_preflight import municipal_calendar_url
from test_ptitesondes_municipal_preflight import EVENT, CALENDAR, candidate
from test_ptitesondes_nonmusic_release_contract import (
    TODAY, URL, private_review, private_access, access, public_catalogue
)


def source():
    # CI runs on the public repository. This reads the EXISTING tracked
    # production catalogue, not a synthetic 548-row substitute.
    return json.loads((ROOT/"docs/ptitesondes/sorties.json").read_text(encoding="utf-8"))


def official_get(url):
    cases={URL: EVENT, municipal_calendar_url(date(2026,11,25)): CALENDAR}
    return cases[url]


def stamps(candidate_):
    return {candidate_["review_id"]:{
        "source_checked_on":TODAY.isoformat(),
        "geo_checked_on":TODAY.isoformat()}}


def run(c=None,a=None,catalogue=None,get=official_get,dates=None,day=TODAY):
    c=c if c is not None else candidate()
    a=a if a is not None else access()
    return rehearse(
        catalogue if catalogue is not None else source(),
        private_review(c),private_access(a),day,source_get=get,
        verified_dates=dates if dates is not None else stamps(c)
    )


class AppendOnlySimulationTests(unittest.TestCase):
    def test_exact_548_historical_rows_are_intact_after_one_hypothetical(self):
        original=source()
        self.assertEqual(len(original["events"]),548)
        before=deepcopy(original)
        fingerprint=canonical_sha256(original)
        summary=run(catalogue=original)
        self.assertEqual(summary["schema"],SCHEMA)
        self.assertEqual(summary["mode"],"in_memory_hypothetical_only_no_patch_no_publication")
        self.assertEqual(summary["historical_preserved"],548)
        self.assertEqual(summary["hypothetical_additions"],1)
        self.assertEqual(summary["hypothetical_total"],549)
        self.assertEqual(summary["historical_records_modified"],0)
        self.assertEqual(summary["historical_records_deleted"],0)
        self.assertEqual(summary["publication_ready"],0)
        self.assertEqual(summary["public_writes"],0)
        self.assertIs(summary["approval_granted_to_publisher"],False)
        self.assertIs(summary["current_publisher_supports_new_categories"],False)
        self.assertEqual(summary["catalogue_sha256"],fingerprint)
        self.assertEqual(original,before)
        self.assertEqual(canonical_sha256(original),fingerprint)
        self.assertNotIn("patch",summary)
        self.assertNotIn("additions",summary)
        self.assertNotIn("events",summary)

    def test_actual_publisher_rejects_all_four_nonmusical_categories(self):
        # Prove existing merge_policy cannot be silently used as a release path.
        catalogue=source()
        categories={row["category"] for row in catalogue["events"]}
        fields=set().union(*(set(e) for e in catalogue["events"]))
        self.assertTrue(set(TYPES).isdisjoint(categories))
        for slug,label in TYPES.items():
            with self.subTest(slug=slug):
                c=candidate()
                c["category_proposal"]=slug
                c["category_label_proposal"]=label
                event=_event_from_proposal(c,TODAY.isoformat(),TODAY.isoformat())
                current_ok,current_reason=valid(event,categories,fields,TODAY)
                self.assertFalse(current_ok)
                self.assertEqual(current_reason,"catégorie inconnue")
                future_ok,_=valid(event,categories|set(TYPES),fields,TODAY)
                self.assertTrue(future_ok)

    def test_current_publisher_category_gate_cannot_be_forged(self):
        original=source()
        attempted=deepcopy(original)
        attempted["events"].append({"id":"fake-seed","category":"lecture-jeunesse"})
        # An attacker changing the reference catalogue to smuggle a
        # future category must not be considered a historical baseline.
        self.assertNotEqual(canonical_sha256(attempted),canonical_sha256(original))
        self.assertEqual(len(original["events"]),548)

    def test_missing_independent_geo_or_source_verification_blocks(self):
        c=candidate()
        for x in ({}, {c["review_id"]:{}},
                  {c["review_id"]:{"source_checked_on":TODAY.isoformat()}},
                  {c["review_id"]:{"source_checked_on":TODAY.isoformat(),
                                  "geo_checked_on":"2026-10-15"}},
                  {c["review_id"]:{"source_checked_on":"2026-11-30",
                                  "geo_checked_on":TODAY.isoformat()}},
                  {c["review_id"]:{"source_checked_on":"garbage",
                                  "geo_checked_on":TODAY.isoformat()}}):
            with self.subTest(stamps=x):
                report=run(dates=x)
                self.assertEqual(report["hypothetical_additions"],0)
                self.assertEqual(report["blocked_from_rehearsal"],1)
                self.assertEqual(report["public_writes"],0)

    def test_missing_official_page_or_calendar_blocks_hypothetical(self):
        c=candidate()
        for changed in (EVENT.replace("mercredi 25 novembre","mercredi 18 novembre"),
                        EVENT.replace("9h30","10h30"),
                        EVENT.replace("Enfants jusqu'à 3 ans","Public adultes"),
                        EVENT.replace("</section>"," Événement annulé </section>")):
            with self.subTest(html=changed[:70]):
                get=lambda url,changed=changed:changed if url==URL else CALENDAR
                self.assertEqual(run(get=get)["hypothetical_additions"],0)
        def broken_calendar(url):
            return EVENT if url==URL else CALENDAR.replace("09h30","10h30")
        self.assertEqual(run(get=broken_calendar)["hypothetical_additions"],0)

    def test_unknown_and_changed_access_conditions_block(self):
        a=access()
        for price,reg in (("explicit_free","not_stated"),
                          ("not_stated","explicit_required"),
                          ("ambiguous","not_stated"),
                          ("contradictory","not_stated")):
            with self.subTest(price=price,registration=reg):
                a=access()
                a["price_evidence"]=price
                a["registration_evidence"]=reg
                self.assertEqual(run(a=a)["hypothetical_additions"],0)

    def test_matching_existing_event_and_source_id_never_append(self):
        c=candidate()
        public=source()
        # Public catalogue may eventually contain the same occurrence,
        # even under a different ID.
        e={"id":"published-elsewhere","title":c["title"],
           "date_start":c["date_start"],"date_end":c["date_end"],
           "city":c["city"],"venue":c["venue"],
           "category":"concert","source_url":c["official_event_url"]}
        public["events"].append(e)
        self.assertEqual(run(catalogue=public)["hypothetical_additions"],0)
        public=source()
        public["events"].append(dict(e,id=c["review_id"]))
        self.assertEqual(run(catalogue=public)["hypothetical_additions"],0)

    def test_no_unverified_musical_fallback_or_wrong_geo(self):
        for change in (
            {"category_proposal":"concert"},
            {"category_proposal":"atelier-numerique",
             "category_label_proposal":"Atelier numérique"},
            {"lat":48.8584,"lng":2.2945},
            {"region_proposal":"La Réunion"},
            {"age_max_proposal":5},
            {"city":"Pointe-à-Pitre"},
        ):
            with self.subTest(change=change),self.assertRaises(ValueError):
                c=candidate()
                c.update(change)
                run(c=c)

    def test_source_cannot_self_approve_through_read_only_model(self):
        for field in ("approved","safe_to_publish","published"):
            with self.subTest(field=field),self.assertRaises(ValueError):
                c=candidate()
                c[field]=True
                run(c=c)

    def test_read_only_no_writes_even_with_source_unavailable(self):
        def unavailable(url):
            raise OSError("offline")
        result=run(get=unavailable)
        self.assertEqual(result["hypothetical_additions"],0)
        self.assertEqual(result["public_writes"],0)
        self.assertEqual(result["publication_ready"],0)

    def test_repeated_same_series_two_distinct_days_are_not_duplicates(self):
        c1=candidate()
        c2=deepcopy(c1)
        c2["date_start"]="2026-11-18"
        c2["date_end"]="2026-11-18"
        c2["review_id"]="municipal-gosier-3067-2026-11-18"
        c2["calendar_url"]=municipal_calendar_url(date(2026,11,18))
        a1=access()
        a2=deepcopy(a1)
        a2["review_id"]=c2["review_id"]
        a2["date_start"]="2026-11-18"
        official_event=EVENT.replace(
            "mercredi 25 novembre de 9h à 9h30",
            "mercredi 18 novembre de 9h à 9h30 ; mercredi 25 novembre de 9h à 9h30")
        calendar_second=(CALENDAR.replace(
            '25</span>', '18</span>').replace("mer. 25 nov.","mer. 18 nov."))
        sources={URL:official_event,c1["calendar_url"]:CALENDAR,
                 c2["calendar_url"]:calendar_second}
        result=rehearse(
            source(),private_review(c1,c2),private_access(a1,a2),TODAY,
            source_get=lambda url:sources[url],
            verified_dates={**stamps(c1),**stamps(c2)}
        )
        self.assertEqual(result["hypothetical_additions"],2)
        self.assertEqual(result["hypothetical_total"],550)
        self.assertEqual(result["public_writes"],0)

    def test_empty_verification_dates_fail_closed_not_default_to_today(self):
        with self.assertRaisesRegex(ValueError, "missing_reviewed_verification_dates"):
            rehearse(source(),private_review(candidate()),private_access(access()),
                     TODAY,source_get=official_get)

    def test_no_auto_update_to_catalogue_timestamp(self):
        old=source()
        before=old["updated_at"]
        result=run(catalogue=old)
        self.assertEqual(old["updated_at"],before)
        self.assertTrue(result["catalogue_unchanged"])
        self.assertEqual(result["historical_records_modified"],0)


if __name__=="__main__":
    unittest.main()
