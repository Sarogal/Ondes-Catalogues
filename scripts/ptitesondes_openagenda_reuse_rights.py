"""Check the *per-event* OpenAgenda v2 licence for factual-data reuse.

Official contract: https://developers.openagenda.com/licence/
OpenAgenda requires attribution to rights.licensor.name AND the source
updatedAt date for its etalab-2.0 data. Never infer one agenda-wide licence.
This is a read-only evidence gate, never an organizer proof, event admission,
right to copy images or description, or publisher authorization.
"""
from datetime import date, datetime, timedelta
import re
import unicodedata

SCHEMA = "ptitesondes.oa_event_factual_reuse_rights.v1"
OPEN_LICENSE_ID = "etalab-2.0"
OPEN_LICENSE_NAME = "Licence Ouverte 2.0"
OPEN_LICENSE_URL = "https://www.data.gouv.fr/pages/legal/licences/etalab-2.0/"


def _source_name(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 120:
        return None
    if unicodedata.normalize("NFC", value) != value:
        return None
    if not value.strip() or value != value.strip():
        return None
    if re.fullmatch(r"[\w .,&'’/()\-+:]{1,120}", value, re.UNICODE) is None:
        return None
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        return None
    return value


def review_event_rights(api_event, today):
    """Return a private, non-publishing rights and attribution assessment."""
    base = {
        "schema": SCHEMA,
        "status": "event_rights_unverified",
        "licensed_factual_reuse_confirmed": False,
        "license_id": None,
        "licensor_attribution": None,
        "source_updated_at": None,
        "attribution_display": None,
        "description_or_image_reuse_allowed_by_this_gate": False,
        "independent_organizer_verified": False,
        "publisher_connected": False,
        "publication_ready": False,
        "public_writes": 0,
    }
    if (not isinstance(api_event, dict) or type(today) is not date
            or api_event.get("removed") is True
            or api_event.get("state") != 2):
        return dict(base, status="nonpublic_or_invalid_event")
    rights = api_event.get("rights")
    if not isinstance(rights, dict):
        return dict(base, status="missing_event_rights")
    licence = rights.get("license")
    if not isinstance(licence, dict):
        return dict(base, status="missing_event_license")
    licence_id = licence.get("id")
    if licence_id != OPEN_LICENSE_ID:
        return dict(base, status="unreviewed_license_kind")
    licensor = rights.get("licensor")
    name = _source_name(licensor.get("name")) if isinstance(licensor, dict) else None
    if name is None:
        return dict(base, status="missing_or_unsafe_licensor_name")
    # The publisher may differ from the licensor when agendas syndicate.
    # Under OpenAgenda's licence, the licensor takes attribution precedence.
    raw = api_event.get("updatedAt")
    if not isinstance(raw, str) or not 19 <= len(raw) <= 40:
        return dict(base, status="missing_source_last_update")
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return dict(base, status="invalid_source_last_update")
    if (stamp.tzinfo is None or stamp.utcoffset() is None
            or not date(2000, 1, 1) <= stamp.date() <= today + timedelta(days=1)):
        return dict(base, status="invalid_source_last_update")
    day = stamp.strftime("%d/%m/%Y")
    display = (name + " — " + OPEN_LICENSE_NAME +
               " — données mises à jour le " + day)
    return {
        **base,
        "status": "open_license_factual_reuse_with_attribution",
        "licensed_factual_reuse_confirmed": True,
        "license_id": OPEN_LICENSE_ID,
        "licensor_attribution": name,
        "source_updated_at": stamp.isoformat(),
        "attribution_display": display,
    }
