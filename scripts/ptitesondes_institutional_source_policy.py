"""Per-INSTITUTION HTML source policy registry, fail-closed and read-only.

A source is reviewed once (and can expire/revoke). Individual events always
need exact-session, family, access, organizer, venue/GPS and live-duplicate
checks. A source-level legal review is NOT an event licence or approval.

The production entrypoint ONLY reads the repository-curated JSON manifest;
untrusted collector fields may not supply, update or override it. Tests use the
pure evaluator with synthetic manifests. Public results contain no source URL,
document text, reviewer identity, coordinates or event data.
"""
from datetime import date
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, urljoin

SCHEMA = "ptitesondes.institutional_source_policy_preflight.v1"
MANIFEST_SCHEMA = "ptitesondes.institutional_source_policy_registry.v1"
MANIFEST_PATH = (
    Path(__file__).resolve().parents[1] /
    "config/ptitesondes_institutional_source_policies.json"
)
MAX_REGISTRY_BYTES = 100_000
MAX_SOURCES = 300
PERMITTED_POLICY = frozenset((
    "pending_source_legal_review",
    "restricted_do_not_reuse",
    "fact_only_source_review_recorded",
))
PERMITTED_PROVENANCE = frozenset((
    "independent_authority_reference_documented_not_rechecked_live",
))
FIELDS = frozenset({
    "source_id", "approved_host", "index_url", "child_prefix",
    "publisher_notice_url", "external_authority_url",
    "authority_expected_path_prefix", "provenance_state",
    "reuse_policy_state", "facts_only_review_evidence_url",
    "reuse_reviewed_on", "reuse_expires_on",
    "no_third_party_description_or_images",
    "access_terms_require_per_session_review",
})
_STATUS = frozenset((
    "source_not_registered", "source_registry_invalid",
    "source_provenance_needs_live_recheck",
    "source_reuse_policy_pending",
    "source_reuse_restricted",
    "source_reuse_review_stale_or_incomplete",
    "source_fact_only_review_recorded_requires_independent_checks",
))


def _out(status):
    if status not in _STATUS:
        status = "source_registry_invalid"
    return {
        "schema": SCHEMA,
        "status": status,
        "owner_host_reference_documented":
            status not in ("source_not_registered", "source_registry_invalid"),
        "ownership_rechecked_live": False,
        "source_level_fact_only_review_recorded":
            status == "source_fact_only_review_recorded_requires_independent_checks",
        "publisher_rights_assumed": False,
        "database_extraction_allowed_assumed": False,
        "media_reuse_allowed": False,
        "event_rights_reviewed": False,
        "event_organizer_attested": False,
        "event_geometry_verified": False,
        "event_access_fully_verified": False,
        "publisher_connected": False,
        "publication_ready": False,
        "approval_granted": False,
        "public_writes": 0,
        "source_or_event_identifiers_present": False,
    }


def _date(value):
    if type(value) is not str or not re.fullmatch(r"20\d\d-\d\d-\d\d", value):
        return None
    try:
        d = date.fromisoformat(value)
        return d if d.isoformat() == value else None
    except ValueError:
        return None


def _url(url):
    if (type(url) is not str or len(url) > 1000 or not url
            or re.search(r"[\x00-\x20\x7f\\]", url)):
        return None
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname
                or parsed.username or parsed.password
                or parsed.port not in (None, 443)
                or parsed.fragment or parsed.query
                or parsed.path.startswith("//")
                or ".." in parsed.path or "%" in parsed.path
                or not re.fullmatch(r"[a-z0-9.-]+", parsed.hostname)
                or "." not in parsed.hostname):
            return None
        return parsed
    except ValueError:
        return None


def _prefix(value):
    return (type(value) is str
            and 2 <= len(value) <= 150
            and value.startswith("/") and value.endswith("/")
            and not value.startswith("//")
            and "%" not in value and ".." not in value
            and "?" not in value and "#" not in value
            and re.fullmatch(r"/[A-Za-z0-9_/-]+/", value) is not None)


