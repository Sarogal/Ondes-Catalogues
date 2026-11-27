"""Read-only, secretless Chromium evidence for the *signed public* festival set.

This program runs in a separate GitHub Actions job with contents:read, a
credential-free checkout and no private intake token. The publisher treats
the resulting HTML as untrusted input and independently validates each field.
Never choose targets from a private patch, from HTML links, or from CLI URLs.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import os
import re
from datetime import datetime, date
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import sys

_AUTOMATION_DIR = str(Path(__file__).resolve().parents[1] / "festival-automation")
if _AUTOMATION_DIR not in sys.path:
    sys.path.insert(0, _AUTOMATION_DIR)

from dns_pinned_https import safe_public_url, fetch_public_html
from grossesondes_archived_html_intake import organizer_homepage
from grossesondes_official_browser_probe import rendered_html, BrowserEvidenceError
from grossesondes_existing_official_updates import linked_pages, page, signed_rotation

SCHEMA = "grossesondes.browser-official-evidence.v1"
MAX_ENTRIES = 8
MAX_LINKS_PER_SITE = 2
MAX_BYTES = 1_400_000
MAX_RAW_PROBES = 48
MAX_FAILURE_SLOTS = 5


def _eligible_url(row):
    url = row.get("officialSite") if isinstance(row, dict) else None
    return url if safe_public_url(url) and organizer_homepage(url) else None


def _rotate(items, slot, count):
    if not items or count <= 0:
        return []
    items = sorted(items, key=lambda pair: pair[0])
    start = (slot * max(1, count)) % len(items)
    return [items[(start + i) % len(items)] for i in range(min(count, len(items)))]


def signed_targets(published, history, today, slot, limit=MAX_ENTRIES, *,
                   quotas=(4, 3, 1)):
    """Prioritize unlocated current editions, then rotate archived origins."""
    if (not isinstance(published, dict) or published.get("schema") != 1
            or not isinstance(published.get("festivals"), list)
            or not isinstance(history, dict) or history.get("schema") != 2
            or not isinstance(history.get("knownFestivals"), list)
            or type(slot) is not int or slot < 0
            or type(limit) is not int or not 1 <= limit <= MAX_ENTRIES):
        raise ValueError("Invalid signed festival inputs")
    unlocated, located, archived = [], [], []
    published_slugs = set()
    for row in published["festivals"]:
        if not isinstance(row, dict) or not isinstance(row.get("slug"), str):
            continue
        published_slugs.add(row["slug"])
        url = _eligible_url(row)
        start = row.get("startDate")
        edition = row["slug"].rsplit("-", 1)[-1]
        if not url:
            continue
        if isinstance(start, str):
            try:
                # The signed catalogue is authoritative, but a finished
                # edition cannot consume scarce future-browser slots.
                if date.fromisoformat(start) < today:
                    continue
            except ValueError:
                continue
        elif start is None:
            if not (edition.isdigit() and len(edition) == 4
                    and int(edition) >= today.year):
                continue
        else:
            continue
        if (row.get("lat") is None or row.get("lon") is None
                or row.get("showOnMap") is not True):
            unlocated.append((row["slug"], url))
        else:
            # Geolocated festivals still announce lineup, prices, cancellations.
            located.append((row["slug"], url))
    for row in history["knownFestivals"]:
        url = _eligible_url(row)
        if not url or not isinstance(row.get("slug"), str):
            continue
        old_year = row.get("lastKnownYear")
        if type(old_year) is not int or not 2024 <= old_year <= today.year:
            continue
        next_year = max(today.year + 1, old_year + 1)
        if row["slug"] + "-" + str(next_year) not in published_slugs:
            archived.append((row["slug"], url))
    # Every two daily cycles rotate all three cohorts. Never starve
    # already-located editions of lineup/price/cancellation rechecks.
    groups = (unlocated, located, archived)
    result = []
    seen = set()
    for group, quota in zip(groups, quotas):
        for _slug, url in _rotate(group, slot, min(limit - len(result), quota)):
            if url not in seen:
                result.append(url)
                seen.add(url)
    # If a cohort is empty or duplicates another official origin, spend
    # spare capacity on the other cohorts rather than wasting a browser slot.
    for group in groups:
        if len(result) >= limit:
            break
        for _slug, url in _rotate(group, slot + 1, len(group)):
            if url not in seen:
                result.append(url)
                seen.add(url)
                if len(result) >= limit:
                    break
    return result


def prioritize_unavailable(published, history, today, slot, *,
                           event_name="", fetch=fetch_public_html, rotation_tick=None):
    """Use ordinary HTTPS probes of the Publisher's own signed batch.

    All probes run in the secretless job. Failures only prioritize ordinary
    browser navigation; they cannot authorize an unsigned URL or publication.
    Leave at least three slots for the rotating cohorts, including archives.
    """
    rotation = slot if rotation_tick is None else rotation_tick
    baseline = signed_targets(published, history, today, rotation)
    budget = MAX_RAW_PROBES if event_name == "push" else 24
    candidates = [
        url for url, _ in signed_rotation(
            published, today.isoformat(), limit=budget, tick=slot)
        if _eligible_url({"officialSite": url}) == url
    ]
    # A successful HTTP response without navigable links can be a dynamic
    # shell. Prioritize these only for explicitly incomplete signed lineups.
    # Ordinary HTTP failures retain precedence and the same slot budget.
    incomplete = {row.get("officialSite") for row in published["festivals"]
                  if isinstance(row, dict) and "bands" in row
                  and row.get("bands") is None and not row.get("lineup")}
    def probe(url):
        try:
            parsed = page(fetch(url))
            if url in incomplete and not linked_pages(url, parsed, prefer_programme=True):
                return "linkless"
            return "ok"
        except (OSError, TimeoutError, ValueError, UnicodeError, TypeError):
            return "unavailable"
    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(zip(candidates, pool.map(probe, candidates)))
    failures = [url for url, state in outcomes if state == "unavailable"]
    linkless = [url for url, state in outcomes if state == "linkless"]
    # Stable daily rotation through unavailable sites; do not repeatedly
    # select the first five when more than five require browser recovery.
    # Prioritize genuinely unlocated future editions among actual failures,
    # without starving located editions' updates. Keep the same five-slot
    # failure budget, and rotate within each cohort (not a named allowlist).
    unlocated = {row.get("officialSite") for row in published["festivals"]
                 if isinstance(row, dict)
                 and (row.get("lat") is None or row.get("lon") is None)}
    missing_geo = [(url, url) for url in failures if url in unlocated]
    other = [(url, url) for url in failures if url not in unlocated]
    geo_quota = min(len(missing_geo), MAX_FAILURE_SLOTS - min(2, len(other)))
    selected = [url for _, url in _rotate(missing_geo, rotation, geo_quota)]
    selected += [url for _, url in _rotate(
        other, rotation, MAX_FAILURE_SLOTS - len(selected))]
    selected += [url for _, url in _rotate(
        [(url, url) for url in linkless], rotation, MAX_FAILURE_SLOTS - len(selected))]
    if not selected:
        return baseline, len(candidates), len(failures)
    # Reserve one rotating root from each cohort before filling spare
    # capacity. In particular, a full unlocated cohort must not displace
    # the archive root merely because baseline was completed with fallbacks.
    reserved = signed_targets(published, history, today, rotation, limit=3,
                              quotas=(1, 1, 1))
    for url in reserved + baseline:
        if len(selected) >= MAX_ENTRIES:
            break
        if url not in selected:
            selected.append(url)
    return selected, len(candidates), len(failures)


def collect(urls, renderer=rendered_html, *, diagnostics=None):
    """Visit signed roots, then at most two safely discovered official links."""
    result, seen = [], set()
    if diagnostics is None:
        diagnostics = []
    for url in urls:
        if url in seen:
            continue
        if not _eligible_url({"officialSite": url}):
            raise ValueError("Unsafe signed browser target")
        try:
            html = renderer(url)
            if (not isinstance(html, str)
                    or not 0 < len(html.encode("utf-8")) <= MAX_BYTES):
                diagnostics.append({"url": url, "status": "invalid_bounded_dom"})
                continue
            result.append({"officialSite": url, "sha256": sha256(
                html.encode("utf-8")).hexdigest(), "html": html})
            seen.add(url)
            diagnostics.append({"url": url, "status": "root_rendered",
                                "bytes": len(html.encode("utf-8"))})
            # A link is only a bounded research target discovered in CURRENT
            # same-host rendered HTML; it cannot grant publication authority.
            links = linked_pages(url, page(html, rendered=True), prefer_programme=True)[:MAX_LINKS_PER_SITE]
            for index, link in enumerate(links, 1):
                # Never disclose an untrusted discovered URL in diagnostics.
                detail = {"url": url, "link_slot": index,
                          "role": "programme" if re.search(
                              r"/(?:lineup|line-up|programmation|programme|program|artists|artistes)/?$",
                              link, re.I) else "other"}
                if link in seen:
                    diagnostics.append(dict(detail, status="link_already_seen"))
                    continue
                if safe_public_url(link) is None:
                    diagnostics.append(dict(detail, status="unsafe_destination"))
                    continue
                seen.add(link)
                try:
                    linked = renderer(link)
                    if (not isinstance(linked, str)
                            or not 0 < len(linked.encode("utf-8")) <= MAX_BYTES):
                        diagnostics.append(dict(detail, status="invalid_bounded_dom"))
                        continue
                    result.append({"officialSite": link, "sha256": sha256(
                        linked.encode("utf-8")).hexdigest(), "html": linked})
                    diagnostics.append(dict(detail, status="link_rendered",
                                            bytes=len(linked.encode("utf-8"))))
                except Exception as exc:
                    reason = exc.reason if isinstance(exc, BrowserEvidenceError) else (
                        "network_error" if isinstance(exc, OSError) else
                        "invalid_evidence" if isinstance(exc, ValueError) else "browser_error")
                    diagnostics.append(dict(detail, status=reason))
                    continue
        except Exception as exc:
            # Log only the already signed URL and fixed error categories, not
            # exception text, response HTML, redirected URLs or credentials.
            reason = exc.reason if isinstance(exc, BrowserEvidenceError) else (
                "network_error" if isinstance(exc, OSError) else
                "invalid_evidence" if isinstance(exc, ValueError) else "browser_error")
            diagnostics.append({"url": url, "status": reason})
            continue
    return {"schema": SCHEMA, "entries": result}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--published", type=Path, required=True)
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    now = datetime.now(ZoneInfo("Europe/Paris"))
    published = json.loads(args.published.read_text(encoding="utf-8"))
    history = json.loads(args.history.read_text(encoding="utf-8"))
    slot = now.date().toordinal() * 2 + (now.hour >= 15)
    # Repeated pushes/retries in the same half-day must not select the
    # same scarce browser slots. Keep the raw batch anchored to its date.
    run_number = os.environ.get("GITHUB_RUN_NUMBER", "")
    rotation = int(run_number) if re.fullmatch(r"[0-9]{1,10}", run_number) else slot
    targets, raw_probed, raw_unavailable = prioritize_unavailable(
        published, history, now.date(), slot,
        event_name=os.environ.get("GITHUB_EVENT_NAME", ""), rotation_tick=rotation)
    print("SIGNED_BROWSER_RAW_PROBES:", raw_probed)
    print("SIGNED_BROWSER_RAW_UNAVAILABLE:", raw_unavailable)
    diagnostics = []
    report = collect(targets, diagnostics=diagnostics)
    print("SIGNED_BROWSER_ROTATION:", rotation)
    print("SIGNED_BROWSER_DIAGNOSTICS:", json.dumps(diagnostics, ensure_ascii=True))
    report["date"] = now.date().isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False) + "\n", encoding="utf-8")
    print("SIGNED_BROWSER_TARGETS:", len(targets))
    roots = sum(entry["officialSite"] in targets for entry in report["entries"])
    print("SIGNED_BROWSER_ROOT_SUCCESSES:", roots)
    print("SIGNED_BROWSER_ROOT_UNAVAILABLE:", len(targets) - roots)
    print("SIGNED_BROWSER_LINK_SUCCESSES:", len(report["entries"]) - roots)
    print("SIGNED_BROWSER_SUCCESSES:", len(report["entries"]))


if __name__ == "__main__":
    main()
