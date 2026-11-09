"""Fail-closed preflight: private outings leads -> strictly verified proposed additions.

Never edits the public catalogue, nor private backlog. Independently checks
OpenDataSoft's session metadata against the official OpenAgenda page, existing
venue registry, immutable historic catalogue and the live public catalogue.
"""
import argparse
import base64
from datetime import date, datetime
import json
import math
import os
import time
from pathlib import Path
from zoneinfo import ZoneInfo
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from merge_policy import ORIGIN, byid, valid, safe_published_event
from private_intake import BRANCH, PATH, github
from official_organizer_proof import canonical_event_title
from proof import norm, meters
from proof_text import verify_event
from venue_registry import VENUES
from ptitesondes_public_place_venues import lookup_public_venue

API = "https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/evenements-publics-openagenda/records"
FIELDS = ("uid,title_fr,description_fr,canonicalurl,timings,status,"
          "location_city,location_name,location_department,location_region,"
          "location_countrycode,location_coordinates,originagenda_title,"
          "age_min,age_max,conditions_fr")
MAX_ROWS = 10
MAX_FETCH = 15


def official_leads(token):
    """Read private GitHub backlog, respecting its branch and access token."""
    if not token:
        raise ValueError("PRIVATE_INTAKE_READ_TOKEN absent")
    from urllib.parse import quote
    result = github(PATH + "/backlog.json?ref=" + quote(BRANCH, safe=""), token)
    if result.get("encoding") != "base64":
        raise ValueError("Backlog privé GitHub non encodé en base64")
    blob = base64.b64decode(result["content"], validate=False)
    if len(blob) > 1_000_000:
        raise ValueError("Backlog privé trop volumineux")
    entries = json.loads(blob)
    if not isinstance(entries, list) or len(entries) > 4000:
        raise ValueError("Backlog privé malformé ou trop volumineux")
    return entries


def registry_location(lead):
    city = norm(lead.get("city"))
    venue = norm(lead.get("venue"))
    matches = [v for v in VENUES if norm(v["city"]) == city
               and venue in {norm(a) for a in v["aliases"]}]
    if len(matches) == 1:
        return matches[0]
    if matches:
        return None  # Ambiguous legacy registry cannot be overruled.
    # Only geographical proof comes from the public places catalogue.
    # OpenAgenda and organizer session checks remain wholly independent.
    return lookup_public_venue(lead.get("city"), lead.get("venue"))


def permitted(lead, today):
    if not isinstance(lead, dict) or lead.get("collector") not in ("opendatasoft-index", "openagenda-v2"):
        return False
    uid = lead.get("external_id")
    if not isinstance(uid, str) or not re.fullmatch(r"[0-9]{1,12}", uid):
        return False
    src = lead.get("source_url")
    if not isinstance(src, str):
        return False
    url = urlparse(src)
    if (url.scheme != "https" or url.hostname != "openagenda.com" or
            url.username or url.password or not url.path.startswith("/") or
            url.query or url.fragment):
        return False
    try:
        d = date.fromisoformat(lead["date_start"])
        if not today <= d <= date.fromordinal(today.toordinal() + 184):
            return False
        if lead.get("date_end") != d.isoformat():
            return False
    except (ValueError, TypeError, KeyError):
        return False
    return bool(lead.get("title") and lead.get("city") and
                registry_location(lead) is not None)


