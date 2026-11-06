"""Cross-source organizer-domain dossier, strictly private and read-only.

Historical link observations are *third-party attributions*, never evidence
that an organizer controls the target. A second reference gives an editor a
better research trail, not permission to publish an officialSite.
"""
from datetime import date
import re
from urllib.parse import urlsplit


SOURCE_ROLES = {"INSTITUTION", "VENUE"}
TARGET_ROLES = {"UNKNOWN", "ORGANIZER_CANDIDATE"}
MAX_AGE_DAYS = 21


def _source_family(host):
    """Conservative source grouping: subdivisions of one host are not independent."""
    host = (host or "").lower().removeprefix("www.")
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2:] == ["gouv", "fr"]:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _same_domain(first, second):
    return first == second or first.endswith("." + second) or second.endswith("." + first)


def organizer_domain_dossiers(leads, history, today, clean_url, classify):
    """Group recent, matching venue/institution *links* by edition + target host.

    Uses only already-vetted source observations from this edition's bounded
    candidate list. Does NOT visit targets, mutate state, approve domains, or
    include inactive editions. A source family counts once even after multiple
    visits or via several subdomains.
    """
    current = date.fromisoformat(today)
    if not isinstance(leads, list) or not isinstance(history, dict):
        raise ValueError("état des liens organisateurs invalide")
    dossiers = []
    for lead in leads:
        if (not isinstance(lead, dict)
                or lead.get("official_status") != "NOT_VERIFIED"
                or lead.get("allowed_to_publish") is not False):
            continue
        slug = lead.get("slug")
        if not isinstance(slug, str) or not slug:
            continue
        try:
            end = date.fromisoformat(lead.get("end_date") or lead.get("start_date"))
        except (ValueError, TypeError):
            continue
        if end < current:
            continue
        urls = lead.get("candidate_urls")
        if not isinstance(urls, list):
            continue
        allowed = {clean_url(url) for url in urls[:12]}
        allowed.discard(None)
        observations = history.get(slug, {})
        if not isinstance(observations, dict):
            raise ValueError("historique de liens organisateurs corrompu")
        targets = {}
        for source_url, record in observations.items():
            if not isinstance(source_url, str) or not isinstance(record, dict):
                continue
            source = clean_url(source_url)
            role = record.get("role")
            if (source not in allowed or role not in SOURCE_ROLES
                    or classify(source) != role
                    or record.get("status") != "REVIEW_REQUIRED"):
                continue
            digest = record.get("fingerprint_sha256")
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                continue
            try:
                seen = date.fromisoformat(record.get("lastChecked"))
            except (ValueError, TypeError):
                continue
            if not 0 <= (current - seen).days <= MAX_AGE_DAYS:
                continue
            links = []
            for field, format_name in (
                ("organizer_links_review_only", "VISIBLE_ANCHOR"),
                ("structured_organizer_links_review_only", "SCHEMA_ORG"),
            ):
                values = record.get(field, [])
                if isinstance(values, list):
                    links.extend((value, format_name) for value in values[:4])
            if not links:
                continue
            source_host = urlsplit(source).hostname
            family = _source_family(source_host)
            for raw, format_name in links:
                target = clean_url(raw)
                if not target or classify(target) not in TARGET_ROLES:
                    continue
                host = urlsplit(target).hostname
                if _same_domain(host, source_host):
                    continue
                by_host = targets.setdefault(host, {"urls": set(), "sources": {}})
                by_host["urls"].add(target)
                evidence = {"source_url": source, "source_role": role,
                            "observed_at": seen.isoformat(),
                            "fingerprint_sha256": digest,
                            "evidence_formats": [format_name]}
                prior = by_host["sources"].get(family)
                if (prior is not None and
                        prior["source_url"] == source and
                        prior["observed_at"] == evidence["observed_at"] and
                        prior["fingerprint_sha256"] == digest):
                    # The same page may express the same link as both an
                    # HTML anchor and JSON-LD: still just one source family.
                    evidence["evidence_formats"] = sorted(set(
                        prior.get("evidence_formats", []) + [format_name]))
                if prior is None or (evidence["observed_at"], evidence["source_url"]) >= (
                        prior["observed_at"], prior["source_url"]):
                    by_host["sources"][family] = evidence
        for host, bundle in sorted(targets.items()):
            sources = sorted(bundle["sources"].values(), key=lambda x: (
                x["source_role"], x["source_url"]))
            dossiers.append({
                "slug": slug,
                "candidate_domain": host,
                "candidate_urls": sorted(bundle["urls"])[:4],
                "source_count": len(sources),
                "source_families": sorted(bundle["sources"]),
                "references": sources[:4],
                "evidence_formats": sorted({
                    fmt for ref in sources for fmt in ref["evidence_formats"]}),
                "corroboration_level": ("MULTI_SOURCE_LINK_ONLY" if len(sources) >= 2
                                         else "SINGLE_SOURCE_LINK_ONLY"),
                "ownership_proven": False,
                "official_site_authorized": False,
                "publication_authorized": False,
                "link_only": True,
            })
    return sorted(dossiers, key=lambda d: (
        d["corroboration_level"] != "MULTI_SOURCE_LINK_ONLY",
        d["slug"], d["candidate_domain"]))
