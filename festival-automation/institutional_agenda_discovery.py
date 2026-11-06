"""Conservative discovery from known municipal/tourism agenda *index* pages.

A trusted seed is fetched at most once per day. Links must name the exact
future edition and day/month, stay on the same institutional hostname, and
carry the edition year in their own URL. No discovered link is fetched on the
day of discovery or published/certified by this module.
"""
import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit

SCHEMA = "grossesondes.institutional-agenda-seeds.v1"
MAX_SEEDS = 24
MAX_INDEX_CHECKS = 3
MAX_NEW_PER_EDITION = 2
MAX_STATE_PER_EDITION = 4
MAX_AGE_DAYS = 14
MONTHS_FR = ("janvier", "fevrier", "mars", "avril", "mai", "juin",
             "juillet", "aout", "septembre", "octobre", "novembre", "decembre")
MONTHS_EN = ("january", "february", "march", "april", "may", "june",
             "july", "august", "september", "october", "november", "december")


def load_seeds(data, clean_url, classify):
    if (not isinstance(data, dict) or data.get("schema") != SCHEMA
            or not isinstance(data.get("seeds"), list)
            or len(data["seeds"]) > MAX_SEEDS):
        raise ValueError("configuration agendas invalides")
    out, used = [], set()
    for item in data["seeds"]:
        if not isinstance(item, dict):
            raise ValueError("entrée agenda invalide")
        slug, raw = item.get("slug"), item.get("index_url")
        if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9-]{4,120}", slug):
            raise ValueError("slug agenda invalide")
        url = clean_url(raw)
        if not url or url != raw or classify(url) != "INSTITUTION":
            raise ValueError("agenda primaire non admissible")
        if slug in used:
            raise ValueError("agenda dupliqué")
        used.add(slug)
        out.append({"slug": slug, "index_url": url})
    return out


def same_host(first, second):
    return (bool(urlsplit(first).hostname)
            and urlsplit(first).hostname == urlsplit(second).hostname)


def matching_index_links(html, index_url, lead, clean_url, normalize, anchors_class):
    """Return only unverified, edition-exact *internal* event detail links."""
    if not isinstance(html, str) or len(html) > 650_000:
        raise ValueError("index HTML invalide")
    if not isinstance(lead, dict) or lead.get("allowed_to_publish") is not False:
        return []
    try:
        day = date.fromisoformat(lead["start_date"])
    except (KeyError, TypeError, ValueError):
        return []
    if not isinstance(lead.get("name"), str):
        return []
    name = normalize(lead["name"])
    if len(name) < 7:
        return []
    # Preserve token boundaries: "Festival #6" does not match "Festival #60".
    event = re.compile(r"^" + re.escape(name) + r"(?:$| )")
    mo_fr, mo_en = MONTHS_FR[day.month-1], MONTHS_EN[day.month-1]
    day_month = re.compile(
        rf"(?<![a-z0-9])0?{day.day}\s+(?:{mo_fr}|{mo_fr[:3]}|{mo_en}|{mo_en[:3]})(?![a-z0-9])")
    parser = anchors_class()
    parser.feed(html)
    found = []
    for href, label, _prefix in parser.anchors[:500]:
        if not isinstance(href, str) or not isinstance(label, str):
            continue
        title = normalize(label)
        if not event.search(title):
            continue
        # The exact day/month must immediately follow the full edition name
        # (optionally preceded by its exact year); no neighbouring editions.
        tail = title[len(name):].strip()
        if tail.startswith(str(day.year) + " "):
            tail = tail[5:]
        if not day_month.match(tail):
            continue
        # When index labels include a year, accept only the edition's year.
        years = {int(y) for y in re.findall(r"(?<!\d)20[2-4]\d(?!\d)", title)}
        if years and years != {day.year}:
            continue
        target = clean_url(urljoin(index_url, href))
        if not target or not same_host(target, index_url) or target == index_url:
            continue
        parsed = urlsplit(target)
        if str(day.year) not in parsed.path.split("/"):
            continue
        if re.search(r"\.(?:pdf|jpg|jpeg|png|gif|webp|svg|zip)(?:$|/)", parsed.path, re.I):
            continue
        if target not in found:
            found.append(target)
        if len(found) >= MAX_NEW_PER_EDITION:
            break
    return found


