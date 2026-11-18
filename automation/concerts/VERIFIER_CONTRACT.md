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

## Required regression matrix

- At least two distinct real future bills from the same venue, plus 1/2/8/20 entirely different named artists.
- Mixed known/new artists; missing or newly named support; explicit unnamed guest; aliases; collisions and duplicates.
- Two-day stability; wrong domain or redirect; moved venue/room; changed date, lineup, genre, status and hours.
- Sold-out versus cancelled/postponed; historic signed documents remain immutable.
- Forged approvals and identity/provenance/time metadata must fail the **publisher**, not merely the source parser.
- Successful Concerts engine and synchronizer CI on the final change, and source-wide read-only watchdog coverage.

Operational boundary: isolated branches and draft PRs only until authorized. Never silently merge, alter Infomaniak, write private approvals or public catalogue JSON, or change production workflows.
