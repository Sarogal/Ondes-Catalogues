"""Conservative festival source watcher: detection is NOT evidence of a field change.
Only writes to the private intake branch. No published JSON is modified.
"""
import argparse
from datetime import date, datetime, timedelta
from hashlib import sha256
from html.parser import HTMLParser
import ipaddress
import json
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo

from structured_evidence import inspect_official_html
from roster_candidates import roster_proposal, merge_proposals
from ticket_status_watch import inspect_ticket_status, stable_ticket_status_observation
from ticket_candidates import (ticket_proposal, merge_ticket_proposals,
                               withdraw_contradicted_ticket_proposals)
from official_ticket_links import ticket_link_leads
from official_ticket_offer_links import structured_offer_links
from ticket_provider_probe import (select_provider_checks, provider_snapshot,
                                   provider_conflict_reason)
from future_editions import edition_candidate, stable_candidate, merge_edition_candidates

PAGES = "https://sarogal.github.io/Ondes-Catalogues/grossesondes/festivals.json"
GIT = "https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/main/docs/grossesondes/festivals.json"
ORIGIN = "https://grosses-ondes.fr/data/festivals.json"
MAX_HTML = 650_000
MAX_JSON = 2_000_000


def permitted_url(url):
    if not isinstance(url, str):
        return False
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        ipaddress.ip_address(host)
        return False
    except ValueError:
        return (parsed.scheme == "https" and bool(host) and "." in host
                and not host.endswith((".local", ".internal", ".localhost", ".test"))
                and not host.startswith("localhost.") and parsed.port in (None, 443)
                and not parsed.username and not parsed.password)
    except (TypeError, AttributeError):
        return False


class SafeRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not permitted_url(newurl) or urlsplit(newurl).hostname != urlsplit(req.full_url).hostname:
            raise ValueError("redirection hors du domaine officiel")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def get_page(url, maximum=MAX_HTML):
    if not permitted_url(url):
        raise ValueError("URL non admissible")
    req = Request(url, headers={"User-Agent": "GrossesOndesOfficialMonitor/1.0",
                                "Accept": "text/html,application/xhtml+xml"})
    with build_opener(SafeRedirects()).open(req, timeout=12) as response:
        if not permitted_url(response.geturl()):
            raise ValueError("destination non admissible")
        content_type = response.headers.get_content_type()
        if content_type not in ("text/html", "application/xhtml+xml"):
            raise ValueError("contenu non HTML")
        raw = response.read(maximum + 1)
        if len(raw) > maximum:
            raise ValueError("page trop volumineuse")
        charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")


def get_json(url):
    if not permitted_url(url):
        raise ValueError("URL JSON non admissible")
    req = Request(url, headers={"User-Agent": "GrossesOndesOfficialMonitor/1.0",
                                "Accept": "application/json"})
    with build_opener(SafeRedirects()).open(req, timeout=25) as response:
        raw = response.read(MAX_JSON + 1)
        if len(raw) > MAX_JSON:
            raise ValueError("catalogue trop volumineux")
        return json.loads(raw.decode("utf-8-sig"))


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "svg", "noscript"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "svg", "noscript"):
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def fingerprint(html):
    parser = VisibleText()
    parser.feed(html)
    text = " ".join(" ".join(parser.parts).casefold().split())
    if len(text) < 100:
        raise ValueError("texte officiel insuffisant (possible page dynamique)")
    return sha256(text.encode("utf-8")).hexdigest()


def indexed(document):
    if document.get("schema") != 1 or not isinstance(document.get("festivals"), list):
        raise ValueError("schéma festivals inattendu")
    rows = document["festivals"]
    if not (90 <= len(rows) <= 3000):
        raise ValueError("volume festivals incohérent")
    ids = [r.get("slug") for r in rows]
    if any(not isinstance(s, str) or not s for s in ids) or len(ids) != len(set(ids)):
        raise ValueError("slugs invalides ou dupliqués")
    return {r["slug"]: r for r in rows}


