"""Festival->Concerts private research handoff for genuine touring concert stops.

A festival looking name must not erase a tour date. Recheck a FIXED approved
institutional index -> exact event-detail link, extract an explicit SINGLE
future day and visible tour claim, and preserve the lead in a bounded PRIVATE
inbox. No festival patch, concert publication, geographic data or artist ID is
created. The Concerts engine independently rechecks every lead before intake.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

SCRIPTS = str(Path(__file__).resolve().parents[1] / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

from national_detail_qualification import _eligible_sources
from national_live_index_recheck import live_index_for_exact_link
from official_watch import get_page
from festival_event_kind import touring_concert_stop
from institutional_event_card import exact_event_card_day
from source_qualification import visible_text, normalized
from grossesondes_archived_html_intake import official_date, atomic_json
from grossesondes_institutional_edition import trusted_source

SCHEMA = "grossesondes.festival-to-concerts-private.v1"
MAX_CHECKS = 2
MAX_LEADS = 120
STATE_SCHEMA = "grossesondes.source-watch.v1"
INBOX_NAME = "concert-tour-referrals.json"


def _trusted_spec(source, today):
    if not isinstance(source, dict):
        return None
    spec = trusted_source(
        source.get("index_url"), source.get("index_page"),
        source.get("url"), source.get("title"), today)
    if spec is None or spec != {
        key: source.get(key) for key in
        ("index_url", "index_page", "url", "title", "year")
    }:
        return None
    return spec



def live_tour_card(source, today, fetch):
    """Reprove the exact link+dated card, including nested li > article.

    The broad institutional festival publisher deliberately rejects nested
    semantic cards because their context can be ambiguous. For CONCERTS
    research only, a single event's card with its OWN exact h2, linked HTTPS
    detail and unambiguous printed day is stronger and independently
    checkable. Never let this relaxed card parser authorize a festival patch.
    """
    if _trusted_spec(source, today) is None:
        return None
    # A previously reviewed, canonical index_page may point directly to
    # page=4 today. No requested URL from an external or private candidate is
    # fetched without first passing the committed trusted_source contract.
    cached = {}
    try:
        direct = fetch(source["index_page"])
        cached[source["index_page"]] = direct
        if exact_event_card_day(direct, source) is not None:
            return direct
    except (OSError, ValueError, TypeError, UnicodeError, KeyError):
        pass
    # Preserve the original source-wide exact visible-link reproof as a
    # fallback for plain anchors or municipal sites without dated cards.
    # Do not download the same private-safe index page twice per candidate.
    def read(url):
        if url in cached:
            return cached[url]
        return fetch(url)
    return live_index_for_exact_link(source, read)


def _tour_day(html, source, today, index_html=None):
    """Only precise current date from article OR an exact linked index card."""
    year = source["year"]
    name = re.sub(r"\s+20[2-4][0-9]$", "", source["title"])
    try:
        dates = official_date(html, {"name": name}, year)
        if dates is None and index_html is not None:
            # The official Limoges agenda prints e.g. "12 Fév 2027" on its
            # linked card, but omits that day in the long event description.
            # Keep this as CONCERT RESEARCH only and recheck both URLs again
            # in Concerts; never treat the card as festival-publisher proof.
            card_day = exact_event_card_day(index_html, source)
            if (card_day is not None
                    and normalized(source["title"]) in visible_text(html)):
                dates = (card_day, card_day)
        if dates is None:
            return None
        first, last = dates
        if (first != last or first < date.fromisoformat(today)
                or not touring_concert_stop(html, first, last)):
            return None
        return first.isoformat()
    except (TypeError, ValueError, UnicodeError):
        return None


def discover(state, queue, today, fetch=get_page, limit=MAX_CHECKS):
    """Only indices resolved from reviewed public registry may be contacted."""
    today_date = date.fromisoformat(today)
    if (not isinstance(state, dict) or state.get("schema") != STATE_SCHEMA
            or type(limit) is not int or not 0 <= limit <= MAX_CHECKS):
        raise ValueError("Invalid trusted festival scan state")
    sources = _eligible_sources(state, queue, today, due_only=False)
    eligible = []
    for row in sources:
        spec = _trusted_spec(row, today)
        if spec is not None:
            eligible.append((row["dossier_id"], spec))
    # Stable rotation; no private referral can control network destinations.
    if eligible and limit:
        offset = (today_date.toordinal() * MAX_CHECKS) % len(eligible)
        selected = [eligible[(offset + i) % len(eligible)]
                    for i in range(min(limit, len(eligible)))]
    else:
        selected = []
    results = []
    for dossier_id, source in selected:
        try:
            index_html = live_tour_card(source, today, fetch)
            if index_html is None:
                continue
            html = fetch(source["url"])
            day = _tour_day(html, source, today, index_html=index_html)
            if day is None:
                continue
            key = sha256(json.dumps({
                "index": source["index_url"], "detail": source["url"],
                "title": source["title"], "day": day
            }, sort_keys=True).encode("utf-8")).hexdigest()[:24]
            results.append({
                "referralId": "festival-tour-" + key,
                "dossierId": dossier_id, "title": source["title"],
                "dateHint": day,
                "indexUrl": source["index_url"],
                "indexPage": source["index_page"],
                "detailUrl": source["url"],
                "classification": "EXPLICIT_TOURING_CONCERT_STOP",
                "reviewRequired": True, "publicationAllowed": False,
                "eventVerifiedByConcerts": False,
            })
        except (OSError, ValueError, TypeError, UnicodeError, KeyError):
            continue
    return results


def merge_inbox(previous, observations, today):
    """Preserve unmatched leads; a missing source today is NOT deletion."""
    now = date.fromisoformat(today)
    if previous is None:
        previous = {"schema": SCHEMA, "referrals": []}
    if (not isinstance(previous, dict) or previous.get("schema") != SCHEMA
            or not isinstance(previous.get("referrals"), list)
            or len(previous["referrals"]) > MAX_LEADS):
        raise ValueError("Invalid confidential concert handoff inbox")
    by_id = {}
    for row in previous["referrals"]:
        if (not isinstance(row, dict)
                or not isinstance(row.get("referralId"), str)
                or row["referralId"] in by_id
                or row.get("publicationAllowed") is not False
                or row.get("eventVerifiedByConcerts") is not False):
            raise ValueError("Unsafe handoff history")
        by_id[row["referralId"]] = dict(row)
    for row in observations:
        if (not isinstance(row, dict)
                or row.get("classification") != "EXPLICIT_TOURING_CONCERT_STOP"
                or row.get("reviewRequired") is not True
                or row.get("publicationAllowed") is not False
                or row.get("eventVerifiedByConcerts") is not False):
            raise ValueError("Untrusted tour observation")
        existing = by_id.get(row["referralId"])
        by_id[row["referralId"]] = {
            **row,
            "firstSeen": existing["firstSeen"] if existing else today,
            "lastSeen": today,
        }
    # Keep up to MAX_LEADS recent and future items; never discard due to a
    # failed fetch or index pagination change on another day.
    active = []
    for row in by_id.values():
        try:
            first = date.fromisoformat(row["firstSeen"])
            last = date.fromisoformat(row["lastSeen"])
            event = date.fromisoformat(row["dateHint"])
        except (ValueError, TypeError, KeyError):
            continue
        if (first <= last <= now and
                now-last <= timedelta(days=45) and
                event >= now-timedelta(days=1)):
            active.append(row)
    active.sort(key=lambda x: (x["lastSeen"], x["referralId"]), reverse=True)
    return {
        "schema": SCHEMA, "as_of": today, "review_only": True,
        "publication_authorized": False,
        "referrals": sorted(active[:MAX_LEADS], key=lambda x: x["referralId"]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--intake", required=True, type=Path)
    ap.add_argument("--limit", type=int, default=MAX_CHECKS)
    args = ap.parse_args()
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    folder = args.intake
    state = json.loads((folder / "source-watch-state.json").read_text(
        encoding="utf-8"))
    queue = json.loads((folder / "national-festival-discovery-review.json").read_text(
        encoding="utf-8"))
    inbox_path = folder / INBOX_NAME
    previous = (json.loads(inbox_path.read_text(encoding="utf-8"))
                if inbox_path.exists() else None)
    seen = discover(state, queue, today, limit=args.limit)
    updated = merge_inbox(previous, seen, today)
    atomic_json(inbox_path, updated)
    print("Touring-concert leads delivered to private inbox=" +
          str(len(updated["referrals"])) + ", fresh=" + str(len(seen)) +
          ", festival_publications=0, concert_approvals=0")


if __name__ == "__main__":
    main()
