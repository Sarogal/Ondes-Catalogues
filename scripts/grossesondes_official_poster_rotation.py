"""Isolated read-only rotation of previously published festival poster candidates."""
from __future__ import annotations
import argparse
from datetime import date, datetime, timezone
import json
from hashlib import sha256
import re
from urllib.parse import urlsplit
from pathlib import Path
import sys
from time import monotonic

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "festival-automation"))
from dns_pinned_https import fetch_public_html, OfficialHTTPStatusError
from grossesondes_existing_official_updates import (
    signed_rotation, current_official_poster_candidates, page, home_matches_edition, linked_pages,
)
from grossesondes_official_html_edition import visible_official_edition, fold
from grossesondes_official_poster_ocr import (
    read_official_poster, poster_review_claims, load_ocr_cache, save_ocr_cache,
    qualified_url, MIN_REVIEW_CONFIDENCE, poster_known_artist_candidates,
    structured_poster_candidates,
)

MAX_HOSTS = 8
MAX_IMAGES = 2
MAX_BROWSER_HOSTS = 2
MAX_LINKED_POSTER_PAGES = 2
MAX_RUN_SECONDS = 180
MAX_DOM_BYTES = 1_400_000
DOM_SCHEMA = 'grossesondes.poster-rendered-review.v1'


def scheduled_poster_tick(now):
    # Two scheduled cycles per UTC day, not six. The scheduled morning
    # and evening runs advance by exactly one slot, whatever the batch count.
    return int(now.timestamp() // 43200)


def capture_rendered_evidence(catalogue, today, tick, limit, *, fetch=fetch_public_html, renderer):
    """Only signed rotation roots, public DOM only; never read private state."""
    if type(limit) is not int or not 1 <= limit <= MAX_HOSTS:
        raise ValueError('Invalid poster host budget')
    entries = []
    attempted = 0
    deadline = monotonic() + MAX_RUN_SECONDS
    for site, rows in signed_rotation(catalogue, today, limit, tick, alternate_order=True):
        if attempted >= MAX_BROWSER_HOSTS or monotonic() >= deadline:
            break
        active = [r for r in rows if not r.get('cancelled')
                  and r.get('status') not in ('Annulé', 'Reporté')]
        if not active:
            continue
        try:
            raw = fetch(site)
            page(raw)
            if any(current_official_poster_candidates(raw, site, r) for r in active):
                continue
        except (OSError, ValueError, TypeError, UnicodeError, KeyError):
            # Including HTTP 429: do not retry through Chromium.
            continue
        attempted += 1
        try:
            html = renderer(site)
            if not isinstance(html, str):
                continue
            body = html.encode('utf-8')
            if not 0 < len(body) <= MAX_DOM_BYTES:
                continue
            entries.append({'site': site, 'html': html, 'sha256': sha256(body).hexdigest()})
        except Exception:
            continue
    return {'schema': DOM_SCHEMA, 'date': today, 'tick': tick, 'entries': entries}


def validated_rendered_evidence(path, catalogue, today, tick, limit):
    """Treat transported DOM as untrusted review input, never as approval."""
    try:
        if path.stat().st_size > MAX_DOM_BYTES * MAX_BROWSER_HOSTS * 6 + 4096:
            return {}
        data = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(data, dict) or data.get('schema') != DOM_SCHEMA
                or data.get('date') != today or type(data.get('tick')) is not int
                or data['tick'] != tick or not isinstance(data.get('entries'), list)
                or len(data['entries']) > MAX_BROWSER_HOSTS):
            return {}
        sites = {site for site, _ in signed_rotation(catalogue, today, limit, tick, alternate_order=True)}
        result = {}
        for entry in data['entries']:
            if not isinstance(entry, dict) or not isinstance(entry.get('site'), str):
                return {}
            site, html = entry['site'], entry.get('html')
            if site not in sites or site in result or not isinstance(html, str):
                return {}
            body = html.encode('utf-8')
            if (not 0 < len(body) <= MAX_DOM_BYTES
                    or sha256(body).hexdigest() != entry.get('sha256')):
                return {}
            result[site] = html
        return result
    except (OSError, ValueError, TypeError, UnicodeError, KeyError):
        return {}


