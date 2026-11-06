"""Independent public preflight for a BATCH of permanent children's places.

A private proposal is an untrusted lead, never permission to publish.
The public allowlist and its pinned editorial / map facts are versioned here.
Unconfigured places are deferred until separately reviewed and registered.
"""
import argparse
import base64
from datetime import date, datetime
from html.parser import HTMLParser
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from zoneinfo import ZoneInfo
from ptitesondes_places import REQUIRED, validate, assert_append_only, norm
from private_intake import github, BRANCH, PATH

REGISTRY = Path("scripts/ptitesondes_place_sources.json")
PRIVATE = "lieux-release-review.json"
PAGES = "https://sarogal.github.io/Ondes-Catalogues/ptitesondes/lieux.json"
SCHEMA = "ptitesondes.public_place_sources.v1"
PRIVATE_SCHEMA = "ptitesondes.place_release_review.v1"
MAX_BATCH = 15


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.omit = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.omit += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.omit:
            self.omit -= 1

    def handle_data(self, data):
        if not self.omit:
            self.parts.append(data)


def safe_host(url):
    try:
        p = urlsplit(url)
        host = p.hostname
        if (p.scheme != "https" or not host or p.port not in (None, 443)
                or p.username or p.password or p.query or p.fragment
                or p.path in ("", "/") or host == "localhost"
                or host.endswith(".localhost") or host.endswith(".local")):
            raise ValueError("untrusted source URL")
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError("literal IP URLs prohibited")
        return host
    except (TypeError, AttributeError, ValueError):
        raise ValueError("untrusted source URL")


def pinned_get(url, host, limit):
    if safe_host(url) != host:
        raise ValueError("source host not pinned")
    req = Request(url, headers={"User-Agent": "PtitesOndes-PublicPlacePreflight/2.0"})
    with build_opener(NoRedirect()).open(req, timeout=18) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("unexpected source status or redirect")
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("source response too large")
    return raw.decode("utf-8-sig")


def meters(lat1, lon1, lat2, lon2):
    a, b = math.radians(lat1), math.radians(lat2)
    da, db = b-a, math.radians(lon2-lon1)
    h = math.sin(da/2)**2 + math.cos(a)*math.cos(b)*math.sin(db/2)**2
    return 12742000*math.asin(min(1, math.sqrt(h)))


def osm_page(mapref):
    return "https://www.openstreetmap.org/" + mapref["type"] + "/" + str(mapref["id"])


def osm_api(mapref):
    suffix = "/full" if mapref["type"] == "way" else ""
    return ("https://api.openstreetmap.org/api/0.6/" + mapref["type"] +
            "/" + str(mapref["id"]) + suffix)


def source_index(document, today):
    if (not isinstance(document, dict) or set(document) != {"schema", "sources"}
            or document["schema"] != SCHEMA
            or not isinstance(document["sources"], list)
            or len(document["sources"]) > 100):
        raise ValueError("public source registry invalid")
    indexed, geo_urls, official_urls = {}, set(), set()
    for src in document["sources"]:
        if not isinstance(src, dict) or set(src) != {
            "id", "facts", "official_anchors", "osm", "aliases"}:
            raise ValueError("public source entry invalid")
        p, m, anchors, aliases = (src["facts"], src["osm"],
                                  src["official_anchors"], src["aliases"])
        if (not isinstance(p, dict) or
                set(p) != REQUIRED - {"lat", "lng", "reviewed_at"} or
                p.get("id") != src["id"] or
                not isinstance(anchors, list) or not 4 <= len(anchors) <= 25 or
                not all(isinstance(v, str) and len(norm(v)) >= 5 for v in anchors) or
                len(set(map(norm, anchors))) != len(anchors) or
                not isinstance(aliases, list) or len(aliases) > 12 or
                any(not isinstance(v, str) or not norm(v) for v in aliases) or
                not isinstance(m, dict) or set(m) != {"type", "id", "lat", "lng", "tags"}):
            raise ValueError("incomplete pinned public source")
        if (m["type"] not in ("node", "way") or
                type(m["id"]) is not int or m["id"] <= 0 or
                any(type(m[k]) not in (float, int) or not math.isfinite(m[k])
                    for k in ("lat", "lng")) or
                not isinstance(m["tags"], dict)):
            raise ValueError("invalid pinned OSM identity")
        expected_tags = {"name", "amenity", "addr:street",
                         "addr:housenumber", "addr:postcode"}
        if m["type"] == "node":
            expected_tags.add("addr:city")
        if (set(m["tags"]) != expected_tags or
                any(not isinstance(value, str) or not norm(value)
                    for value in m["tags"].values()) or
                m["tags"]["addr:postcode"] != p["postal_code"] or
                norm(m["tags"].get("addr:city", p["city"])) != norm(p["city"]) or
                not re.search(r"(?<![0-9])"+re.escape(m["tags"]["addr:housenumber"])+r"(?![0-9])", p["address"]) or
                not re.search(r"\\b"+re.escape(norm(m["tags"]["addr:street"]))+r"\\b", norm(p["address"])) or
                not re.search(r"\\b"+re.escape(p["postal_code"])+r"\\b", p["address"])):
            raise ValueError("OSM address not pinned to place")
        stamp = today.isoformat()
        canonical = dict(p, lat=m["lat"], lng=m["lng"], reviewed_at=stamp)
        validate({"version": 1, "updated_at": stamp, "places": [canonical]})
        official_url = p["official_url"]
        if safe_host(official_url) == "api.openstreetmap.org":
            raise ValueError("official proof is not independent")
        if p["geo_source_url"] != osm_page(m):
            raise ValueError("map source does not match its OSM object")
        if (src["id"] in indexed or official_url in official_urls
                or osm_page(m) in geo_urls):
            raise ValueError("duplicate pinned source")
        indexed[src["id"]] = src
        official_urls.add(official_url)
        geo_urls.add(osm_page(m))
    return indexed


