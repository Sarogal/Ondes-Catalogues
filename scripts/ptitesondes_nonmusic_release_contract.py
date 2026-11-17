"""Read-only contract for FUTURE non-musical children's outings.

This is NOT installed in the publisher and does not convert review reports
into patch.v1 additions. Its output deliberately cannot authorize publication.
The live site v172, private approvals and the municipal publisher still need
separate, explicit review before activation.
"""
from collections import Counter
from datetime import date, timedelta
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit
from proof import norm

SCHEMA = "ptitesondes.nonmusic_release_readiness.v1"
REVIEW_SCHEMA = "ptitesondes.gosier_private_review_candidates.v1"
ACCESS_SCHEMA = "ptitesondes.gosier_access_review.v1"
TYPES = {
    "lecture-jeunesse": "Lecture jeunesse",
    "atelier-numerique": "Atelier numérique",
    "lecture-cinema": "Lecture et cinéma",
    "jeux-famille": "Jeux en famille",
}
GOSIER = "Le Gosier"
VENUE = "Médiathèque Raoul Georges Nicolo"
LOCATION = (16.20547, -61.48950)

SERIES = {
    "mon doudou raconte": "lecture-jeunesse",
    "les rendez vous du numerique": "atelier-numerique",
    "la magie des histoires": "lecture-jeunesse",
    "le rendez vous des p tits racoons": "lecture-cinema",
    "les jeux du samedi": "jeux-famille",
}


def matching_category(title, category):
    name = norm(title)
    matches = [key for prefix, key in SERIES.items() if name.startswith(prefix)]
    return len(matches) == 1 and matches[0] == category


def explicit_age_matches(candidate):
    token = candidate.get("audience_evidence")
    lo, hi = candidate.get("age_min_proposal"), candidate.get("age_max_proposal")
    label = candidate.get("age_label_proposal")
    if token == "tous_ages_familles":
        return label == "En famille" and lo is None and hi is None
    if not isinstance(token, str):
        return False
    m = re.fullmatch(r"jusqua_(\d{1,2})_ans", token)
    if m:
        n = int(m.group(1))
        return n <= 17 and lo is None and hi == n and label == f"Jusqu’à {n} ans"
    m = re.fullmatch(r"des_(\d{1,2})_ans", token)
    if m:
        n = int(m.group(1))
        return n <= 17 and lo == n and hi is None and label == f"Dès {n} ans"
    return False

UID = re.compile(r"municipal-gosier-([1-9]\d{0,11})-(\d{4}-\d{2}-\d{2})\Z")
CODE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
TIME = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d\Z")


def require(value, reason):
    if not value:
        raise ValueError("read_only_release_contract_" + reason)


def safe_event_url(url):
    if not isinstance(url, str):
        return False
    try:
        p = urlsplit(url)
        return (p.scheme == "https" and p.netloc == "www.villedugosier.fr"
                and re.fullmatch(r"/evenement/[a-z0-9-]+", p.path) is not None
                and not p.query and not p.fragment and not p.username)
    except ValueError:
        return False


