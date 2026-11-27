"""Read-only comparison of national cultural and Acceslibre directory points.

Concordance is a research hint only; no publication or independence claim.
Reuse the existing bounded national CSV transport, never fetch row URLs.
"""
from collections import Counter
import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlencode
from ptitesondes_acceslibre_geo_hints import download, COLUMNS, MAX_FIELD, MAX_BYTES, _row
from ptitesondes_cultural_directory_discovery import PAGE_SIZE, parse_page, identity, is_family_lead
from ptitesondes_national_cultural_directory_probe import URL, _fetch
from ptitesondes_cultural_directory_identity import directory_identity
from ptitesondes_cultural_directory_geo_probe import classify, point, distance
from ptitesondes_family_national_source_preflight import norm_text


MAX_PROBE_PAGES = 24


def candidates(fetch=_fetch, *, pages=MAX_PROBE_PAGES):
    """Bounded broader sample, with no selection by venue or municipality."""
    if type(pages) is not int or not 1 <= pages <= MAX_PROBE_PAGES:
        raise ValueError("invalid_probe_budget")
    found = {}
    total = None
    for page in range(1, pages + 1):
        doc = fetch(URL.split("?")[0] + "?" + urlencode({"page": page, "page_size": PAGE_SIZE}))
        _, current_total = parse_page(doc, page)
        if total is not None and total != current_total:
            raise ValueError("directory_changed_during_scan")
        total = current_total
        for row in doc["data"]:
            key = identity(row)
            if key and is_family_lead(row) and classify(row) == "distinct_directory_point_unverified":
                normalized = tuple(map(norm_text, key))
                if normalized in found:
                    found[normalized] = None
                else:
                    found[normalized] = row
        if page >= max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE):
            break
    return [row for row in found.values() if row is not None]


def inspect_official_content(lead, html, *, diagnostics=None):
    """Read-only explicit identity, address and family evidence stages."""
    from ptitesondes_open_world_permanent_place_ban import (
        _parse_place_main, ACTIVITIES, ACCESS, RESTRICTED, CLOSED, MAX_HTML,
    )
    from ptitesondes_cultural_directory_identity import address_format
    if not isinstance(html, str) or not 50 <= len(html) <= MAX_HTML:
        return "page_invalid"
    parser = _parse_place_main(html, allow_role_main=True)
    names = {norm_text(lead.get(k)) for k in ("nom_du_lieu", "nom_usuel_du_lieu")} - {""}
    if not parser.seen_main or len(parser.headings) != 1 or parser.headings[0] not in names:
        if diagnostics is not None:
            detail = ("main_missing" if not parser.seen_main else
                      "heading_missing" if not parser.headings else
                      "headings_multiple" if len(parser.headings) != 1 else "heading_different")
            diagnostics["identity_" + detail] += 1
        return "page_identity_unconfirmed"
    if any(RESTRICTED.search(b) or CLOSED.search(b) for b in parser.blocks):
        return "page_access_restricted"
    city, postcode = lead["commune"], lead["code_postal"]
    street = lead.get("numero_et_libelle_voie")
    if not isinstance(street, str) or not norm_text(street):
        return "directory_street_missing"
    if not address_format(lead.get("adresse_complete"), street, postcode, city):
        return "directory_address_conflict"
    if lead.get("adresse_entree_public") not in (None, "") and not address_format(
            lead["adresse_entree_public"], street, postcode, city):
        return "directory_entrance_conflict"
    expected = norm_text(street) + " " + postcode + " " + norm_text(city)
    if expected not in parser.blocks:
        return "page_address_unconfirmed"
    import re
    if not any(re.search(pattern, b) for pattern, _ in ACTIVITIES for b in parser.blocks):
        return "page_family_service_unconfirmed"
    if not any(re.search(pattern, b) for pattern, _ in ACCESS for b in parser.blocks):
        return "page_public_access_unconfirmed"
    return "page_content_concordant_unverified"