def official_proof(html, anchors):
    if not isinstance(html, str) or not 200 < len(html) <= 450000:
        raise ValueError("official source absent")
    parser = Visible()
    parser.feed(html.replace("\u00ad", ""))
    text = norm(" ".join(parser.parts))
    if not all(norm(a) in text for a in anchors):
        raise ValueError("official identity, activities or access conditions differ")


def mapped_proof(xml, m, proposal):
    if not isinstance(xml, str) or len(xml) > 350000:
        raise ValueError("OSM proof unavailable")
    root = ET.fromstring(xml)
    if root.tag != "osm":
        raise ValueError("unexpected OSM document")
    objs = [v for v in root.findall(m["type"])
            if v.get("id") == str(m["id"])]
    if len(objs) != 1:
        raise ValueError("pinned OSM feature missing or ambiguous")
    feature = objs[0]
    tags = {t.get("k"): t.get("v") for t in feature.findall("tag")}
    if any(norm(tags.get(k)) != norm(v) for k, v in m["tags"].items()):
        raise ValueError("exact OSM name, category or address mismatch")
    if m["type"] == "node":
        lat, lng = float(feature.get("lat")), float(feature.get("lon"))
        tolerance = 5
    else:
        points = {}
        for node in root.findall("node"):
            points[node.get("id")] = (float(node.get("lat")), float(node.get("lon")))
        refs = [x.get("ref") for x in feature.findall("nd")]
        if (not 4 <= len(refs) <= 200 or refs[0] != refs[-1]
                or not all(v in points for v in refs)):
            raise ValueError("invalid building geometry")
        vertices = [points[v] for v in refs[:-1]]
        lat = sum(v[0] for v in vertices) / len(vertices)
        lng = sum(v[1] for v in vertices) / len(vertices)
        tolerance = 30
    if (not math.isfinite(lat) or not math.isfinite(lng)
            or not -90 <= lat <= 90 or not -180 <= lng <= 180
            or meters(lat, lng, m["lat"], m["lng"]) > tolerance
            or meters(lat, lng, proposal["lat"], proposal["lng"]) > tolerance):
        raise ValueError("OSM coordinates differ from pinned location")
    return round(lat, 7), round(lng, 7)


def verify_envelope(private):
    if (not isinstance(private, dict) or
            private.get("schema") != PRIVATE_SCHEMA or
            private.get("safe_to_publish") is not False or
            private.get("mode") != "private_proposal_only" or
            not isinstance(private.get("proposals"), list) or
            not isinstance(private.get("records"), list) or
            len(private["proposals"]) > MAX_BATCH or len(private["records"]) > 4000):
        raise ValueError("untrusted private proposal envelope")
    ids = [p.get("id") for p in private["proposals"] if isinstance(p, dict)]
    if len(ids) != len(private["proposals"]) or len(ids) != len(set(ids)):
        raise ValueError("private proposal IDs duplicated or malformed")
    return private["proposals"]


def pinned_proposal(proposal, private, source, today):
    facts, mapref = source["facts"], source["osm"]
    if (not isinstance(proposal, dict)
            or set(proposal) != set(facts) | {"lat", "lng", "reviewed_at"}
            or any(type(proposal.get(k)) is not type(v) or proposal[k] != v
                   for k, v in facts.items())):
        raise ValueError("private claims diverge from public pinned evidence")
    try:
        reviewed = date.fromisoformat(proposal["reviewed_at"])
    except (TypeError, ValueError, KeyError):
        raise ValueError("private review date invalid")
    if not 0 <= (today-reviewed).days <= 14:
        raise ValueError("private review expired or future dated")
    if (any(type(proposal[k]) not in (float, int) or
            not math.isfinite(proposal[k]) for k in ("lat", "lng")) or
            meters(proposal["lat"], proposal["lng"],
                   mapref["lat"], mapref["lng"]) > 20):
        raise ValueError("private location does not match pinned geometry")
    matching = [r for r in private["records"] if isinstance(r, dict)
                and norm(r.get("city")) == norm(facts["city"])
                and norm(r.get("venue")) == norm(facts["name"])]
    if (len(matching) != 1 or
            matching[0].get("status") != "requires_independent_public_preflight"):
        raise ValueError("private approval stage missing")
    return proposal


