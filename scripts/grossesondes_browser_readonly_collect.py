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

SCHEMA = "grossesondes.browser-official-evidence.v1"
MAX_ENTRIES = 8
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
    current, archived = [], []
    published_slugs = set()
    for row in published["festivals"]:
        if not isinstance(row, dict) or not isinstance(row.get("slug"), str):
            continue
        published_slugs.add(row["slug"])
        url = _eligible_url(row)
        if (url and (row.get("lat") is None or row.get("lon") is None)
                and row.get("showOnMap") is not True
                and isinstance(row.get("startDate"), str)
                and row["startDate"][:4].isdigit()
                and int(row["startDate"][:4]) >= today.year):
            current.append((row["slug"], url))
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
    current_budget = min(limit, 5)
    result = _rotate(current, slot, current_budget)
    result += _rotate(archived, slot, limit - len(result))
    # Different historic and current entries can share one official host.
    return list(dict.fromkeys(url for _, url in result))[:limit]


def collect(urls, renderer=rendered_html):
    """Fail closed on each network attempt; never record error bodies."""
    result = []
    for url in urls:
        if not _eligible_url({"officialSite": url}):
            raise ValueError("Unsafe signed browser target")
        try:
            html = renderer(url)
            if not isinstance(html, str) or not 0 < len(html.encode("utf-8")) <= MAX_BYTES:
                continue
            result.append({"officialSite": url, "sha256": sha256(
                html.encode("utf-8")).hexdigest(), "html": html})
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