def contextual_poster_match(site, url, row, page_date_match, reading, result):
    """Review-only association: exact visible edition + named first-party image.

    The URL is a freshly discovered visible candidate, not a user-supplied
    proof or a standalone source. Never emit fields from this association.
    """
    if (not page_date_match or not qualified_url(site, url)
            or result.get("status") != "edition_identity_or_dates_unproven"):
        return False
    diagnostic = result.get("diagnostics", {})
    if (diagnostic.get("year_matches") is not True
            or diagnostic.get("contradictory_dates") is not False
            or diagnostic.get("cancellation_detected") is not False):
        return False
    year = date.fromisoformat(row["startDate"]).year
    name = re.sub(r"\b20[2-4]\d\b", "", fold(row["name"]))
    brand = [w for w in re.findall(r"[a-z0-9]+", name)
             if w not in ("festival", "fest")]
    filename = fold(urlsplit(url).path.rsplit("/", 1)[-1])
    tokens = set(re.findall(r"[a-z0-9]+", filename))
    years = set(re.findall(r"(?<!\d)20[2-4]\d(?!\d)", filename))
    if (len("".join(brand)) < 3 or not set(brand).issubset(tokens)
            or years != {str(year)}):
        return False
    return any(w["confidence"] >= MIN_REVIEW_CONFIDENCE
               and re.search(r"(?<!\d)" + str(year) + r"(?!\d)", w["text"])
               for w in reading.get("words", []))