def api_record(uid, get=None):
    """Retrieve by immutable OpenAgenda UID; never trust an unbounded title search."""
    if not re.fullmatch(r"[0-9]{1,12}", str(uid)):
        raise ValueError("UID de proposition invalide")
    args = urlencode({"limit": MAX_ROWS, "select": FIELDS,
                      "where": "uid='" + str(uid) + "'"})
    url = API + "?" + args
    # Bound retries to transient transport failures; never retry invalid evidence.
    for attempt in range(3):
        try:
            if get is not None:
                doc = get(url)
            else:
                request = Request(url, headers={
                    "Accept": "application/json",
                    "User-Agent": "PtitesOndesIndependentEvidence/1.0",
                })
                with urlopen(request, timeout=18) as response:
                    if urlparse(response.geturl()).hostname != urlparse(API).hostname:
                        raise ValueError("Redirection ODS non autorisée")
                    data = response.read(250_001)
                if len(data) > 250_000:
                    raise ValueError("Réponse ODS trop volumineuse")
                doc = json.loads(data)
            break
        except (HTTPError, URLError, ConnectionError, TimeoutError) as exc:
            if isinstance(exc, HTTPError) and exc.code not in (429, 500, 502, 503, 504):
                raise
            if attempt == 2:
                raise
            time.sleep(0.4 * (2 ** attempt))
    if not isinstance(doc, dict) or not isinstance(doc.get("results"), list):
        raise ValueError("Réponse ODS malformée")
    rows = [r for r in doc["results"] if str(r.get("uid", "")) == str(uid)]
    if len(rows) != 1:
        raise ValueError("UID absent ou non unique dans l'index")
    return rows[0]


def category_for(title, description):
    """Explicit family-music categories only; reject adult events by default."""
    name = norm(title)
    body = norm(title + " " + description)
    if "conte musical" in name:
        return "conte-musical", "Conte musical"
    if "eveil musical" in name:
        return "eveil-musical", "Éveil musical"
    if "atelier musical" in name or "atelier d eveil" in name:
        return "atelier-musical", "Atelier musical"
    if "spectacle musical" in name and any(x in body for x in ("enfant","jeune public","famill","tout petit","bebe")):
        return "spectacle-musical", "Spectacle musical"
    if "cine concert" in name and any(x in body for x in ("enfant","jeune public","famill","tout petit","bebe")):
        return "cine-concert", "Ciné-concert"
    if "concert" in name and any(x in name for x in ("enfant","jeune public","famill","tout petit","bebe")):
        return "concert", "Concert"
    # Many official family listings use a short work title ("Momo",
    # "Ici, là-bas") and state the format solely in the description.
    # Require BOTH an explicit child/family cue and an explicit music format.
    # The official date, venue, source and coordinates are verified later.
    details = norm(description)
    if any(x in details for x in ("famill", "enfant", "jeune public",
                                   "tout petit", "bebe")):
        for label, category, caption in (
            ("conte musical", "conte-musical", "Conte musical"),
            ("cine concert", "cine-concert", "Ciné-concert"),
            ("eveil musical", "eveil-musical", "Éveil musical"),
            ("atelier musical", "atelier-musical", "Atelier musical"),
            ("spectacle musical", "spectacle-musical", "Spectacle musical"),
        ):
            if label in details:
                return category, caption
        if re.search(r"\bconcert\b", details):
            return "concert", "Concert"
    return None


# Official organizer evidence: these slots are exclusively school/group sessions,
# not publicly bookable family outings; other sessions of the same show remain.
# https://www.opera-bordeaux.com/famille-orchestre-momo-lenfant-peche-86301
# https://www.opera-bordeaux.com/famille-orchestre-les-droles-de-petites-betes-86441
SCHOOL_ONLY_TIMES = {
    ("54065371", "2027-01-22"): frozenset({"14:30"}),
    ("66367832", "2027-01-28"): frozenset({"14:30"}),
    ("66367832", "2027-01-29"): frozenset({"14:30"}),
}


def confirmed_session(timings, day, uid=None):
    if isinstance(timings, str):
        timings = json.loads(timings)
    if not isinstance(timings, list):
        raise ValueError("Séances détaillées absentes")
    times = []
    for x in timings:
        if not isinstance(x, dict):
            continue
        begin = x.get("begin")
        if not isinstance(begin, str):
            continue
        try:
            stamp = datetime.fromisoformat(begin)
        except ValueError:
            continue
        if stamp.tzinfo is None:
            continue
        if stamp.date().isoformat() == day:
            times.append(stamp.strftime("%H:%M"))
    if not times:
        raise ValueError("Séance datée et horodatée absente")
    restricted = SCHOOL_ONLY_TIMES.get((str(uid), day), frozenset())
    times = [time for time in times if time not in restricted]
    if not times:
        raise ValueError("Séance uniquement scolaire ou réservée")
    if len(set(times)) > 4:
        raise ValueError("Trop de séances le même jour")
    return ", ".join(sorted(set(times)))