def inspect_official(lead, hit, page_read=None):
    from ptitesondes_national_cultural_directory_probe import directory_website_hints
    from ptitesondes_unlisted_source_safe_recheck import read_cultural_https, same_cultural_authority
    from ptitesondes_open_world_permanent_place_ban import _cultural_named_page
    from ptitesondes_dila_municipal_domains import _host
    from urllib.parse import urlsplit
    page_read = page_read or read_cultural_https
    listed = [url for url in directory_website_hints(lead, try_https_upgrade=True) if _host(url)]
    counts = Counter()
    hint = hit.get("website_hint")
    if hint:
        counts["acceslibre_website_present"] += 1
        if any(same_cultural_authority(url, hint) for url in listed):
            counts["both_directories_website_agree"] += 1
    if not 1 <= len(listed) <= 4:
        counts["directory_website_missing_or_ambiguous"] += 1
        return counts
    city, venue = identity(lead)
    aliases = tuple(lead[k] for k in ("nom_du_lieu", "nom_usuel_du_lieu")
                    if isinstance(lead.get(k), str) and 2 <= len(lead[k]) <= 180)
    for url in listed:
        try:
            final, html = page_read(url)
            if not same_cultural_authority(url, final) or urlsplit(final).query or urlsplit(final).fragment:
                raise ValueError("unexpected_authority")
            reason = inspect_official_content(lead, html, diagnostics=counts)
            if reason == "page_identity_unconfirmed":
                target = _cultural_named_page(venue, final, html, verified_aliases=aliases)
                counts["exact_named_link_found" if target else "exact_named_link_unavailable"] += 1
                if target:
                    final, html = page_read(target)
                    if not same_cultural_authority(url, final) or urlsplit(final).query or urlsplit(final).fragment:
                        raise ValueError("unexpected_authority")
                    reason = inspect_official_content(lead, html, diagnostics=counts)
            counts[reason] += 1
        except (OSError, ValueError, TypeError, KeyError, UnicodeError, OverflowError):
            counts["page_unavailable"] += 1
    return counts


def compare(leads, rows, *, inspect=None):
    targets = {}
    buckets = [dict() for _ in leads]
    for i, row in enumerate(leads):
        city = norm_text(row.get("commune"))
        code = row.get("code_commune")
        for name in {norm_text(row.get(k)) for k in ("nom_du_lieu", "nom_usuel_du_lieu")} - {""}:
            targets.setdefault((city, code, name), set()).add(i)
    scanned = 0
    for row in rows:
        scanned += 1
        if not isinstance(row, dict):
            continue
        key = (norm_text(row.get("commune")), row.get("code_insee"), norm_text(row.get("name")))
        for i in targets.get(key, ()):
            bucket = buckets[i]
            rid = row.get("id")
            parsed = _row(row) if isinstance(rid, str) and 0 < len(rid) <= 100 else None
            if len(bucket) >= 2:
                continue
            if parsed is None:
                bucket["invalid"] = None
            elif rid in bucket and bucket[rid] != parsed:
                bucket["conflict"] = None
            else:
                bucket[rid] = parsed
    counts, numberless, official = Counter(), Counter(), Counter()
    inspected = 0
    for lead, bucket in zip(leads, buckets):
        if not bucket:
            reason = "no_exact_match"
        elif len(bucket) != 1:
            reason = "ambiguous"
        else:
            hit = next(iter(bucket.values()))
            if hit is None:
                reason = "invalid_match"
            elif hit["postcode"] != lead.get("code_postal"):
                reason = "postcode_conflict"
            elif distance(point(lead["latitude"], lead["longitude"]), (hit["lat_hint"], hit["lng_hint"])) > 65:
                reason = "point_conflict"
            else:
                reason = "concordant_directory_hint"
                if inspect is not None and inspected < 5:
                    inspected += 1
                    try:
                        official.update(inspect(lead, hit))
                    except (OSError, ValueError, TypeError, KeyError, UnicodeError, OverflowError):
                        official["inspection_unavailable"] += 1
        counts[reason] += 1
        d = Counter()
        directory_identity(*identity(lead), lead, d)
        if d.get("numbered_street_missing"):
            numberless[reason] += 1
    return {"leads": len(leads), "rows_scanned": scanned, "counts": dict(counts),
            "numberless_counts": dict(numberless), "official_inspected": inspected,
            "official_counts": dict(official), "publication_ready": False, "public_writes": 0}


def probe():
    leads = candidates()
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "national.csv"
        download(path)
        if not 0 < path.stat().st_size <= MAX_BYTES:
            raise ValueError("invalid_export")
        csv.field_size_limit(MAX_FIELD)
        with path.open(encoding="utf-8-sig", newline="") as stream:
            header = stream.readline()
            stream.seek(0)
            reader = csv.DictReader(stream, delimiter=";" if ";" in header else ",", strict=True)
            fields = reader.fieldnames or []
            if not COLUMNS.issubset(fields) or len(fields) != len(set(fields)):
                raise ValueError("invalid_export_schema")
            return compare(leads, reader, inspect=inspect_official)


if __name__ == "__main__":
    try:
        print(json.dumps(probe(), sort_keys=True))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, OverflowError, csv.Error):
        print("::error::Acceslibre cultural comparison unavailable")
        raise SystemExit(1) from None
