"""Isolated read-only rotation of previously published festival poster candidates."""
from __future__ import annotations
import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "festival-automation"))
from dns_pinned_https import fetch_public_html, OfficialHTTPStatusError
from grossesondes_existing_official_updates import (
    signed_rotation, current_official_poster_candidates, page, home_matches_edition,
)
from grossesondes_official_poster_ocr import (
    read_official_poster, poster_review_claims, load_ocr_cache, save_ocr_cache,
)

MAX_HOSTS = 8
MAX_IMAGES = 2
MAX_RUN_SECONDS = 180


def scan(catalogue, today, *, tick=None, limit=MAX_HOSTS, cache=None,
         fetch=fetch_public_html, reader=read_official_poster, slug=None):
    """Use only URLs from the public catalogue and their freshly read DOM.

    No new URLs supplied by CLI, no edits, no publication authority.
    The poster may itself carry the edition proof missing from visible HTML.
    All outputs remain review-only, even when text recognition is strong.
    """
    if type(limit) is not int or not 1 <= limit <= MAX_HOSTS:
        raise ValueError("Invalid poster host budget")
    if cache is None:
        cache = {}
    selected = signed_rotation(catalogue, today, limit, tick)
    if slug is not None:
        # Manual diagnostic selects an existing catalogue slug, not a URL.
        selected = [(site, [r for r in rows if r.get("slug") == slug])
                    for site, rows in signed_rotation(catalogue, today, 60, 0)]
        selected = [(site, rows) for site, rows in selected if rows]
        # A catalogue can have more than sixty distinct hosts.
        if not selected:
            for i in range(1, 20):
                selected = [(site, [r for r in rows if r.get("slug") == slug])
                            for site, rows in signed_rotation(catalogue, today, 60, i)]
                selected = [(site, rows) for site, rows in selected if rows]
                if selected:
                    break
    report = {"review_only": True, "publication_authorized": False,
              "checked_hosts": 0, "images_read": 0, "edition_matches": 0,
              "budget_exhausted": False, "rows": []}
    deadline = monotonic() + MAX_RUN_SECONDS
    for site, rows in selected:
        if monotonic() >= deadline:
            report["budget_exhausted"] = True
            break
        report["checked_hosts"] += 1
        try:
            html = fetch(site)
            parsed = page(html)
        except (OSError, ValueError, TypeError, UnicodeError, KeyError):
            report["rows"].append({"slug": rows[0]["slug"], "status": "html_unavailable"})
            continue
        count = 0
        limited = False
        for row in rows:
            if row.get("cancelled") or row.get("status") in ("Annulé", "Reporté"):
                continue
            candidates = current_official_poster_candidates(html, site, row)
            diagnostic = {"slug": row["slug"], "status": "no_candidate",
                          "html_edition_match": home_matches_edition(parsed, row, today),
                          "candidates": len(candidates), "images": []}
            report["rows"].append(diagnostic)
            for url in candidates:
                if limited or count >= MAX_IMAGES or monotonic() >= deadline:
                    break
                count += 1
                report["images_read"] += 1
                reading = reader(site, url, cache=cache)
                result = poster_review_claims(row, reading)
                matched = result["status"] == "edition_matches_review_only"
                report["edition_matches"] += int(matched)
                # No recognized text, image bytes, or URL in public logs.
                diagnostic["images"].append({
                    "status": reading.get("status"),
                    "qualification": result["status"],
                    "claim_types": sorted(result["claims"]),
                    "sha256": reading.get("sha256"),
                    "cache_hit": reading.get("cache_hit", False)})
                diagnostic["status"] = "reviewed"
                if reading.get("status") == "rate_limited":
                    limited = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--slug")
    parser.add_argument("--tick", type=int)
    parser.add_argument("--limit", type=int, default=MAX_HOSTS)
    parser.add_argument("--private-cache", type=Path)
    args = parser.parse_args()
    if args.catalogue.stat().st_size > 10_000_000:
        raise ValueError("Catalogue exceeds budget")
    catalogue = json.loads(args.catalogue.read_text(encoding="utf-8"))
    today = date.today().isoformat()
    tick = args.tick if args.tick is not None else int(datetime.now(timezone.utc).timestamp() // 14400)
    cache = load_ocr_cache(args.private_cache) if args.private_cache else {}
    report = scan(catalogue, today, tick=tick, limit=args.limit, slug=args.slug, cache=cache)
    if args.private_cache:
        save_ocr_cache(args.private_cache, cache)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
