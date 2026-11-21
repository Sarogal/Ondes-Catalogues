"""Private exhaustive inventory: reconcile EVERY national candidate with real stages.

Offline only. Names, evidence and intermediate municipal leads stay in the
private intake branch. This report never authorizes a publication or web fetch.
"""
import argparse
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SCHEMA = "grossesondes.national-blocker-inventory-private.v1"
REPORTS = {
    "discovery": "national-festival-discovery-review.json",
    "editorial": "national-festival-editorial-review.json",
    "funnel": "national-festival-generic-publisher-funnel.json",
    "handoff": "national-festival-publisher-handoff.json",
    "municipal": "national-municipal-pages-review.json",
    "concerts": "concert-tour-referrals.json",
}


def _name(value):
    if not isinstance(value, str):
        return ""
    folded = unicodedata.normalize("NFKD", value.casefold())
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[a-z0-9]+", re.sub(r"\s+20[2-4][0-9]$", "", folded)))


def _index(rows, key):
    if not isinstance(rows, list):
        raise ValueError("Missing private stage rows")
    out = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get(key), str) or row[key] in out:
            raise ValueError("Invalid or duplicate private dossier")
        out[row[key]] = row
    return out


def _patch_only_leads(patch, catalogue, today):
    """Include unadmitted private patch leads without trusting their claims.

    A deferred item can document an unannounced edition, unresolved geolocation
    or an archival mismatch. None is a publisher approval. Never limit names,
    genres, sites or organizers to a preapproved registry.
    """
    if patch is None:
        return []
    if (not isinstance(patch, dict)
            or patch.get("schema") != "grossesondes.patch.v1"
            or patch.get("generated_at") != today
            or patch.get("safe_to_publish") is not False):
        raise ValueError("Unsafe or stale private patch")
    if (not isinstance(patch.get("deferred"), list)
            or not isinstance(patch.get("additions"), list)
            or len(patch["deferred"]) > 10000
            or len(patch["additions"]) > 2000):
        raise ValueError("Invalid private patch entries")
    known_slugs = {
        r.get("slug") for r in catalogue["festivals"] if isinstance(r, dict)
    }
    extra = {}
    for entry, kind in (
        *((row, "PRIVATE_ADDITION_NOT_PUBLISHED") for row in patch["additions"]),
        *((row, "DEFERRED_RESEARCH_ONLY") for row in patch["deferred"]),
    ):
        if not isinstance(entry, dict):
            raise ValueError("Malformed private patch item")
        slug = entry.get("slug")
        if slug is None:
            # A field-level research note can lack a distinct festival identity.
            continue
        if (not isinstance(slug, str)
                or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug) is None):
            raise ValueError("Unsafe private patch slug")
        if slug in known_slugs:
            continue
        record = extra.setdefault(slug, {
            "slug": slug,
            "name_hint": (entry.get("name") if isinstance(entry.get("name"), str)
                          else slug.replace("-", " ")),
            "record_kinds": [],
            "issues_review_only": [],
            "sources_review_only": [],
            "publication_authorized": False,
            "independent_publisher_recheck_completed": False,
            "editorial_fit": "UNASSESSED_BY_AUTOMATION",
        })
        if kind not in record["record_kinds"]:
            record["record_kinds"].append(kind)
        issue = entry.get("issue")
        if isinstance(issue, str) and len(issue) <= 2000:
            if issue not in record["issues_review_only"]:
                record["issues_review_only"].append(issue)
        # These are clues only, never authorization for HTTP fetches.
        sources = entry.get("sources", [])
        if isinstance(sources, list):
            for source in sources[:12]:
                if (isinstance(source, str) and len(source) <= 1200
                        and source not in record["sources_review_only"]):
                    record["sources_review_only"].append(source)
    return sorted(extra.values(), key=lambda row: row["slug"])