def verify_references(pages, git, origin):
    live, committed, baseline = indexed(pages), indexed(git), indexed(origin)
    if pages != git:
        # Public-only metadata for incident diagnosis. Never relax the
        # fail-closed equality guard, and never include private intake data.
        changed = [slug for slug in sorted(set(live) & set(committed))
                   if live[slug] != committed[slug]]
        missing = sorted(set(committed) - set(live))
        extra = sorted(set(live) - set(committed))
        raise ValueError(
            "DIVERGENCE : GitHub Pages et JSON Git main différents, "
            "aucune collecte mutante ; "
            f"Pages generatedAt={pages.get('generatedAt')}, "
            f"Git generatedAt={git.get('generatedAt')}, "
            f"Pages={len(live)}, Git={len(committed)}, "
            f"champs d'édition divergents={len(changed)}, "
            f"absents={len(missing)}, nouveaux={len(extra)}, "
            f"exemples={changed[:3]}; "
            "ne pas publier avant réconciliation."
        )
    if not set(baseline).issubset(live):
        raise ValueError("édition Infomaniak initiale absente de GitHub Pages")
    return {"published": len(live), "origin": len(baseline),
            "changed_since_origin": sum(live[s] != v for s, v in baseline.items())}


def source_inventory(catalogue, today):
    """Group editions by official URL: a shared URL is never fetched twice."""
    sources = {}
    missing = []
    for row in indexed(catalogue).values():
        slug, url = row["slug"], row.get("officialSite")
        if not permitted_url(url):
            missing.append(slug)
            continue
        try:
            ahead = (date.fromisoformat(row["startDate"]) - today).days
        except (ValueError, TypeError, KeyError):
            ahead = None
        urgent = ahead is not None and -7 <= ahead <= 60
        entry = sources.setdefault(url, {"url": url, "slugs": [], "urgent": False})
        entry["slugs"].append(slug)
        entry["urgent"] = entry["urgent"] or urgent
    return sources, missing


def source_leads(catalogue, today):
    """Expose existing public references for editorial classification only.

    Neither the source field nor auditSources is sufficient to certify that a
    URL belongs to the organizer. Nothing found here is fetched as an official
    source or admitted to field-level validators.
    """
    rows = indexed(catalogue)
    _inventory, missing = source_inventory(catalogue, today)
    result = []
    for slug in missing:
        row = rows[slug]
        raw = [row.get("source")]
        if isinstance(row.get("auditSources"), list):
            raw.extend(x for x in row["auditSources"] if isinstance(x, str))
        possible = []
        for value in raw:
            if permitted_url(value) and value not in possible:
                possible.append(value)
            if len(possible) >= 12:
                break
        result.append({
            "slug": slug,
            "name": row.get("name"),
            "organizer": row.get("organizer"),
            "lineup": row.get("lineup", []),
            "start_date": row.get("startDate"),
            "end_date": row.get("endDate"),
            "candidate_urls": possible,
            "official_status": "NOT_VERIFIED",
            "allowed_to_publish": False,
        })
    return result


def cycle_pick(rows, count, tick):
    """Stable round-robin: every slot advances, even if no page changed."""
    if not rows or count <= 0:
        return []
    ordered = sorted(rows, key=lambda r: (sha256(r["url"].encode("utf-8")).hexdigest(), r["url"]))
    count = min(count, len(ordered))
    start = (tick * count) % len(ordered)
    return [ordered[(start + i) % len(ordered)] for i in range(count)]


