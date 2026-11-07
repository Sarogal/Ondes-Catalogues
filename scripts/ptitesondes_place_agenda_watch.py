#!/usr/bin/env python3
"""Watch exact, reviewed venue programme pages. Private leads only, NEVER publish.

The permanent-place catalogue and the dated-outings catalogue are immutable
inputs. Dates from a season, opening hours or recurring weekday patterns are
never promoted to an event. Only explicitly timed JSON-LD Event sessions can
be emitted as *unverified leads* for an independent proof pipeline.
"""
import argparse
from datetime import date, timedelta
from hashlib import sha256
from html.parser import HTMLParser
import ipaddress
import json
from pathlib import Path
import re
import unicodedata
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import build_opener, HTTPRedirectHandler, Request

SCHEMA = "ptitesondes.place_agenda_watch.v1"
STATE = "ptitesondes.place_agenda_watch_state.v1"
REPORT = "ptitesondes.place_agenda_watch_report.v1"
APPROVED_HOSTS = {
    "www.montpellier.fr", "agenda.montpellier.fr",
    "museum.toulouse-metropole.fr", "www.ville-pace.bzh",
    "parents.loire-atlantique.fr",
}
MAX_BYTES = 300_000
DATE_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})$")
JSON_LD = re.compile(r'<script\b(?=[^>]*\btype\s*=\s*["\x27]application/ld\+json["\x27])[^>]*>(.*?)</script\s*>', re.I | re.S)


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "").lower())
    return " ".join(re.sub(r"[^a-z0-9]+", " ", "".join(
        c for c in s if not unicodedata.combining(c))).split())


def safe_url(value):
    if not isinstance(value, str) or len(value) > 500:
        return False
    p = urlparse(value)
    if (p.scheme != "https" or p.hostname not in APPROVED_HOSTS or
            p.username or p.password or p.port or p.query or p.fragment or
            not p.path.startswith("/")):
        return False
    try:
        ipaddress.ip_address(p.hostname)
        return False
    except ValueError:
        return True


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch(url):
    if not safe_url(url):
        raise ValueError("Source hors liste autorisée")
    opener = build_opener(NoRedirect)
    with opener.open(Request(url, headers={
        "User-Agent": "PtitesOndesVenueAgendaWatch/1.0 (read-only)",
        "Accept": "text/html",
    }), timeout=15) as response:
        if response.geturl() != url:
            raise ValueError("Redirection refusée")
        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type.lower():
            raise ValueError("Le programme n'est pas une page HTML")
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError("Page trop volumineuse")
        return body.decode("utf-8", "replace")


class Visible(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "header", "noscript", "svg"}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.parts.append(data)


def visible_text(html):
    parser = Visible()
    parser.feed(html)
    return " ".join(" ".join(parser.parts).split())


def structured_events(html):
    for raw in JSON_LD.findall(html):
        if len(raw) > 100_000:
            continue
        try:
            document = json.loads(raw)
        except (ValueError, TypeError):
            continue
        batch = document if isinstance(document, list) else [document]
        for item in batch:
            if not isinstance(item, dict):
                continue
            nodes = item.get("@graph", [item])
            if not isinstance(nodes, list):
                continue
            for node in nodes[:100]:
                if isinstance(node, dict):
                    yield node


def event_leads(html, source, today):
    """Candidates only. Exact local venue and an actual timestamp required."""
    result = []
    aliases = [norm(a) for a in source["venue_aliases"]]
    for event in structured_events(html):
        types = event.get("@type", [])
        if isinstance(types, str):
            types = [types]
        if not isinstance(types, list) or not any(
                isinstance(t, str) and t.rsplit("/", 1)[-1].endswith("Event")
                for t in types):
            continue
        title, start, end = event.get("name"), event.get("startDate"), event.get("endDate")
        if not isinstance(title, str) or not 5 <= len(title.strip()) <= 180:
            continue
        if not isinstance(start, str) or not DATE_TIME.fullmatch(start):
            continue
        try:
            day = date.fromisoformat(start[:10])
        except ValueError:
            continue
        if not today <= day <= today + timedelta(days=183):
            continue
        if end is not None:
            if not isinstance(end, str) or not DATE_TIME.fullmatch(end):
                continue
            if end[:10] != start[:10]:
                continue  # A season or multi-day span is not a session.
        location = event.get("location")
        if not isinstance(location, dict):
            continue
        venue = norm(location.get("name"))
        if not venue or not any(alias in venue for alias in aliases):
            continue
        link = event.get("url") or source["url"]
        if not isinstance(link, str) or not safe_url(link):
            continue
        if urlparse(link).hostname != urlparse(source["url"]).hostname:
            continue
        result.append({
            "place_id": source["place_id"], "name": title.strip(),
            "start": start, "end": end, "source_url": link,
            "status": "requires_independent_session_proof",
        })
        if len(result) == 30:
            break
    return sorted({(r["name"], r["start"], r["source_url"]): r
                   for r in result}.values(), key=lambda r: (r["start"], r["name"]))


