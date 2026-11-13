#!/usr/bin/env python3
"""Read-only browser smoke test for the public P'tites Ondes outings map.

No private repository access, GitHub write token, or publication permission.
The browser report distinguishes delivered JSON, JS ingestion, search results,
and WebGL tile rendering (which may be limited on a headless runner).
"""
import json
import os
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright

SITE = "https://ptitesondes.fr/sorties.html"
PAGES = "https://sarogal.github.io/Ondes-Catalogues/ptitesondes/sorties.json"
OUT = Path(os.environ.get("PTITESONDES_SMOKE_OUTPUT", "/tmp/ptitesondes-site-smoke"))
EXPECTED = [
    "openagenda-813941-2027-01-13",
    "openagenda-813941-2027-01-20",
    "openagenda-813941-2027-01-27",
    "openagenda-813941-2027-02-03",
    "openagenda-813941-2027-02-10",
]


def fetch_public_json():
    request = Request(PAGES, headers={"User-Agent": "ptitesondes-site-smoke/1.0"})
    with urlopen(request, timeout=35) as response:
        if response.status != 200:
            raise RuntimeError("Pages responded HTTP " + str(response.status))
        document = json.load(response)
    if document.get("version") != 3 or not isinstance(document.get("events"), list):
        raise ValueError("Unexpected Pages schema")
    events = document["events"]
    if len(events) < 527:
        raise AssertionError("Public catalogue unexpectedly shrank below 527")
    by_id = {event.get("id"): event for event in events}
    missing = [key for key in EXPECTED if key not in by_id]
    if missing:
        raise AssertionError("Accoord UID 813941 entries absent from Pages: " + ", ".join(missing))
    for key in EXPECTED:
        if by_id[key].get("title") != "Contes & comptines":
            raise AssertionError("Unexpected Accoord title: " + key)
    return document


