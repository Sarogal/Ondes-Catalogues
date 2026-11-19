"""Trusted source-wide verifier contract shared by approval and private diagnostics.

Only committed, reviewed Python code can add an automatic source. Discovery
records, venue source lists, a candidate URL and the private registry CANNOT
register a new verifier or grant approval. Each handler re-fetches first-party
evidence and the actual publisher still independently validates the signature.

Adding a verifier: implement/test a source-wide module, add ONE reviewed spec
here, and add publisher contract tests. Do not add per-event URLs to this map.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class VerifierSpec:
    # None only for original Rex/Atabal guarded branches in official_recheck.
    module: str | None
    discovery_detail_flag_required: bool


# Fixed names and import targets are trusted code, NEVER interpreted from
# registry candidate data or an external JSON response.
VERIFIER_SPECS = MappingProxyType({
    "agenda_officiel_rex_genre": VerifierSpec(None, False),
    # Source-wide parser; the exact two trusted venue hosts are frozen in
    # generic_music_event.SPECS, never imported from discovery candidates.
    "agenda_officiel_structuré": VerifierSpec("generic_music_event", False),
    "agenda_officiel_molotov_genre": VerifierSpec("molotov_official", False),
    "agenda_officiel_ferrailleur_genre": VerifierSpec("ferrailleur_official", True),
    "agenda_officiel_backstage_detail": VerifierSpec("backstage_recheck", False),
    "agenda_officiel_atabal_detail": VerifierSpec(None, True),
    "agenda_officiel_blacklab_detail_review": VerifierSpec(
        "blacklab_official_recheck", True),
    "agenda_officiel_laiterie_detail_review": VerifierSpec(
        "laiterie_official_recheck", True),
    "agenda_officiel_rockstore_detail_review": VerifierSpec(
        "rockstore_official_recheck", True),
    "bateau_ivre_official_detail_review": VerifierSpec(
        "bateau_ivre_official_recheck", True),
    "agenda_officiel_bonjour_minuit_detail_review": VerifierSpec(
        "bonjour_minuit_official_recheck", True),
    "bbc_official_detail_review": VerifierSpec(
        "bbc_official_recheck", True),
    "agenda_officiel_cave_poetes_detail": VerifierSpec(
        "cave_poetes_official_recheck", True),
})

AUTOMATIC_RECHECK_SOURCES = frozenset(VERIFIER_SPECS)
DISCOVERY_DETAIL_FLAG_REQUIRED_SOURCES = frozenset(
    source for source, spec in VERIFIER_SPECS.items()
    if spec.discovery_detail_flag_required
)
