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


def candidates(fetch=_fetch):
    found = {}
    for page in range(1, 13):
        doc = fetch(URL.split("?")[0] + "?" + urlencode({"page": page, "page_size": PAGE_SIZE}))
        parse_page(doc, page)
        for row in doc["data"]:
            key = identity(row)
            if key and is_family_lead(row) and classify(row) == "distinct_directory_point_unverified":
                normalized = tuple(map(norm_text, key))
                if normalized in found:
                    found[normalized] = None
                else:
                    found[normalized] = row
    return [row for row in found.values() if row is not None]


def compare(leads, rows):
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
    counts, numberless = Counter(), Counter()
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
        counts[reason] += 1
        d = Counter()
        directory_identity(*identity(lead), lead, d)
        if d.get("numbered_street_missing"):
            numberless[reason] += 1
    return {"leads": len(leads), "rows_scanned": scanned, "counts": dict(counts),
            "numberless_counts": dict(numberless), "publication_ready": False, "public_writes": 0}


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
            return compare(leads, reader)


if __name__ == "__main__":
    try:
        print(json.dumps(probe(), sort_keys=True))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, OverflowError, csv.Error):
        print("::error::Acceslibre cultural comparison unavailable")
        raise SystemExit(1) from None
