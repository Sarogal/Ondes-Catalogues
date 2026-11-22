"""Original factual HTML drafts and event-scoped OA licence triage (NO WRITES).

An unlicensed web page is not automatically a prohibited fact. Conversely, a
public event page or a licence string in its footer does not license prose,
images, a third-party database, or bulk extraction.

A draft is private work material and has no approval / publisher authority.
Only separately verified exact-session evidence may yield a factual draft.
Never log private drafts from a public GitHub Action.
"""
from datetime import date, datetime
import re

from ptitesondes_family_national_scope import FAMILY_TYPES
from ptitesondes_html_first_party_session_proof import corroborate_first_party_session
from ptitesondes_html_family_age import triage_html_family_age
from ptitesondes_html_access_conditions import triage_html_access_conditions
from ptitesondes_openagenda_v2_direct_evidence import SCHEMA as OA_SOURCE_SCHEMA

SCHEMA = "ptitesondes.factual_reuse_preflight.v1"
_OA_LICENSE = "etalab-2.0"
_OA_LICENSE_URL = "https://www.data.gouv.fr/pages/legal/licences/etalab-2.0/"
_ALLOWED_AUDIENCES = frozenset((
    "explicit_children", "explicit_family", "explicit_mixed",
))
# These statuses are only declarations by the identified official source.
_ACCESS_SENTENCES = {
    "free_disclosed": "Séance annoncée gratuite par la source.",
    "free_with_mandatory_membership":
        "Séance annoncée gratuite, avec carte ou adhésion obligatoire "
        "(coût de la carte non vérifié).",
    "paid_disclosed": "Tarif payant annoncé ; consulter la source pour le montant.",
    "paid_amount_unknown": "Séance payante annoncée ; montant non précisé.",
    "unknown": "Tarif non précisé par la source.",
}
_REG_SENTENCES = {
    "required": "Inscription ou réservation annoncée nécessaire.",
    "explicit_not_required": "Aucune inscription annoncée nécessaire.",
    "unknown": "Modalités d'inscription non précisées.",
}
_AUDIENCE_SENTENCES = {
    "explicit_children": "Public enfant annoncé.",
    "explicit_family": "Public familial annoncé.",
    "explicit_mixed": "Public enfants et adultes annoncé.",
}


def _base(reason):
    return {
        "schema": SCHEMA, "reason": reason, "status": "held",
        "draft": None,
        "source_facts_reuse_review_needed": True,
        "database_and_source_terms_review_needed": True,
        "source_licence_assumed": False,
        "copyrighted_description_reused": False,
        "third_party_image_reused": False,
        "editorial_reviewed": False,
        "rights_reviewed": False,
        "organizer_independently_verified": False,
        "publisher_connected": False,
        "publication_ready": False,
        "approval_granted": False,
        "public_writes": 0,
    }


def _public_string(value, maximum):
    """Reject HTML and control characters, never clean a fake claim silently."""
    return (isinstance(value, str) and 1 <= len(value.strip()) <= maximum
            and value.strip() == value
            and not re.search(r"[\x00-\x1f\x7f<>]", value))


