"""Read-only JS-rendered organizer proof diagnostic. Not a publication gate.

Only a code-reviewed historical officialSite is navigated. Browser requests
are constrained to that HTTPS host and output has *no* dates, URLs, HTML,
credentials, candidate fields or coordinates. A positive result is a hint,
never independent publisher revalidation or automatic publication.
"""
import argparse
from datetime import date
import json
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from datetime import datetime

from grossesondes_archived_html_intake import organizer_homepage, candidate
from grossesondes_stage import official_text
from grossesondes_structured_edition import pinned_parent_identity

SCHEMA = "grossesondes.official-browser-preflight.v1"


def trusted_parent(history, slug):
    if (not isinstance(history, dict)
            or history.get("schema") != 2
            or not isinstance(history.get("knownFestivals"), list)
            or not isinstance(slug, str) or not slug):
        raise ValueError("Invalid public archive selection")
    matches = [p for p in history["knownFestivals"]
               if isinstance(p, dict) and p.get("slug") == slug]
    if len(matches) != 1:
        raise ValueError("Archive identity is not unique")
    parent = matches[0]
    identity = pinned_parent_identity(parent)
    if (identity is None or parent.get("lastKnownYear") != identity[1]
            or not organizer_homepage(parent.get("officialSite"))):
        raise ValueError("Untrusted archive origin or year")
    year = max(2027, identity[1] + 1)
    if year > 2028:
        raise ValueError("No supported future edition year")
    return parent, year


def request_allowed(url, official_site):
    """Block cross-origin resources, unsafe redirects and non-HTTPS requests."""
    if not organizer_homepage(official_site):
        return False
    try:
        source, request = urlsplit(official_site), urlsplit(url)
        return (request.scheme == "https"
                and request.hostname == source.hostname
                and request.port in (None, 443)
                and request.username is None and request.password is None
                and not request.fragment)
    except (ValueError, AttributeError):
        return False


def compare_proof(parent, year, today, raw, rendered):
    source = {"officialSite": parent["officialSite"], "year": year}
    def possible(html):
        try:
            return bool(candidate(parent, source, html, today))
        except (ValueError, TypeError, UnicodeError):
            return False
    # In particular, embedded JSON-LD alone is never reported as a visible
    # browser proof: the same original strict validator is used both times.
    raw_ok = possible(raw)
    rendered_ok = possible(rendered)
    if not raw_ok and rendered_ok:
        verdict = "RENDERED_DOM_CANDIDATE_ONLY"
    elif raw_ok and rendered_ok:
        verdict = "RAW_AND_RENDERED_CANDIDATE_ONLY"
    else:
        verdict = "NO_BROWSER_VISIBLE_PROOF"
    return {
        "schema": SCHEMA, "review_only": True,
        "safe_to_publish": False, "publication_authorized": False,
        "publisher_independent_recheck": False,
        "raw_candidate": raw_ok, "rendered_candidate": rendered_ok,
        "verdict": verdict,
    }


def rendered_html(official_site):
    """Browser is isolated: no secrets, off-origin requests or storage."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                service_workers="block", accept_downloads=False,
                java_script_enabled=True)
            context.route("**/*", lambda route: (
                route.continue_() if request_allowed(route.request.url, official_site)
                else route.abort()))
            page = context.new_page()
            page.goto(official_site, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(1600)
            if not request_allowed(page.url, official_site):
                raise ValueError("Unsafe destination")
            result = page.content()
            if not 0 < len(result) <= 1_400_000:
                raise ValueError("Invalid rendered page")
            return result
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    history = json.loads(args.archive.read_text(encoding="utf-8"))
    parent, year = trusted_parent(history, args.slug)
    today = datetime.now(ZoneInfo("Europe/Paris")).date()
    # Never persist response bodies or log exceptions from network sources.
    try:
        raw = official_text(parent["officialSite"], registered=True, raw=True)
        html = rendered_html(parent["officialSite"])
        result = compare_proof(parent, year, today, raw, html)
    except (Exception):
        result = {
            "schema": SCHEMA, "review_only": True, "safe_to_publish": False,
            "publication_authorized": False, "publisher_independent_recheck": False,
            "raw_candidate": False, "rendered_candidate": False,
            "verdict": "BROWSER_OR_HTTP_UNAVAILABLE",
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True) + "\n",
                           encoding="utf-8")
    print("OFFICIAL_BROWSER_DIAGNOSTIC:", result["verdict"])


if __name__ == "__main__":
    main()
