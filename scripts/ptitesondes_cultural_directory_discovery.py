"""Bounded nationwide discovery from the Ministry's current cultural directory.

Private leads only, no GPS, no automatic approval, no dated events. Rotate
pages of the complete directory instead of maintaining a city/venue list.
The caller must persist the cursor and leads together; a failed scan leaves
both unchanged. This primitive does not modify the existing queue.
"""
from urllib.parse import urlencode
import re

from ptitesondes_family_national_source_preflight import norm_text
from ptitesondes_national_cultural_directory_probe import URL, _fetch

PAGE_SIZE = 20
MAX_PAGES = 4
MAX_TOTAL = 2_000_000
FAMILY = re.compile(
    r"\b(?:ludotheques?|jeune public|jeunesse|enfants?|tout petits|"
    r"petite enfance|eveil artistique|eveil musical|eveil sensoriel|"
    r"parents enfants)\b")
CULTURAL_FIELDS = ("nom_du_lieu", "nom_usuel_du_lieu", "description",
                   "types_noms_publics", "sous_domaines_noms_publics",
                   "domaines_noms_publics")
SCHEMA = "ptitesondes.cultural_directory_private_page.v1"


def identity(row):
    if not isinstance(row, dict):
        return None
    city = row.get("commune")
    name = row.get("nom_du_lieu") or row.get("nom_usuel_du_lieu")
    if any(not isinstance(x, str) or not 2 <= len(x.strip()) <= 180
           or not norm_text(x) or any(ord(c) < 32 or ord(c) == 127 for c in x)
           for x in (city, name)):
        return None
    if norm_text(city) == norm_text(name):
        return None
    # No invented location or coordinates. Commune code establishes only
    # geographic scope, not the venue's position or public accessibility.
    code = row.get("code_commune")
    if not isinstance(code, str) or not re.fullmatch(r"(?:[0-9]{5}|2[AB][0-9]{3})", code):
        return None
    return city.strip(), name.strip()


def is_family_lead(row):
    for key in CULTURAL_FIELDS:
        value = row.get(key)
        if isinstance(value, str) and len(value) <= 30000:
            if FAMILY.search(norm_text(value)):
                return True
        elif isinstance(value, list) and len(value) <= 100:
            if any(isinstance(v, str) and len(v) <= 1000
                   and FAMILY.search(norm_text(v)) for v in value):
                return True
    return False


def parse_page(doc, page):
    if not isinstance(doc, dict) or not isinstance(doc.get("meta"), dict):
        raise ValueError("invalid_directory_page")
    total = doc["meta"].get("total")
    rows = doc.get("data")
    if (type(total) is not int or not 0 <= total <= MAX_TOTAL
            or not isinstance(rows, list)
            or not 1 <= page <= max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
            or len(rows) != min(PAGE_SIZE, max(0, total - (page - 1) * PAGE_SIZE))
            or any(not isinstance(row, dict) for row in rows)):
        raise ValueError("incomplete_directory_page")
    leads = {}
    for row in rows:
        pair = identity(row)
        if pair is None or not is_family_lead(row):
            continue
        city, venue = pair
        key = (norm_text(city), norm_text(venue))
        leads[key] = {"city": city, "venue": venue,
                      "status": "not_inspected_yet", "observed_at": None,
                      "public_eligible": False, "gps_verified": False,
                      "official_site_verified": False}
    return list(leads.values()), total


def scan(previous_page=1, *, fetch=_fetch, budget=MAX_PAGES):
    if (type(previous_page) is not int or not 1 <= previous_page <= MAX_TOTAL
            or type(budget) is not int or not 1 <= budget <= MAX_PAGES):
        raise ValueError("invalid_directory_cursor")
    page = previous_page
    leads = {}
    examined = pages = 0
    total = None
    for _ in range(budget):
        query = URL.split("?")[0] + "?" + urlencode({
            "page": page, "page_size": PAGE_SIZE})
        try:
            doc = fetch(query)
            found, current_total = parse_page(doc, page)
        except (OSError, ValueError):
            # Only reset a persisted cursor if a fresh complete first page
            # independently proves that the requested page no longer exists.
            # A truncated response or transient outage on an in-range page
            # must not silently move the cursor or lose unseen records.
            if pages or page == 1:
                raise
            first = fetch(URL.split("?")[0] + "?" + urlencode({
                "page": 1, "page_size": PAGE_SIZE}))
            first_found, first_total = parse_page(first, 1)
            if page <= max(1, (first_total + PAGE_SIZE - 1) // PAGE_SIZE):
                raise
            page, doc = 1, first
            found, current_total = first_found, first_total
        if total is not None and total != current_total:
            raise ValueError("directory_changed_during_scan")
        total = current_total
        examined += len(doc["data"])
        pages += 1
        for row in found:
            leads[(norm_text(row["city"]), norm_text(row["venue"]))] = row
        last = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        if page == last:
            page = 1
            break
        page += 1
    return {"schema": SCHEMA, "next_page": page, "records": list(leads.values()),
            "rows_examined": examined, "pages_examined": pages,
            "directory_total": total, "publication_ready": False, "public_writes": 0}


PROBE_FIELDS = ("code_commune", "site_internet_et_autres_liens",
                "adresse_complete", "numero_et_libelle_voie", "adresse_entree_public",
                "accessible_au_public", "conditions_acces", "conditions_ouverture",
                "types_noms_publics", "domaines_noms_publics", "description")


def format_counts(rows):
    """Aggregate shapes only: no identities, URLs, addresses or raw values."""
    from collections import Counter
    result = {}
    for key in PROBE_FIELDS:
        counts = Counter()
        for row in rows:
            if key not in row:
                shape = "missing"
            else:
                value = row[key]
                if value is None:
                    shape = "null"
                elif isinstance(value, str):
                    shape = "blank" if not value.strip() else "text"
                    if value.strip().startswith(("[", "{")):
                        import json
                        try:
                            parsed = json.loads(value)
                            if isinstance(parsed, (list, dict)):
                                shape = "json_list_text" if isinstance(parsed, list) else "json_object_text"
                        except ValueError:
                            pass
                    if key == "accessible_au_public" and norm_text(value) in ("oui", "non", "true", "false", "1", "0"):
                        shape = "boolean_text"
                elif type(value) is bool:
                    shape = "boolean"
                elif isinstance(value, list):
                    shape = "list"
                elif isinstance(value, dict):
                    shape = "object"
                elif type(value) in (int, float):
                    shape = "number"
                else:
                    shape = "other"
            counts[shape] += 1
        result[key] = dict(counts)
    return result


def live_probe():
    rows = []
    def observed_fetch(url):
        doc = _fetch(url)
        rows.extend(doc["data"])
        return doc
    result = scan(budget=2, fetch=observed_fetch)
    return {key: value for key, value in result.items() if key != "records"} | {
        "family_leads": len(result["records"]), "field_shapes": format_counts(rows)}


if __name__ == "__main__":
    import json
    try:
        print(json.dumps(live_probe(), sort_keys=True))
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        print("::error::Cultural directory pagination unavailable or invalid")
        raise SystemExit(1) from None