def scheduled(row):
    status = row.get("status")
    if isinstance(status, str):
        try:
            status = json.loads(status)
        except ValueError:
            return False
    return isinstance(status, dict) and status.get("id") == 1


def openagenda_path_parts(raw):
    """Parse only a strict HTTPS event page, without unsafe URL components."""
    if not isinstance(raw, str):
        return None
    p = urlparse(raw)
    try:
        port = p.port
    except ValueError:
        return None
    if (p.scheme != "https" or p.hostname != "openagenda.com" or
            port not in (None, 443) or p.username or p.password or
            p.query or p.fragment):
        return None
    match = re.fullmatch(r"/(?:(?:fr|en)/)?([^/]+)/events/([^/]+)", p.path)
    return match.groups() if match else None


def reconciled_openagenda_url(lead, row):
    """Permit only same-UID OA v2 aliases on the very same OpenAgenda agenda.

    ODS already has to return exactly one record for this UID. The proposed
    event still needs official independent time, title, venue and GPS proof.
    Never allow similarity-only matches or cross-agenda redirects.
    """
    original = lead["source_url"]
    canonical = row.get("canonicalurl")
    source_parts = openagenda_path_parts(original)
    target_parts = openagenda_path_parts(canonical)
    if source_parts is None or target_parts is None:
        raise ValueError("URL canonique non autorisée")
    if original == canonical:
        return canonical
    # Verified real-world syndication of the Bordeaux opera programme:
    # OpenAgenda v2 links an UID-prefixed event under operanationalbordeaux,
    # while the ODS mirror uses its UID-free slug under ville-de-bordeaux.
    # Never infer arbitrary cross-agenda aliases from similar titles.
    pinned_pairs = {("operanationalbordeaux", "ville-de-bordeaux")}
    same_agenda = source_parts[0] == target_parts[0]
    reviewed_syndication = (source_parts[0], target_parts[0]) in pinned_pairs
    expected_source_slug = lead["external_id"] + "_" + target_parts[1]
    if (lead.get("collector") != "openagenda-v2" or
            not (same_agenda or reviewed_syndication) or
            source_parts[1] != expected_source_slug):
        raise ValueError("URL canonique différente")
    return canonical


def make_event(lead, row, location, today):
    """Build only from exact dated first-party fields and reviewed venue coords."""
    if str(row.get("uid")) != lead["external_id"]:
        raise ValueError("UID source différent")
    canonical = reconciled_openagenda_url(lead, row)
    if norm(row.get("title_fr")) != norm(lead["title"]):
        raise ValueError("Titre différent")
    if norm(row.get("location_city")) != norm(lead["city"]):
        raise ValueError("Ville différente")
    if norm(row.get("location_name")) != norm(lead["venue"]):
        raise ValueError("Lieu différent")
    if row.get("location_countrycode") not in ("FR",):
        raise ValueError("Pays non validé")
    if not scheduled(row):
        raise ValueError("Statut différent de programmé")
    coords = row.get("location_coordinates")
    if not isinstance(coords, dict):
        raise ValueError("Position source absente")
    try:
        lat, lng = float(coords["lat"]), float(coords["lon"])
    except (ValueError, TypeError, KeyError):
        raise ValueError("Position source non numérique")
    if not math.isfinite(lat) or not math.isfinite(lng) or meters(
            (lat, lng), (location["lat"], location["lng"])) > 65:
        raise ValueError("Position source incompatible avec le registre vérifié")
    # Reject a known school-only session even when the abbreviated ODS
    # description does not independently classify its family audience.
    day = lead["date_start"]
    performance_time = confirmed_session(row.get("timings"), day, lead["external_id"])
    category = category_for(row["title_fr"], row.get("description_fr") or "")
    if not category:
        raise ValueError("Destination familiale musicale insuffisamment explicite")
    department = row.get("location_department")
    region = row.get("location_region")
    source = row.get("originagenda_title")
    if not all(isinstance(v, str) and v.strip() for v in (department, region, source)):
        raise ValueError("Département, région ou auteur manquant")
    e = {
        "id": "openagenda-" + lead["external_id"] + "-" + day,
        "title": row["title_fr"].strip(),
        "category": category[0], "category_label": category[1],
        "date_start": day, "date_end": day,
        "time": performance_time,
        "city": row["location_city"], "department": department,
        "region": region, "venue": row["location_name"],
        "source_url": canonical,
        "source_label": source,
        "verified_at": today.isoformat(), "geo_verified_at": today.isoformat(),
        "geo_precision": "venue",
        # Use independently documented venue registry point, never blind ODS coords.
        "lat": location["lat"], "lng": location["lng"],
    }
    # Omit age and price if unverified; they are NEVER inferred from a title.
    # The public policy checker independently reconfirms source, sessions, GPS.
    return e


