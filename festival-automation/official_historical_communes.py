"""Resolve historical locality names with the national INSEE COG movement file.

No event-specific overrides, no street-level or fuzzy coordinates. Only a unique
chronological path to a current COM identity can nominate a parent commune.
The live geographical API must independently verify that final identity.
"""
from collections import defaultdict
import csv
from datetime import date
from functools import lru_cache
import io
import re
import ssl

from dns_pinned_https import DNSPinnedHTTPSConnection
from grossesondes_official_html_edition import fold

COG_HOST = "www.insee.fr"
COG_PATH = "/fr/statistiques/fichier/8740222/v_mvt_commune_2026.csv"
COG_URL = "https://" + COG_HOST + COG_PATH
MAX_BYTES = 16_000_000
MAX_ROWS = 150_000
MAX_HOPS = 32
CODE = re.compile(r"^[0-9AB]{5}$")
TYPES = {"COM", "COMA", "COMD"}
# Name change, creation/fusion of communes, change of associated/delegated
# commune status. Other movements (including splits) cannot establish a
# unique parent through this route.
SAFE_MOVEMENTS = {"10", "32", "33", "34", "35"}
HEADER = ("MOD", "DATE_EFF", "TYPECOM_AV", "COM_AV", "TNCC_AV",
          "NCC_AV", "NCCENR_AV", "LIBELLE_AV", "TYPECOM_AP", "COM_AP",
          "TNCC_AP", "NCC_AP", "NCCENR_AP", "LIBELLE_AP")


def normalize(value):
    return "".join(re.findall(r"[a-z0-9]+", fold(value)))


def department(code):
    return code[:3] if code.startswith(("97", "98")) else code[:2]


@lru_cache(maxsize=1)
def read_movements():
    """One bounded, fixed-origin download per Publisher process."""
    conn = DNSPinnedHTTPSConnection(COG_HOST, port=443, timeout=20,
                                    context=ssl.create_default_context())
    try:
        conn.request("GET", COG_PATH, headers={
            "User-Agent": "GrossesOndesFranceCommune/1.0",
            "Accept": "text/csv,application/octet-stream",
            "Accept-Encoding": "identity",
        })
        response = conn.getresponse()
        data = response.read(MAX_BYTES + 1)
        if (response.status != 200 or not 0 < len(data) <= MAX_BYTES
                or response.getheader("Content-Encoding", "identity").lower() != "identity"
                or response.getheader("Content-Type", "").split(";", 1)[0].lower()
                not in ("text/csv", "text/plain", "application/csv",
                        "application/octet-stream", "application/vnd.ms-excel")
                or not data.endswith((b"\n", b"\r"))):
            raise ValueError("Invalid COG movement download")
        declared = response.getheader("Content-Length")
        if declared is not None and int(declared) != len(data):
            raise ValueError("Incomplete COG movement download")
        return data.decode("utf-8-sig")
    finally:
        conn.close()


def historical_parent(city, known_department, text, today=None):
    """Return (historical code, current name, current code), or None.

    Every transition is keyed by administrative type, code and exact name.
    Reused INSEE codes and multi-destination events are not silently merged.
    """
    try:
        today = today or date.today()
        if (not isinstance(text, str) or not 0 < len(text) <= MAX_BYTES
                or not text.endswith(("\n", "\r"))):
            return None
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        if tuple(next(reader, ())) != HEADER:
            return None
        wanted = normalize(city)
        edges = defaultdict(lambda: defaultdict(set))
        origins = set()
        for i, row in enumerate(reader):
            if i >= MAX_ROWS or len(row) != len(HEADER):
                return None
            mod, raw_day, before_type, before_code, _, _, _, before_name, after_type, after_code, _, _, _, after_name = row
            day = date.fromisoformat(raw_day)
            if day > today:
                continue
            if not CODE.fullmatch(before_code) or not CODE.fullmatch(after_code):
                return None
            before = (before_type, before_code, before_name)
            after = (after_type, after_code, after_name)
            edges[before][day].add((mod, after))
            if (before_type in TYPES and normalize(before_name) == wanted
                    and (known_department is None or department(before_code) == known_department)):
                origins.add(before)
        if len(origins) != 1:
            return None
        origin = next(iter(origins))
        current = origin
        cursor = date.min
        changed = False
        for _ in range(MAX_HOPS):
            dates = [d for d in edges[current] if d > cursor]
            if not dates:
                if (not changed or current[0] != "COM"
                        or normalize(current[2]) == wanted
                        or (known_department is not None
                            and department(current[1]) != known_department)):
                    return None
                return origin[1], current[2], current[1]
            cursor = min(dates)
            movements = edges[current][cursor]
            if (len(movements) != 1
                    or any(mod not in SAFE_MOVEMENTS for mod, _ in movements)):
                return None
            _, successor = next(iter(movements))
            if successor[0] not in TYPES:
                return None
            changed = changed or successor != current
            current = successor
        return None
    except (ValueError, TypeError, csv.Error, UnicodeError, AttributeError):
        return None
