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

## Placeholder performers in official structured pages

Some real first-party sites emit schema.org `Event.performer` as
`{"@type":"Organization","name":"Organization"}`. The word "Organization"
is a **schema placeholder**, not evidence of a band. The discovery engine
retains the visible event title as an **unverified review hint** and marks
`structuredPerformerProof: missing_review_only` instead of creating a
fictional artist. That hint cannot satisfy the verifier/publisher, which
require genuinely named `MusicGroup` or `Person` performers.

If the same official page shows an exact visible genre label but has no
verified structured line-up, the private HTML preflight records a distinct
`html_event_genre_visible_lineup_unverified` reason. This is useful for
future source verification and **never** grants approval or publication.

## First-party visible-bill discovery (no publishing)

`generic_visible_bill.py` reuses the **already approved** HTTPS host, venue
identity and individual event URL path from the generic first-party manifest.
It examines only event pages that `discover.scan_venues` has **already**
fetched within the normal three-link rotating window. No additional
requests, scraping sweep or per-concert exceptions are introduced.

For a newly discovered individual HTML event, the visible page must contain
a single concert heading, a future show date (not a ticket-sale date), the
reviewed venue and city, and a complete bill of individually named
`► ARTIST – Genre` headings in precisely the order of the event headline.
Every artist must have a recognized explicit event-level genre. The number
of named acts is not arbitrarily capped. An unannounced trailing guest is
kept separately and never invented as an artist.

Candidates have the distinct source `agenda_officiel_visible_bill`,
`publicationAllowed: false` and `reviewRequired: true`. They never
approve during discovery. Only after **two distinct stable days** does
`official_recheck` fetch the exact HTTPS event page independently and
run the entire visible artist/date/genre/venue proof again.

The independently checked official evidence has
`sourceStructure=verified-first-party-visible-bill-v1`, a fixed
`visibleBillProfile=heading-artist-genre-v1`, the complete list of
`officialArtistNames`, `officialGenreLabels`, `verifiedVenueId`, and
the date of the second fetch. The separate publisher strictly validates
this exact proof shape, venue/host/path, genre list, name-to-artist-ID
reconciliation, duplicates, event identity and time provenance. No
genre label or artist inferred from the venue's global menu, biography,
an `Organization` placeholder or a ticket-sale date may pass.

The source-wide read-only `published_watch` checks later official HTML
for bill, genre, date and venue changes; it never cancels, deletes or edits
an event itself. No event names, dates, artist IDs or event URLs become
special-case approval rules.

## Required regression matrix

- At least two distinct real future bills from the same venue, plus 1/2/8/20 entirely different named artists.
- Mixed known/new artists; missing or newly named support; explicit unnamed guest; aliases; collisions and duplicates.
- Two-day stability; wrong domain or redirect; moved venue/room; changed date, lineup, genre, status and hours.
- Sold-out versus cancelled/postponed; historic signed documents remain immutable.
- Forged approvals and identity/provenance/time metadata must fail the **publisher**, not merely the source parser.
- Successful Concerts engine and synchronizer CI on the final change, and source-wide read-only watchdog coverage.

Operational boundary: CI-validated, controlled merges only. Never alter Infomaniak, write private approvals or public catalogue JSON during a venue admission audit, or change unrelated production workflows.

## Genres individuels depuis une biographie officielle (recherche privée)

Les pages officielles de **tournée** n'indiquent souvent aucun genre musical.
`artist_genre_preflight.py` tente d'abord le profil structuré `MusicGroup` ou
`Person` musicien. Si cette preuve n'existe pas, il est autorisé à suivre
**un seul** lien explicitement intitulé `Bio`, `Biographie`, `Biography` ou
`About`, présent sur cette même page officielle et pointant vers le **même
hôte HTTPS**. Aucun moteur de recherche, domaine tiers, redirection, catalogue
de noms d'artistes, URL de profil construite ou exception concert n'est autorisé.

La biographie est relue indépendamment, après vérification robots. Elle doit
nommer sans ambiguïté le même artiste dans le titre HTML et dans un premier
paragraphe parlant directement de son propre style avec un **sous-genre
explicite** (pas `rock`, `metal` ou `hardcore` génériques, et aucun homonyme
électronique). Les mentions de groupes influents, menus, concerts passés,
négations et recommandations sont exclues.

Une telle preuve a le périmètre `individual_artist_not_event`, et
`eventDateLocationAndLineupProved=false`. Elle ne certifie **jamais**
la date, le plateau, le lieu, la sécurité géographique ou l'existence d'un
concert. Tous ces éléments restent sous les contrôles indépendants du
publisher. Ce module ne signe **aucune** approbation et ne change **aucun**
genre de concert. Les détails ne sont archivés que dans GrossesOndes privé.