def covered_by_published_range(lead, published_events):
    """Fail closed when a dated session is already inside a published series.

    Public cards may legitimately group consecutive performances into one
    date_start/date_end span. Compare exact title, city and venue identities,
    not merely the initial day. Never merge distinct venues or different
    works based on fuzzy names or shared sources.
    """
    try:
        day = date.fromisoformat(lead["date_start"])
    except (KeyError, ValueError, TypeError):
        return False
    identity = (norm(lead.get("title")), norm(lead.get("city")),
                norm(lead.get("venue")))
    if any(not value for value in identity):
        return False
    for item in published_events:
        if not isinstance(item, dict) or (
                norm(item.get("title")), norm(item.get("city")),
                norm(item.get("venue"))) != identity:
            continue
        try:
            start = date.fromisoformat(item["date_start"])
            end = date.fromisoformat(item.get("date_end") or item["date_start"])
        except (KeyError, ValueError, TypeError):
            continue
        if start <= day <= end:
            return True
    return False



def unique_review_candidates(leads, today, with_alternatives=False):
    """Avoid wasting bounded review slots on two mirrors of a single UID/day.

    OpenDataSoft and OpenAgenda v2 are *not* independent proofs. They often
    submit the same session twice with different OpenAgenda URL aliases.
    Prefer the ODS index lead only as an input to the existing strict ODS
    record and organizer verification, NEVER as evidence of the session.

    Contradictory identity or collector URL for the same UID/date blocks that
    entire group; no fuzzy identity guessing and no widening URL rules.
    """
    eligible = [x for x in leads if permitted(x, today)]
    grouped = {}
    for lead in eligible:
        grouped.setdefault((lead["external_id"], lead["date_start"]), []).append(lead)
    candidates = []
    duplicates_skipped = 0
    conflicting_uid_days = 0
    priority = {"opendatasoft-index": 0, "openagenda-v2": 1}
    for batch in grouped.values():
        identities = {
            (norm(lead["title"]), norm(lead["city"]), norm(lead["venue"]),
             lead["date_end"]) for lead in batch
        }
        sources_by_collector = {}
        for lead in batch:
            sources_by_collector.setdefault(lead["collector"], set()).add(
                lead["source_url"])
        if (len(identities) != 1 or
                any(len(urls) != 1 for urls in sources_by_collector.values())):
            conflicting_uid_days += 1
            continue  # a disagreement must never select an arbitrary winner
        preferred = min(batch, key=lambda lead: (
            priority[lead["collector"]], lead["source_url"]))
        # Strict alternate collector paths for the SAME immutable UID/day only.
        # Both leads were independently constrained by permitted(), identical
        # title/city/venue/date, and one canonical URL per collector.
        # This is not a second proof or a relaxation of canonical URL rules.
        variants = tuple(lead for lead in batch
                         if lead is not preferred
                         and lead["source_url"] != preferred["source_url"])
        candidates.append(
            dict(preferred, _same_uid_date_alternatives=variants)
            if with_alternatives else preferred)
        duplicates_skipped += len(batch) - 1
    candidates.sort(key=lambda x: (
        x["date_start"], x["source_url"], x["external_id"]))
    return candidates, len(eligible), duplicates_skipped, conflicting_uid_days