def audit(review, access, catalogue, today):
    """Preserve all security blockers; no input can flip ready_to_publish."""
    require(type(today) is date, "invalid_day")
    require(isinstance(review, dict) and review.get("schema") == REVIEW_SCHEMA
            and review.get("mode") == "private_review_only_no_patch_no_publication"
            and review.get("approved") == 0
            and review.get("published") == 0
            and type(review.get("approved")) is int
            and type(review.get("published")) is int
            and isinstance(review.get("candidates"), list)
            and len(review["candidates"]) <= 100
            and "additions" not in review, "invalid_review")
    require(isinstance(access, dict) and access.get("schema") == ACCESS_SCHEMA
            and access.get("mode") == "private_access_review_only_no_patch"
            and type(access.get("approved")) is int and access["approved"] == 0
            and type(access.get("published")) is int and access["published"] == 0
            and isinstance(access.get("reviewed"), list)
            and len(access["reviewed"]) == len(review["candidates"])
            and "additions" not in access, "invalid_access")
    require(isinstance(catalogue, dict) and catalogue.get("version") == 3
            and isinstance(catalogue.get("events"), list)
            and len(catalogue["events"]) >= 100, "invalid_catalogue")
    published_ids = {e["id"] for e in catalogue["events"]
                     if isinstance(e, dict) and isinstance(e.get("id"), str)}
    require(len(published_ids) == len(catalogue["events"]),
            "duplicate_public_ids")
    categories = {e.get("category") for e in catalogue["events"]}
    access_map = {entry.get("review_id"): entry for entry in access["reviewed"]
                  if isinstance(entry, dict)}
    require(len(access_map) == len(access["reviewed"]), "duplicate_access_reviews")
    ids = set()
    rows = []
    for c in review["candidates"]:
        require(isinstance(c, dict), "invalid_candidate")
        identifier = c.get("review_id")
        match = UID.fullmatch(identifier) if isinstance(identifier, str) else None
        require(match is not None and identifier not in ids and
                identifier in access_map, "unmatched_candidate")
        ids.add(identifier)
        try:
            day = date.fromisoformat(match.group(2))
            coords = (float(c["lat"]), float(c["lng"]))
        except (KeyError, ValueError, TypeError):
            raise ValueError("read_only_release_contract_invalid_candidate_fields")
        require(all(math.isfinite(v) for v in coords) and coords == LOCATION,
                "invalid_venue_point")
        require(c.get("source_event_id") == match.group(1)
                and c.get("date_start") == day.isoformat()
                and c.get("date_end") == day.isoformat()
                and today <= day <= today + timedelta(days=184)
                and c.get("city") == GOSIER and c.get("venue") == VENUE
                and c.get("timezone") == "America/Guadeloupe"
                and c.get("region_proposal") == "Guadeloupe"
                and c.get("department_proposal") == "Guadeloupe (971)"
                and c.get("source_label_proposal") == "Ville du Gosier"
                and safe_event_url(c.get("official_event_url"))
                and c.get("safe_to_publish") is False
                and c.get("approved") is False and c.get("published") is False
                and c.get("review_status") == "category_and_access_pending"
                and c.get("price") is None
                and c.get("access_conditions") == "requires_individual_review"
                and isinstance(c.get("start_local"), str)
                and TIME.fullmatch(c["start_local"])
                and isinstance(c.get("end_local"), str)
                and TIME.fullmatch(c["end_local"])
                and c["start_local"] < c["end_local"], "candidate_identity")
        category = c.get("category_proposal")
        require(category in TYPES
                and c.get("category_label_proposal") == TYPES[category]
                and matching_category(c.get("title"), category),
                "category_unreviewed")
        require(explicit_age_matches(c), "age_not_bound_to_official_cue")
        for key in ("age_min_proposal", "age_max_proposal"):
            value = c.get(key)
            require(value is None or (type(value) is int and 0 <= value <= 17),
                    "age_invalid")
        if c.get("age_min_proposal") is not None and c.get("age_max_proposal") is not None:
            require(c["age_min_proposal"] <= c["age_max_proposal"], "age_inverted")
        a = access_map[identifier]
        require(a.get("official_event_url") == c["official_event_url"]
                and a.get("date_start") == day.isoformat()
                and a.get("safe_to_publish") is False
                and a.get("approved") is False and a.get("published") is False
                and a.get("review_required") is True, "access_unbound")
        blockers = [
            "municipal_public_prevalidator_not_activated",
            "private_manual_approval_not_present",
            "frontend_v172_category_filter_unverified",
        ]
        if category not in categories:
            blockers.append("category_not_accepted_by_current_public_contract")
        if identifier in published_ids:
            blockers.append("already_public")
        for ev in catalogue["events"]:
            if not isinstance(ev, dict):
                continue
            try:
                first = date.fromisoformat(ev["date_start"])
                last = date.fromisoformat(ev.get("date_end") or ev["date_start"])
            except (ValueError, TypeError, KeyError):
                continue
            if first <= day <= last and (
                    ev.get("source_url") == c.get("official_event_url") or
                    (norm(ev.get("title")) == norm(c.get("title"))
                     and norm(ev.get("city")) == norm(c.get("city"))
                     and norm(ev.get("venue")) == norm(c.get("venue")))):
                blockers.append("already_public_semantic_or_range")
                break
        if a.get("access_status") == "cancelled_or_unavailable":
            blockers.append("cancelled_or_unavailable")
        elif a.get("access_status") == "official_session_no_longer_confirmed":
            blockers.append("official_session_changed")
        elif a.get("access_status") == "clarification_required":
            blockers.append("access_information_requires_manual_review")
        elif a.get("access_status") != "conditions_explicit_to_recheck":
            blockers.append("unknown_access_status")
        if a.get("price_evidence") not in (
                "explicit_free", "explicit_price", "not_stated",
                "ambiguous", "contradictory"):
            blockers.append("unrecognized_price_evidence")
        if a.get("registration_evidence") not in (
                "explicit_required", "explicit_not_required", "not_stated",
                "ambiguous", "contradictory"):
            blockers.append("unrecognized_registration_evidence")
        rows.append({
            "review_id": identifier, "category": category,
            "blockers": sorted(set(blockers)),
            "publication_ready": False, "approval_granted": False,
        })
    # No rights/flags from private source input may be trusted as approval.
    codes = Counter(reason for e in rows for reason in e["blockers"])
    return {
        "schema": SCHEMA,
        "mode": "readiness_report_only_never_publish",
        "as_of": today.isoformat(), "candidates_examined": len(rows),
        "blocked": len(rows), "publication_ready": 0,
        "approval_granted": 0, "public_writes": 0,
        "reason_counts": dict(sorted(codes.items())),
        "details_for_private_review_only": rows,
    }


def main():
    import argparse
    p = argparse.ArgumentParser()
    for name in ("review", "access", "catalogue", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--date", type=date.fromisoformat, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError("refuse_overwriting_existing_report")
    sources = [json.loads(getattr(args, n).read_text(encoding="utf-8"))
               for n in ("review", "access", "catalogue")]
    r = audit(*sources, args.date)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(r, indent=2, ensure_ascii=False) + "\n",
                           encoding="utf-8")
    # Only aggregated counts on public CI; row identifiers remain private.
    print(json.dumps({
        "candidates_examined": r["candidates_examined"],
        "blocked": r["blocked"],
        "publication_ready": 0, "public_writes": 0
    }))


if __name__ == "__main__":
    main()
