#!/usr/bin/env python3
"""Read-only, safe HTTPS evidence probe of previously UNKNOWN Concert sources.

The private intake queue is NOT an authority manifest. This probe fetches a
small rotating sample to distinguish reachable first-party pages from broken
leads. It NEVER registers hosts, signs events or writes public catalogue data.

Security: resolve all A/AAAA records, reject any non-global address, pin the
connection to one validated IP, keep TLS hostname/SNI validation, follow ZERO
redirects, and check robots.txt on that same pinned connection.
"""
from __future__ import annotations

import argparse
import datetime as dt
import http.client
import ipaddress
import json
import re
import socket
import ssl
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo

import discover
import source_admission_intake as intake

SCHEMA = "grossesondes.concert.source-evidence-probe.v1"
MAX_BYTES = 400_000
AGENT = discover.AGENT


def public_ip_addresses(host):
    """Reject mixed public/private DNS; no fallback to an unvalidated IP."""
    infos = socket.getaddrinfo(
        host, 443, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    ips = sorted({entry[4][0] for entry in infos})
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError("DNS origin has unsafe or missing address")
    return ips


class PinnedHTTPS(http.client.HTTPSConnection):
    """TLS name stays 'host' while TCP connects only to the audited address."""
    def __init__(self, host, ip, timeout=8):
        super().__init__(host, port=443, timeout=timeout,
                         context=ssl.create_default_context())
        self.pinned_ip = ip

    def connect(self):
        self.sock = socket.create_connection(
            (self.pinned_ip, 443), self.timeout, self.source_address)
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


def checked_uri(url, host):
    if intake.valid_https(url) != host:
        raise ValueError("Untrusted HTTPS host or URI")
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.username or parts.password or parts.port
            or parts.fragment or not parts.path.startswith("/")
            or "\r" in url or "\n" in url):
        raise ValueError("Invalid first-party URI")
    return parts.path + (("?" + parts.query) if parts.query else "")


def request_pinned(url, host, ip, cap=MAX_BYTES):
    path = checked_uri(url, host)
    connection = PinnedHTTPS(host, ip, timeout=8)
    try:
        connection.request("GET", path, headers={
            "User-Agent": AGENT, "Accept": "text/html,application/ld+json,*/*",
            "Accept-Encoding": "identity", "Connection": "close",
        })
        response = connection.getresponse()
        # No redirects of any kind, including to apparently trusted hosts.
        if response.status not in (200, 404):
            raise ValueError("Source returned non-success HTTP status")
        data = response.read(cap + 1)
        if len(data) > cap:
            raise ValueError("Source response over cap")
        return response.status, data.decode("utf-8", errors="replace")
    finally:
        connection.close()


def safe_fetch(url, cache):
    """For each host, pin a verified IP and obey robots on that very IP."""
    host = intake.valid_https(url)
    if host is None:
        raise ValueError("Untrusted HTTPS origin")
    if host not in cache:
        ips = public_ip_addresses(host)
        ip = ips[0]
        status, content = request_pinned(
            "https://" + host + "/robots.txt", host, ip, cap=120_000)
        if status == 404:
            robots = None  # Absent robots.txt, not a network failure.
        else:
            robots = RobotFileParser()
            robots.set_url("https://" + host + "/robots.txt")
            robots.parse(content.splitlines())
        cache[host] = (ip, robots)
    ip, robots = cache[host]
    if robots is not None and not robots.can_fetch(AGENT, url):
        raise ValueError("robots.txt forbids the candidate page")
    status, content = request_pinned(url, host, ip)
    if status != 200:
        raise ValueError("First-party page missing")
    return content


class _Metadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = []
        self.in_title = False
        self.ld = []
        self.in_ld = False
        self.ld_parts = []
        self.canonicals = []

    def handle_starttag(self, tag, attrs):
        props = dict(attrs)
        if tag == "title":
            self.in_title = True
        elif tag == "script" and props.get("type", "").lower() == "application/ld+json":
            self.in_ld = True
            self.ld_parts = []
        elif tag == "link" and props.get("rel", "").casefold() == "canonical":
            self.canonicals.append(props.get("href"))

    def handle_data(self, value):
        if self.in_title:
            self.title.append(value)
        if self.in_ld:
            self.ld_parts.append(value)

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag == "script" and self.in_ld:
            self.ld.append("".join(self.ld_parts))
            self.in_ld = False


