"""Independent administrative centre for an already proven 2027 commune.

No candidate URL can ever be fetched: hostname, HTTPS, path, query keys and
HTTP transport are fixed by code. DNS pins the resolved public IP, TLS verifies
geo.api.gouv.fr, proxies and redirects are not used. Ambiguous names fail closed.
Returned WGS84 point is a *commune centre*, NEVER a festival site.
"""
from __future__ import annotations
import json
from math import isfinite
import re
import ssl
from pathlib import Path
import sys
from urllib.parse import urlencode

SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
from dns_pinned_https import DNSPinnedHTTPSConnection
from grossesondes_official_html_edition import fold

HOST = "geo.api.gouv.fr"
MAX_BYTES = 160_000
MAX_RESULTS = 50
INSEE = re.compile(r"^[0-9A-B]{5}$")
DEPT = re.compile(r"^[0-9A-B]{2,3}$")


def normalize(value):
    return "".join(re.findall(r"[a-z0-9]+", fold(value)))


def search_url(city):
    if (not isinstance(city, str) or not 2 <= len(city.strip()) <= 80
            or not re.fullmatch(r"[\wÀ-ÿ .'()\-]+", city, re.U)
            or any(x in city for x in ("?", "&", "#", "/", "\\", "\r", "\n"))):
        raise ValueError("Invalid administrative commune search")
    query = urlencode({
        "nom": city.strip(),
        "fields": "nom,code,codeDepartement,centre",
        "format": "geojson",
        "geometry": "centre",
        "zone": "metro,drom,com",
    })
    return f"https://{HOST}/communes?{query}"


def fetch_admin_communes(url):
    """Only this one exact API may be requested; never follow redirects."""
    if (not isinstance(url, str) or not url.startswith(f"https://{HOST}/communes?")
            or url != search_url_from_existing(url)):
        raise ValueError("Unexpected administrative API request")
    conn = DNSPinnedHTTPSConnection(HOST, port=443, timeout=10,
                                    context=ssl.create_default_context())
    try:
        conn.request("GET", url.split(HOST, 1)[1],
                     headers={"User-Agent": "GrossesOndesFranceCommune/1.0",
                              "Accept": "application/geo+json,application/json",
                              "Accept-Encoding": "identity"})
        response = conn.getresponse()
        data = response.read(MAX_BYTES + 1)
        if (response.status != 200 or len(data) > MAX_BYTES
                or response.getheader("Content-Encoding", "identity").lower() != "identity"
                or response.getheader("Content-Type", "").split(";", 1)[0].lower()
                   not in ("application/json", "application/geo+json")):
            raise ValueError("Untrusted administrative response")
        return json.loads(data.decode("utf-8"))
    finally:
        conn.close()


def search_url_from_existing(url):
    """Canonical path/query reconstructed from one validated name field."""
    from urllib.parse import parse_qs, urlsplit
    try:
        parts = urlsplit(url)
        if (parts.scheme != "https" or parts.hostname != HOST
                or parts.netloc != HOST or parts.path != "/communes"
                or parts.fragment or parts.username is not None):
            raise ValueError("Invalid api origin")
        fields = parse_qs(parts.query, strict_parsing=True, keep_blank_values=True)
        if set(fields) != {"nom", "fields", "format", "geometry", "zone"}:
            raise ValueError("Unapproved API query")
        if any(len(values) != 1 for values in fields.values()):
            raise ValueError("Duplicate query")
        return search_url(fields["nom"][0])
    except (TypeError, AttributeError, ValueError) as exc:
        raise ValueError("Unapproved API query") from exc


def verified_commune(city, known_department=None, reader=fetch_admin_communes):
    """Return a UNIQUE exact administrative commune centre or None.

    Department codes in signed rows disambiguate same-name communes. A
    department LABEL is never silently converted into an INSEE code.
    """
    try:
        url = search_url(city)
        source = reader(url)
        if not isinstance(source, dict) or source.get("type") != "FeatureCollection":
            return None
        features = source.get("features")
        if not isinstance(features, list) or len(features) > MAX_RESULTS:
            return None
        expected = normalize(city)
        if known_department not in (None, ""):
            if (not isinstance(known_department, str)
                    or DEPT.fullmatch(known_department.strip().upper()) is None):
                return None  # A département label requires its own government proof.
            dept_code = known_department.strip().upper()
        else:
            dept_code = None
        matches = []
        for feature in features:
            if not isinstance(feature, dict) or feature.get("type") != "Feature":
                continue
            props, geometry = feature.get("properties"), feature.get("geometry")
            if not isinstance(props, dict) or not isinstance(geometry, dict):
                continue
            nom, code, dep = (props.get("nom"), props.get("code"),
                              props.get("codeDepartement"))
            coords = geometry.get("coordinates")
            if (not isinstance(nom, str) or normalize(nom) != expected
                    or not isinstance(code, str) or INSEE.fullmatch(code) is None
                    or not isinstance(dep, str) or DEPT.fullmatch(dep) is None
                    or (dept_code is not None and dept_code != dep.upper())
                    or geometry.get("type") != "Point"
                    or not isinstance(coords, list) or len(coords) != 2
                    or not all(type(c) in (int, float) and isfinite(c) for c in coords)
                    or not (-180 <= coords[0] <= 180 and -90 <= coords[1] <= 90)
                    or (coords[0] == 0 and coords[1] == 0)):
                continue
            matches.append((code, nom, float(coords[1]), float(coords[0])))
        if len(matches) != 1:
            return None
        code, nom, lat, lon = matches[0]
        return {"city": nom, "codeInsee": code, "lat": lat, "lon": lon,
                "geoPrecision": "commune", "geoSource": url,
                "markerMeaning": "centre_indicatif_de_commune"}
    except (OSError, TimeoutError, ValueError, TypeError, UnicodeError):
        return None
