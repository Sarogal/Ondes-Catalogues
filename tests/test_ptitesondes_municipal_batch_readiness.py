"""Network-free batch contract. Synthetic Gosier fixtures are NOT real proofs."""
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ptitesondes_municipal_batch_readiness import (
    SCHEMA, inspect_municipal_batch,
)
from ptitesondes_municipal_appendonly_dryrun import canonical_sha256
from ptitesondes_municipal_admission import editorial_decision_line
from ptitesondes_municipal_human_decision import (
    API, APPROVER, MANIFEST_SCHEMA, REPOSITORY,
    canonical_digest, decision_line, html_digest,
)
from ptitesondes_municipal_preflight import municipal_calendar_url
from test_ptitesondes_nonmusic_release_contract import (
    TODAY, private_review, private_access,
)
from test_ptitesondes_municipal_preflight import candidate

PR_SHA = "a" * 40
WEEK = ("lundi", "mardi", "mercredi", "jeudi", "vendredi",
        "samedi", "dimanche")


def historical():
    return json.loads(
        (ROOT / "docs/ptitesondes/sorties.json").read_text(encoding="utf-8")
    )


def sample_nine(*, public=None, known_conditions=True):
    """Nine entirely synthetic fixtures, based on session shapes only.

    Invented SPIP ids (9001..9009) and URLs do NOT represent actual municipal
    evidence, prices or approvals. No external host is contacted.
    """
    if public is None:
        public = historical()
    specs = [
        ("2026-11-18", "Mon doudou raconte : heure du conte pour les tout-petits",
         "09:00", "09:30", "lecture-jeunesse", "Lecture jeunesse",
         "jusqua_3_ans", "Jusqu’à 3 ans", None, 3, "Enfants jusqu'à 3 ans"),
        ("2026-11-18", "Les rendez-vous du numérique : robotique",
         "09:30", "11:30", "atelier-numerique", "Atelier numérique",
         "des_8_ans", "Dès 8 ans", 8, None, "Dès 8 ans"),
        ("2026-11-18", "La magie des histoires : heure du conte",
         "10:00", "11:00", "lecture-jeunesse", "Lecture jeunesse",
         "des_4_ans", "Dès 4 ans", 4, None, "Dès 4 ans"),
        ("2026-11-21", "Les jeux du samedi",
         "09:00", "16:30", "jeux-famille", "Jeux en famille",
         "tous_ages_familles", "En famille", None, None,
         "Pour tous les âges et toute la famille"),
        ("2026-11-25", "Mon doudou raconte : heure du conte pour les tout-petits",
         "09:00", "09:30", "lecture-jeunesse", "Lecture jeunesse",
         "jusqua_3_ans", "Jusqu’à 3 ans", None, 3, "Enfants jusqu'à 3 ans"),
        ("2026-11-25", "Les rendez-vous du numérique : robotique",
         "09:30", "11:30", "atelier-numerique", "Atelier numérique",
         "des_8_ans", "Dès 8 ans", 8, None, "Dès 8 ans"),
        ("2026-11-25", "La magie des histoires : heure du conte",
         "10:00", "11:00", "lecture-jeunesse", "Lecture jeunesse",
         "des_4_ans", "Dès 4 ans", 4, None, "Dès 4 ans"),
        ("2026-11-25", "Le rendez-vous des P'tits Racoons : lecture et cinéma",
         "15:00", "17:00", "lecture-cinema", "Lecture et cinéma",
         "des_5_ans", "Dès 5 ans", 5, None, "Dès 5 ans"),
        ("2026-11-28", "Les jeux du samedi",
         "09:00", "16:30", "jeux-famille", "Jeux en famille",
         "tous_ages_familles", "En famille", None, None,
         "Pour tous les âges et toute la famille"),
    ]
    docs, pages, cal_cards, comments = [], {}, {}, []
    for idx, spec in enumerate(specs, start=9001):
        day, title, start, end, slug, label, audience, age_label, lo, hi, age_text = spec
        d = date.fromisoformat(day)
        src = "https://www.villedugosier.fr/evenement/simulation-" + str(idx)
        c = candidate()
        c.update({
            "review_id": f"municipal-gosier-{idx}-{day}",
            "source_event_id": str(idx),
            "title": title,
            "date_start": day, "date_end": day,
            "start_local": start, "end_local": end,
            "category_proposal": slug, "category_label_proposal": label,
            "audience_evidence": audience,
            "age_label_proposal": age_label,
            "age_min_proposal": lo, "age_max_proposal": hi,
            "official_event_url": src,
            "calendar_url": municipal_calendar_url(d),
        })
        a = {
            "review_id": c["review_id"], "official_event_url": src,
            "date_start": day, "access_status": (
                "conditions_explicit_to_recheck" if known_conditions
                else "clarification_required"
            ),
            "price": None, "registration": "unknown",
            "price_evidence": "explicit_free" if known_conditions else "not_stated",
            "registration_evidence": (
                "explicit_required" if known_conditions else "not_stated"
            ),
            "review_required": True,
            "safe_to_publish": False, "approved": False, "published": False,
        }
        start_html = f"{int(start[:2])}h{start[3:]}"
        end_html = f"{int(end[:2])}h{end[3:]}"
        official_html = (
            f"<h1>{title}</h1><section>Médiathèque Raoul Georges Nicolo "
            f"{WEEK[d.weekday()]} {d.day} novembre de "
            f"{start_html} à {end_html}. {age_text}. "
            + ("Gratuit. Inscription obligatoire." if known_conditions else "")
            + "</section><p>Calendrier</p>"
        )
        pages[src] = official_html
        card = (
            '<div class="media-eve">'
            f'<span class="jour">{d.day}</span>'
            '<span class="mois">nov</span>'
            f'<span class="annee">{d.year}</span>'
            f'<h2 class="evenement-titre-{idx}"><a href="{src}">{title}</a></h2>'
            f'<span class="evenement-lieu-{idx}">'
            'Médiathèque Raoul Georges Nicolo</span>'
            f'<span class="horraires">{start_html} - {end_html}</span></div>'
        )
        cal_cards.setdefault(c["calendar_url"], []).append(card)
        m = {
            "schema": MANIFEST_SCHEMA,
            "mode": "request_human_review_no_publication",
            "review_id": c["review_id"], "pr_number": 88,
            "head_sha": PR_SHA,
            "candidate_sha256": canonical_digest(c),
            "access_sha256": canonical_digest(a),
            "event_html_sha256": html_digest(official_html),
            "catalogue_sha256": canonical_digest(public),
            "date_start": day, "official_event_url": src,
        }
        docs.append({
            "review": private_review(c), "access": private_access(a),
            "manifest": m,
        })
        comments.append({
            "id": idx,
            "body": decision_line(m, "APPROVE"),
            "user": {"login": APPROVER, "type": "User"},
            "author_association": "OWNER",
        })
        if not known_conditions:
            comments.append({
                "id": idx + 100,
                "body": editorial_decision_line(m, "SOURCE_ONLY"),
                "user": {"login": APPROVER, "type": "User"},
                "author_association": "OWNER",
            })
    pages.update({url: "".join(cards) for url, cards in cal_cards.items()})
    def get_official(url):
        return pages[url]
    def get_private(url, token):
        if token != "test-only-token":
            raise ValueError("forbidden_token")
        if url == API + "/pulls/88":
            return {
                "number": 88, "state": "open", "merged_at": None,
                "head": {"sha": PR_SHA, "repo": {"full_name": REPOSITORY}},
                "base": {"ref": "main", "repo": {"full_name": REPOSITORY}},
            }
        if url == API + "/collaborators/Sarogal/permission":
            return {"permission": "admin"}
        if url == API + "/issues/88/comments?per_page=100&page=1":
            return comments
        raise ValueError("forbidden_endpoint")
    return docs, get_official, get_private


