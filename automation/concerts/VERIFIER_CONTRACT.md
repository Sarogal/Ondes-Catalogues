# Contract of reusable concert-source verifiers — Grosses Ondes

## Permanent rule

A new verifier must accept **future concerts from the venue**. The code must never list the next band's name, show title, date, concert ID or URL as an acceptance condition. Existing manually signed event IDs and URLs remain reserved for history and safety.

## Independent stages

1. Discovery is always quarantined: date, genre, venue and individual first-party URL only, with no production write.
2. Stability requires **two distinct days with the same identity**, not multiple runs in a single day.
3. Independent review fetches the exact first-party event page again. The complete bill is established from **named artist sections** and rechecked against the original headline, date, room and genre. Biographies and recommendations cannot invent new acts.
4. One, two, eight, twenty or more named musicians are admitted by proof, including new acts. No arbitrary cap on **new musicians**. Only bounded source size, identity length and strict source verification. Unannounced guests are not invented.
5. Canonical names and aliases must be reconciled, and historic signed event IDs, official URLs, same-day venue clashes and duplicates protected.
6. A separate publisher validates the complete program, fresh proof, URL, exact venue, date, artist IDs, genres and timing, independently of the discovery process.
7. Door opening hours never become musical start hours. A concert being sold out is not a cancellation.
8. Any **published** event from an officially supported venue is eligible for a read-only published-watch review, **without adding its ID to the code**. Change detection never deletes or cancels an event by itself.

## Source-wide first-party venue registry

`generic_first_party_venue_specs_v1.json` is the **only committed venue authority** for
the generic structured verifier. The verifier reads it through a strict,
immutable, fail-closed loader: source discovery feeds and private registries
cannot register or alter an authorized host. Each new entry requires a reviewed
official host, venue identity, geography and real representative event proofs,
plus contract/publisher regression tests. Never add individual concert IDs,
artist names, dates or event URLs as admission rules.

`venue_admission_audit.py` is a **read-only, non-authorizing** discovery
report. Exact source/catalogue venue matches, HTTPS and geography are triage
inputs only. Even an apparently perfect match never changes the trusted
registry, signs an approval or publishes an event.

`reviewed_venue_specs_v1.json` is a **different publisher contract** for
independently reviewed *new venue address/location* evidence. Its `venues`
map remains empty until a separate geographical approval PR; it must **never**
be reused for generic source host registrations. The two independent schemas
are intentionally kept separate and tested together.

## HTML proof exploration (not a publisher contract)

`official_html_evidence.py` detects independently fetched event-page **visible**
genre labels, but only when the individual first-party URL has not redirected,
the headline and complete known bill correlate, the first concert date under the
headline matches, and the venue and city are visible on that SAME event page.

Supported positive hints include a short `<p>metal</p>` event badge near the
headline, or named performer headings such as `► ARTIST – Metal Indus –`.
Descriptions, venue-wide navigation menus, artist biographies, unrelated
recommendations and generic "Rock" **do not** corroborate genre. Ambiguous
headlines, changed date, venue or cross-host URL fail closed.

These signals appear only in the **private** structured preflight, retaining
`publicationAllowed: false` and `approvalsProposed: 0`. They NEVER rewrite a
registry lead as `genre_tag_review`, sign an approval, or satisfy the actual
publisher. The next stage must provide a separately reviewed publisher contract
with live first-party examples and independent provenance checks.

## Required regression matrix

- At least two distinct real future bills from the same venue, plus 1/2/8/20 entirely different named artists.
- Mixed known/new artists; missing or newly named support; explicit unnamed guest; aliases; collisions and duplicates.
- Two-day stability; wrong domain or redirect; moved venue/room; changed date, lineup, genre, status and hours.
- Sold-out versus cancelled/postponed; historic signed documents remain immutable.
- Forged approvals and identity/provenance/time metadata must fail the **publisher**, not merely the source parser.
- Successful Concerts engine and synchronizer CI on the final change, and source-wide read-only watchdog coverage.

Operational boundary: CI-validated, controlled merges only. Never alter Infomaniak, write private approvals or public catalogue JSON during a venue admission audit, or change unrelated production workflows.