def scan(catalogue, today, *, tick=None, limit=MAX_HOSTS, cache=None,
         fetch=fetch_public_html, reader=read_official_poster, slug=None,
         browser_fetch=None, browser_sites=None):
    """Use only URLs from the public catalogue and their freshly read DOM.

    No new URLs supplied by CLI, no edits, no publication authority.
    The poster may itself carry the edition proof missing from visible HTML.
    All outputs remain review-only, even when text recognition is strong.
    """
    if type(limit) is not int or not 1 <= limit <= MAX_HOSTS:
        raise ValueError("Invalid poster host budget")
    if cache is None:
        cache = {}
    public_rows = catalogue.get("festivals", []) if isinstance(catalogue, dict) else catalogue
    artist_names = {name for entry in public_rows if isinstance(entry, dict)
                    for name in (entry.get("lineup") if isinstance(entry.get("lineup"), list) else [])
                    if isinstance(name, str)}
    selected = signed_rotation(catalogue, today, limit, tick, alternate_order=True)
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
              "budget_exhausted": False, "browser_hosts": 0,
              "contextual_edition_matches": 0, "known_artist_hint_count": 0,
              "structured_artist_count": 0, "structured_pass_count": 0, "rows": []}
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
        rendered = None
        browser_status = "not_needed"
        active = [r for r in rows if not r.get("cancelled")
                  and r.get("status") not in ("Annulé", "Reporté")]
        if (active and browser_fetch is not None
                and not any(current_official_poster_candidates(html, site, row)
                            for row in active)
                and (browser_sites is None or site in browser_sites)
                and report["browser_hosts"] < MAX_BROWSER_HOSTS
                and monotonic() < deadline):
            report["browser_hosts"] += 1
            try:
                rendered = browser_fetch(site)
                if not isinstance(rendered, str) or not 0 < len(rendered) <= 1_400_000:
                    raise ValueError("Invalid rendered DOM")
                browser_status = "rendered"
            except Exception:
                # Browser exceptions may contain remote text; never log it.
                rendered = None
                browser_status = "unavailable"
        count = 0
        limited = False
        linked_surfaces = []
        linked_attempted = False
        for row in rows:
            if row.get("cancelled") or row.get("status") in ("Annulé", "Reporté"):
                continue
            candidates = current_official_poster_candidates(html, site, row)
            raw_count = len(candidates)
            if not candidates and rendered is not None:
                candidates = current_official_poster_candidates(rendered, site, row)
            rendered_count = len(candidates) if not raw_count else 0
            linked_count = 0
            # Only traverse a bounded set of real official anchors. Share
            # their fetch budget across all editions of the same host.
            if not candidates and not limited and count < MAX_IMAGES:
                if not linked_attempted:
                    linked_attempted = True
                    links = linked_pages(site, parsed)
                    if rendered is not None:
                        links += linked_pages(site, page(rendered))
                    for link in list(dict.fromkeys(links))[:MAX_LINKED_POSTER_PAGES]:
                        if monotonic() >= deadline:
                            break
                        try:
                            content = fetch(link)
                            if isinstance(content, str) and 0 < len(content) <= 650_000:
                                linked_surfaces.append((link, content))
                        except OfficialHTTPStatusError as exc:
                            # No fallback requests after an explicit 429.
                            if getattr(exc, "status", None) == 429 or getattr(exc, "code", None) == 429:
                                limited = True
                                break
                        except (OSError, ValueError, TypeError, UnicodeError, KeyError):
                            continue
                if not limited:
                    for link, content in linked_surfaces:
                        candidates.extend(current_official_poster_candidates(content, link, row))
                    candidates = list(dict.fromkeys(candidates))[:MAX_IMAGES]
                    linked_count = len(candidates)
            try:
                start, end = date.fromisoformat(row["startDate"]), date.fromisoformat(row["endDate"])
                page_date_match = any(visible_official_edition(source, row["name"], start, end)
                                      for source in (html, rendered, *(content for _, content in linked_surfaces)) if source)
            except (ValueError, TypeError, KeyError):
                page_date_match = False
            diagnostic = {"slug": row["slug"], "status": "no_candidate",
                          "exact_visible_page_dates": page_date_match,
                          "raw_html_chars": len(html),
                          "raw_candidates": raw_count,
                          "browser_status": browser_status,
                          "rendered_html_chars": len(rendered) if rendered else 0,
                          "rendered_candidates": rendered_count,
                          "linked_candidates": linked_count,
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
                contextual = contextual_poster_match(site, url, row, page_date_match, reading, result)
                report["contextual_edition_matches"] += int(contextual)
                hints = poster_known_artist_candidates(reading, artist_names) if matched or contextual else []
                report["known_artist_hint_count"] += len(hints)
                typed = structured_poster_candidates(row, reading)
                report["structured_artist_count"] += len(typed["artists"])
                report["structured_pass_count"] += len(typed["passes"])
                # No recognized text, image bytes, or URL in public logs.
                diagnostic["images"].append({
                    "status": reading.get("status"),
                    "qualification": result["status"],
                    "contextual_edition_match": contextual,
                    "known_artist_hint_count": len(hints),
                    "structured_artist_count": len(typed["artists"]),
                    "structured_pass_count": len(typed["passes"]),
                    "qualification_diagnostics": result.get("diagnostics", {}),
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
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--capture-rendered-evidence", type=Path)
    parser.add_argument("--rendered-evidence", type=Path)
    args = parser.parse_args()
    if args.catalogue.stat().st_size > 10_000_000:
        raise ValueError("Catalogue exceeds budget")
    catalogue = json.loads(args.catalogue.read_text(encoding="utf-8"))
    today = date.today().isoformat()
    tick = args.tick if args.tick is not None else scheduled_poster_tick(datetime.now(timezone.utc))
    cache = load_ocr_cache(args.private_cache) if args.private_cache else {}
    if args.capture_rendered_evidence and (not args.browser or args.private_cache
            or args.rendered_evidence or args.slug):
        parser.error("DOM capture is public-only, without private cache or slug")
    if args.rendered_evidence and (args.browser or args.slug):
        parser.error("Transported DOM is separate from browser execution")
    browser_fetch = None
    if args.browser:
        from grossesondes_official_browser_probe import rendered_html
        browser_fetch = rendered_html
    if args.capture_rendered_evidence:
        evidence = capture_rendered_evidence(catalogue, today, tick, args.limit,
                                             renderer=browser_fetch)
        args.capture_rendered_evidence.parent.mkdir(parents=True, exist_ok=True)
        args.capture_rendered_evidence.write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf-8")
        print("Public rendered roots:", len(evidence["entries"]))
        return
    browser_sites = None
    if args.rendered_evidence:
        evidence = validated_rendered_evidence(args.rendered_evidence, catalogue,
                                              today, tick, args.limit)
        browser_sites = set(evidence)
        if evidence:
            browser_fetch = lambda site: evidence[site]
    report = scan(catalogue, today, tick=tick, limit=args.limit, slug=args.slug,
                  cache=cache, browser_fetch=browser_fetch, browser_sites=browser_sites)
    if args.private_cache:
        save_ocr_cache(args.private_cache, cache)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