def validate_config(registry, catalogue, state):
    if (not isinstance(registry, dict) or registry.get("schema") != SCHEMA
            or not isinstance(registry.get("sources"), list)
            or not 1 <= len(registry["sources"]) <= 40):
        raise ValueError("Registre de programmes inconnu")
    if not isinstance(catalogue, dict) or not isinstance(catalogue.get("places"), list):
        raise ValueError("Catalogue de lieux invalide")
    known = {p.get("id") for p in catalogue["places"] if isinstance(p, dict)}
    if state is None:
        state = {"schema": STATE, "fingerprints": {}}
    if (not isinstance(state, dict) or state.get("schema") != STATE
            or not isinstance(state.get("fingerprints"), dict)):
        raise ValueError("Etat de surveillance invalide")
    ids, urls = set(), set()
    for s in registry["sources"]:
        if (not isinstance(s, dict) or set(s) != {
                "id", "place_id", "url", "kind", "identity", "venue_aliases"}
                or s["place_id"] not in known
                or s["kind"] not in {"programme", "venue-page"}
                or not safe_url(s["url"])
                or not isinstance(s["id"], str)
                or not re.fullmatch(r"[a-z0-9-]{5,100}", s["id"])
                or not isinstance(s["identity"], str) or len(s["identity"]) < 5
                or not isinstance(s["venue_aliases"], list)
                or not s["venue_aliases"]
                or not all(isinstance(x, str) and len(x) >= 5
                           for x in s["venue_aliases"])
                or s["id"] in ids or s["url"] in urls):
            raise ValueError("Source de programme non homologuée")
        ids.add(s["id"])
        urls.add(s["url"])
    if any(k not in ids or not isinstance(v, str) or
           not re.fullmatch("[0-9a-f]{64}", v)
           for k, v in state["fingerprints"].items()):
        raise ValueError("Empreinte historique non fiable")
    return state


def run_watch(registry, catalogue, previous=None, getter=fetch, today=None):
    today = today or date.today()
    previous = validate_config(registry, catalogue, previous)
    fingerprints = dict(previous["fingerprints"])
    entries, changes, leads = [], [], []
    for source in registry["sources"]:
        record = {"id": source["id"], "place_id": source["place_id"],
                  "kind": source["kind"], "url": source["url"]}
        try:
            html = getter(source["url"])
            if not isinstance(html, str) or len(html.encode("utf-8")) > MAX_BYTES:
                raise ValueError("Réponse HTML invalide ou excessive")
            content = visible_text(html)
            if norm(source["identity"]) not in norm(content):
                raise ValueError("Identité du lieu absente de la page")
            digest = sha256(norm(content).encode("utf-8")).hexdigest()
            before = fingerprints.get(source["id"])
            fingerprints[source["id"]] = digest
            record["status"] = "ok"
            record["changed"] = before is not None and before != digest
            record["initialized"] = before is None
            if record["changed"] or record["initialized"]:
                changes.append({"id": source["id"], "place_id": source["place_id"],
                                "reason": "initial_watch" if before is None
                                else "official_page_changed"})
            if source["kind"] == "programme":
                leads.extend(event_leads(html, source, today))
                # Official institutions frequently publish exact sessions as
                # dated headings rather than structured JSON-LD. Use only
                # explicitly reviewed adapters; each lead remains private.
                from ptitesondes_place_agenda_curated import curated_leads
                leads.extend(curated_leads(source, html, today))
                # Strictly bounded first-party drilldown for Totems only.
                # Detail URLs are discovered on the official municipality
                # index, but never trusted until their individual date,
                # place, age and time match on the detail itself.
                from ptitesondes_place_agenda_pace import pace_agenda_leads
                leads.extend(pace_agenda_leads(source, html, today, getter))
        except (OSError, HTTPError, ValueError, UnicodeError) as error:
            record["status"] = "source_unavailable"
            record["reason"] = type(error).__name__
            # Previous fingerprint survives failure.
        entries.append(record)
    report = {"schema": REPORT, "policy": "no_automatic_publication",
              "sources": entries, "changes": changes,
              "event_candidates": sorted(
                  {(e["place_id"], e["name"], e["start"], e["source_url"]): e
                   for e in leads}.values(), key=lambda e: (e["start"], e["name"]))}
    return {"schema": STATE, "fingerprints": fingerprints}, report


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sources", type=Path, required=True)
    p.add_argument("--catalogue", type=Path, required=True)
    p.add_argument("--existing", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    args = p.parse_args()
    registry = json.loads(args.sources.read_text(encoding="utf-8"))
    catalogue = json.loads(args.catalogue.read_text(encoding="utf-8"))
    old = json.loads(args.existing.read_text(encoding="utf-8")) if args.existing.is_file() else None
    state, report = run_watch(registry, catalogue, old,
                              today=date.today())
    args.output.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    ok = sum(x["status"] == "ok" for x in report["sources"])
    print(f"Programmes officiels: {ok}/{len(report['sources'])} consultes ; "
          f"{len(report['changes'])} changements ; "
          f"{len(report['event_candidates'])} pistes non publiables.")
    if not ok:
        raise SystemExit("Aucune source officielle accessible; état précédent préservé.")


if __name__ == "__main__":
    main()
