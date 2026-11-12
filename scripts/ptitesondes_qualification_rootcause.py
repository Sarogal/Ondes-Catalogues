"""Private root-cause audit of previously admissible P'tites Ondes outings.

Reuses unchanged publication preflight and only records bounded, enumerated
failure counts. No candidate identity, URL, exception string or proof is
written to GitHub Actions public logs. No event is approved or published.
"""
import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from ptitesondes_candidate_promotion import (
    API, FIELDS, MAX_FETCH, MAX_ROWS, evaluate, permitted, unique_review_candidates,
)
from ptitesondes_private_qualification_diagnostics import reason_bucket

SCHEMA = "ptitesondes.private_outings_rootcause.v1"
MAX_CANDIDATES = 200
ODS_PROBE_CODES = frozenset({
    "uid_absent", "uid_nonunique", "uid_unique", "unexpected_uid",
    "http_403", "http_404", "http_429", "http_5xx",
    "network_error", "invalid_json_or_schema", "unexpected_error",
})
REASONS = frozenset({
    "already_published", "schema", "audience_or_music_signal_absent",
    "official_age_unconfirmed", "canonical_pair_unreviewed",
    "canonical_url_invalid", "ods_uid_unresolved",
    "ods_http_4xx", "ods_http_429", "ods_http_5xx",
    "ods_network_error", "official_date_unconfirmed",
    "official_time_unconfirmed", "official_venue_unconfirmed",
    "geo_inconsistent", "source_page_unavailable",
    "other",
})


def explicit_reason(detail):
    """Strict bounded taxonomy, never quote free-text reasons to reports."""
    status = detail.get("status")
    if status == "already_published":
        return "already_published"
    if status == "rejected_schema":
        return "schema"
    msg = str(detail.get("reason", "")).casefold()
    if "destination familiale musicale insuffisamment explicite" in msg:
        return "audience_or_music_signal_absent"
    if "âge minimum non confirmé" in msg:
        return "official_age_unconfirmed"
    if "url canonique différente" in msg:
        return "canonical_pair_unreviewed"
    if "url canonique non autorisée" in msg:
        return "canonical_url_invalid"
    if "uid absent ou non unique dans l'index" in msg:
        return "ods_uid_unresolved"
    if "http error 429" in msg:
        return "ods_http_429"
    if re.search(r"http error 5\d\d", msg):
        return "ods_http_5xx"
    if re.search(r"http error 4\d\d", msg):
        return "ods_http_4xx"
    if "timed out" in msg or "urlopen error" in msg or "name or service not known" in msg:
        return "ods_network_error"
    if "date complète non confirmée" in msg:
        return "official_date_unconfirmed"
    if "tous les horaires ne sont pas confirmés" in msg:
        return "official_time_unconfirmed"
    if "lieu absent de la fiche officielle" in msg:
        return "official_venue_unconfirmed"
    if any(word in msg for word in ("position", "géolocalis", "gps", "coordonn")):
        return "geo_inconsistent"
    if "page officielle inaccessible" in msg or "source officielle inaccessible" in msg:
        return "source_page_unavailable"
    return "other"


def probe_uid_in_index(uid, *, get=None):
    """Independent read-only ODS UID count; never returns event payload."""
    if not isinstance(uid, str) or not re.fullmatch(r"[0-9]{1,12}", uid):
        raise ValueError("UID non autorisé")
    query = API + "?" + urlencode({
        "limit": MAX_ROWS, "select": FIELDS, "where": "uid='" + uid + "'"})
    if get is None:
        def get(url):
            request = Request(url, headers={
                "Accept": "application/json",
                "User-Agent": "PtitesOndesRootCauseAudit/1.0"})
            with urlopen(request, timeout=18) as response:
                if urlparse(response.geturl()).hostname != urlparse(API).hostname:
                    raise ValueError("Redirection ODS non autorisée")
                raw = response.read(250_001)
            if len(raw) > 250_000:
                raise ValueError("Réponse trop volumineuse")
            return json.loads(raw)
    try:
        data = get(query)
        if not isinstance(data, dict) or not isinstance(data.get("results"), list):
            return "invalid_json_or_schema"
        rows = data["results"]
        if any(not isinstance(row, dict) for row in rows):
            return "invalid_json_or_schema"
        matches = [row for row in rows if str(row.get("uid", "")) == uid]
        if not matches:
            return "uid_absent" if not rows else "unexpected_uid"
        return "uid_unique" if len(matches) == 1 else "uid_nonunique"
    except HTTPError as err:
        if err.code == 403:
            return "http_403"
        if err.code == 404:
            return "http_404"
        if err.code == 429:
            return "http_429"
        if 500 <= err.code <= 599:
            return "http_5xx"
        return "unexpected_error"
    except (URLError, TimeoutError, ConnectionError):
        return "network_error"
    except (ValueError, TypeError, KeyError, OSError):
        return "invalid_json_or_schema"


