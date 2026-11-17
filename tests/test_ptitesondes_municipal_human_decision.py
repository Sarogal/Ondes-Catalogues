"""Network-free security tests for human approval evidence; never release."""
from copy import deepcopy
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ptitesondes_municipal_human_decision import (
    API, APPROVER, MANIFEST_SCHEMA, REPOSITORY, SCHEMA,
    audit_human_decision, canonical_digest, decision_line,
    html_digest, review_comments,
)
from test_ptitesondes_nonmusic_release_contract import (
    proposal, access, public_catalogue,
)

HEAD = "a" * 40
HTML = "<h1>Mon doudou raconte</h1><p>mercredi 25 novembre de 9h à 9h30</p>"


def fixture():
    candidate = proposal()
    conditions = access()
    catalogue = public_catalogue()
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "mode": "request_human_review_no_publication",
        "review_id": candidate["review_id"],
        "pr_number": 88,
        "head_sha": HEAD,
        "candidate_sha256": canonical_digest(candidate),
        "access_sha256": canonical_digest(conditions),
        "event_html_sha256": html_digest(HTML),
        "catalogue_sha256": canonical_digest(catalogue),
        "date_start": "2026-11-25",
        "official_event_url": candidate["official_event_url"],
    }
    pr = {
        "number": 88,
        "state": "open",
        "merged_at": None,
        "head": {"sha": HEAD, "repo": {"full_name": REPOSITORY}},
        "base": {"ref": "main", "repo": {"full_name": REPOSITORY}}
    }
    return manifest, candidate, conditions, catalogue, pr


def human_comment(manifest, decision="APPROVE", id=101):
    return {
        "id": id,
        "body": decision_line(manifest, decision),
        "user": {"login": APPROVER, "type": "User"},
        "author_association": "OWNER"
    }


def run(modify=None, comments=None, permission="admin"):
    m, c, a, catalog, pr = fixture()
    if modify:
        modify(m, c, a, catalog, pr)
    if comments is None:
        comments = [human_comment(m)]
    def get(url, token):
        if token != "test-private-read-token":
            raise ValueError("token_required")
        if url == API + "/pulls/88":
            return pr
        if url == API + "/collaborators/Sarogal/permission":
            return {"permission": permission}
        if url == API + "/issues/88/comments?per_page=100&page=1":
            return comments
        raise ValueError("endpoint_not_allowed")
    return audit_human_decision(
        m, c, a, HTML, catalog, "test-private-read-token", get)


