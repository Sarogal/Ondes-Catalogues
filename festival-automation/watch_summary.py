"""Human-readable, honest GitHub Actions summary of a PRIVATE festival watch.

A successful workflow does not imply that a catalogue change was discovered or
published. This module never uses network access and never writes festival data.
"""
import argparse
from datetime import date
import json
from pathlib import Path
import re


def safe_text(value):
    return re.sub(r"[^\w ./:()=-]", "_", str(value).replace("\n", " "))[:160]


def render(report):
    if report.get("schema") != "grossesondes.source-watch-report.v1":
        raise ValueError("rapport de veille non reconnu")
    scanned = report.get("scanned")
    unavailable = report.get("unavailable")
    if not isinstance(scanned, list) or not isinstance(unavailable, list):
        raise ValueError("rapport de veille incomplet")
    coverage = report.get("coverage") or {}
    updates = report.get("candidateUpdateCount", 0)
    editions = report.get("candidateEditionCount", 0)
    deferred = report.get("deferredAdded", 0)
    tickets = report.get("ticketStatusReviewCount", 0)
    ticket_proposals = report.get("ticketProposalCount", 0)
    vendor_checks = report.get("ticket_provider_checks_review_only", [])
    conflicts = report.get("ticket_provider_conflicts_review_only", [])
    withdrawn = report.get("ticketProposalWithdrawnCount", 0)
    first_checks = report.get("ticket_provider_first_checks_review_only", 0)
    if not isinstance(vendor_checks, list) or any(
            not isinstance(row, dict)
            or row.get("publication_authorized") is not False
            or row.get("result") not in (
                "INACCESSIBLE", "UNVERIFIED", "CONFLICT",
                "MATCHED_NO_STOCK", "EXPLICIT_CATEGORY_HINTS", "SENSITIVE_REVIEW")
            for row in vendor_checks):
        raise ValueError("rapport de prestataires invalide")
    if not isinstance(conflicts, list) or any(
            not isinstance(row, dict)
            or row.get("publication_authorized") is not False
            or row.get("reason") not in (
                "VENDOR_SENSITIVE_REVIEW", "VENDOR_STRUCTURED_CONFLICT",
                "CATEGORY_DISAGREEMENT")
            for row in conflicts):
        raise ValueError("contradictions prestataires invalides")
    if any(type(value) is not int or value < 0 for value in (
            updates, editions, deferred, tickets, ticket_proposals, withdrawn, first_checks)):
        raise ValueError("compteurs de propositions invalides")
    lineup_checks = report.get("lineup_dispute_checks_review_only", [])
    if not isinstance(lineup_checks, list) or any(
            not isinstance(x, dict)
            or x.get("publication_authorized") is not False
            or x.get("artist_update_authorized") is not False
            or x.get("signal") not in (
                "ALTERNATIVE_ONLY", "CATALOGUE_ONLY", "BOTH_MENTIONED",
                "NEITHER_MENTIONED", "INSUFFICIENT_EDITION_MATCH",
                "INSUFFICIENT_ROSTER_CONTEXT", "INACCESSIBLE_OR_UNKNOWN")
            for x in lineup_checks):
        raise ValueError("discordances de programmation non fiables")
    attempted = len(scanned) + len(unavailable)
    lines = [
        "### Grosses Ondes — Veille officielle Festivals",
        "",
        f"- Date de vérification : {safe_text(report.get('date', '?'))}",
        f"- Éditions au catalogue : {coverage.get('catalogue_editions', '?')}",
        f"- Sites officiels distincts : {coverage.get('official_sources', '?')}",
        f"- Éditions sans source officielle HTTPS : {coverage.get('editions_without_official_https', '?')}",
        f"- Sources tentées : {attempted} ; pages exploitables : {len(scanned)} ; indisponibles : {len(unavailable)}",
        f"- Nouvelles propositions de programmation : **{updates}**",
        f"- Nouvelles propositions d'édition : **{editions}**",
        f"- Propositions privées de catégories de billets : **{ticket_proposals}**",
        f"- Propositions de billets retirées après contradiction : **{withdrawn}**",
        f"- Contradictions prestataires en revue privée : **{len(conflicts)}**",
        f"- Liens de billetteries repérés, à qualifier (archives incluses) : **{len(report.get('ticket_link_leads_review_only', []))}**",
        f"- Pages de prestataires examinées pour éditions en cours/à venir : **{len(vendor_checks)}** (aucune autorisation de publication)",
        f"- Nouvelles éditions ou nouveaux liens prestataires essayés : **{first_checks}** (rotation privée, même en cas d’accès refusé)",
        f"- Billetteries/statuts : **{tickets}** signaux revus sur deux jours "
        "(catégories uniquement ; aucune preuve de festival complet)",
        f"- Contrôles privés de programmations contradictoires : **{len(lineup_checks)}** (aucun remplacement autorisé)",
        f"- Nouvelles URL de festivals découvertes ce passage : **{report.get('festival_source_discovery_new_urls_review_only', 0)}** ; en attente de revue privée : **{report.get('festival_source_discovery_pending_urls_review_only', 0)}** (aucune visite automatique ni certification)",
        f"- Nouveaux signalements différés : {deferred}",
        "- Modifications de la carte publiées par cette veille : **0** (collecte privée uniquement)",
    ]
    if updates == editions == deferred == tickets == ticket_proposals == 0:
        lines.extend(["", "**Aucun nouveau changement publiable identifié pendant ce passage.** "
                      "Les informations non vérifiées et les sources indisponibles ne "
                      "déclenchent pas de mise à jour artificielle."])
    else:
        lines.extend(["", "**Les propositions privées ne sont pas des publications.** "
                      "Elles nécessitent une seconde vérification dans le synchroniseur public."])
    if lineup_checks:
        lines.extend(["", "#### Programmations contestées — revue humaine obligatoire",
                      "Une mention différente ne constitue jamais une annonce de remplacement."])
        for item in lineup_checks:
            lines.append("- `" + safe_text(item.get("slug", "?")) + "` : "
                         + safe_text(item.get("signal", "?")) + " — "
                         + safe_text(item.get("url", "?")))
    new_websites = report.get("festival_source_discovery_review_only", [])
    if not isinstance(new_websites, list) or any(
            not isinstance(link, dict)
            or link.get("publication_authorized") is not False
            or link.get("official_site_authorized") is not False
            or link.get("link_only") is not True
            or link.get("status") != "UNVERIFIED_DISCOVERY"
            for link in new_websites):
        raise ValueError("nouvelles pistes non certifiées invalides")
    if new_websites:
        lines.extend(["", "#### Nouvelles sources — privées et non vérifiées",
                      "Ces liens ne prouvent pas la maîtrise d'un domaine organisateur."])
        for link in new_websites[:8]:
            lines.append("- `" + safe_text(link.get("slug", "?")) + "` : "
                         + safe_text(link.get("candidate_url", "?"))
                         + " — depuis " + safe_text(link.get("discovered_from", "?")))
    index_checks = report.get("institutional_agenda_index_checks_review_only", [])
    index_new = report.get("institutional_agenda_discovered_review_only", [])
    index_count = report.get("institutional_agenda_new_urls_review_only", 0)
    index_pending = report.get("institutional_agenda_pending_urls_review_only", 0)
    if (not isinstance(index_checks, list) or not isinstance(index_new, list)
            or any(type(n) is not int or n < 0 for n in (index_count, index_pending))
            or any(not isinstance(row, dict) or
                   row.get("publication_authorized") is not False or
                   row.get("status") not in ("SCANNED", "INACCESSIBLE")
                   for row in index_checks)
            or any(not isinstance(row, dict) or
                   row.get("publication_authorized") is not False or
                   row.get("status") != "UNVERIFIED_INDEX_LINK"
                   for row in index_new)):
        raise ValueError("découverte index non certifiée invalide")
    if index_checks or index_pending:
        lines.extend(["", "#### Index d'agendas institutionnels (collecte privée)",
                      f"{len(index_checks)} index testé(s), {index_count} nouvelle(s) fiche(s) ; "
                      f"{index_pending} piste(s) en file privée. Aucune publication ni certification."])
        for row in index_new[:6]:
            lines.append("- `" + safe_text(row.get("slug", "?")) + "` : "
                         + safe_text(row.get("candidate_url", "?")) +
                         " (non vérifié, à recontrôler)")
    if unavailable:
        lines.extend(["", "Sources indisponibles (échantillon) :"])
        for row in unavailable[:8]:
            lines.append(f"- `{safe_text(row.get('slug', '?'))}` : "
                         f"{safe_text(row.get('reason', 'inconnue'))}")
    # This is an editorial worklist ONLY. A source/auditSources link is never
    # promoted to a registered organizer site or a publishable proof.
    leads=report.get("source_reference_leads_review_only", [])
    if not isinstance(leads,list):
        raise ValueError("pistes officielles non structurées")
    try:
        today=date.fromisoformat(report["date"])
    except (KeyError, TypeError, ValueError):
        today=None
    upcoming=[]
    for lead in leads:
        if not isinstance(lead,dict):
            continue
        if (lead.get("official_status") != "NOT_VERIFIED"
                or lead.get("allowed_to_publish") is not False
                or not isinstance(lead.get("candidate_urls"),list)
                or not lead["candidate_urls"] or today is None):
            continue
        try:
            day=date.fromisoformat(lead["start_date"])
        except (KeyError, TypeError, ValueError):
            continue
        if day >= today:
            upcoming.append((day,lead))
    upcoming.sort(key=lambda entry:(entry[0],str(entry[1].get("slug", ""))))
    if upcoming:
        lines.extend(["", "#### Priorités de couverture : éditions futures sans site officiel vérifié",
                      f"{len(upcoming)} édition(s) avec références à contrôler. "
                      "Ces liens **ne sont pas encore des preuves d'organisateur**."])
        for day,lead in upcoming[:8]:
            url=next((u for u in lead["candidate_urls"] if isinstance(u,str)), "")
            lines.append("- `"+safe_text(lead.get("slug", "?"))+"` "
                         +"("+day.isoformat()+") : référence à qualifier — "
                         +safe_text(url))
    ticket_leads = report.get("ticket_link_leads_review_only", [])
    if not isinstance(ticket_leads, list) or any(
            not isinstance(item, dict)
            or item.get("verification_status") != "LINK_ONLY"
            or item.get("publication_authorized") is not False
            for item in ticket_leads):
        raise ValueError("pistes de billetterie non fiables")
    if ticket_leads:
        lines.extend(["", "#### Liens de billetterie à qualifier (non vérifiés)",
                      "Ces liens proviennent de pages référencées mais ne confirment "
                      "**aucune disponibilité ni catégorie de billets**."])
        for lead in ticket_leads[:8]:
            lines.append("- `" + safe_text(lead.get("slug", "?")) + "` : "
                         + safe_text(lead.get("provider", "?")) + " — "
                         + safe_text(lead.get("ticket_url", "?")))
    if conflicts:
        lines.extend(["", "#### Contradictions exigeant une revue manuelle",
                      "Ces signaux bloquent les propositions automatiques concernées ; "
                      "ils ne certifient aucun statut commercial."])
        for row in conflicts[:8]:
            lines.append("- " + safe_text(row.get("slug", "?")) + " : " +
                         safe_text(row.get("reason", "?")))
    if vendor_checks:
        lines.extend(["", "#### Billetteries liées aux festivals en cours ou à venir",
                      "Une réponse HTTP ou un JSON-LD du prestataire n'est jamais "
                      "une preuve de stock publiable. HTTP 403 reste inconnu."])
        for row in vendor_checks[:8]:
            lines.append("- " + safe_text(row.get("slug", "?")) + " : " +
                         safe_text(row.get("provider", "?")) + " / " +
                         safe_text(row.get("result", "INCONNU")) + " (" +
                         str(len(row.get("categories_review_only", []))) +
                         " catégorie(s) à examiner, non publiée(s))")
    scheduling = report.get("source_qualification_scheduler_review_only")
    if scheduling is not None:
        if (not isinstance(scheduling, dict)
                or scheduling.get("publication_authorized") is not False
                or any(type(scheduling.get(k)) is not int
                       or scheduling[k] < 0
                       for k in ("already_checked_today",
                                 "inaccessible_backoff", "eligible_editions"))):
            raise ValueError("diagnostic de rotation des sources non sécurisé")
        lines.extend([
            "", "#### Rotation des références non certifiées",
            "- Éditions éligibles : **"
            + str(scheduling["eligible_editions"]) + "** ; URL déjà contrôlées aujourd'hui : **"
            + str(scheduling["already_checked_today"])
            + "** ; URL indisponibles en délai de reprise : **"
            + str(scheduling["inaccessible_backoff"]) + "**.",
            "Les URLs écartées temporairement ne sont ni annulées, "
            "ni considérées comme vérifiées ; aucune publication autorisée."
        ])
    qualified = report.get("source_qualification_review_only", [])
    if (not isinstance(qualified, list) or any(
            not isinstance(entry, dict)
            or entry.get("publication_authorized") is not False
            or (("roster_names_mentioned_review_only" in entry
                 or "roster_names_unmentioned_review_only" in entry) and (
                 entry.get("artist_update_authorized") is not False
                 or entry.get("roster_evidence_is_complete") is not False
                 or any(not isinstance(entry.get(key), list)
                        or len(entry[key]) > 30
                        or any(not isinstance(name, str) for name in entry[key])
                        for key in ("roster_names_mentioned_review_only",
                                    "roster_names_unmentioned_review_only"))))
            or entry.get("status") not in
               ("NOT_VERIFIED", "REVIEW_REQUIRED", "REJECTED")
            or entry.get("role") not in
               ("TICKETING", "VENUE", "INSTITUTION", "ORGANIZER_CANDIDATE",
                "SOCIAL", "MEDIA", "THIRD_PARTY", "UNKNOWN")
            for entry in qualified)):
        raise ValueError("qualifications de sources non sécurisées")
    if qualified:
        count = sum(entry["status"] == "REVIEW_REQUIRED" for entry in qualified)
        lines.extend([
            "", "#### Sources candidates examinées (revue privée uniquement)",
            f"{len(qualified)} URL(s) tentée(s) ; {count} dossier(s) avec nom et date concordants.",
            "Une concordance ne prouve ni propriété du site organisateur, "
            "ni stock de billets, et ne modifie jamais `officialSite`."
        ])
        for entry in qualified[:8]:
            lines.append(
                "- `" + safe_text(entry.get("slug", "?")) + "` : "
                + safe_text(entry.get("role", "?")) + " / "
                + safe_text(entry.get("status", "?")) + " — "
                + safe_text(entry.get("url", "?"))
            )
            if "roster_names_mentioned_review_only" in entry:
                matched = entry["roster_names_mentioned_review_only"]
                absent = entry["roster_names_unmentioned_review_only"]
                lines.append(
                    "  - Mentions de groupes du catalogue : **"
                    + str(len(matched)) + "/"
                    + str(len(matched) + len(absent))
                    + "** ; les noms non mentionnés ne sont pas des annulations."
                )
    organizer_leads = report.get("organizer_domain_leads_review_only", [])
    if (not isinstance(organizer_leads, list) or any(
            not isinstance(item, dict)
            or item.get("publication_authorized") is not False
            or not isinstance(item.get("candidate_url"), str)
            or not item["candidate_url"].startswith("https://")
            or item.get("evidence_format", "VISIBLE_ANCHOR") not in
               ("VISIBLE_ANCHOR", "SCHEMA_ORG")
            or item.get("link_only", True) is not True
            for item in organizer_leads)):
        raise ValueError("liens organisateur candidats non sécurisés")
    if organizer_leads:
        structured_count = sum(
            item.get("evidence_format") == "SCHEMA_ORG" for item in organizer_leads)
        lines.extend([
            "", "#### Liens possibles vers l'organisateur (revue humaine)",
            f"{len(organizer_leads)} lien(s) repérés sur des pages de lieux "
            "ou de collectivités, dont **"
            + str(structured_count) + "** piste(s) schema.org. "
            "Aucun domaine n'est authentifié automatiquement."
        ])
        for item in organizer_leads[:8]:
            lines.append(
                "- `" + safe_text(item.get("slug", "?")) + "` : "
                + safe_text(item["candidate_url"]) + " ("
                + safe_text(item.get("evidence_format", "VISIBLE_ANCHOR"))
                + " ; non certifié)"
            )
    consolidated = report.get("organizer_domain_evidence_review_only", [])
    if (not isinstance(consolidated, list) or any(
            not isinstance(item, dict)
            or item.get("publication_authorized") is not False
            or item.get("official_site_authorized") is not False
            or item.get("ownership_proven") is not False
            or item.get("link_only") is not True
            or item.get("corroboration_level") not in
               ("SINGLE_SOURCE_LINK_ONLY", "MULTI_SOURCE_LINK_ONLY")
            or type(item.get("source_count")) is not int
            or item["source_count"] < 1
            or not isinstance(item.get("candidate_domain"), str)
            or not isinstance(item.get("references"), list)
            or not item["references"]
            or ("evidence_formats" in item and (
                not isinstance(item["evidence_formats"], list)
                or not item["evidence_formats"]
                or len(item["evidence_formats"]) > 2
                or any(fmt not in ("VISIBLE_ANCHOR", "SCHEMA_ORG")
                       for fmt in item["evidence_formats"])))
            or any(ref.get("source_role") not in ("VENUE", "INSTITUTION")
                   for ref in item["references"]
                   if isinstance(ref, dict))
            or any(not isinstance(ref, dict) for ref in item["references"])
            for item in consolidated)):
        raise ValueError("consolidation de domaines non sécurisée")
    if consolidated:
        multiple = sum(item["corroboration_level"] == "MULTI_SOURCE_LINK_ONLY"
                       for item in consolidated)
        lines.extend([
            "", "#### Domaines candidats — liens consolidés, non certifiés",
            f"{len(consolidated)} dossier(s) privé(s), dont {multiple} avec "
            "des liens provenant de plusieurs familles de sources.",
            "Même plusieurs liens concordants ne prouvent jamais que "
            "l'organisateur maîtrise un domaine. Aucun site officiel publié."
        ])
        for item in consolidated[:8]:
            lines.append(
                "- `" + safe_text(item.get("slug", "?")) + "` : "
                + safe_text(item["candidate_domain"]) + " — "
                + str(item["source_count"]) + " source(s), "
                + safe_text(item["corroboration_level"]) + " (non certifié)"
            )
    # Independent regional leads are URLs, not verified events.
    regional_checks = report.get("regional_festival_indexes_review_only", [])
    page_checked = report.get("regional_festival_pagination_checked_review_only", 0)
    page_attempted = report.get(
        "regional_festival_pagination_attempted_review_only", page_checked)
    page_inaccessible = report.get(
        "regional_festival_pagination_inaccessible_review_only",
        page_attempted - page_checked)
    page_new = report.get("regional_festival_pagination_discovered_review_only", 0)
    page_pending = report.get("regional_festival_pagination_pending_review_only", 0)
    regional_new = report.get("regional_festival_discoveries_review_only", [])
    visible_article_total = report.get("regional_festival_visible_articles_review_only", 0)
    article_new = report.get("regional_festival_article_clues_new_review_only", 0)
    article_pending = report.get("regional_festival_article_clues_pending_review_only", 0)
    article_new_rows = report.get("regional_festival_article_new_review_only", [])
    if (any(type(x) is not int or x < 0 for x in
            (visible_article_total, article_new, article_pending))
            or not isinstance(article_new_rows, list)
            or article_new > 12 * max(1, len(regional_checks))
            or article_new > article_pending or article_pending > 100
            or len(article_new_rows) != min(article_new, 12)
            or any(not isinstance(x, dict)
                   or x.get("publication_authorized") is not False
                   or x.get("fetch_eligible") is not False
                   or not isinstance(x.get("title"), str)
                   or "candidate_url" in x
                   for x in article_new_rows)):
        raise ValueError("observations de cartes sans lien invalides")
    archive_status = report.get("regional_festival_archive_status_review_only", "NOT_CHECKED")
    archive_total = report.get("regional_festival_archive_reference_count_review_only", 0)
    archive_hints = report.get("regional_festival_archive_hints_count_review_only", 0)
    archive_new = report.get("regional_festival_archive_links_new_review_only", 0)
    regional_configured = report.get("regional_festival_configured_sources_review_only", 0)
    curated_search_views = report.get("regional_festival_curated_search_views_review_only", 0)
    regional_regions = report.get("regional_festival_configured_regions_review_only", 0)
    regional_attempted = report.get("regional_festival_regions_attempted_review_only", 0)
    regional_pass = report.get("regional_festival_regions_this_pass_review_only")
    regional_linkless = report.get("regional_festival_no_visible_links_review_only", 0)
    regional_unmatched = report.get("regional_festival_visible_unmatched_review_only", 0)
    regional_script_hint = report.get("regional_festival_possible_dynamic_review_only", 0)
    regional_scanned = report.get("regional_festival_scanned_this_pass_review_only", 0)
    regional_inaccessible = report.get("regional_festival_inaccessible_this_pass_review_only", 0)
    regional_count = report.get("regional_festival_new_links_review_only", 0)
    regional_existing = report.get("regional_festival_existing_links_skipped_review_only", 0)
    regional_pending = report.get("regional_festival_pending_links_review_only", 0)
    regional_details = report.get("regional_festival_detail_pages_checked_review_only", 0)
    regional_published = report.get("regional_festival_publications", 0)
    if (archive_status not in
            ("NOT_CHECKED", "CONSISTENT", "DIVERGENT", "UNAVAILABLE_OR_INVALID")
            or any(type(n) is not int or n < 0 for n in
                   (archive_total, archive_hints, archive_new))
            or archive_hints > archive_total
            or archive_new > len(regional_new)
            or (archive_status != "CONSISTENT" and
                (archive_total != 0 or archive_hints != 0 or archive_new != 0))):
        raise ValueError("compteurs archive régionale non certifiés invalides")
    if (any(type(x) is not int or x < 0
            for x in (page_attempted, page_checked, page_inaccessible,
                      page_new, page_pending))
            or page_attempted > len(regional_checks)
            or page_attempted != page_checked + page_inaccessible
            or page_new > page_pending or page_pending > 45
            or page_attempted != sum(
                row.get("page_kind") == "PAGINATION"
                for row in regional_checks if isinstance(row, dict))
            or page_checked != sum(
                row.get("page_kind") == "PAGINATION"
                and row.get("status") == "SCANNED"
                for row in regional_checks if isinstance(row, dict))
            or page_inaccessible != sum(
                row.get("page_kind") == "PAGINATION"
                and row.get("status") == "INACCESSIBLE"
                for row in regional_checks if isinstance(row, dict))):
        raise ValueError("pagination régionale non sécurisée")
    if (not isinstance(regional_checks, list) or not isinstance(regional_new, list)
            or any(type(n) is not int or n < 0 for n in
                   (regional_count, regional_existing, regional_pending, regional_details,
                    regional_published, regional_configured, curated_search_views, regional_regions,
                    regional_attempted, regional_scanned, regional_inaccessible,
                    regional_linkless, regional_unmatched, regional_script_hint))
            or regional_pass is not None and (
                type(regional_pass) is not int or regional_pass != len({
                    row.get("region") for row in regional_checks
                    if isinstance(row, dict)}))
            or regional_linkless + regional_unmatched > regional_scanned
            or regional_script_hint > regional_linkless
            or (any(k in report for k in (
                    "regional_festival_no_visible_links_review_only",
                    "regional_festival_visible_unmatched_review_only",
                    "regional_festival_possible_dynamic_review_only"))
                and (regional_linkless != sum(
                    row.get("page_diagnostic") == "NO_VISIBLE_LINKS"
                    for row in regional_checks if isinstance(row, dict))
                or regional_unmatched != sum(
                    row.get("page_diagnostic") == "VISIBLE_LINKS_NO_CANDIDATE"
                    for row in regional_checks if isinstance(row, dict))
                or regional_script_hint != sum(
                    row.get("script_backed_linkless_hint") is True
                    for row in regional_checks if isinstance(row, dict))))
            or curated_search_views > regional_configured
            or regional_regions > regional_configured
            or regional_attempted > regional_regions
            or regional_scanned + regional_inaccessible != len(regional_checks)
            or regional_count != len(regional_new) or regional_details != 0
            or regional_published != 0
            or any(not isinstance(row, dict)
                   or row.get("publication_authorized") is not False
                   or row.get("status") not in ("SCANNED", "INACCESSIBLE")
                   for row in regional_checks)
            or any(not isinstance(row, dict)
                   or row.get("publication_authorized") is not False
                   or row.get("status") != "UNVERIFIED_THEME_LINK"
                   or row.get("new_this_pass") is not True
                   for row in regional_new)):
        raise ValueError("découverte régionale non certifiée invalide")
    if regional_checks or regional_pending:
        regions = sorted({row["region"] for row in regional_checks})
        lines.extend([
            "", "#### Découverte régionale indépendante — jamais publiée",
            f"Pagination bornée : {page_attempted} tentative(s) différée(s), "
            f"{page_checked} page(s) accessibles, {page_inaccessible} indisponible(s), "
            f"{page_new} page(s) d'index nouvellement repérée(s), "
            f"{page_pending} en file privée. Aucune page trouvée n'est visitée le jour même.",
            f"Vues de recherche officielles et strictement autorisées : "
            f"{curated_search_views}.",
            f"Sources configurées : {regional_configured}, régions configurées : "
            f"{regional_regions}, régions tentées depuis le début de journée : "
            f"{regional_attempted}.",
            f"Cartes événementielles visibles sans lien : {visible_article_total} carte(s) "
            f"inspectée(s), {article_new} nouvelle(s) piste(s) de revue non visitables, "
            f"{article_pending} piste(s) en file privée ; aucune date certifiée.",
            f"Diagnostic des index accessibles : {regional_linkless} sans lien visible, "
            f"{regional_unmatched} avec liens visibles mais sans candidat, "
            f"{regional_script_hint} sans lien visible malgré présence de scripts "
            "(simple indice de chargement dynamique, non confirmé).",
            f"Passage : {len(regional_checks)} index tentés dans {len(regions)} région(s), "
            f"{regional_scanned} accessibles, {regional_inaccessible} indisponibles ; "
            f"**{regional_count} nouvelles URL thématiques** (ce passage) ; "
            f"{regional_pending} en file privée ; {regional_existing} lien(s) déjà "
            "connu(s), non recompté(s). Détails vérifiés : 0 ; publications : 0.",
            f"Archives : {archive_status} ; {archive_total} références historiques, "
            f"{archive_hints} noms datés utilisables comme pistes ; "
            f"{archive_new} nouvelles URL repérées grâce aux noms d'archives. "
            "Un millésime dans un titre ne confirme aucune date précise.",
            "Attention : une URL thématique n'établit ni un festival futur, ni son lieu, "
            "ni ses dates. Qualification nécessaire avant toute proposition.",
        ])
        for row in regional_new[:6]:
            lines.append("- " + safe_text(row.get("title", "?")) + " — "
                         + safe_text(row.get("candidate_url", "?"))
                         + " (inconnu, non vérifié)")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    print(render(report), end="")


if __name__ == "__main__":
    main()