def rootcause_audit(leads, baseline, published, today, *,
                    review=evaluate, index_probe=probe_uid_in_index):
    """Review every admissible UID/date exactly once, using the existing gate."""
    candidates, raw_eligible, duplicates, conflicts = unique_review_candidates(
        leads, today)
    if len(candidates) > MAX_CANDIDATES:
        raise ValueError("Trop de candidats pour l'audit ciblé")
    if not isinstance(leads, list) or len(leads) > 4000:
        raise ValueError("Backlog privé invalide")
    seen, cause_counts, groups, ods_probes = set(), Counter(), Counter(), Counter()
    checked = prevalidated = 0
    index_cache = {}
    for start in range(0, len(candidates), MAX_FETCH):
        batch = candidates[start:start + MAX_FETCH]
        keys = {(e["external_id"], e["date_start"]) for e in batch}
        if len(keys) != len(batch) or seen.intersection(keys):
            raise ValueError("UID/date répété")
        raw_batch = [e for e in leads if permitted(e, today) and
                     (e["external_id"], e["date_start"]) in keys]
        patch, report = review(raw_batch, baseline, published, today,
                               limit=MAX_FETCH, slot=0)
        items = report.get("details", [])
        if (report.get("date") != today.isoformat() or
                report.get("mode") != "preview_no_public_write" or
                report.get("eligible_with_reviewed_venue") != len(batch) or
                report.get("checked") != len(batch) or
                report.get("accepted_preflight") != len(patch.get("additions", [])) or
                patch.get("safe_to_publish") is not False or
                not isinstance(items, list) or
                len(items) + len(patch["additions"]) != len(batch)):
            raise ValueError("Lot de qualification incomplet")
        lookup = {}
        for candidate in raw_batch:
            lookup.setdefault((candidate["source_url"], candidate["date_start"]),
                              set()).add(candidate["external_id"])
        for item in items:
            if not isinstance(item, dict) or item.get("status") not in (
                    "already_published", "rejected_schema", "unverified", "deferred"):
                raise ValueError("Décision de vérification inconnue")
            cause = explicit_reason(item)
            if cause not in REASONS:
                raise ValueError("Code de refus non autorisé")
            cause_counts[cause] += 1
            groups[reason_bucket(item)] += 1
            if cause == "ods_uid_unresolved":
                uids = lookup.get((item.get("source_url"), item.get("date")))
                if not uids or len(uids) != 1:
                    ods_probes["unexpected_error"] += 1
                else:
                    uid = next(iter(uids))
                    if uid not in index_cache:
                        index_cache[uid] = index_probe(uid)
                    result = index_cache[uid]
                    if result not in ODS_PROBE_CODES:
                        raise ValueError("Diagnostic ODS non autorisé")
                    ods_probes[result] += 1
        checked += len(batch)
        prevalidated += len(patch["additions"])
        seen.update(keys)
    if (seen != {(c["external_id"], c["date_start"]) for c in candidates} or
            checked != len(candidates) or
            prevalidated + sum(cause_counts.values()) != checked or
            sum(groups.values()) != sum(cause_counts.values()) or
            sum(ods_probes.values()) != cause_counts["ods_uid_unresolved"]):
        raise ValueError("Comptages de diagnostic incohérents")
    ids = [e["id"] for e in published["events"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Identifiants publics dupliqués")
    return {
        "schema": SCHEMA, "day": today.isoformat(),
        "mode": "private_diagnostic_only_no_approval",
        "backlog_total": len(leads), "raw_eligible": raw_eligible,
        "unique_admissible": len(candidates),
        "duplicate_collector_leads": duplicates,
        "conflicting_uid_days_excluded": conflicts,
        "checked": checked, "prevalidated": prevalidated,
        "reason_groups": dict(sorted(groups.items())),
        "failure_codes": dict(sorted(cause_counts.items())),
        "ods_uid_probe_codes": dict(sorted(ods_probes.items())),
        "public_catalogue_at_audit": {
            "events": len(ids), "updated_at": published["updated_at"]},
        "private_approvals": 0, "public_writes": 0,
    }


def public_summary(data):
    if data.get("schema") != SCHEMA:
        raise ValueError("Diagnostic absent")
    return {k: data[k] for k in (
        "backlog_total", "unique_admissible", "checked",
        "prevalidated", "public_writes") if type(data.get(k)) is int}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backlog-file", required=True, type=Path)
    parser.add_argument("--catalogue-file", required=True, type=Path)
    parser.add_argument("--reference-file", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date()
    leads = json.loads(args.backlog_file.read_text(encoding="utf-8"))
    published = json.loads(args.catalogue_file.read_text(encoding="utf-8"))
    baseline = json.loads(args.reference_file.read_text(encoding="utf-8"))
    report = rootcause_audit(leads, baseline, published, today)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps(public_summary(report), sort_keys=True))


if __name__ == "__main__":
    main()