def event_indicators(html, url, date):
    """Only checks the claimed event identity, NOT true event provenance."""
    if not isinstance(html, str) or len(html) > MAX_BYTES:
        return False
    parser = _Metadata()
    parser.feed(html)
    seen = False
    for source in parser.ld[:24]:
        if len(source) > 150_000:
            continue
        try:
            data = json.loads(source)
        except (ValueError, TypeError):
            continue
        nodes = data if isinstance(data, list) else [data]
        for node in nodes:
            if not isinstance(node, dict):
                continue
            kind = node.get("@type", "")
            types = kind if isinstance(kind, list) else [kind]
            if not {"Event", "MusicEvent"}.intersection(types):
                continue
            if (not isinstance(node.get("name"), str)
                    or not isinstance(node.get("startDate"), str)
                    or node["startDate"][:10] != date):
                continue
            source_url = node.get("url")
            if source_url is not None and source_url != url:
                continue
            seen = True
    return seen


def choose(rows, today, slot, limit):
    if (not isinstance(today, dt.date) or isinstance(today, dt.datetime)
            or type(slot) is not int or slot not in (0, 1, 2)
            or type(limit) is not int or not 1 <= limit <= 6):
        raise ValueError("Invalid private source probe budget")
    rows = sorted(rows, key=lambda x: (
        -x.get("stableOnDistinctDays", 0), -x.get("sameHostEventLeads", 0),
        x["host"]))
    if not rows:
        return []
    window = min(len(rows), 3 * limit)
    offset = ((today - dt.date(2026, 11, 21)).days * window) % len(rows)
    begin, end = slot * window // 3, (slot + 1) * window // 3
    return [rows[(offset + i) % len(rows)] for i in range(begin, end)]


def build(intake_report, today, *, slot=0, limit=3, fetch=safe_fetch):
    if (not isinstance(intake_report, dict)
            or intake_report.get("schema") != intake.SCHEMA
            or not isinstance(intake_report.get("reviewQueue"), list)
            or intake_report.get("automaticTrustGranted") is not False
            or intake_report.get("publicationAllowed") is not False):
        raise ValueError("Untrusted source discovery queue")
    eligible = [x for x in intake_report["reviewQueue"]
                if isinstance(x, dict)
                and x.get("alreadyReviewedAuthority") is False
                and type(x.get("stableOnDistinctDays")) is int
                and x["stableOnDistinctDays"] > 0
                and type(x.get("sameHostEventLeads")) is int
                and x["sameHostEventLeads"] > 0
                and intake.valid_https("https://" + str(x.get("host")) + "/")
                    == x.get("host")]
    selected = choose(eligible, today, slot, limit)
    counts, rows, cache = Counter(), [], {}
    for entry in selected:
        result = {"host": entry["host"], "status": "held",
                  "firstPartyPageFetched": False,
                  "exactEventDetailFetched": False,
                  "matchingStructuredDate": False,
                  "independentCorroborationVerified": False,
                  "automaticTrustGranted": False,
                  "publicationAllowed": False}
        try:
            example = next(
                e for e in entry.get("examples", [])
                if isinstance(e, dict)
                and intake.valid_https(e.get("sourcePage")) == entry["host"]
                and intake.valid_https(e.get("eventUrl")) == entry["host"]
                and isinstance(e.get("date"), str))
            listing = fetch(example["sourcePage"], cache)
            if not isinstance(listing, str) or not listing:
                raise ValueError("First-party page empty")
            result["firstPartyPageFetched"] = True
            detail = fetch(example["eventUrl"], cache)
            result["exactEventDetailFetched"] = True
            result["matchingStructuredDate"] = event_indicators(
                detail, example["eventUrl"], example["date"])
            result["status"] = ("needs_independent_official_corroboration"
                                if result["matchingStructuredDate"]
                                else "needs_individual_event_evidence")
        except (ValueError, TypeError, StopIteration, OSError,
                TimeoutError, ssl.SSLError) as exc:
            # No automatic trust for missing pages, DNS errors, robots
            # denials or pages with ambiguous / non-structured event content.
            result["status"] = "held_unverifiable_source"
            result["failureClass"] = type(exc).__name__
        counts[result["status"]] += 1
        rows.append(result)
    return {"schema": SCHEMA, "asOf": today.isoformat(),
            "eligibleUnknownHosts": len(eligible), "checkedHosts": len(rows),
            "scanSlot": slot, "statusCounts": dict(sorted(counts.items())),
            "independentCorroborationVerified": False,
            "automaticTrustGranted": False, "publicationAllowed": False,
            "sourceChecks": rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scan-slot", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--max-hosts", type=int, default=3)
    args = parser.parse_args()
    day = dt.datetime.now(ZoneInfo("Europe/Paris")).date()
    result = build(json.loads(args.intake.read_text(encoding="utf-8")),
                   day, slot=args.scan_slot, limit=args.max_hosts)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(
        result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Private unknown source HTTPS evidence probe completed; "
          "no authority or concert approved.")


if __name__ == "__main__":
    main()