def rotating_batch(candidates, today, limit, slot=0):
    """Four deterministic windows/day; no cursor or mutable private state.

    Only already-eligible, chronologically sorted leads are rotated.
    Across four scheduled previews, up to four different 15-lead batches
    are examined. With larger backlogs, the daily start advances so the
    remaining batches are not permanently starved.
    """
    if type(limit) is not int or not 1 <= limit <= MAX_FETCH:
        raise ValueError("Taille de lot de vérification interdite")
    if type(slot) is not int or not 0 <= slot <= 3:
        raise ValueError("Créneau de vérification interdit")
    if not candidates:
        return [], 0, 0
    pages = (len(candidates) + limit - 1) // limit
    page = (today.toordinal() * 4 + slot) % pages
    return candidates[page * limit:(page + 1) * limit], page, pages


def evaluate(leads, baseline, published, today, fetch=api_record,
             verifier=verify_event, limit=MAX_FETCH, slot=0):
    historic = byid(baseline)
    existing = byid(published)
    if any(k not in existing or existing[k] != v for k, v in historic.items()):
        raise ValueError("Catalogue historique différent du public")
    fields = set().union(*(set(ev) for ev in baseline["events"]))
    categories = {x["category"] for x in baseline["events"]}
    signatures = {(canonical_event_title(e), norm(e.get("city")),
                   norm(e.get("venue")), e.get("date_start"))
                  for e in published["events"]}
    urls = {(e.get("source_url"), e.get("date_start"))
            for e in published["events"]}
    candidates, eligible_raw, duplicates, conflicts = unique_review_candidates(
        leads, today, with_alternatives=True)
    selected, page, pages = rotating_batch(candidates, today, limit, slot)
    accepted, rejected, assessed = [], [], 0
    for lead in selected:
        assessed += 1
        evidence = {"source_url": lead["source_url"], "date": lead["date_start"]}
        # Avoid even contacting ODS for an occurrence already represented by
        # a multi-day published fiche (e.g. Bordeaux 21–22 Jan or 6–7 Feb).
        if covered_by_published_range(lead, published["events"]):
            rejected.append(dict(evidence, status="already_published",
                                 reason="séance couverte par une fiche publiée"))
            continue
        try:
            record = fetch(lead["external_id"])
            # On an exact canonical-URL disagreement, a second collector's
            # already-qualified alias may be tried against the SAME official
            # UID record. Every alternative still runs all safety checks.
            event = None
            last_canonical_error = None
            for option in (lead, *lead.get("_same_uid_date_alternatives", ())):
                try:
                    event = make_event(option, record, registry_location(option), today)
                    break
                except ValueError as exc:
                    if str(exc) != "URL canonique différente":
                        raise
                    last_canonical_error = exc
            if event is None:
                raise last_canonical_error or ValueError("URL canonique différente")
            signature = (canonical_event_title(event), norm(event["city"]),
                         norm(event["venue"]), event["date_start"])
            if event["id"] in existing or signature in signatures or (
                    event["source_url"], event["date_start"]) in urls:
                rejected.append(dict(evidence, status="already_published"))
                continue
            structural, reason = valid(event, categories, fields, today)
            if not structural:
                rejected.append(dict(evidence, status="rejected_schema", reason=reason))
                continue
            checked, reason = verifier(event, baseline["events"])
            if not checked:
                rejected.append(dict(evidence, status="unverified", reason=reason))
                continue
            accepted.append(event)
            signatures.add(signature)
            urls.add((event["source_url"], event["date_start"]))
        except (ValueError, TypeError, KeyError, OSError) as exc:
            rejected.append(dict(evidence, status="deferred",
                                 reason=str(exc)[:250]))
    if len(accepted) > 100:
        raise ValueError("Limite de 100 fiches par patch dépassée")
    patch = {
        "schema": "ptitesondes.patch.v1", "generated_at": str(today),
        "safe_to_publish": False,
        "source": {"url": ORIGIN, "version": 3,
                   "updated_at": baseline["updated_at"],
                   "events_count": len(baseline["events"])},
        "checks": {"ids_unique": True, "official_sources_verified": True,
                   "no_production_changes": True},
        "additions": accepted, "updates": [], "deferred": [],
    }
    from collections import Counter
    reasons = Counter(x.get("status", "unknown") + ": " +
                      str(x.get("reason", ""))[:110] for x in rejected)
    report = {
        "reason_counts": dict(sorted(reasons.items())),
        "date": str(today), "mode": "preview_no_public_write",
        "backlog_total": len(leads), "eligible_with_reviewed_venue": len(candidates),
        "eligible_raw": eligible_raw,
        "duplicate_collector_leads_skipped": duplicates,
        "conflicting_uid_days_deferred": conflicts,
        "review_slot": slot, "review_batch": page + 1 if pages else 0,
        "review_batches": pages,
        "checked": assessed, "accepted_preflight": len(accepted),
        "deferred_or_duplicates": len(rejected), "details": rejected,
    }
    return patch, report


