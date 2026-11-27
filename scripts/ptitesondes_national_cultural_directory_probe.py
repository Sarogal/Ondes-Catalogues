"""Read-only probe of the Ministry of Culture's public national directory.

The data.gouv.fr resource is the official Base des lieux culturels ouverts.
No candidate or personal data is printed, no file or catalogue is changed.
A successful probe validates transport and exposes field names, not venues.
"""
import json
import re
from urllib.request import Request, build_opener, HTTPRedirectHandler

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


def probe(opener=None):
    reader = opener or build_opener(NoRedirect()).open
    request = Request(URL, headers={"Accept": "application/json",
                      "User-Agent": "PtitesOndesCulturalDirectoryProbe/1.0"})
    with reader(request, timeout=20) as response:
        if response.status != 200 or response.geturl() != URL:
            raise ValueError("noncanonical_tabular_response")
        raw = response.read(MAX_BYTES + 1)
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("oversized_tabular_response")
    return schema_summary(json.loads(raw))


if __name__ == "__main__":
    try:
        print(json.dumps(probe(), ensure_ascii=False, sort_keys=True))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        print("::error::National cultural directory schema probe failed.")
        raise SystemExit(1) from None