def duplicate(existing, source, lat, lng):
    facts, m = source["facts"], source["osm"]
    aliases = {norm(a) for a in source["aliases"] + [facts["name"]]}
    for item in existing:
        same_city = norm(item["city"]) == norm(facts["city"])
        if (item["official_url"] == facts["official_url"] or
                item["geo_source_url"] == facts["geo_source_url"] or
                (same_city and (norm(item["address"]) == norm(facts["address"])
                  or norm(item["name"]) in aliases
                  or meters(item["lat"], item["lng"], lat, lng) <= 80))):
            return item["id"]
    return None


def evaluate(private, current, registry, today, read=pinned_get):
    """Verify all candidates independently; one bad venue cannot block others."""
    validate(current)
    sources = source_index(registry, today)
    candidates = verify_envelope(private)
    outcomes = []
    approved = []
    for p in candidates:
        sid = p["id"]
        src = sources.get(sid)
        if src is None:
            outcomes.append({"id": sid, "status": "not_publicly_configured"})
            continue
        try:
            pinned_proposal(p, private, src, today)
            if any(item["id"] == sid for item in current["places"]):
                outcomes.append({"id": sid, "status": "already_public"})
                continue
            if duplicate(current["places"] + approved, src, p["lat"], p["lng"]):
                raise ValueError("existing alias, address, map object or nearby place")
            url = src["facts"]["official_url"]
            html = read(url, safe_host(url), 450000)
            official_proof(html, src["official_anchors"])
            geo_url = osm_api(src["osm"])
            xml = read(geo_url, "api.openstreetmap.org", 350000)
            lat, lng = mapped_proof(xml, src["osm"], p)
            new = dict(src["facts"], lat=lat, lng=lng,
                       reviewed_at=today.isoformat())
            validate({"version": 1, "updated_at": today.isoformat(),
                      "places": [new]})
            if duplicate(current["places"] + approved, src, lat, lng):
                raise ValueError("mapped place conflicts with existing place")
            approved.append(new)
            outcomes.append({"id": sid, "status": "independently_verified"})
        except (ValueError, TypeError, KeyError, OSError, OverflowError,
                ET.ParseError) as exc:
            outcomes.append({"id": sid, "status": "deferred",
                             "reason": str(exc)[:160]})
    out = {"version": 1, "updated_at": today.isoformat(),
           "places": current["places"] + approved} if approved else current
    assert_append_only(current, out)
    return out, outcomes


def private_json(token):
    if not token:
        raise ValueError("PRIVATE_INTAKE_READ_TOKEN absent")
    p = quote(PATH+"/"+PRIVATE, safe="/")+"?ref="+quote(BRANCH, safe="")
    data = github(p, token)
    if data.get("encoding") != "base64":
        raise ValueError("private proposal unreadable")
    raw = base64.b64decode("".join(data["content"].split()), validate=True)
    if len(raw) > 150000:
        raise ValueError("private proposal oversized")
    return json.loads(raw)


def live_review(token, current, today, registry_file=REGISTRY):
    private = private_json(token)
    sources = json.loads(registry_file.read_text(encoding="utf-8"))
    # Always compare the deployed baseline before making a promotion decision.
    live = json.loads(pinned_get(PAGES, "sarogal.github.io", 1000000))
    validate(live)
    if live != current:
        raise ValueError("GitHub Pages baseline differs from repository")
    return evaluate(private, current, sources, today)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=("preview", "apply"), default="preview")
    p.add_argument("--file", type=Path,
                   default=Path("docs/ptitesondes/lieux.json"))
    args = p.parse_args()
    current = json.loads(args.file.read_text(encoding="utf-8"))
    today = datetime.now(ZoneInfo("Europe/Paris")).date()
    candidate, outcomes = current, []
    try:
        candidate, outcomes = live_review(
            os.getenv("PRIVATE_INTAKE_READ_TOKEN", ""), current, today)
    except (ValueError, TypeError, KeyError, OSError, UnicodeError,
            json.JSONDecodeError) as exc:
        outcomes = [{"id": "global", "status": "deferred",
                     "reason": str(exc)[:160]}]
    count = len(candidate["places"]) - len(current["places"])
    changed = count > 0 and args.mode == "apply"
    if changed:
        args.file.write_text(
            json.dumps(candidate, ensure_ascii=False, indent=2)+"\n",
            encoding="utf-8")
    if os.getenv("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as out:
            out.write("changed="+str(changed).lower()+"\n")
    report = {"candidates": len(outcomes), "approved": count,
              "published_to_worktree": count if changed else 0,
              "mode": args.mode, "outcomes": outcomes}
    print("Prévalidation publique indépendante :",
          json.dumps(report, ensure_ascii=False))
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as out:
            out.write("### Prévalidation publique des lieux\n"
                      "Propositions : "+str(len(outcomes))+
                      " ; vérifiées : "+str(count)+
                      " ; préparées : "+str(count if changed else 0)+"\n")


if __name__ == "__main__":
    main()
