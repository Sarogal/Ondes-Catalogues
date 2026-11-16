"""Adversarial offline tests: a genuine municipal gate is NOT a publisher."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ptitesondes_municipal_admission import (
    SCHEMA, editorial_decision_line,
    explicit_municipal_category_valid, inspect_municipal_admission,
)
from ptitesondes_municipal_human_decision import (
    API, APPROVER, MANIFEST_SCHEMA, REPOSITORY,
    canonical_digest, decision_line, html_digest,
)
from ptitesondes_municipal_preflight import municipal_calendar_url
from test_ptitesondes_municipal_preflight import (
    EVENT, CALENDAR, candidate,
)
from test_ptitesondes_nonmusic_release_contract import (
    TODAY, URL, access, private_access, private_review,
)
from ptitesondes_municipal_appendonly_dryrun import _event_from_proposal

PR_SHA = "a" * 40
PR_NUMBER = 88


def catalogue():
    return json.loads((ROOT / "docs/ptitesondes/sorties.json").read_text(encoding="utf-8"))


def fixture(*, explicit=True, event_html=None):
    c = candidate()
    a = access()
    if explicit:
        a["access_status"] = "conditions_explicit_to_recheck"
        a["price_evidence"] = "explicit_free"
        a["registration_evidence"] = "explicit_required"
    html = event_html if event_html is not None else (
        EVENT.replace("</section>",
                      " Gratuit. Inscription obligatoire. </section>")
        if explicit else EVENT
    )
    doc = catalogue()
    m = {
        "schema": MANIFEST_SCHEMA, "mode": "request_human_review_no_publication",
        "review_id": c["review_id"], "pr_number": PR_NUMBER,
        "head_sha": PR_SHA, "candidate_sha256": canonical_digest(c),
        "access_sha256": canonical_digest(a),
        "event_html_sha256": html_digest(html),
        "catalogue_sha256": canonical_digest(doc),
        "date_start": c["date_start"],
        "official_event_url": c["official_event_url"],
    }
    return doc, c, a, m, html


def github_for(manifest, *, decision="APPROVE", permission="admin",
               editorial="ABSENT"):
    pr = {
        "number": PR_NUMBER, "state": "open", "merged_at": None,
        "head": {"sha": PR_SHA, "repo": {"full_name": REPOSITORY}},
        "base": {"ref": "main", "repo": {"full_name": REPOSITORY}},
    }
    decisions = [] if decision == "ABSENT" else [
        {"id": 101, "body": decision_line(manifest, "APPROVE"),
         "user": {"login": APPROVER, "type": "User"},
         "author_association": "OWNER"},
    ]
    if decision == "REVOKE":
        decisions.append({
            "id": 102, "body": decision_line(manifest, "REVOKE"),
            "user": {"login": APPROVER, "type": "User"},
            "author_association": "OWNER",
        })
    if editorial in ("SOURCE_ONLY", "REVOKE", "FORGED", "STALE"):
        body = editorial_decision_line(manifest, "SOURCE_ONLY")
        if editorial == "STALE":
            body = body.replace(manifest["head_sha"], "f" * 40)
        decisions.append({
            "id": 103, "body": body,
            "user": {"login": "not-the-owner" if editorial == "FORGED" else APPROVER,
                     "type": "User"},
            "author_association": "OWNER",
        })
        if editorial == "REVOKE":
            decisions.append({
                "id": 104,
                "body": editorial_decision_line(manifest, "REVOKE"),
                "user": {"login": APPROVER, "type": "User"},
                "author_association": "OWNER",
            })
    def get(url, token):
        if token != "test-token":
            raise ValueError("token_mismatch")
        if url == API + "/pulls/88":
            return pr
        if url == API + "/collaborators/Sarogal/permission":
            return {"permission": permission}
        if url == API + "/issues/88/comments?per_page=100&page=1":
            return decisions
        raise ValueError("unapproved_test_endpoint")
    return get


def execute(*, doc=None, c=None, a=None, m=None, html=None,
            decision="APPROVE", editorial="ABSENT", geo=True,
            token="test-token", cal=CALENDAR, unavailable=False, github=None):
    catalog, cand, conditions, manifest, official = fixture()
    catalog = doc if doc is not None else catalog
    cand = c if c is not None else cand
    conditions = a if a is not None else conditions
    manifest = m if m is not None else manifest
    official = html if html is not None else official

    def get(url):
        if unavailable:
            raise OSError("offline")
        data = {URL: official, municipal_calendar_url(date(2026,11,25)): cal}
        return data[url]
    return inspect_municipal_admission(
        catalog, private_review(cand), private_access(conditions),
        manifest, TODAY, token=token, source_get=get,
        github_get=github or github_for(
            manifest, decision=decision, editorial=editorial),
        geo_check=lambda ev: (geo, "independent registry test fixture"),
    )


class MunicipalAdmissionGateTests(unittest.TestCase):
    def test_human_authenticated_exact_proof_is_diagnostic_not_release(self):
        before = catalogue()
        original = deepcopy(before)
        out = execute(doc=before)
        self.assertEqual(len(before["events"]), 548)
        self.assertEqual(out["schema"], SCHEMA)
        self.assertTrue(out["technical_admission_diagnostic_passed"])
        self.assertTrue(out["authenticated_human_evidence"])
        self.assertEqual(out["blockers"], [])
        self.assertFalse(out["publication_ready"])
        self.assertFalse(out["approval_granted_to_publisher"])
        self.assertTrue(out["publication_connector_not_activated"])
        self.assertEqual(out["public_writes"], 0)
        self.assertNotIn("patch", out)
        self.assertNotIn("additions", out)
        self.assertNotIn("events", out)
        self.assertEqual(original, before)

    def test_no_private_approval_or_revocation_blocks(self):
        for decision in ("ABSENT", "REVOKE"):
            with self.subTest(decision=decision):
                out = execute(decision=decision)
                self.assertFalse(out["technical_admission_diagnostic_passed"])
                self.assertFalse(out["authenticated_human_evidence"])
                self.assertIn("authenticated_private_approval_absent_or_revoked",
                              out["blockers"])
        out = execute(token=None)
        self.assertIn("authenticated_private_approval_missing", out["blockers"])

    def test_unknown_access_conditions_require_separate_editorial_decision(self):
        doc, c, a, m, html = fixture(explicit=False)
        out = execute(doc=doc, c=c, a=a, m=m, html=html)
        self.assertIn("editorial_unknown_conditions_pending", out["blockers"])
        self.assertFalse(out["publication_ready"])
        self.assertFalse(out["technical_admission_diagnostic_passed"])

    def test_explicit_second_editorial_consent_unlocks_only_diagnostic(self):
        doc, c, a, m, html = fixture(explicit=False)
        out = execute(doc=doc, c=c, a=a, m=m, html=html,
                      editorial="SOURCE_ONLY")
        self.assertTrue(out["authenticated_human_evidence"])
        self.assertTrue(out["authenticated_unknown_access_source_only_decision"])
        self.assertTrue(out["technical_admission_diagnostic_passed"])
        self.assertFalse(out["publication_ready"])
        self.assertNotIn("price", out)
        self.assertNotIn("registration", out)
        self.assertNotIn("additions", out)

    def test_forged_or_revoked_editorial_consent_fails_closed(self):
        doc, c, a, m, html = fixture(explicit=False)
        for editorial in ("FORGED", "STALE", "REVOKE"):
            with self.subTest(editorial=editorial):
                out = execute(doc=doc, c=c, a=a, m=m, html=html,
                              editorial=editorial)
                self.assertTrue(out["authenticated_human_evidence"])
                self.assertFalse(
                    out["authenticated_unknown_access_source_only_decision"])
                self.assertIn("editorial_unknown_conditions_pending",
                              out["blockers"])
                self.assertFalse(out["publication_ready"])

    def test_source_changed_after_approval_invalidates_manifest(self):
        doc, c, a, m, html = fixture()
        different = html.replace("Gratuit.", "Gratuit pour tous.")
        out = execute(doc=doc, c=c, a=a, m=m, html=different)
        self.assertIn("private_evidence_or_decision_unverified", out["blockers"])

    def test_unauthenticated_or_insufficient_permission_fails_closed(self):
        m = fixture()[3]
        out = execute(github=github_for(m, permission="read"))
        self.assertIn("private_evidence_or_decision_unverified", out["blockers"])

    def test_wrong_date_and_time_cannot_borrow_adjacent_session(self):
        doc, c, a, m, html = fixture()
        for bad in (html.replace("mercredi 25 novembre", "mercredi 18 novembre"),
                    html.replace("9h30", "10h30"),
                    CALENDAR.replace("09h30", "10h30")):
            with self.subTest(bad=bad[:60]):
                out = execute(html=bad) if bad != CALENDAR.replace("09h30", "10h30") else execute(cal=bad)
                self.assertFalse(out["technical_admission_diagnostic_passed"])

    def test_cancelled_or_full_event_rejected(self):
        html = fixture()[4]
        for word in ("Événement annulé.", "Événement complet."):
            with self.subTest(word=word):
                out = execute(html=html.replace("</section>", word+"</section>"))
                self.assertFalse(out["technical_admission_diagnostic_passed"])

    def test_wrong_geolocation_and_missing_independent_registry(self):
        out = execute(geo=False)
        self.assertIn("independent_venue_registry_missing_or_different",
                      out["blockers"])
        doc,c,a,m,html = fixture()
        c["lat"] = 48.85
        with self.assertRaisesRegex(ValueError, "invalid_venue_point"):
            execute(c=c)

    def test_different_source_same_event_is_duplicate(self):
        doc = catalogue()
        original_len = len(doc["events"])
        doc["events"].append({
            "id": "published-under-another-feed",
            "title": candidate()["title"], "date_start": "2026-11-25",
            "date_end": "2026-11-25", "city": "Le Gosier",
            "venue": "Médiathèque Raoul Georges Nicolo",
            "source_url": "https://another.example/one",
            "category": "concert",
        })
        # The catalogue hash is bound to the human decision: mismatch blocks.
        out = execute(doc=doc)
        self.assertFalse(out["technical_admission_diagnostic_passed"])
        self.assertEqual(len(doc["events"]), original_len + 1)
        # Re-bind the new snapshot to a new human review and check duplication.
        cat,c,a,m,html = fixture()
        m["catalogue_sha256"] = canonical_digest(doc)
        out = execute(doc=doc, m=m)
        self.assertIn("duplicate_published_across_sources", out["blockers"])

    def test_unknown_category_and_forged_musical_category_are_rejected(self):
        doc,c,a,m,html = fixture()
        for category in ("concert", "invented-jeunesse", "atelier-numerique"):
            with self.subTest(category=category):
                bad = deepcopy(c)
                bad["category_proposal"] = category
                if category == "atelier-numerique":
                    bad["category_label_proposal"] = "Atelier numérique"
                with self.assertRaises(ValueError):
                    execute(c=bad)

    def test_independent_source_unavailable_rejects(self):
        out = execute(unavailable=True)
        self.assertFalse(out["technical_admission_diagnostic_passed"])
        self.assertIn("municipal_source_unavailable", out["blockers"])

    def test_production_allowlist_unmodified(self):
        doc = catalogue()
        event = _event_from_proposal(candidate(), TODAY.isoformat(), TODAY.isoformat())
        ok, reason = explicit_municipal_category_valid(event, doc, TODAY)
        self.assertTrue(ok, reason)
        from merge_policy import valid
        cats = {r["category"] for r in doc["events"]}
        fields = set().union(*(set(r) for r in doc["events"]))
        self.assertEqual(valid(event, cats, fields, TODAY),
                         (False, "catégorie inconnue"))

    def test_historical_catalogue_modification_detected_during_read(self):
        doc = catalogue()
        first = doc["events"][0]["title"]
        def malicious_geo(ev):
            doc["events"][0]["title"] = "HACKED"
            return True, "forged"
        _,c,a,m,html = fixture()
        def source(url):
            return html if url == URL else CALENDAR
        with self.assertRaisesRegex(ValueError, "historical_catalogue_mutated"):
            inspect_municipal_admission(
                doc, private_review(c), private_access(a), m, TODAY,
                token="test-token", source_get=source,
                github_get=github_for(m), geo_check=malicious_geo)
        self.assertNotEqual(doc["events"][0]["title"], first)

    def test_no_scheduled_workflow_or_public_patch_created(self):
        doc = catalogue()
        out = execute(doc=doc)
        self.assertFalse(out["publication_ready"])
        self.assertEqual(out["historical_records_modified"], 0)
        self.assertEqual(out["historical_records_deleted"], 0)
        self.assertEqual(out["public_writes"], 0)


if __name__ == "__main__":
    unittest.main()