def map_snapshot(page):
    return page.evaluate(
        """() => {
          const node = document.querySelector('#outings-map');
          const canvas = node && node.querySelector('canvas.maplibregl-canvas');
          const shape = item => {
            if (!item) return null;
            const rect = item.getBoundingClientRect();
            const css = getComputedStyle(item);
            return {width: Math.round(rect.width), height: Math.round(rect.height),
              display: css.display, visibility: css.visibility};
          };
          const fallback = [...document.querySelectorAll('main p')].find(
            e => e.textContent.includes('La carte n’a pas pu être chargée'));
          return {
            mapContainer: shape(node),
            mapLibreClass: !!(node && node.classList.contains('maplibregl-map')),
            canvas: shape(canvas),
            mapErrorTextVisible: !!(fallback && fallback.getClientRects().length &&
              getComputedStyle(fallback).visibility !== 'hidden'),
            scripts: [...document.querySelectorAll('script[src]')].map(x => x.src),
            stylesheets: [...document.querySelectorAll('link[rel="stylesheet"]')].map(x => x.href)
          };
        }"""
    )


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {
        "schema": "ptitesondes.site_browser_smoke.v1",
        "site": SITE,
        "pages": PAGES,
        "expected_accoord_count": len(EXPECTED),
        "read_only": True,
    }
    browser = None
    failure = None
    try:
        source = fetch_public_json()
        report["pages_count"] = len(source["events"])
        report["pages_updated_at"] = source.get("updated_at")
        report["pages_accoord_ids"] = EXPECTED
        report["pages_accepted"] = True

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--enable-webgl", "--use-gl=angle", "--use-angle=swiftshader"],
            )
            page = browser.new_page(
                viewport={"width": 1440, "height": 1000},
                locale="fr-FR",
                timezone_id="Europe/Paris",
                device_scale_factor=1,
            )
            errors = []
            failed_requests = []
            map_http_errors = []
            page.on("pageerror", lambda error: errors.append(str(error)[:500]))
            page.on(
                "requestfailed",
                lambda req: failed_requests.append(
                    {"url": req.url[:250], "failure": str(req.failure)[:200]}
                ) if len(failed_requests) < 30 else None,
            )
            page.on(
                "response",
                lambda resp: map_http_errors.append(
                    {"url": resp.url[:250], "status": resp.status}
                ) if resp.status >= 400 and re.search(
                    r"maplibre|tile|openfreemap|style\.json|openmap", resp.url, re.I
                ) and len(map_http_errors) < 30 else None,
            )

            response = page.goto(SITE, wait_until="domcontentloaded", timeout=60000)
            report["site_http_status"] = response.status if response else None
            if not response or response.status != 200:
                raise AssertionError("Outings HTML is not served as HTTP 200")
            page.wait_for_function(
                "() => window.PtitesOndesSortiesStatus && window.PtitesOndesSortiesStatus.source",
                timeout=45000,
            )
            status = page.evaluate("() => ({...window.PtitesOndesSortiesStatus})")
            report["frontend_data_status"] = status
            if status.get("source") != "github-pages":
                raise AssertionError("Frontend did not load the verified Pages source")
            if status.get("events") != len(source["events"]):
                raise AssertionError("Frontend event count differs from Pages JSON")
            if status.get("updated_at") != source.get("updated_at"):
                raise AssertionError("Frontend timestamp differs from Pages JSON")

            page.locator("#outings-count").wait_for(timeout=20000)
            page.wait_for_timeout(900)
            report["frontend_counter"] = page.locator("#outings-count").inner_text()
            report["frontend_map"] = map_snapshot(page)
            if report["frontend_map"]["mapContainer"] is None:
                raise AssertionError("Missing #outings-map container")

            search = page.get_by_label("Ville, département ou mot-clé")
            if search.count() == 0:
                search = page.locator("input[type='search'], input[type='text']").first()
            if search.count() == 0:
                raise AssertionError("Outings search control not found")

            search.fill("Bourderies")
            page.wait_for_timeout(1200)
            search_count = page.get_by_text("Contes & comptines", exact=True).count()
            report["bourderies_title_matches"] = search_count
            report["bourderies_page_count"] = page.locator("#outings-count").inner_text()
            if search_count == 0:
                search.fill("comptines")
                page.wait_for_timeout(1200)
                search_count = page.get_by_text("Contes & comptines", exact=True).count()
                report["comptines_title_matches"] = search_count
                report["comptines_page_count"] = page.locator("#outings-count").inner_text()

            report["title_visible_after_search"] = search_count > 0
            page.screenshot(path=str(OUT / "site-search.png"), full_page=False)

            # A list match is not proof that the geographic marker is shown.
            # Preserve a distinct screenshot while the Accoord filter is active.
            page.locator("#outings-map").scroll_into_view_if_needed(timeout=12000)
            page.wait_for_timeout(2200)
            report["filtered_map"] = map_snapshot(page)
            report["filtered_visible_counters"] = page.evaluate(
                """() => [...document.querySelectorAll('strong, span, p, div')]
                  .filter(x => !x.children.length).map(x => x.textContent.trim())
                  .filter(x => /^\\d+ sorties? visibles?$/i.test(x)).slice(0, 6)"""
            )
            page.screenshot(
                path=str(OUT / "site-bourderies-map.png"), full_page=False
            )
            search.fill("")
            page.wait_for_timeout(700)
            page.locator("#outings-map").scroll_into_view_if_needed(timeout=12000)
            page.wait_for_timeout(1800)
            report["map_after_scroll"] = map_snapshot(page)
            page.screenshot(path=str(OUT / "site-map.png"), full_page=False)
            report["browser_page_errors"] = errors
            report["browser_failed_requests"] = failed_requests
            report["browser_map_http_errors"] = map_http_errors
            report["map_diagnostic_only"] = (
                "Canvas presence is not proof of successful tile rendering; "
                "a headless WebGL/CDN failure does not establish a universal outage."
            )

            if not report["title_visible_after_search"]:
                raise AssertionError(
                    "No Accoord title rendered by the search UI, despite 5 valid Pages entries"
                )
    except Exception as error:
        failure = type(error).__name__ + ": " + str(error)
        report["failure"] = failure
    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        (OUT / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
    if failure:
        print("Echec du test navigateur (aucune publication effectuée).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
