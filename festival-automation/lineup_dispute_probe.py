"""Bounded, private review of a *known* festival lineup discrepancy.

A ticketing or association page can mention different artists without proving a
replacement. This module emits only provenance and human-review signals. It
never modifies a roster, authorizes publication or creates a public patch.
"""
from datetime import date
import json
import re

def mentions(text, artist, normalized):
    name = normalized(artist)
    return (bool(name) and re.search(
        r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])",
        text) is not None)


def probe_disputes(leads, state, today, specs, fetch, assess,
                   visible_text, clean_url, normalized, limit=2):
    """One check per source per day, maximum two requests for all disputes.

    Check ONLY editions with missing officialSite included in the already
    validated Pages/Git report. A disputed source must be an existing private
    lead, not an arbitrary remote URL. Even matching evidence is review-only.
    """
    current = date.fromisoformat(today)
    if not isinstance(leads, list) or not isinstance(specs, dict) or not 0 <= limit <= 2:
        raise ValueError("configuration de discordance invalide")
    history = state.setdefault("lineup_dispute_last_checked", {})
    if not isinstance(history, dict):
        raise ValueError("historique des discordances invalide")
    active = {row["slug"]: row for row in leads if (
        isinstance(row, dict) and isinstance(row.get("slug"), str)
        and row.get("allowed_to_publish") is False
        and row.get("official_status") == "NOT_VERIFIED")}
    result = []
    for slug, spec in sorted(specs.items()):
        if not isinstance(spec, dict) or not isinstance(slug, str):
            raise ValueError("dispute non structurée")
        if set(spec) != {"public_artist", "alternative_artist", "shared_artists", "urls"}:
            raise ValueError("champs de discordance invalides")
        old, new = spec["public_artist"], spec["alternative_artist"]
        anchors, urls = spec["shared_artists"], spec["urls"]
        if (not all(isinstance(x, str) and 2 <= len(x) <= 120 for x in (old, new))
                or not isinstance(anchors, list) or not 2 <= len(anchors) <= 6
                or any(not isinstance(x, str) or not 2 <= len(x) <= 120 for x in anchors)
                or len({normalized(x) for x in [old, new] + anchors}) != 2 + len(anchors)
                or not isinstance(urls, list) or not 1 <= len(urls) <= 2
                or len(urls) != len(set(urls))):
            raise ValueError("dossier d'artistes contradictoire invalide")
        for url in urls:
            if clean_url(url) != url:
                raise ValueError("URL de discordance non sûre")
        lead = active.get(slug)
        if not lead:
            continue
        try:
            start = date.fromisoformat(lead["start_date"])
            end = date.fromisoformat(lead.get("end_date") or lead["start_date"])
        except (ValueError, TypeError, KeyError):
            continue
        if end < current or (start - current).days > 30:
            continue
        lineup = lead.get("lineup")
        if not isinstance(lineup, list) or any(not isinstance(a, str) for a in lineup):
            continue
        published = {normalized(a) for a in lineup}
        # Stop automatically once a published roster no longer has the disputed
        # old artist, or already includes the proposed alternative.
        if (normalized(old) not in published or normalized(new) in published
                or not {normalized(a) for a in anchors}.issubset(published)):
            continue
        allowed = {clean_url(u) for u in lead.get("candidate_urls", [])
                   if isinstance(u, str)}
        if not set(urls).issubset(allowed):
            raise ValueError("source contestée absente des pistes privées")
        previous = history.setdefault(slug, {})
        if not isinstance(previous, dict):
            raise ValueError("historique d'édition contestée invalide")
        for url in urls:
            if len(result) >= limit:
                break
            if isinstance(previous.get(url), dict) and previous[url].get("observed_at") == today:
                continue
            evidence = {
                "slug": slug, "url": url, "observed_at": today,
                "public_artist": old, "alternative_artist": new,
                "signal": "INACCESSIBLE_OR_UNKNOWN", "matched_shared_artists": [],
                "publication_authorized": False,
                "artist_update_authorized": False,
            }
            try:
                html = fetch(url)
                assessed = assess(lead, url, today, html=html)
                if assessed.get("status") == "REVIEW_REQUIRED":
                    text = visible_text(html)
                    matches = [a for a in anchors if mentions(text, a, normalized)]
                    evidence["matched_shared_artists"] = matches
                    evidence["fingerprint_sha256"] = assessed.get("fingerprint_sha256")
                    if len(matches) < 2:
                        evidence["signal"] = "INSUFFICIENT_ROSTER_CONTEXT"
                    else:
                        old_found, new_found = (mentions(text, name, normalized)
                                                for name in (old, new))
                        evidence["signal"] = ("BOTH_MENTIONED" if old_found and new_found
                                              else "CATALOGUE_ONLY" if old_found
                                              else "ALTERNATIVE_ONLY" if new_found
                                              else "NEITHER_MENTIONED")
                else:
                    evidence["signal"] = "INSUFFICIENT_EDITION_MATCH"
            except (OSError, ValueError, UnicodeError):
                # A 403 / unreadable page is NOT an announcement or an
                # accidental deletion of an artist.
                pass
            previous[url] = {k: evidence[k] for k in (
                "observed_at", "signal", "fingerprint_sha256", "matched_shared_artists")
                if k in evidence}
            result.append(evidence)
    return result


def load_curated(path):
    content = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(content, dict) or len(content) > 12:
        raise ValueError("trop de dossiers de programmation contestée")
    return content