def eligible_seed_rows(leads, seeds, state, today, clean_url, classify):
    """Seed host must already be present in the edition's known PRIMARY refs."""
    current = date.fromisoformat(today)
    by_slug = {lead.get("slug"): lead for lead in leads if isinstance(lead, dict)}
    checks = state.get("institutional_agenda_index_last_checked", {})
    if not isinstance(checks, dict):
        raise ValueError("historique index invalide")
    choices = []
    for seed in seeds:
        slug, origin = seed["slug"], seed["index_url"]
        lead = by_slug.get(slug)
        if (not lead or lead.get("official_status") != "NOT_VERIFIED"
                or lead.get("allowed_to_publish") is not False
                or classify(origin) != "INSTITUTION"):
            continue
        try:
            start = date.fromisoformat(lead["start_date"])
            end = date.fromisoformat(lead.get("end_date") or lead["start_date"])
        except (ValueError, TypeError, KeyError):
            continue
        if end < current or end < start or not isinstance(lead.get("candidate_urls"), list):
            continue
        # Even a curated seed must be scoped to a municipality already
        # referenced for this edition (avoid arbitrary third-party crawling).
        candidate_hosts = {urlsplit(u).hostname for u in lead["candidate_urls"]
                           if isinstance(u, str) and clean_url(u)}
        if urlsplit(origin).hostname not in candidate_hosts:
            continue
        last = checks.get(origin, "")
        if last:
            try:
                seen = date.fromisoformat(last)
            except (TypeError, ValueError):
                raise ValueError("date index corrompue")
            if seen > current:
                raise ValueError("date index future")
            if seen == current:
                continue
        choices.append((last, start.isoformat(), slug, lead, origin))
    choices.sort(key=lambda x: (bool(x[0]), x[0], x[1], x[2]))
    return [(row[3], row[4]) for row in choices[:MAX_INDEX_CHECKS]]


def accepted_index_leads(leads, state, seeds, today, clean_url, classify):
    """Reintroduce fresh discovered detail URLs for next-day PRIVATE review.

    Historical intake is untrusted; re-check original seed ownership, source
    and destination hostname, edition/year, age and volume on every use.
    """
    now = date.fromisoformat(today)
    origins = {s["slug"]: s["index_url"] for s in seeds}
    pending = state.get("institutional_agenda_candidate_pages", {})
    if not isinstance(pending, dict):
        raise ValueError("file privée index corrompue")
    output = []
    for lead in leads:
        row = dict(lead)
        existing = list(row.get("candidate_urls") or [])
        seed = origins.get(row.get("slug"))
        if (seed and row.get("official_status") == "NOT_VERIFIED"
                and row.get("allowed_to_publish") is False):
            try:
                start = date.fromisoformat(row["start_date"])
                end = date.fromisoformat(row.get("end_date") or row["start_date"])
            except (ValueError, TypeError, KeyError):
                end = None
                start = None
            if end and end >= now and classify(seed) == "INSTITUTION":
                allowed_host = any(same_host(seed, u) for u in existing
                                   if isinstance(u, str) and clean_url(u))
                if allowed_host:
                    checked = pending.get(row["slug"], [])
                    if isinstance(checked, list):
                        for item in checked[:MAX_STATE_PER_EDITION]:
                            if not isinstance(item, dict) or item.get("source") != seed:
                                continue
                            clean = clean_url(item.get("candidate_url"))
                            if (not clean or not same_host(seed, clean)
                                    or str(start.year) not in urlsplit(clean).path.split("/")
                                    or item.get("status") != "UNVERIFIED_INDEX_LINK"
                                    or item.get("publication_authorized") is not False):
                                continue
                            try:
                                first_seen = date.fromisoformat(item["lastSeen"])
                            except (ValueError, TypeError, KeyError):
                                continue
                            if not timedelta(0) <= now - first_seen <= timedelta(days=MAX_AGE_DAYS):
                                continue
                            if clean not in existing and len(existing) < 12:
                                existing.append(clean)
        row["candidate_urls"] = existing
        output.append(row)
    return output