# Public runner logs and job summaries must never contain private candidate
# URLs, exception details, or arbitrary rejection messages. Full reports remain
# local to the job and are persisted only in the private intake branch.
PUBLIC_COUNT_KEYS = (
    "backlog_total", "eligible_with_reviewed_venue", "eligible_raw",
    "duplicate_collector_leads_skipped", "conflicting_uid_days_deferred",
    "review_slot", "review_batch", "review_batches",
    "checked", "accepted_preflight", "deferred_or_duplicates",
)


def public_run_summary(report):
    """Strict numeric allowlist for public logs, never reason_counts/details."""
    if not isinstance(report, dict):
        raise ValueError("Rapport de prévalidation absent")
    day = date.fromisoformat(report["date"]).isoformat()
    return {
        "date": day, "mode": "preview_no_public_write",
        **{key: report[key] for key in PUBLIC_COUNT_KEYS
           if type(report.get(key)) is int},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output-dir", type=Path,
                    default=Path("/tmp/ptitesondes-promotion"))
    ap.add_argument("--limit", type=int, default=MAX_FETCH)
    ap.add_argument("--slot", type=int, default=0, choices=range(4))
    ap.add_argument("--backlog-file", type=Path)
    ap.add_argument("--reference-file", type=Path)
    ap.add_argument("--catalogue-file", type=Path,
                    default=Path("docs/ptitesondes/sorties.json"))
    ap.add_argument("--date", type=date.fromisoformat)
    args = ap.parse_args()
    if not 1 <= args.limit <= MAX_FETCH:
        raise ValueError("Taille de lot hors limite")
    today = args.date or datetime.now(ZoneInfo("Europe/Paris")).date()
    if args.backlog_file is not None:
        leads = json.loads(args.backlog_file.read_text(encoding="utf-8"))
        if not isinstance(leads, list) or len(leads) > 4000:
            raise ValueError("Backlog local malformé")
    else:
        leads = official_leads(os.environ.get("PRIVATE_INTAKE_READ_TOKEN", ""))
    if args.reference_file is not None:
        baseline = json.loads(args.reference_file.read_text(encoding="utf-8"))
    else:
        request = Request(ORIGIN, headers={"User-Agent": "OndesPublicDataAudit/1.0"})
        with urlopen(request, timeout=30) as response:
            raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("Référence historique trop volumineuse")
        baseline = json.loads(raw)
    published = json.loads(args.catalogue_file.read_text(encoding="utf-8"))
    patch, report = evaluate(leads, baseline, published, today,
                             limit=args.limit, slot=args.slot)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "preview-patch.json").write_text(
        json.dumps(patch, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (args.output_dir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(public_run_summary(report), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