class HumanApprovalEvidenceTests(unittest.TestCase):
    def test_owner_exact_approval_proves_only_one_prerequisite(self):
        out = run()
        self.assertEqual(out["schema"], SCHEMA)
        self.assertTrue(out["human_approval_evidence"])
        self.assertEqual(out["last_decision"], "authenticated_approval")
        self.assertIs(out["publication_ready"], False)
        self.assertIs(out["approval_granted_to_publisher"], False)
        self.assertEqual(out["public_writes"], 0)
        self.assertNotIn("additions", out)
        self.assertNotIn("patch", out)

    def test_revoke_after_approval_wins(self):
        m = fixture()[0]
        r = run(comments=[human_comment(m, id=100),
                          human_comment(m, decision="REVOKE", id=102)])
        self.assertFalse(r["human_approval_evidence"])
        self.assertEqual(r["last_decision"], "revoked_or_absent")

    def test_reapproval_after_revoke_requires_new_exact_comment(self):
        m = fixture()[0]
        r = run(comments=[
            human_comment(m, id=100),
            human_comment(m, "REVOKE", 101),
            human_comment(m, "APPROVE", 103),
        ])
        self.assertTrue(r["human_approval_evidence"])

    def test_no_comment_or_unrelated_comment_never_approves(self):
        self.assertFalse(run(comments=[])["human_approval_evidence"])
        m = fixture()[0]
        for wrong in (
            "APPROVED", "ok continue", "PTITESONDES APPROVE",
            decision_line(m, "APPROVE") + "\nAutorisé",
            decision_line(m, "APPROVE").replace(m["head_sha"], "b" * 40),
            decision_line(m, "APPROVE").replace(m["review_id"], "municipal-gosier-3067-2026-11-18"),
        ):
            with self.subTest(wrong=wrong[:60]):
                c = human_comment(m)
                c["body"] = wrong
                self.assertFalse(run(comments=[c])["human_approval_evidence"])

    def test_bot_and_unsigned_user_cannot_approve(self):
        m = fixture()[0]
        for override in (
            {"user": {"login": "github-actions[bot]", "type": "Bot"}},
            {"user": {"login": "Sarogal", "type": "Bot"}},
            {"user": {"login": "untrusted", "type": "User"}},
            {"author_association": "NONE"},
            {"author_association": "CONTRIBUTOR"},
            {"id": True},
        ):
            with self.subTest(override=override):
                comment = human_comment(m)
                comment.update(override)
                self.assertFalse(run(comments=[comment])["human_approval_evidence"])

    def test_permission_must_be_confirmed_by_github(self):
        for perm in ("read", "triage", "write", "none", None):
            with self.subTest(perm=perm), self.assertRaisesRegex(
                    ValueError, "permission_not_verified"):
                run(permission=perm)
        self.assertTrue(run(permission="maintain")["human_approval_evidence"])

    def test_pr_repository_sha_state_base_and_merge_must_match(self):
        variants = (
            ("head_sha", lambda m,c,a,k,p: p["head"].update(sha="b" * 40)),
            ("base_ref", lambda m,c,a,k,p: p["base"].update(ref="other")),
            ("head_repo", lambda m,c,a,k,p: p["head"]["repo"].update(full_name="fake/repo")),
            ("base_repo", lambda m,c,a,k,p: p["base"]["repo"].update(full_name="fake/repo")),
            ("closed", lambda m,c,a,k,p: p.update(state="closed")),
            ("merged", lambda m,c,a,k,p: p.update(merged_at="2026-11-16T20:00:00Z")),
            ("number", lambda m,c,a,k,p: p.update(number=89)),
        )
        for name,fn in variants:
            with self.subTest(name=name), self.assertRaisesRegex(
                    ValueError, "head_or_repository_changed"):
                run(modify=fn)

    def test_evidence_byte_changes_invalidate_prior_decision(self):
        for name, mutate in (
            ("candidate", lambda m,c,a,k,p: c.update(title="Titre modifié")),
            ("access", lambda m,c,a,k,p: a.update(price_evidence="explicit_free")),
            ("catalogue", lambda m,c,a,k,p: k["events"].append({"id":"extra"})),
        ):
            with self.subTest(name=name), self.assertRaisesRegex(
                    ValueError, "private_evidence_changed"):
                run(modify=mutate)

    def test_html_change_invalidates_prior_decision(self):
        m,c,a,k,pr = fixture()
        with self.assertRaisesRegex(ValueError, "private_evidence_changed_event_html_sha256"):
            audit_human_decision(m,c,a,HTML+" modifié",k,"non-empty",lambda *x:None)

    def test_source_self_approval_is_rejected_even_with_human_comment(self):
        for change in ({"approved": True}, {"safe_to_publish": True}):
            with self.subTest(change=change), self.assertRaisesRegex(
                    ValueError, "source_cannot_self_approve"):
                run(modify=lambda m,c,a,k,p:c.update(change))
        with self.assertRaisesRegex(ValueError, "source_cannot_self_approve"):
            run(modify=lambda m,c,a,k,p:a.update(approved=True))

    def test_forged_manifest_or_invalid_date_never_authorizes(self):
        for name,fn in (
            ("schema",lambda m,c,a,k,p:m.update(schema="fake")),
            ("extras",lambda m,c,a,k,p:m.update(approved=True)),
            ("uid",lambda m,c,a,k,p:m.update(review_id="wrong")),
            ("day",lambda m,c,a,k,p:m.update(date_start="2026-13-25")),
            ("boolean_pr_number",lambda m,c,a,k,p:m.update(pr_number=True)),
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                run(modify=fn)

    def test_empty_token_and_bad_comment_pagination_fail_closed(self):
        m,c,a,k,pr=fixture()
        with self.assertRaisesRegex(ValueError, "missing_private_read_token"):
            audit_human_decision(m,c,a,HTML,k,"",lambda *x:None)
        with self.assertRaisesRegex(ValueError, "invalid_github_comment_page"):
            review_comments(m,"token",lambda url,t: {"bad":"json"})

    def test_unbounded_pagination_denied_without_trusting_first_page(self):
        m=fixture()[0]
        def get(url,t):
            return [human_comment(m,id=i) for i in range(100)]
        with self.assertRaisesRegex(ValueError, "too_many_github_comments"):
            review_comments(m,"token",get)


if __name__ == "__main__":
    unittest.main()
