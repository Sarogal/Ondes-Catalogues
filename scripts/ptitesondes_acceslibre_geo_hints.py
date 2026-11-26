"""Read-only national Acceslibre discovery, using the open CSV resource.

One streamed export covers all current catalogue research groups. The dataset
is collaborative: matches are *hints*, never independent event proof or GPS
approval. No activity, city, venue or website list limits discovery.
"""
import argparse
import csv
from datetime import date
import json
import math
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

from proof import norm
from ptitesondes_catalogue_geo_research import research_queue
from ptitesondes_catalogue_geo_rotation import identity
from ptitesondes_dynamic_municipal_source_links import _safe_url

RESOURCE = "https://www.data.gouv.fr/api/1/datasets/r/5b0f44f2-e6ea-4a58-874d-6fe364b40342"
# Fixed transport providers for one national public dataset, not venue hosts.
EXPORT_HOSTS = frozenset(("www.data.gouv.fr", "data.gouv.fr", "static.data.gouv.fr",
                          "acceslibre.beta.gouv.fr", "acceslibre.gouv.fr", "acceslibre.info"))
MAX_BYTES = 300_000_000
MAX_FIELD = 262_144
SCHEMA = "ptitesondes.acceslibre.geo_hints.v1"
COLUMNS = frozenset(("id", "name", "commune", "code_insee", "postal_code",
                     "numero", "voie", "latitude", "longitude", "site_internet"))
CODE = re.compile(r"(?:[0-9]{5}|2[AB][0-9]{3})")


def _trusted_export(url):
    try:
        u = urlsplit(url)
        return (u.scheme == "https" and u.hostname in EXPORT_HOSTS
                and u.port in (None, 443) and not u.username and not u.password
                and not u.fragment)
    except (ValueError, TypeError):
        return False