def prepare_private_html_factual_draft(lead, page, index_pin, child_path):
    """Create a limited original factual proposal for PRIVATE review only.

    No description, quotations, image or licence is sourced from source HTML.
    Source title is retained as an identity fact, never inserted in the draft
    description; editorial rights and organiser checks remain independent.
    A missing fee or registration statement is described as 'not stated'.
    """
    proof = corroborate_first_party_session(lead, page, index_pin, child_path)
    if proof.get("visible_exact_session") is not True:
        return _base("exact_official_session_not_corroborated")

    if (not isinstance(lead, dict)
            or any(not _public_string(lead.get(key), maximum)
                   for key, maximum in (
                       ("title", 180), ("city", 120), ("venue", 160),
                       ("source_url", 1000), ("date_start", 10),
                       ("start_local", 5)))
            or lead.get("category") not in FAMILY_TYPES):
        return _base("missing_or_invalid_factual_fields")
    try:
        day = date.fromisoformat(lead["date_start"])
        if day.isoformat() != lead["date_start"]:
            raise ValueError()
        clock = datetime.strptime(lead["start_local"], "%H:%M")
        if clock.strftime("%H:%M") != lead["start_local"]:
            raise ValueError()
    except (ValueError, TypeError):
        return _base("invalid_date_or_clock")

    audience = triage_html_family_age(lead, page, index_pin, child_path)
    if (audience.get("reason") != "visible_first_party_family_age_terms_only"
            or audience.get("audience_state") not in _ALLOWED_AUDIENCES
            or audience.get("family_or_age_review_pending") is not False):
        return _base("family_public_not_explicitly_confirmed")

    access = triage_html_access_conditions(lead, page, index_pin, child_path)
    if access.get("reason") != "visible_first_party_access_terms_only":
        return _base("source_access_terms_unreadable")
    if (access["price_state"] == "conflicting"
            or access["registration_state"] == "conflicting"):
        return _base("source_access_terms_conflicting")
    if (access["price_state"] not in _ACCESS_SENTENCES
            or access["registration_state"] not in _REG_SENTENCES):
        return _base("unsupported_access_terms")

    age_min, age_max = audience["age_min"], audience["age_max"]
    if age_min is not None and age_max is not None:
        age_sentence = f"Âges annoncés : de {age_min} à {age_max} ans."
    elif age_min is not None:
        age_sentence = f"Âge minimum annoncé : {age_min} ans."
    elif age_max is not None:
        age_sentence = f"Âge maximum annoncé : {age_max} ans."
    else:
        age_sentence = "Âge non précisé par la source."

    label = FAMILY_TYPES[lead["category"]][0]
    # This is original P'tites Ondes prose, assembled only from corroborated
    # factual fields. The event's original marketing prose is never used.
    summary = (
        f"{label} à {lead['venue']} ({lead['city']}), "
        f"le {day.strftime('%d/%m/%Y')} à {lead['start_local']}. "
        f"{_AUDIENCE_SENTENCES[audience['audience_state']]} "
        f"{age_sentence} {_ACCESS_SENTENCES[access['price_state']]} "
        f"{_REG_SENTENCES[access['registration_state']]}"
    )

    # This is intentionally NOT the public catalogue / patch.v1 schema.
    private_draft = {
        "schema": "ptitesondes.private_original_facts_draft.v1",
        "source_title_identity_only": lead["title"],
        "title": f"{label} — {lead['city']}",
        "city": lead["city"], "venue": lead["venue"],
        "date_start": lead["date_start"],
        "start_local": lead["start_local"],
        "source_url": lead["source_url"],
        "category": lead["category"],
        "age_min": age_min, "age_max": age_max,
        "audience_source_claim": audience["audience_state"],
        "price_source_claim": access["price_state"],
        "registration_source_claim": access["registration_state"],
        "original_factual_summary": summary,
        "source_description": None, "image_url": None,
        "source_rights_status": "source_policy_review_pending",
        "safe_to_publish": False,
    }
    return dict(
        _base("facts_only_private_draft_requires_source_policy_review"),
        status="private_draft_for_rights_review",
        draft=private_draft,
    )


def triage_openagenda_licence_metadata(api_event, checked_direct_evidence):
    """Check a single event's OA rights shape; never inherit agenda licence.

    This diagnostic must follow an exact API v2/UID evidence check. An
    authentic record may still contain invalid/false legal rights metadata.
    The function intentionally returns NO licensor's personal name or URL.
    """
    out = {
        "schema": SCHEMA, "route": "source_evidence_unverified",
        "recognized_open_licence_claim": False,
        "licensor_name_claimed": False,
        "source_update_timestamp_claimed": False,
        "attribution_metadata_complete": False,
        "per_event_licence_must_be_respected": True,
        "images_and_third_party_content_not_cleared": True,
        "rights_reviewed": False, "approval_granted": False,
        "publication_ready": False, "public_writes": 0,
    }
    if (not isinstance(api_event, dict)
            or not isinstance(checked_direct_evidence, dict)
            or checked_direct_evidence.get("schema") != OA_SOURCE_SCHEMA
            or checked_direct_evidence.get("source_evidence_structurally_valid")
               is not True
            or checked_direct_evidence.get("approval_granted") is not False
            or checked_direct_evidence.get("public_writes") != 0):
        return out

    rights = api_event.get("rights")
    license_info = rights.get("license") if isinstance(rights, dict) else None
    licensor = rights.get("licensor") if isinstance(rights, dict) else None
    if not isinstance(license_info, dict) or not isinstance(licensor, dict):
        return dict(out, route="missing_event_rights")
    licence = license_info.get("id")
    name = licensor.get("name")
    source_name_present = (isinstance(name, str)
                           and bool(name.strip())
                           and len(name) <= 200
                           and not re.search(r"[\x00-\x1f<>]", name))
    update = api_event.get("updatedAt")
    update_present = False
    if isinstance(update, str) and 20 <= len(update) <= 40:
        try:
            parsed = datetime.fromisoformat(update.replace("Z", "+00:00"))
            update_present = (
                parsed.tzinfo is not None and parsed.utcoffset() is not None
                and 2000 <= parsed.year <= 2100
            )
        except ValueError:
            pass
    open_claim = (
        licence == _OA_LICENSE
        and license_info.get("url") == _OA_LICENSE_URL
        and license_info.get("name") == "Licence Ouverte 2.0"
    )
    state = (
        "open_licence_claim_ready_for_independent_rights_review"
        if open_claim and source_name_present and update_present else
        "open_licence_claim_attribution_incomplete"
        if open_claim else
        "other_or_unknown_licence_requires_review"
    )
    return dict(
        out, route=state,
        recognized_open_licence_claim=bool(open_claim),
        licensor_name_claimed=bool(source_name_present),
        source_update_timestamp_claimed=bool(update_present),
        attribution_metadata_complete=bool(
            open_claim and source_name_present and update_present),
    )