def choose_sources(catalogue, today, phase="primary", limit=24, tick_override=None):
    """Reserve at most one third for urgent editions; rotate the remainder.

    Both daily passes have disjoint slices within each group whenever the
    source pool is large enough. The choice does not mutate source state or
    create a commit merely because the clock advanced.
    """
    if phase not in ("primary", "catchup") or not (1 <= limit <= 48):
        raise ValueError("phase ou volume de collecte invalide")
    sources, _missing = source_inventory(catalogue, today)
    if tick_override is not None and (type(tick_override) is not int or tick_override < 0):
        raise ValueError("curseur de rotation invalide")
    tick = ((today - date(2026, 11, 4)).days * 2 + (phase == "catchup")
            if tick_override is None else tick_override)
    urgent = [r for r in sources.values() if r["urgent"]]
    routine = [r for r in sources.values() if not r["urgent"]]
    near = cycle_pick(urgent, min((limit + 2) // 3, len(urgent)), tick)
    general = cycle_pick(routine, min(limit - len(near), len(routine)), tick)
    remaining = limit - len(near) - len(general)
    if remaining:
        used = {r["url"] for r in near}
        near.extend(cycle_pick([r for r in urgent if r["url"] not in used], remaining, tick))
    return [(r["slugs"][0], r["url"]) for r in near + general]

def choose_pending_rechecks(catalogue, today, phase, limit, state, tick_override=None):
    """Reserve <=1/6 of checks for yesterday's structured evidence.

    Future editions, artists, ticket categories and sensitive statuses share
    the same budget; all URLs must be registered in the published catalogue.
    The normal national rotation continues for the remaining slots.
    """
    regular=choose_sources(catalogue,today,phase,limit,tick_override=tick_override)
    records=state.get("future_edition_observations", {})
    roster_records=state.get("roster_candidate_observations", {})
    ticket_records=state.get("ticket_status_observations", {})
    if not all(isinstance(value,dict) for value in (
            records, roster_records, ticket_records)):
        raise ValueError("état des observations à recontrôler invalide")
    yesterday=(today - timedelta(days=1)).isoformat()
    official,_=source_inventory(catalogue,today)
    pending=set()
    for item in (list(records.values()) + list(roster_records.values())
                 + list(ticket_records.values())):
        if (isinstance(item,dict)
                and item.get("lastSeen")==yesterday
                and isinstance(item.get("source"),str)
                and item["source"] in official):
            pending.add(item["source"])
    if not pending:
        return regular
    tick=((today-date(2026,11,4)).days * 2 + (phase=="catchup")
          if tick_override is None else tick_override)
    slots=min(len(pending),max(1,limit//6))
    urgent=[official[url] for url in sorted(pending)]
    priority=cycle_pick(urgent,slots,tick)
    selected=[(row["slugs"][0],row["url"]) for row in priority]
    used={url for _slug,url in selected}
    selected.extend((slug,url) for slug,url in regular if url not in used)
    return selected[:limit]


def resumable_rotation_tick(state, today, phase):
    """Resume the NEXT unvisited source slice after delayed or missed cron runs.

    This private-state cursor moves only after at least one source was actually
    scanned. No historical dates are replayed and no publication gate changes.
    """
    tick = state.get("rotation_next_tick")
    if tick is None:
        tick = (today - date(2026, 11, 4)).days * 2 + (phase == "catchup")
    if type(tick) is not int or tick < 0:
        raise ValueError("curseur de rotation des sources invalide")
    return tick


def stable_roster_observation(state, slug, url, observations, today):
    """Require the SAME artist evidence on two consecutive calendar days.

    Source-page text fingerprints alone cannot establish this: embedded
    JSON-LD can change while visible HTML stays identical. Persist a separate
    digest of the bounded, exact edition/performer clues. This is a private
    recheck hint, never an authorization to publish.
    """
    records=state.setdefault("roster_candidate_observations", {})
    if not isinstance(records,dict):
        raise ValueError("état des programmations à recontrôler invalide")
    if not isinstance(observations,list) or len(observations)!=1:
        records.pop(slug,None)
        return False
    obs=observations[0]
    hints=obs.get("hints")
    if (obs.get("slug")!=slug or obs.get("source_url")!=url
            or obs.get("publication_authorized") is not False
            or not isinstance(hints,dict)
            or not set(hints) <= {"new_performers", "place_name_unverified"}
            or not isinstance(hints.get("new_performers"),list)
            or not 1 <= len(hints["new_performers"]) <= 12):
        records.pop(slug,None)
        return False
    proof={key:obs.get(key) for key in (
        "slug","source_url","name_on_source","startDate_source","endDate_source")}
    proof["artists"]=hints["new_performers"]
    digest=sha256(json.dumps(proof,sort_keys=True,ensure_ascii=False).encode("utf-8")).hexdigest()
    previous=records.get(slug,{})
    yesterday=(date.fromisoformat(today)-timedelta(days=1)).isoformat()
    stable=(isinstance(previous,dict) and previous.get("source")==url
            and previous.get("digest")==digest
            and previous.get("lastSeen")==yesterday)
    records[slug]={"source":url,"digest":digest,
                   "firstSeen":previous.get("firstSeen") if stable else today,
                   "lastSeen":today}
    return stable


def analyze(state, slug, url, digest, today):
    previous = state["sources"].get(url)
    if previous and previous["sha256"] == digest:
        return "unchanged", None
    state["sources"][url] = {"sha256": digest, "slug": slug,
                              "firstSeen": previous["firstSeen"] if previous else today,
                              "lastChanged": today}
    if previous is None:
        return "baseline", None
    return "changed", {"slug": slug, "issue":
        "Contenu du site officiel modifié ; aucune date, programmation, annulation ou tarif déduit automatiquement.",
        "sources": [url], "observed_at": today, "fingerprint_sha256": digest}


def merge_deferred(patch, findings, today):
    if patch.get("schema") != "grossesondes.patch.v1" or patch.get("safe_to_publish") is not False:
        raise ValueError("patch privé incompatible")
    for field in ("additions", "updates", "history_additions", "history_updates", "deferred"):
        if not isinstance(patch.get(field), list):
            raise ValueError("patch privé incomplet : " + field)
    fingerprints = {(p.get("slug"), p.get("fingerprint_sha256"), p.get("evidence_kind"))
                    for p in patch["deferred"]}
    count = 0
    for finding in findings:
        key = (finding["slug"], finding["fingerprint_sha256"], finding.get("evidence_kind"))
        if key not in fingerprints:
            patch["deferred"].append(finding)
            fingerprints.add(key)
            count += 1
    if count:
        patch["generated_at"] = today
    return count


def latest_patch(folder, today):
    patches = []
    for file in folder.glob("patch-????-??-??.json"):
        try:
            day = date.fromisoformat(file.stem[6:])
            if day <= date.fromisoformat(today):
                patches.append((day, file))
        except ValueError:
            continue
    if not patches:
        raise ValueError("aucun patch privé historique à préserver")
    day, file = max(patches)
    patch = json.loads(file.read_text(encoding="utf-8"))
    if patch.get("generated_at") != day.isoformat():
        raise ValueError("date du patch privé discordante")
    return patch


def run(folder, today, phase="primary", limit=24, download_json=get_json, download_page=get_page, download_vendor=None):
    folder = Path(folder)
    pages, git, origin = (download_json(u) for u in (PAGES, GIT, ORIGIN))
    reference = verify_references(pages, git, origin)
    inventory, without_source = source_inventory(pages, date.fromisoformat(today))
    leads = source_leads(pages, date.fromisoformat(today))
    statefile = folder / "source-watch-state.json"
    state = json.loads(statefile.read_text(encoding="utf-8")) if statefile.exists() else {"schema": "grossesondes.source-watch.v1", "sources": {}}
    if state.get("schema") != "grossesondes.source-watch.v1" or not isinstance(state.get("sources"), dict):
        raise ValueError("état de veille non reconnu")
    rotation_tick = resumable_rotation_tick(state, date.fromisoformat(today), phase)
    vendor_history = state.setdefault("ticket_provider_last_checked", {})
    if not isinstance(vendor_history, dict):
        raise ValueError("historique des vérifications prestataires invalide")
    report = {"schema": "grossesondes.source-watch-report.v1", "date": today,
              "phase": phase, "rotationTick": rotation_tick,
              "references": reference, "scanned": [], "changed": [],
              "baselines": [], "unavailable": [], "structured_candidates": [],
              "candidate_updates": [], "candidateUpdateCount": 0,
               "candidate_editions": [], "candidateEditionCount": 0, "deferredAdded": 0,
              "ticket_status_observed": [], "ticket_status_review": [],
              "ticketStatusReviewCount": 0,
              "ticketProposals": [], "ticketProposalCount": 0,
              "ticket_link_leads_review_only": [],
              "ticket_provider_checks_review_only": [],
              "ticket_provider_first_checks_review_only": 0,
              "ticket_provider_conflicts_review_only": [],
              "ticketProposalWithdrawnCount": 0,
              "publishedChanges": 0,
              "coverage": {"catalogue_editions": len(pages["festivals"]),
                           "official_sources": len(inventory),
                           "urgent_sources": sum(x["urgent"] for x in inventory.values()),
                           "editions_without_official_https": len(without_source),
                           "sources_seen": len(set(inventory) & set(state["sources"])),
                           "missing_with_reference_leads": sum(bool(x["candidate_urls"]) for x in leads)},
              "editions_without_official_https": without_source,
              "source_reference_leads_review_only": leads}
    findings = []
    proposed_updates = []
    proposed_editions = []
    proposed_tickets = []
    original = indexed(origin)
    live = indexed(pages)
    for slug, url in choose_pending_rechecks(
            pages, date.fromisoformat(today), phase, limit, state,
            tick_override=rotation_tick):
        try:
            html = download_page(url)
            digest = fingerprint(html)
            previous_state = state["sources"].get(url)
            outcome, finding = analyze(state, slug, url, digest, today)
            report["scanned"].append({"slug": slug, "url": url, "state": outcome})
            if outcome == "baseline":
                report["baselines"].append(slug)
            if finding:
                findings.append(finding)
                report["changed"].append({"slug": slug, "url": url})
            # Each JSON-LD hint is tied to an edition already in the last
            # published catalogue. Never use it to modify data automatically.
            clues_by_slug = {}
            # A provider link on the registered page is a review lead only.
            # It is never fetched as proof or promoted to ticketAvailability.
            ticket_links = ticket_link_leads(html, url, permitted_url)
            for related_slug in inventory[url]["slugs"]:
                # Event-linked JSON-LD offers take priority over generic
                # anchors. Both are private leads, never publication proof.
                exact_offers = structured_offer_links(
                    html, url, live[related_slug], permitted_url)
                candidates = exact_offers + ticket_links
                used_ticket_urls = set()
                for lead in candidates:
                    if lead["ticket_url"] in used_ticket_urls:
                        continue
                    used_ticket_urls.add(lead["ticket_url"])
                    report["ticket_link_leads_review_only"].append({
                        "slug": related_slug, "source_url": url, **lead,
                    })
                observed = inspect_ticket_status(
                    html, live[related_slug], url, today)
                digest_ticket = stable_ticket_status_observation(
                    state, related_slug, url, observed, today)
                if observed:
                    report["ticket_status_observed"].extend(observed)
                if digest_ticket:
                    record = observed[0]
                    report["ticket_status_review"].append(record)
                    report["ticketStatusReviewCount"] += 1
                    proposed = ticket_proposal(
                        original.get(related_slug), live[related_slug], record, today)
                    if proposed:
                        proposed_tickets.append(proposed)
                        report["ticketProposals"].append({
                            "slug": related_slug,
                            "categories": len(proposed["changes"][0]["after"]["categories"]),
                            "proofMode": proposed["proofMode"],
                            "publication_authorized": False,
                        })
                    findings.append({
                        "slug": related_slug,
                        "issue": "Billetterie ou statut JSON-LD observé deux jours : "
                                 "revue indépendante obligatoire, aucune publication.",
                        "sources": [url], "observed_at": today,
                        "fingerprint_sha256": digest_ticket,
                        "evidence_kind": "schema.org-ticket-status-two-day",
                        "structured_evidence": observed,
                        "safe_to_publish": False,
                    })
                hints = inspect_official_html(html, live[related_slug], url, today)
                if hints:
                    clues_by_slug[related_slug] = hints
                    report["structured_candidates"].extend(hints)
            possible_editions = {}
            for related_slug, hints in clues_by_slug.items():
                for observation in hints:
                    candidate = edition_candidate(
                        live[related_slug], original.get(related_slug),
                        observation, live, today)
                    if candidate:
                        possible_editions.setdefault(candidate["slug"], []).append(candidate)
                roster_stable = stable_roster_observation(
                    state, related_slug, url, hints, today)
                proposal = roster_proposal(
                    original.get(related_slug), live[related_slug], hints,
                    previous_state, digest, today) if roster_stable else None
                if proposal:
                    proposed_updates.append(proposal)
                    report["candidate_updates"].append({
                        "slug": related_slug,
                        "added_artists": proposal["changes"][0]["after"][
                            len(proposal["changes"][0]["before"]):],
                        "proofMode": proposal["proofMode"],
                        "publication_authorized": False,
                    })
                findings.append({
                    "slug": related_slug,
                    "issue": "Indice schema.org du site officiel : validation indépendante du champ requise.",
                    "sources": [url], "observed_at": today,
                    "fingerprint_sha256": digest, "evidence_kind": "schema.org",
                    "structured_evidence": hints, "safe_to_publish": False,
                })
            # Conflicting JSON-LD events for one proposed edition cannot
            # become a two-day certificate, even if one entry looks plausible.
            for new_slug, candidates in possible_editions.items():
                if len(candidates) != 1:
                    state.setdefault("future_edition_observations", {}).pop(new_slug, None)
                    continue
                if stable_candidate(state, candidates[0], today):
                    proposed_editions.append(candidates[0])
                    report["candidate_editions"].append({
                        "slug": new_slug, "basedOn": candidates[0]["originSlug"],
                        "proofMode": candidates[0]["proofMode"],
                        "publication_authorized": False,
                    })
        except (OSError, ValueError, UnicodeError) as error:
            report["unavailable"].append({"slug": slug, "url": url,
                                          "reason": (type(error).__name__ + ": " + str(error))[:180]})
    # Read-only provider diagnostics: an organizer link is not a ticket proof.
    # Expired editions are omitted from live probes, but archived link leads
    # remain in the report for historical research.
    vendor_fetch = download_vendor if download_vendor is not None else download_page
    conflicting_slugs = set()
    for lead, edition in select_provider_checks(
            report["ticket_link_leads_review_only"], live, today, limit=3,
            last_checked=vendor_history):
        prior = vendor_history.get(lead["slug"])
        # Backwards-compatible migration from the existing single-URL state.
        # The per-URL history only schedules checks, never constitutes proof.
        attempted_urls = dict(prior.get("urls", {})) if (
            isinstance(prior, dict) and isinstance(prior.get("urls"), dict)
        ) else {}
        if isinstance(prior, dict) and isinstance(prior.get("ticket_url"), str):
            if isinstance(prior.get("lastChecked"), str):
                attempted_urls.setdefault(prior["ticket_url"], prior["lastChecked"])
        first_check = lead["ticket_url"] not in attempted_urls
        if first_check:
            report["ticket_provider_first_checks_review_only"] += 1
        snapshot = {"result": "INACCESSIBLE", "categories_review_only": []}
        try:
            html = vendor_fetch(lead["ticket_url"])
            snapshot = provider_snapshot(html, edition)
        except (OSError, ValueError, UnicodeError):
            # HTTP 403, dynamic pages and oversized documents are unknown,
            # never interpreted as a sold-out or sold-in state.
            pass
        report["ticket_provider_checks_review_only"].append({
            "slug": lead["slug"], "source_url": lead["source_url"],
            "ticket_url": lead["ticket_url"], "provider": lead["provider"],
            "observed_at": today, "publication_authorized": False,
            **snapshot,
        })
        # An unsuccessful attempt counts for rotation but never for proof.
        # Persist only sanitized URLs supplied by the registered organizer.
        attempted_urls[lead["ticket_url"]] = today
        # Cap private state growth; do not persist query strings or arbitrary
        # new links (all keys originate from sanitizer-checked vendor leads).
        recent = sorted(
            ((url, day) for url, day in attempted_urls.items()
             if isinstance(url, str) and url.startswith("https://")
             and isinstance(day, str)),
            key=lambda item: (item[1], item[0] == lead["ticket_url"]),
            reverse=True,
        )[:12]
        vendor_history[lead["slug"]] = {
            "ticket_url": lead["ticket_url"], "lastChecked": today,
            "urls": dict(recent),
        }
        official_observation = next((
            observation for observation in report["ticket_status_observed"]
            if observation.get("slug") == lead["slug"]
            and observation.get("source") == lead["source_url"]
        ), None)
        conflict = provider_conflict_reason(snapshot, official_observation)
        if conflict:
            conflicting_slugs.add(lead["slug"])
            report["ticket_provider_conflicts_review_only"].append({
                "slug": lead["slug"], "provider": lead["provider"],
                "reason": conflict, "observed_at": today,
                "publication_authorized": False,
            })
    if conflicting_slugs:
        # A provider conflict is a veto, never an alternative stock source.
        proposed_tickets = [proposal for proposal in proposed_tickets
                            if proposal["slug"] not in conflicting_slugs]
        report["ticketProposals"] = [
            proposal for proposal in report["ticketProposals"]
            if proposal["slug"] not in conflicting_slugs
        ]
    report["coverage"]["sources_seen"] = len(set(inventory) & set(state["sources"]))
    # Persist proposals only after checking the immutable Infomaniak source.
    # An old private proposal is never overwritten by the automated intake.
    if findings or proposed_updates or proposed_editions or proposed_tickets or conflicting_slugs:
        patch = latest_patch(folder, today)
        if conflicting_slugs:
            report["ticketProposalWithdrawnCount"] = withdraw_contradicted_ticket_proposals(
                patch, conflicting_slugs)
        report["deferredAdded"] = merge_deferred(patch, findings, today)
        if proposed_updates:
            report["candidateUpdateCount"] = merge_proposals(
                patch, proposed_updates, origin, today)
        if proposed_editions:
            report["candidateEditionCount"] = merge_edition_candidates(
                patch, proposed_editions, origin, today)
        if proposed_tickets:
            report["ticketProposalCount"] = merge_ticket_proposals(
                patch, proposed_tickets, origin, today)
        if (report["deferredAdded"] or report["candidateUpdateCount"]
                or report["candidateEditionCount"] or report["ticketProposalCount"]
                or report["ticketProposalWithdrawnCount"]):
            (folder / f"patch-{today}.json").write_text(
                json.dumps(patch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if report["scanned"]:
        # Cron missing? The next successful pass resumes the reserved slice.
        # Never advance the cursor if all official sources were unreachable.
        state["rotation_next_tick"] = rotation_tick + 1
    old_state = json.loads(statefile.read_text(encoding="utf-8")) if statefile.exists() else None
    if state != old_state:
        statefile.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intake", required=True, type=Path)
    parser.add_argument("--phase", choices=("primary", "catchup"), default="primary")
    parser.add_argument("--limit", type=int, default=24)
    args = parser.parse_args()
    if not (1 <= args.limit <= 48):
        parser.error("limit doit être entre 1 et 48")
    today = datetime.now(ZoneInfo("Europe/Paris")).date().isoformat()
    report = run(args.intake, today, args.phase, args.limit)
    out = Path("/tmp/grossesondes-official-watch")
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v if not isinstance(v, list) else len(v) for k, v in report.items()}, ensure_ascii=False))
    for item in report["unavailable"]:
        print("SOURCE_INDISPONIBLE:", json.dumps(item, ensure_ascii=False))
    for item in report["ticket_provider_checks_review_only"]:
        print("BILLETTERIE_A_REVOIR:", json.dumps({
            "slug": item["slug"], "provider": item["provider"],
            "result": item["result"], "categories": len(item["categories_review_only"]),
            "publication_authorized": False,
        }, ensure_ascii=False))
    print("COUVERTURE_SOURCES:", json.dumps(report["coverage"], ensure_ascii=False))


if __name__ == "__main__":
    main()