class ExportRedirect(HTTPRedirectHandler):
    max_redirections = 4
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _trusted_export(newurl):
            raise ValueError("untrusted_export_redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(path, *, opener=None):
    """Fetch the single official resource, never URLs found inside its rows."""
    opener = opener or build_opener(ExportRedirect()).open
    request = Request(RESOURCE, headers={
        "Accept": "text/csv,application/octet-stream",
        "Accept-Encoding": "identity", "User-Agent": "PtitesOndesAcceslibreResearch/1.0"})
    with opener(request, timeout=45) as response:
        if response.status != 200 or not _trusted_export(response.geturl()):
            raise ValueError("untrusted_export_response")
        size = response.getheader("Content-Length")
        if size is not None and (not size.isdigit() or int(size) > MAX_BYTES):
            raise ValueError("oversized_export")
        if (response.getheader("Content-Encoding") or "identity").lower() != "identity":
            raise ValueError("unexpected_export_encoding")
        received = 0
        with Path(path).open("xb") as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                received += len(chunk)
                if received > MAX_BYTES:
                    raise ValueError("oversized_export")
                out.write(chunk)
        if received == 0 or (size is not None and received != int(size)):
            raise ValueError("incomplete_export")


def _name(value):
    if not isinstance(value, str):
        return ""
    # French definite articles only. Never remove distinctive words or use
    # fuzzy substring similarity (two adjacent theatres may have similar names).
    return re.sub(r"^(?:le|la|les|l) ", "", norm(value))


def _row(row):
    if not isinstance(row, dict):
        return None
    code, postal = row.get("code_insee", ""), row.get("postal_code", "")
    if (not isinstance(code, str) or not CODE.fullmatch(code)
            or not isinstance(postal, str) or not re.fullmatch(r"[0-9]{5}", postal)):
        return None
    try:
        lat, lng = float(row["latitude"]), float(row["longitude"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None
    if not (math.isfinite(lat) and math.isfinite(lng)
            and -90 <= lat <= 90 and -180 <= lng <= 180 and (lat, lng) != (0, 0)):
        return None
    url = row.get("site_internet") or ""
    if url and not _safe_url(url):
        url = ""
    return {"erp_id": row["id"], "name": row["name"], "city": row["commune"],
            "code_insee": code, "postcode": postal, "number": row.get("numero") or "",
            "street": row.get("voie") or "", "lat_hint": lat, "lng_hint": lng,
            "website_hint": url or None, "publication_ready": False}


def scan(catalogue, today, rows):
    groups = research_queue(catalogue, today)["research_groups"]
    targets = {}
    for group in groups:
        key = (norm(group["city"]), _name(group["venue"]))
        if all(key):
            targets.setdefault(key, []).append(group)
    candidates = {}
    count = 0
    for row in rows:
        count += 1
        if not isinstance(row, dict) or not all(isinstance(row.get(k), str)
                    for k in ("name", "commune", "id")):
            continue
        key = (norm(row["commune"]), _name(row["name"]))
        if key not in targets:
            continue
        # Preserve ambiguity even if one of the competing rows lacks GPS.
        bucket = candidates.setdefault(key, {})
        if len(bucket) >= 2:
            continue
        rid = row["id"]
        parsed = _row(row)
        if not rid or len(rid) > 100:
            bucket["invalid"] = None
            continue
        if rid in bucket and bucket[rid] != parsed:
            bucket["conflict"] = None
        else:
            bucket[rid] = parsed
    hints = {}
    ambiguous = missing = 0
    for key, matched_groups in targets.items():
        bucket = candidates.get(key, {})
        if len(bucket) != 1 or len(matched_groups) != 1:
            ambiguous += len(matched_groups) if bucket else 0
            missing += len(matched_groups) if not bucket else 0
            continue
        row = next(iter(bucket.values()))
        if row is None:
            missing += 1
            continue
        group = matched_groups[0]
        # Do not equate a same-named town in another department.
        department = re.search(r"\(([0-9]{2,3}|2[AB])\)$", group.get("department") or "")
        if department and not row["code_insee"].startswith(department.group(1)):
            missing += 1
            continue
        hints[identity(group)] = dict(group_city=group["city"], group_venue=group["venue"],
                                      hint=row, independent_recheck_required=True)
    return dict(schema=SCHEMA, day=today.isoformat(), resource=RESOURCE,
                groups=len(groups), rows_scanned=count, unique_hints=len(hints),
                ambiguous_groups=ambiguous, unmatched_groups=missing,
                covered_missing_events=sum(len(g["missing_ids"]) for g in groups if identity(g) in hints),
                hints=hints, publication_ready=False, public_writes=0)


def scan_file(catalogue, today, path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError("invalid_export_file")
    csv.field_size_limit(MAX_FIELD)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        sample = stream.read(8192)
        stream.seek(0)
        # The standard is semicolon; official exports can also use comma.
        header = sample.splitlines()[0]
        separator = ";" if ";" in header else ","
        reader = csv.DictReader(stream, delimiter=separator, strict=True)
        fields = reader.fieldnames or []
        if not COLUMNS.issubset(fields) or len(fields) != len(set(fields)):
            raise ValueError("unexpected_acceslibre_schema")
        return scan(catalogue, today, reader)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--catalogue", type=Path, required=True)
    p.add_argument("--day", type=date.fromisoformat, required=True)
    modes = p.add_mutually_exclusive_group(required=True)
    modes.add_argument("--csv", type=Path)
    modes.add_argument("--live", action="store_true")
    a = p.parse_args()
    catalogue = json.loads(a.catalogue.read_text(encoding="utf-8"))
    if a.live:
        with TemporaryDirectory(prefix="po-acceslibre-") as folder:
            export = Path(folder) / "erp.csv"
            download(export)
            report = scan_file(catalogue, a.day, export)
    else:
        report = scan_file(catalogue, a.day, a.csv)
    # This first live rehearsal exports counts only; no candidate becomes proof.
    print(json.dumps({k: v for k, v in report.items() if k != "hints"}))


if __name__ == "__main__":
    main()
