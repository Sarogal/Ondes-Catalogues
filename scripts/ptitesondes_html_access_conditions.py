"""Read-only first-party access terms triage for HTML child-session pages.

Never turn an absence of price or registration text into a free/no-booking
claim. Never infer the cost or accessibility of a required membership card.
All findings describe *one source's visible claims*, not admission rights,
organizer ownership, licensing or an approved event.
"""
import re

from ptitesondes_family_national_source_preflight import _Visibility, norm_text
from ptitesondes_html_first_party_session_proof import (
    corroborate_first_party_session,
)

SCHEMA = "ptitesondes.html_visible_access_terms_readonly.v1"
MAX_HTML = 500_000
MAX_FRAGMENTS = 1200
PRICE_STATES = frozenset({
    "free_disclosed", "free_with_mandatory_membership",
    "paid_disclosed", "paid_amount_unknown", "unknown", "conflicting",
})
REGISTRATION_STATES = frozenset({
    "required", "explicit_not_required", "unknown", "conflicting",
})
FREE = re.compile(r"\b(?:gratuit|gratuite|gratuits|gratuites|entree gratuite|acces gratuit)\b")
PRICE = re.compile(r"\b\d{1,4}(?:[,.]\d{1,2})?\s*(?:euros?\b|eur\b)")
PAID_WORD = re.compile(r"\b(?:payant|payante|payants|payantes|non gratuit|non gratuite)\b")
MEMBERSHIP = re.compile(
    r"\b(?:carte(?:\s+mpt)?|carte\s+d\s+adhesion|"
    r"adhesion|adherent(?:s|e|es)?)\b"
)
MANDATORY = re.compile(
    r"\b(?:obligatoire|obligatoires|necessaire|necessaires|"
    r"requise|requis|exigee|exige|indispensable|"
    r"sur presentation de|reserve aux adherents)\b"
)
OPTIONAL = re.compile(r"\b(?:facultatif|facultative|optionnel|optionnelle)\b")
REQUIRED_REG = re.compile(
    r"\b(?:sur inscription|inscription obligatoire|inscription requise|"
    r"sur reservation|reservation obligatoire|reservation requise)\b"
)
NOT_REQUIRED_REG = re.compile(
    r"\b(?:sans inscription|inscription non obligatoire|"
    r"sans reservation|reservation non obligatoire)\b"
)


class _VisibleEventAccess(_Visibility):
    """Bounded visible fragments after one event H1, excluding related cards."""
    def __init__(self):
        super().__init__()
        self.h1_seen = False
        self.in_h1 = False
        self.heading = False
        self.heading_parts = []
        self.stop = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        hidden = super().handle_starttag(tag, attrs)
        if hidden or self.stop:
            return
        if tag == "h1" and not self.h1_seen:
            self.in_h1 = True
        elif self.h1_seen and tag in ("h2", "h3"):
            self.heading = tag
            self.heading_parts = []

    def handle_data(self, data):
        if self._hidden() or self.stop:
            return
        if self.heading:
            self.heading_parts.append(data)
        elif self.h1_seen and not self.in_h1:
            for raw in data.splitlines():
                # Preserve currency semantics through accent/punctuation fold.
                piece = norm_text(raw.replace("€", " euros "))
                if 0 < len(piece) <= 200 and len(self.parts) < MAX_FRAGMENTS:
                    self.parts.append(piece)

    def handle_endtag(self, tag):
        if tag == "h1" and self.in_h1:
            self.h1_seen = True
            self.in_h1 = False
        elif tag == self.heading:
            heading = norm_text(" ".join(self.heading_parts))
            if heading.startswith(("autres evenements", "evenements similaires",
                                   "vous aimerez aussi", "a decouvrir aussi")):
                self.stop = True
            self.heading = False
        super().handle_endtag(tag)


def _default(reason):
    return {
        "schema": SCHEMA,
        "reason": reason,
        "price_state": "unknown",
        "registration_state": "unknown",
        "mandatory_card_or_membership_claimed": False,
        "membership_fee_stated_on_source": False,
        "membership_cost_independently_verified": False,
        "first_party_visible_session_required": True,
        "first_party_source_access_review_pending": True,
        "family_audience_independently_attested": False,
        "organizer_independently_attested": False,
        "rights_reviewed": False,
        "publication_ready": False,
        "approval_granted": False,
        "public_writes": 0,
    }


def triage_html_access_conditions(lead, page, index_pin, child_path):
    """Fixed-schema report: source terms only, no URLs or raw HTML output."""
    proof = corroborate_first_party_session(lead, page, index_pin, child_path)
    if proof.get("visible_exact_session") is not True:
        return _default("unverified_exact_first_party_session")
    html = page.get("html")
    if not isinstance(html, str) or not 50 <= len(html) <= MAX_HTML:
        return _default("invalid_official_page")
    parser = _VisibleEventAccess()
    try:
        parser.feed(html)
        parser.close()
    except (ValueError, TypeError):
        return _default("unreadable_visible_terms")
    if not parser.h1_seen or not parser.parts:
        return _default("no_visible_event_terms")

    chunks = parser.parts
    has_free = any(FREE.search(part) for part in chunks)
    # A membership card fee is NOT necessarily the session ticket price.
    membership_fee = any(PRICE.search(part) and MEMBERSHIP.search(part)
                         for part in chunks)
    event_price = any(PRICE.search(part) and not MEMBERSHIP.search(part)
                      for part in chunks)
    has_paying_without_amount = any(PAID_WORD.search(part) for part in chunks)
    mandatory_membership = any(
        MEMBERSHIP.search(part) and MANDATORY.search(part)
        and not OPTIONAL.search(part)
        for part in chunks
    )
    optional_membership = any(
        MEMBERSHIP.search(part) and OPTIONAL.search(part)
        for part in chunks
    )
    reg_required = any(REQUIRED_REG.search(part) for part in chunks)
    reg_not_required = any(NOT_REQUIRED_REG.search(part) for part in chunks)
    # Contradictory statements anywhere in this event's visible body must
    # remain a review case, not be "solved" by trusting a preferred phrase.
    if ((has_free and (event_price or has_paying_without_amount))
            or (mandatory_membership and optional_membership)):
        price_state = "conflicting"
    elif has_free:
        price_state = ("free_with_mandatory_membership" if mandatory_membership
                       else "free_disclosed")
    elif event_price:
        price_state = "paid_disclosed"
    elif has_paying_without_amount:
        price_state = "paid_amount_unknown"
    else:
        price_state = "unknown"
    if reg_required and reg_not_required:
        registration_state = "conflicting"
    elif reg_required:
        registration_state = "required"
    elif reg_not_required:
        registration_state = "explicit_not_required"
    else:
        registration_state = "unknown"

    # Even if price/booking terms are explicit, reuse rights or actual
    # membership fee is NOT independently established. No publisher gate.
    needs_review = (
        price_state in ("unknown", "conflicting", "paid_amount_unknown",
                        "free_with_mandatory_membership")
        or registration_state in ("unknown", "conflicting")
    )
    return dict(
        _default("visible_first_party_access_terms_only"),
        price_state=price_state,
        registration_state=registration_state,
        mandatory_card_or_membership_claimed=bool(mandatory_membership),
        membership_fee_stated_on_source=bool(membership_fee),
        first_party_source_access_review_pending=bool(needs_review),
    )