def _record_valid(rec):
    if not isinstance(rec, dict) or set(rec) != FIELDS:
        return False
    sid = rec["source_id"]
    if (type(sid) is not str or len(sid) > 100
            or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", sid)):
        return False
    idx, notice, authority = (
        _url(rec.get(k)) for k in (
            "index_url", "publisher_notice_url", "external_authority_url",
        )
    )
    if not idx or not notice or not authority:
        return False
    if (type(rec["approved_host"]) is not str
            or idx.hostname != rec["approved_host"]
            or notice.hostname != idx.hostname
            or authority.hostname == idx.hostname
            or not _prefix(rec["child_prefix"])
            or not _prefix(rec["authority_expected_path_prefix"])
            or rec["provenance_state"] not in PERMITTED_PROVENANCE
            or rec["reuse_policy_state"] not in PERMITTED_POLICY
            or rec["no_third_party_description_or_images"] is not True
            or rec["access_terms_require_per_session_review"] is not True):
        return False

    policy = rec["reuse_policy_state"]
    if policy in ("pending_source_legal_review", "restricted_do_not_reuse"):
        return (rec["facts_only_review_evidence_url"] is None
                and rec["reuse_reviewed_on"] is None
                and rec["reuse_expires_on"] is None)

    evidence = _url(rec.get("facts_only_review_evidence_url"))
    checked, expires = _date(rec.get("reuse_reviewed_on")), _date(
        rec.get("reuse_expires_on"))
    return bool(evidence and checked and expires
                and checked <= expires
                and 0 < (expires - checked).days <= 180)


def _manifest_valid(manifest):
    if not isinstance(manifest, dict) or set(manifest) != {
            "schema", "entries"} or manifest["schema"] != MANIFEST_SCHEMA:
        return False
    entries = manifest["entries"]
    if not isinstance(entries, list) or not 0 <= len(entries) <= MAX_SOURCES:
        return False
    seen_ids, seen_index, seen_hosts = set(), set(), set()
    for item in entries:
        if not _record_valid(item):
            return False
        identity = (item["approved_host"], item["index_url"])
        if (item["source_id"] in seen_ids or identity in seen_index
                or item["approved_host"] in seen_hosts):
            # Per-domain decisions cannot conflict; multiple index paths on
            # the same domain require one consolidated institutional policy.
            return False
        seen_ids.add(item["source_id"])
        seen_index.add(identity)
        seen_hosts.add(item["approved_host"])
    return True


def assess_source_policy(manifest, trusted_index, child_prefix, today):
    """Pure isolated evaluator; NEVER consume policy records from collectors."""
    if (type(today) is not date or
            not _manifest_valid(manifest)
            or not isinstance(trusted_index, dict)
            or set(trusted_index) != {"approved_host", "exact_index_url"}
            or not isinstance(child_prefix, str)):
        return _out("source_registry_invalid")
    pinned = trusted_index.get("exact_index_url")
    host = trusted_index.get("approved_host")
    u = _url(pinned)
    if not u or u.hostname != host or not _prefix(child_prefix):
        return _out("source_registry_invalid")
    entry = next((e for e in manifest["entries"]
                  if e["approved_host"] == host
                  and e["index_url"] == pinned), None)
    if entry is None:
        return _out("source_not_registered")
    if entry["child_prefix"] != child_prefix:
        return _out("source_registry_invalid")
    if entry["provenance_state"] not in PERMITTED_PROVENANCE:
        return _out("source_provenance_needs_live_recheck")
    if entry["reuse_policy_state"] == "restricted_do_not_reuse":
        return _out("source_reuse_restricted")
    if entry["reuse_policy_state"] == "pending_source_legal_review":
        return _out("source_reuse_policy_pending")

    start, end = _date(entry["reuse_reviewed_on"]), _date(
        entry["reuse_expires_on"])
    if start is None or end is None or not start <= today <= end:
        return _out("source_reuse_review_stale_or_incomplete")
    return _out("source_fact_only_review_recorded_requires_independent_checks")


def committed_source_policy(trusted_index, child_prefix, today):
    """Only trusted committed registry bytes; no path nor policy injection."""
    try:
        if MANIFEST_PATH.stat().st_size > MAX_REGISTRY_BYTES:
            return _out("source_registry_invalid")
        raw = MANIFEST_PATH.read_bytes()
        if len(raw) > MAX_REGISTRY_BYTES:
            return _out("source_registry_invalid")
        manifest = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, ValueError):
        return _out("source_registry_invalid")
    return assess_source_policy(manifest, trusted_index, child_prefix, today)


class _AuthorityLinks(HTMLParser):
    """Visible links in the institutional authority's main article only."""
    VOID = frozenset((
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    ))
    HIDDEN = frozenset((
        "script", "style", "noscript", "template", "iframe", "svg",
        "nav", "footer", "header", "head",
    ))

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if len(self.stack) >= 70:
            raise ValueError("authority_html_too_deep")
        props = dict(attrs)
        css = str(props.get("style") or "").lower().replace(" ", "")
        previous = self.stack[-1] if self.stack else (False, False)
        in_main = previous[0] or tag in ("main", "article")
        hidden = (previous[1] or tag in self.HIDDEN
                  or "hidden" in props
                  or props.get("aria-hidden") == "true"
                  or "display:none" in css or "visibility:hidden" in css)
        if tag not in self.VOID:
            self.stack.append((in_main, hidden))
        if tag == "a" and in_main and not hidden:
            self.links.append(props.get("href"))

    def handle_endtag(self, tag):
        if tag not in self.VOID and self.stack:
            self.stack.pop()


def corroborate_independent_authority_link(
        entry, fetched_page, *, primary_source_host=None):
    """Validate separate authority site links to a specific source site.

    Must be fetched by a hardened, independently pinned HTTPS/no-redirect
    transport. This only corroborates the institutional site relationship,
    not event rights or source licensing.
    """
    if (not _record_valid(entry)
            or not isinstance(fetched_page, dict)
            or set(fetched_page) != {"url", "html"}
            or fetched_page["url"] != entry["external_authority_url"]
            or (primary_source_host is not None
                and entry["approved_host"] != primary_source_host)):
        return False
    raw = fetched_page["html"]
    if type(raw) is not str or not 100 <= len(raw) <= 450_000:
        return False
    parsed = _AuthorityLinks()
    try:
        parsed.feed(raw)
        parsed.close()
    except (ValueError, TypeError):
        return False
    base = entry["external_authority_url"]
    for href in parsed.links:
        if (type(href) is not str
                or not href.startswith("https://")):
            continue
        u = _url(href)
        if (u is not None and u.hostname == entry["approved_host"]
                and u.path.startswith(
                    entry["authority_expected_path_prefix"])):
            return True
    return False
