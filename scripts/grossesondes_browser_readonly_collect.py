"""Read-only, secretless Chromium evidence for the *signed public* festival set.

This program runs in a separate GitHub Actions job with contents:read, a
credential-free checkout and no private intake token. The publisher treats
the resulting HTML as untrusted input and independently validates each field.
Never choose targets from a private patch, from HTML links, or from CLI URLs.
"""
from __future__ import annotations

import argparse
from datetime import datetime, date
from hashlib import sha256
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import sys

_AUTOMATION_DIR = str(Path(__file__).resolve().parents[1] / "festival-automation")
if _AUTOMATION_DIR not in sys.path:
    sys.path.insert(0, _AUTOMATION_DIR)

from dns_pinned_https import safe_public_url
from grossesondes_archived_html_intake import organizer_homepage
from grossesondes_official_browser_probe import rendered_html
from grossesondes_existing_official_updates import linked_pages, page

SCHEMA = "grossesondes.browser-official-evidence.v1"
MAX_ENTRIES = 8
MAX_LINKS_PER_SITE = 2
MAX_BYTES = 1_400_000


def _eligible_url(row):
    url = row.get("officialSite") if isinstance(row, dict) else None
    return url if safe_public_url(url) and organizer_homepage(url) else None


def _rotate(items, slot, count):
    if not items or count <= 0:
        return []
    items = sorted(items, key=lambda pair: pair[0])
    start = (slot * max(1, count)) % len(items)
    return [items[(start + i) % len(items)] for i in range(min(count, len(items)))]


def signed_targets(published, history, today, slot, limit=MAX_ENTRIES):
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
    quotas = (4, 3, 1)
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


def collect(urls, renderer=rendered_html):
    """Visit signed roots, then at most two safely discovered official links."""
    result, seen = [], set()
    for url in urls:
        if url in seen:
            continue
        if not _eligible_url({"officialSite": url}):
            raise ValueError("Unsafe signed browser target")
        try:
            html = renderer(url)
            if (not isinstance(html, str)
                    or not 0 < len(html.encode("utf-8")) <= MAX_BYTES):
                continue
            result.append({"officialSite": url, "sha256": sha256(
                html.encode("utf-8")).hexdigest(), "html": html})
            seen.add(url)
            # A link is only a bounded research target discovered in CURRENT
            # same-host rendered HTML; it cannot grant publication authority.
            links = linked_pages(url, page(html))[:MAX_LINKS_PER_SITE]
            for link in links:
                if link in seen or safe_public_url(link) is None:
                    continue
                seen.add(link)
                try:
                    linked = renderer(link)
                    if (not isinstance(linked, str)
                            or not 0 < len(linked.encode("utf-8")) <= MAX_BYTES):
                        continue
                    result.append({"officialSite": link, "sha256": sha256(
                        linked.encode("utf-8")).hexdigest(), "html": linked})
                except Exception:
                    continue
        except Exception:
            # Deliberately omit URL, exception message and page body from logs.
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
    targets = signed_targets(published, history, now.date(), slot)
    report = collect(targets)
    report["date"] = now.date().isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False) + "\n", encoding="utf-8")
    print("SIGNED_BROWSER_TARGETS:", len(targets))
    print("SIGNED_BROWSER_SUCCESSES:", len(report["entries"]))


if __name__ == "__main__":
    main()
