"""Read-only probe of the Ministry of Culture's public national directory.

The data.gouv.fr resource is the official Base des lieux culturels ouverts.
No candidate or personal data is printed, no file or catalogue is changed.
A successful probe validates transport and exposes field names, not venues.
"""
import json
import re
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from ptitesondes_family_national_source_preflight import norm_text

RESOURCE = "4bd1a20e-4dfd-40ff-bd4d-c714f7085de8"
URL = ("https://tabular-api.data.gouv.fr/api/resources/" + RESOURCE
       + "/data/?page_size=1")
MAX_BYTES = 250_000


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def schema_summary(doc):
    if not isinstance(doc, dict) or not isinstance(doc.get("data"), list):
        raise ValueError("unexpected_tabular_schema")
    rows = doc["data"]
    if len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError("unexpected_tabular_page_size")
    fields = sorted(rows[0])
    if (not 1 <= len(fields) <= 200
            or any(not isinstance(f, str) or not re.fullmatch(
                r"[\w .()'’/-]{1,100}", f) for f in fields)):
        raise ValueError("unexpected_tabular_fields")
    return {"source": "ministere_culture_base_lieux_ouverts",
            "schema_fields": fields, "sample_rows": 1,
            "publication_ready": False, "public_writes": 0}


def _fetch(url, opener=None):
    reader = opener or build_opener(NoRedirect()).open
    request = Request(url, headers={"Accept": "application/json",
                      "User-Agent": "PtitesOndesCulturalDirectoryProbe/1.0"})
    with reader(request, timeout=20) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("noncanonical_tabular_response")
        raw = response.read(MAX_BYTES + 1)
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("oversized_tabular_response")
    return json.loads(raw)


def _rows(doc):
    """Only accept a complete bounded result, never a partial first page."""
    if not isinstance(doc, dict):
        raise ValueError("invalid_filtered_directory")
    rows, meta = doc.get("data"), doc.get("meta")
    if (not isinstance(rows, list) or not isinstance(meta, dict)
            or type(meta.get("total")) is not int
            or meta["total"] != len(rows) or len(rows) > 8
            or any(not isinstance(r, dict) for r in rows)):
        raise ValueError("incomplete_filtered_directory")
    return rows


def exact_directory_record(city, venue, *, fetch=_fetch):
    """Fresh nationwide authority lookup by exact venue and city.

    Results are research clues only. No URL visit, publication or GPS claim.
    Both name fields are queried, duplicates and conflicting identities held.
    """
    if any(not isinstance(v, str) or not 2 <= len(v) <= 180
           or not norm_text(v) or any(ord(c) < 32 for c in v)
           for v in (city, venue)):
        raise ValueError("invalid_cultural_identity")
    records = {}
    for field in ("nom_du_lieu", "nom_usuel_du_lieu"):
        query = URL.split("?")[0] + "?" + urlencode({
            "commune__exact": city, field + "__exact": venue, "page_size": 8})
        for row in _rows(fetch(query)):
            if (norm_text(row.get("commune")) != norm_text(city)
                    or norm_text(venue) not in {
                        norm_text(row.get("nom_du_lieu")), norm_text(row.get("nom_usuel_du_lieu"))}):
                raise ValueError("unexpected_filtered_identity")
            rid = row.get("__id")
            if type(rid) not in (str, int) or not str(rid) or len(str(rid)) > 100:
                raise ValueError("invalid_directory_record_id")
            key = str(rid)
            if key in records and records[key] != row:
                raise ValueError("conflicting_directory_record")
            records[key] = row
    return next(iter(records.values())) if len(records) == 1 else None


def live_filtered_probe():
    """Test the actual API's documented filters using its own first public row.

    Log no establishment identity or values, only a verified lookup outcome.
    """
    sample = _fetch(URL)
    schema = schema_summary(sample)
    row = sample["data"][0]
    city, name = row.get("commune"), row.get("nom_du_lieu") or row.get("nom_usuel_du_lieu")
    matched = exact_directory_record(city, name)
    schema["exact_lookup_unique"] = matched is not None
    if matched is not None:
        schema["lookup_id_matches_sample"] = matched.get("__id") == row.get("__id")
        if not schema["lookup_id_matches_sample"]:
            raise ValueError("filtered_sample_identity_mismatch")
    return schema


def probe(opener=None):
    return schema_summary(_fetch(URL, opener))


if __name__ == "__main__":
    try:
        print(json.dumps(live_filtered_probe(), ensure_ascii=False, sort_keys=True))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        print("::error::National cultural directory schema probe failed.")
        raise SystemExit(1) from None
