"""Read-only JS-rendered organizer proof diagnostic. Not a publication gate.

Only a code-reviewed historical officialSite is navigated. Browser requests
are constrained to that HTTPS host and output has *no* dates, URLs, HTML,
credentials, candidate fields or coordinates. A positive result is a hint,
never independent publisher revalidation or automatic publication.
"""
import argparse
from html.parser import HTMLParser
from datetime import date
import json
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from datetime import datetime
import sys

_AUTOMATION_DIR = str(Path(__file__).resolve().parents[1] / "festival-automation")
if _AUTOMATION_DIR not in sys.path:
    sys.path.insert(0, _AUTOMATION_DIR)

from grossesondes_archived_html_intake import organizer_homepage, candidate, official_date
from grossesondes_stage import official_text
from grossesondes_structured_edition import pinned_parent_identity
from dns_pinned_https import safe_public_url, resolve_global_ips

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
            # JSON-LD by itself cannot count as a rendered *visible* DOM date.
            return (official_date(html, parent, year) is not None
                    and candidate(parent, source, html, today) is not None)
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


class BrowserEvidenceError(ValueError):
    """Fixed diagnostic categories; never include remote response data."""
    REASONS = frozenset(("unsafe_origin", "navigation_failed", "unsafe_destination",
                         "invalid_bounded_dom", "dom_input_over_limit",
                         "dom_compaction_insufficient", "http_429", "http_rejected"))

    def __init__(self, reason):
        self.reason = reason if reason in self.REASONS else "navigation_failed"
        super().__init__(self.reason)



MAX_DOM_BYTES = 1_400_000
# Processing ceiling only; the accepted evidence limit is unchanged.
MAX_COMPACTION_INPUT_BYTES = 8_000_000


class _ExecutableScriptBodies(HTMLParser):
    """Locate already-executed script payloads without reserializing HTML."""

    # Do not interpret apparent tags inside other serialized raw/RCDATA elements.
    CDATA_CONTENT_ELEMENTS = (
        "script", "style", "textarea", "title", "xmp", "iframe",
        "noembed", "noframes", "noscript", "plaintext",
    )

    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self.html = html
        self.line = 1
        self.line_offset = 0
        self.script_start = None
        self.spans = []

    def source_index(self):
        line, column = self.getpos()
        while self.line < line:
            self.line_offset = self.html.index("\n", self.line_offset) + 1
            self.line += 1
        return self.line_offset + column

    def handle_starttag(self, tag, attrs):
        if tag != "script":
            return
        types = [v for k, v in attrs if k == "type"]
        # Preserve structured data, unknown types and legacy declarations.
        executable = (not any(k == "language" for k, _ in attrs)
                      and (not types or (len(types) == 1 and
                           (types[0] or "").strip().lower() in (
                               "text/javascript", "application/javascript",
                               "module", ""))))
        self.script_start = (self.source_index() + len(self.get_starttag_text())
                             if executable else None)

    def handle_startendtag(self, tag, attrs):
        # A self-closing foreign-element script has no payload.
        pass

    def handle_endtag(self, tag):
        if tag == "script" and self.script_start is not None:
            end = self.source_index()
            if end - self.script_start >= 1024:
                self.spans.append((self.script_start, end))
            self.script_start = None


def bounded_rendered_html(html):
    """Keep original evidence unless oversized; strip only executable JS bodies."""
    if not isinstance(html, str):
        raise BrowserEvidenceError("invalid_bounded_dom")
    size = len(html.encode("utf-8"))
    if 0 < size <= MAX_DOM_BYTES:
        return html
    if size == 0:
        raise BrowserEvidenceError("invalid_bounded_dom")
    if size > MAX_COMPACTION_INPUT_BYTES:
        raise BrowserEvidenceError("dom_input_over_limit")
    parser = _ExecutableScriptBodies(html)
    try:
        parser.feed(html)
        parser.close()
    except (AssertionError, ValueError):
        raise BrowserEvidenceError("invalid_bounded_dom") from None
    # Preserve every node, attribute, stylesheet, link, JSON-LD and image.
    # Keep one whitespace character rather than creating :empty.
    pieces = []
    previous = 0
    for start, end in parser.spans:
        pieces.extend((html[previous:start], " "))
        previous = end
    pieces.append(html[previous:])
    compact = "".join(pieces)
    if not 0 < len(compact.encode("utf-8")) <= MAX_DOM_BYTES:
        raise BrowserEvidenceError("dom_compaction_insufficient")
    return compact