def inspect(docs=None, reference=None, current=None, *,
            ref_pin=None, cur_pin=None, get=None, gh=None, token="test-only-token",
            geo_ok=True):
    reference = reference if reference is not None else historical()
    current = current if current is not None else historical()
    originals, source, private = sample_nine(public=current)
    return inspect_municipal_batch(
        reference, current, docs if docs is not None else originals, TODAY,
        reference_sha256=ref_pin or canonical_sha256(reference),
        current_sha256=cur_pin or canonical_sha256(current),
        token=token, source_get=get or source, github_get=gh or private,
        geo_check=lambda ev: (geo_ok, "injected synthetic venue proof"),
    )


class MunicipalBatchReadinessTests(unittest.TestCase):
    def test_nine_independent_occurrences_and_two_dates_same_series(self):
        reference = historical()
        snap = deepcopy(reference)
        out = inspect(reference=reference, current=reference)
        self.assertGreaterEqual(len(reference["events"]), 548)
        self.assertEqual(out["schema"], SCHEMA)
        self.assertEqual(out["reviewed_unique_occurrences"], 9)
        self.assertEqual(out["isolated_diagnostic_passes"], 9)
        self.assertEqual(out["blocked_occurrences"], 0)
        self.assertEqual(out["reference_historical_preserved"], len(reference["events"]))
        self.assertEqual(out["current_historical_preserved"], len(reference["events"]))
        self.assertTrue(out["catalogues_unchanged"])
        self.assertFalse(out["publisher_wired"])
        self.assertFalse(out["publication_ready"])
        self.assertFalse(out["approval_granted_to_publisher"])
        self.assertEqual(out["public_writes"], 0)
        for absent in ("events", "patch", "additions", "updates", "approved"):
            self.assertNotIn(absent, out)
        self.assertEqual(reference, snap)

    def test_missing_private_token_blocks_all_nine(self):
        out = inspect(token=None)
        self.assertEqual(out["isolated_diagnostic_passes"], 0)
        self.assertEqual(out["blocked_occurrences"], 9)
        self.assertIn("authenticated_private_approval_missing",
                      out["blocked_reason_counts"])

    def test_unapproved_realistic_unknown_access_blocks_without_decisions(self):
        docs, source, private = sample_nine(known_conditions=False)
        def omit_decisions(url, token):
            if "/comments?" in url:
                return []
            return private(url, token)
        out = inspect(docs=docs, get=source, gh=omit_decisions)
        self.assertEqual(out["isolated_diagnostic_passes"], 0)
        self.assertEqual(out["public_writes"], 0)

    def test_signed_source_only_approval_for_unknown_access_is_diagnostic_only(self):
        docs, source, private = sample_nine(known_conditions=False)
        out = inspect(docs=docs, get=source, gh=private)
        self.assertEqual(out["isolated_diagnostic_passes"], 9)
        self.assertFalse(out["publication_ready"])

    def test_duplicate_dossier_id_rejected(self):
        docs, source, private = sample_nine()
        docs[1] = deepcopy(docs[0])
        out = inspect(docs=docs, get=source, gh=private)
        self.assertEqual(out["isolated_diagnostic_passes"], 8)
        self.assertEqual(out["blocked_occurrences"], 1)
        self.assertIn("duplicate_batch_review_id", out["blocked_reason_counts"])

    def test_cross_feed_published_duplicate_cannot_pass_with_new_snapshot(self):
        original = historical()
        current = deepcopy(original)
        docs, source, private = sample_nine(public=current)
        c = docs[0]["review"]["candidates"][0]
        current["events"].append({
            "id": "alternate-feed-duplicate",
            "title": c["title"], "category": "concert",
            "date_start": c["date_start"], "date_end": c["date_end"],
            "city": c["city"], "venue": c["venue"],
            "source_url": "https://different.example/real",
        })
        # Re-bind all private manifests to the new current SHA. Their exact
        # identities are intentionally reapproved in this test fixture.
        for row in docs:
            row["manifest"]["catalogue_sha256"] = canonical_digest(current)
        new_private = _private_from(docs)
        result = inspect(docs=docs, reference=original, current=current,
                         get=source, gh=new_private)
        self.assertEqual(result["isolated_diagnostic_passes"], 8)
        self.assertIn("duplicate_occurrence_within_batch_or_catalogue",
                      result["blocked_reason_counts"])
        self.assertEqual(len(current["events"]), len(original["events"]) + 1)

    def test_old_private_catalogue_snapshot_is_not_reused(self):
        original = historical()
        current = deepcopy(original)
        docs, source, private = sample_nine(public=original)
        current["events"].append({
            "id": "legitimate-new-append", "title": "Other event",
            "date_start": "2026-11-21", "date_end": "2026-11-21",
            "city": "Paris", "venue": "Autre lieu", "source_url": "https://example.com",
        })
        out = inspect(docs=docs, reference=original, current=current,
                      get=source, gh=private)
        self.assertEqual(out["isolated_diagnostic_passes"], 0)
        self.assertIn("private_evidence_or_decision_unverified",
                      out["blocked_reason_counts"])

    def test_mismatching_sha_pins_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "catalogue_changed"):
            inspect(ref_pin="f" * 64)
        with self.assertRaisesRegex(ValueError, "catalogue_changed"):
            inspect(cur_pin="f" * 64)
        with self.assertRaisesRegex(ValueError, "missing_catalogue_sha"):
            inspect(ref_pin="not-a-sha")

    def test_historical_modification_or_deletion_not_permitted(self):
        orig = historical()
        changed = deepcopy(orig)
        changed["events"][0]["title"] = "HACKED"
        with self.assertRaisesRegex(ValueError, "historical_catalogue_modified"):
            inspect(reference=orig, current=changed)
        changed = deepcopy(orig)
        changed["events"].pop()
        with self.assertRaisesRegex(ValueError, "historical_catalogue_modified"):
            inspect(reference=orig, current=changed)

    def test_reordering_historical_prefix_is_forbidden(self):
        original = historical()
        reordered = deepcopy(original)
        reordered["events"][0], reordered["events"][1] = (
            reordered["events"][1], reordered["events"][0]
        )
        with self.assertRaisesRegex(ValueError, "historical_catalogue_modified"):
            inspect(reference=original, current=reordered)

    def test_source_unavailable_or_changed_blocks(self):
        docs, source, private = sample_nine()
        def dead(url):
            raise OSError("offline")
        out = inspect(docs=docs, get=dead, gh=private)
        self.assertEqual(out["isolated_diagnostic_passes"], 0)
        self.assertIn("municipal_source_unavailable", out["blocked_reason_counts"])
        def changed_html(url):
            html = source(url)
            if "/evenement/simulation-" in url:
                return html.replace("Médiathèque Raoul Georges Nicolo",
                                    "Un autre lieu")
            return html
        out = inspect(docs=docs, get=changed_html, gh=private)
        self.assertEqual(out["isolated_diagnostic_passes"], 0)

    def test_wrong_geo_cannot_be_accepted(self):
        out = inspect(geo_ok=False)
        self.assertEqual(out["isolated_diagnostic_passes"], 0)
        self.assertIn("independent_venue_registry_missing_or_different",
                      out["blocked_reason_counts"])

    def test_duplicate_ids_in_current_catalogue_are_rejected(self):
        current = historical()
        current["events"].append(deepcopy(current["events"][0]))
        with self.assertRaises(ValueError):
            inspect(current=current)

    def test_invalid_batch_item_never_authorizes(self):
        docs, source, private = sample_nine()
        bad = deepcopy(docs)
        bad[0]["manifest"]["review_id"] = "forged"
        with self.assertRaisesRegex(ValueError, "cross_dossier_identity"):
            inspect(docs=bad, get=source, gh=private)
        with self.assertRaisesRegex(ValueError, "invalid_batch_size"):
            inspect(docs=[])

    def test_mutation_in_independent_geo_check_is_detected(self):
        ref = historical()
        cur = deepcopy(ref)
        docs, source, private = sample_nine(public=cur)
        def tamper(event):
            cur["events"][0]["title"] = "Tampered"
            return True, "fake"
        with self.assertRaisesRegex(ValueError, "catalogue_mutated_during_batch"):
            inspect_municipal_batch(
                ref, cur, docs, TODAY,
                reference_sha256=canonical_sha256(ref),
                current_sha256=canonical_sha256(cur),
                token="test-only-token", source_get=source,
                github_get=private, geo_check=tamper,
            )


def _private_from(docs):
    comments = []
    for n, row in enumerate(docs):
        comments.append({
            "id": n + 1, "body": decision_line(row["manifest"], "APPROVE"),
            "user": {"login": APPROVER, "type": "User"},
            "author_association": "OWNER",
        })
    def get(url, token):
        if token != "test-only-token":
            raise ValueError("forbidden_token")
        if url == API + "/pulls/88":
            return {
                "number": 88, "state": "open", "merged_at": None,
                "head": {"sha": PR_SHA, "repo": {"full_name": REPOSITORY}},
                "base": {"ref": "main", "repo": {"full_name": REPOSITORY}},
            }
        if url == API + "/collaborators/Sarogal/permission":
            return {"permission": "admin"}
        if url == API + "/issues/88/comments?per_page=100&page=1":
            return comments
        raise ValueError("bad_endpoint")
    return get


if __name__ == "__main__":
    unittest.main()