def scan_indexes(report, state, seeds, today, fetch, clean_url, classify,
                 normalize, anchors_class, curated=None):
    """Run ≤3 index fetches and persist never-publishable page candidates."""
    if report.get("schema") != "grossesondes.source-watch-report.v1":
        raise ValueError("rapport officiel invalide")
    if report.get("date") != today:
        raise ValueError("date de rapport discordante")
    from_leads = report.get("source_reference_leads_review_only")
    if not isinstance(from_leads, list):
        raise ValueError("pistes officielles invalides")
    if curated is not None:
        # Same curated refs as used by source_qualification itself.
        from source_qualification import with_curated_leads
        from_leads = with_curated_leads(from_leads, curated)
    checks = state.setdefault("institutional_agenda_index_last_checked", {})
    pending = state.setdefault("institutional_agenda_candidate_pages", {})
    if not isinstance(checks, dict) or not isinstance(pending, dict):
        raise ValueError("état agenda invalide")
    known = {(slug, rec.get("candidate_url"))
             for slug, rows in pending.items() if isinstance(rows, list)
             for rec in rows if isinstance(rec, dict)}
    outcomes, discovered = [], []
    for lead, origin in eligible_seed_rows(from_leads, seeds, state, today,
                                            clean_url, classify):
        result = {"slug": lead["slug"], "index_url": origin, "checked_at": today,
                  "publication_authorized": False, "status": "INACCESSIBLE"}
        try:
            html = fetch(origin)
            found = matching_index_links(html, origin, lead, clean_url,
                                         normalize, anchors_class)
            result["status"] = "SCANNED"
            result["matched_links"] = len(found)
            existing = set(lead.get("candidate_urls") or [])
            records = pending.setdefault(lead["slug"], [])
            if not isinstance(records, list):
                raise ValueError("file agenda édition corrompue")
            for url in found:
                if url in existing:
                    continue
                same = next((r for r in records if r.get("candidate_url") == url), None)
                record = {"source": origin, "candidate_url": url,
                          "lastSeen": today, "status": "UNVERIFIED_INDEX_LINK",
                          "publication_authorized": False}
                if same is None:
                    records.append(record)
                else:
                    same.update(record)
                discovered.append({"slug": lead["slug"], **record,
                                   "new_this_pass": (lead["slug"], url) not in known})
        except (OSError, ValueError, UnicodeError):
            # 403/dynamic/oversized remains UNKNOWN; never an event status.
            result["status"] = "INACCESSIBLE"
        checks[origin] = today
        outcomes.append(result)
    # Prune stale/out-of-scope observations so the private branch stays small.
    valid_slugs = {lead["slug"] for lead in from_leads if isinstance(lead, dict)
                   and lead.get("official_status") == "NOT_VERIFIED"}
    today_date = date.fromisoformat(today)
    for slug in list(pending):
        rows = pending[slug]
        if slug not in valid_slugs or not isinstance(rows, list):
            pending.pop(slug, None)
            continue
        fresh = []
        for rec in rows:
            if not isinstance(rec, dict):
                continue
            try:
                age = today_date - date.fromisoformat(rec["lastSeen"])
            except (ValueError, TypeError, KeyError):
                continue
            if timedelta(0) <= age <= timedelta(days=MAX_AGE_DAYS):
                fresh.append(rec)
        pending[slug] = fresh[-MAX_STATE_PER_EDITION:]
        if not pending[slug]:
            pending.pop(slug, None)
    report["institutional_agenda_index_checks_review_only"] = outcomes
    report["institutional_agenda_discovered_review_only"] = discovered
    report["institutional_agenda_new_urls_review_only"] = sum(
        row["new_this_pass"] for row in discovered)
    report["institutional_agenda_pending_urls_review_only"] = sum(
        len(rows) for rows in pending.values())
    return discovered


def main():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from official_watch import get_page
    from source_qualification import clean_url, classify, normalized, Anchors
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=MAX_INDEX_CHECKS)
    args = parser.parse_args()
    if not 1 <= args.limit <= MAX_INDEX_CHECKS:
        parser.error("limite index 1-3 attendue")
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    statefile = args.intake / "source-watch-state.json"
    state = json.loads(statefile.read_text(encoding="utf-8"))
    if state.get("schema") != "grossesondes.source-watch.v1":
        raise ValueError("état de veille invalide")
    config = json.loads(Path(__file__).with_name("curated_agenda_indexes.json").read_text(encoding="utf-8"))
    seeds = load_seeds(config, clean_url, classify)
    curated = json.loads(Path(__file__).with_name("curated_source_leads.json").read_text(encoding="utf-8"))
    # Temporary subset limits number of institutional network requests.
    selected = eligible_seed_rows(
        __import__("source_qualification").with_curated_leads(
            report["source_reference_leads_review_only"], curated),
        seeds, state, today, clean_url, classify)[:args.limit]
    selected_keys = {(lead["slug"], url) for lead, url in selected}
    seeds = [item for item in seeds if (item["slug"], item["index_url"]) in selected_keys]
    scan_indexes(report, state, seeds, today, get_page, clean_url,
                 classify, normalized, Anchors, curated)
    statefile.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("AGENDAS_INSTITUTIONNELS:", json.dumps({
        "checked": len(report["institutional_agenda_index_checks_review_only"]),
        "new_pages": report["institutional_agenda_new_urls_review_only"],
        "pending": report["institutional_agenda_pending_urls_review_only"],
        "published": 0,
    }))


if __name__ == "__main__":
    main()