def build_inventory(reports, catalogue, today, patch=None):
    if (not isinstance(catalogue, dict) or catalogue.get("schema") != 1
            or not isinstance(catalogue.get("festivals"), list)):
        raise ValueError("Signed public catalogue required")
    for name, report in reports.items():
        if (not isinstance(report, dict) or report.get("as_of") != today
                or report.get("review_only") is not True
                or report.get("publication_authorized") is not False):
            raise ValueError("Missing, stale or unsafe " + name)
    dis = reports["discovery"]
    rows = dis.get("dossiers")
    if not isinstance(rows, list) or len(rows) > 200:
        raise ValueError("Unbounded private discovery")
    editorial = _index(reports["editorial"].get("dossiers"), "id")
    funnel = _index(reports["funnel"].get("dossiers"), "dossier_id")
    handoff = _index(reports["handoff"].get("dossiers"), "id")
    ids = [d.get("id") for d in rows if isinstance(d, dict)]
    if (len(ids) != len(rows) or len(set(ids)) != len(ids)
            or set(ids) != set(editorial) or set(ids) != set(funnel)
            or set(ids) != set(handoff)):
        raise ValueError("National dossier lost between stages")
    existing = set()
    for row in catalogue["festivals"]:
        if not isinstance(row, dict):
            raise ValueError("Malformed public festival")
        # Undated signed listings are valid but cannot prove an EXACT edition.
        start = row.get("startDate")
        if start is None:
            continue
        if not isinstance(start, str) or not re.fullmatch(r"20[2-4][0-9]-[01][0-9]-[0-3][0-9]", start):
            raise ValueError("Malformed public edition date")
        existing.add((_name(row.get("name")), int(start[:4])))
    referrals = {}
    for ref in reports["concerts"].get("referrals", []):
        if not isinstance(ref, dict) or ref.get("dossierId") not in ids:
            raise ValueError("Unmatched concert referral")
        referrals.setdefault(ref["dossierId"], []).append(ref.get("classification"))
    output = []
    for d in rows:
        ident = d["id"]
        title, year = d.get("name_hint"), d.get("edition_year_hint")
        if not isinstance(title, str) or not title or type(year) is not int:
            raise ValueError("Unnamed or undated national identity")
        e, f, h = editorial[ident], funnel[ident], handoff[ident]
        published = (_name(title), year) in existing
        if published != (f.get("status") == "EXACT_EDITION_IN_PUBLIC_SNAPSHOT"):
            raise ValueError("Publisher funnel/public snapshot mismatch")
        sources = d.get("sources")
        if not isinstance(sources, list) or len(sources) > 12:
            raise ValueError("Invalid dossier source list")
        observation = e.get("primary_observation")
        dates_seen = bool(isinstance(observation, dict)
                          and observation.get("dates_visible_in_primary") is True)
        blockers = e.get("missing_checks", [])
        if not isinstance(blockers, list) or not all(isinstance(x, str) for x in blockers):
            raise ValueError("Invalid editorial blockers")
        output.append({
            "id": ident, "name": title, "edition_year": year,
            "city_hint": d.get("city_hint"), "region_hint": d.get("region_hint"),
            "sources_review_only": [
                {"kind": s.get("kind"), "url": s.get("url")}
                for s in sources if isinstance(s, dict)
            ],
            "primary_edition_dates_observed": dates_seen,
            "first_party_date_hint_review_only": ({
                "start": observation.get("start_date_hint"),
                "end": observation.get("end_date_hint"),
            } if dates_seen else None),
            "editorial_status": e.get("status"),
            "editorial_missing_checks": sorted(set(blockers)),
            "location_enrichment_only": [
                b for b in blockers if b == "coordinates_review"
            ],
            "publisher_funnel_status": f.get("status"),
            "handoff_status": h.get("status"),
            "in_signed_public_catalogue": published,
            "generic_proposal_missing": (
                not published and f.get("status") == "NO_GENERIC_PUBLISHER_PROPOSAL"
            ),
            "first_party_dates_without_generic_proposal": (
                dates_seen and not published
                and f.get("status") == "NO_GENERIC_PUBLISHER_PROPOSAL"
            ),
            "concert_referral_types": referrals.get(ident, []),
            "independent_publisher_recheck_completed": (
                f.get("independent_publisher_recheck_completed") is True
            ),
            "editorial_fit": "UNASSESSED_BY_AUTOMATION",
            "publication_authorized": False,
        })
    names = {(_name(d["name"]), d["edition_year"]) for d in output}
    extra, seen = [], set()
    for site in reports["municipal"].get("rows", []):
        for field in ("unknown_music_links_review_only", "untyped_event_links_review_only"):
            for item in site.get(field, []):
                title, url = item.get("title_hint"), item.get("detail_url_review_only")
                if not isinstance(title, str) or not isinstance(url, str):
                    raise ValueError("Invalid intermediate municipal lead")
                key = (_name(title), url)
                if key in seen or (_name(title), int(
                        re.search(r"20[2-4][0-9]", title).group())
                        if re.search(r"20[2-4][0-9]", title) else -1) in names:
                    continue
                seen.add(key)
                extra.append({
                    "name": title, "source_url_review_only": url,
                    "index_url_review_only": item.get("index_url_review_only"),
                    "parent_dossier_id": site.get("dossier_id"),
                    "qualification": item.get("classification"),
                    "publication_authorized": False,
                })
    patch_leads = _patch_only_leads(patch, catalogue, today)
    counts = Counter(r["publisher_funnel_status"] for r in output)
    return {
        "schema": SCHEMA, "as_of": today, "review_only": True,
        "safe_to_publish": False, "publication_authorized": False,
        "publications": 0,
        "dossiers_count": len(output),
        "dossiers_without_generic_proposal": counts["NO_GENERIC_PUBLISHER_PROPOSAL"],
        "dossiers_already_in_public_snapshot": counts["EXACT_EDITION_IN_PUBLIC_SNAPSHOT"],
        "dossiers_with_first_party_dates_without_proposal": sum(
            r["first_party_dates_without_generic_proposal"] for r in output),
        "municipal_intermediate_leads_count": len(extra),
        "patch_only_unpublished_references_count": len(patch_leads),
        "total_named_leads": len(output) + len(extra) + len(patch_leads),
        "dossiers": output, "municipal_intermediate_leads": extra,
        "patch_only_unpublished_references": patch_leads,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--intake", type=Path, required=True)
    p.add_argument("--catalog", type=Path, required=True)
    args = p.parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    reports = {name: json.loads((args.intake / file).read_text(encoding="utf-8"))
               for name, file in REPORTS.items()}
    catalogue = json.loads(args.catalog.read_text(encoding="utf-8"))
    private_patch = json.loads((args.intake / f"patch-{today}.json").read_text(
        encoding="utf-8"))
    inventory = build_inventory(reports, catalogue, today, patch=private_patch)
    output = args.intake / "national-festival-blocker-inventory.json"
    output.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print("Private inventory: named national=" + str(inventory["dossiers_count"])
          + ", unpublished=" + str(inventory["dossiers_without_generic_proposal"])
          + ", municipal extra=" + str(inventory["municipal_intermediate_leads_count"])
          + ", patch-only references=" + str(inventory["patch_only_unpublished_references_count"])
          + ", publications=0")


if __name__ == "__main__":
    main()
