"""Verify the ACTUAL GitHub Pages catalogues after deployment.

Compare against immutable committed JSON, not only a green deploy job.
Other GitHub Pages JSON catalogues are never modified here.
"""
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen
from ptitesondes_places import validate, assert_append_only

ROOT = Path("docs/ptitesondes")
ORIGIN = "https://sarogal.github.io/Ondes-Catalogues/ptitesondes/"
LIMITS = {"sorties.json": 9000000, "lieux.json": 1000000}


def get_json(url, limit):
    req = Request(url, headers={"User-Agent": "PtitesOndes-PagesIntegrity/1.0",
                                "Accept": "application/json"})
    with urlopen(req, timeout=15) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("Pages response or redirect unexpected")
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("published catalogue oversized")
    return json.loads(raw.decode("utf-8-sig"))


def equivalent(expected, published):
    if not isinstance(expected, dict) or not isinstance(published, dict):
        return False
    if set(expected) != {"sorties.json", "lieux.json"} or set(published) != set(expected):
        return False
    validate(expected["lieux.json"])
    try:
        validate(published["lieux.json"])
    except ValueError:
        return False
    for item in ("sorties.json", "lieux.json"):
        if expected[item] != published[item]:
            return False
    return True


def verify(read=get_json, sleep=time.sleep, tries=8):
    expected = {name: json.loads((ROOT / name).read_text(encoding="utf-8"))
                for name in LIMITS}
    validate(expected["lieux.json"])
    if not isinstance(expected["sorties.json"].get("events"), list):
        raise ValueError("outings file invalid")
    for attempt in range(tries):
        try:
            live = {name: read(ORIGIN + name, size)
                    for name, size in LIMITS.items()}
            if equivalent(expected, live):
                print("GitHub Pages: sorties", len(live["sorties.json"]["events"]),
                      "| lieux", len(live["lieux.json"]["places"]),
                      "| JSON servi identique au dépôt public")
                return True
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            print("Vérification Pages non concluante:",type(exc).__name__)
        if attempt < tries - 1:
            sleep(8)
    raise ValueError("GitHub Pages still differs from committed outings or places")


if __name__ == "__main__":
    verify()