def wait_for_linkless_dom(page, timeout_error):
    """Give a linkless dynamic shell a bounded chance to finish rendering.

    No clicks, arbitrary navigation, network-idle waits or origin exceptions.
    Ordinary pages with an anchor retain the original timing.
    """
    anchors = page.locator("a[href]")
    if anchors.count() == 0:
        try:
            anchors.first.wait_for(state="attached", timeout=4000)
        except timeout_error:
            pass


def rendered_html(official_site):
    """Browser is isolated: no secrets, off-origin requests or storage."""
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

    # Browser DNS must resolve to the exact globally validated IP. Same-host
    # request filtering alone would allow DNS rebinding to private addresses.
    if safe_public_url(official_site) is None:
        raise BrowserEvidenceError("unsafe_origin")
    host = urlsplit(official_site).hostname
    addresses = resolve_global_ips(host)
    pinned = next((ip for ip in addresses if ":" not in ip), addresses[0])
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, chromium_sandbox=True,
            args=["--host-resolver-rules=MAP " + host + " " + pinned])

        try:
            context = browser.new_context(
                service_workers="block", accept_downloads=False,
                java_script_enabled=True)
            context.route("**/*", lambda route: (
                route.continue_() if request_allowed(route.request.url, official_site)
                else route.abort()))
            page = context.new_page()
            response = page.goto(official_site, wait_until="domcontentloaded", timeout=20000)
            if response is None:
                raise BrowserEvidenceError("navigation_failed")
            if response.status != 200:
                raise BrowserEvidenceError("http_429" if response.status == 429 else "http_rejected")
            page.wait_for_timeout(1600)
            if not request_allowed(page.url, official_site):
                raise BrowserEvidenceError("unsafe_destination")
            wait_for_linkless_dom(page, PlaywrightTimeout)
            if not request_allowed(page.url, official_site):
                raise BrowserEvidenceError("unsafe_destination")
            return bounded_rendered_html(page.content())
        finally:
            browser.close()


def probe_sources(parent, year, today, raw_fetch=official_text,
                  browser_fetch=rendered_html):
    """Attempt both transports independently, even after HTTP failure."""
    raw, rendered = "", ""
    raw_available, browser_available = False, False
    try:
        raw = raw_fetch(parent["officialSite"], registered=True, raw=True)
        raw_available = isinstance(raw, str) and bool(raw.strip())
    except Exception:
        pass
    try:
        rendered = browser_fetch(parent["officialSite"])
        browser_available = isinstance(rendered, str) and bool(rendered.strip())
    except Exception:
        pass
    result = compare_proof(parent, year, today,
                           raw if raw_available else "",
                           rendered if browser_available else "")
    result.update(raw_available=raw_available,
                  browser_available=browser_available)
    if not raw_available and not browser_available:
        result["verdict"] = "BROWSER_OR_HTTP_UNAVAILABLE"
    elif result["raw_candidate"] and not browser_available:
        result["verdict"] = "RAW_CANDIDATE_BROWSER_UNAVAILABLE"
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    history = json.loads(args.archive.read_text(encoding="utf-8"))
    parent, year = trusted_parent(history, args.slug)
    today = datetime.now(ZoneInfo("Europe/Paris")).date()
    result = probe_sources(parent, year, today)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True) + "\n",
                           encoding="utf-8")
    print("OFFICIAL_BROWSER_DIAGNOSTIC:", result["verdict"])


if __name__ == "__main__":
    main()
