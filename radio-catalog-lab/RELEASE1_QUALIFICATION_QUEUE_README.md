# Grosses Ondes — Release 1: progressive qualification queue (draft)

**2026-11-20 — separate public laboratory, read-only; not an admission or publisher.**

This tool fills the gap between already-developed central identity reconciliation
(PR #474) and technical stream evidence. It deliberately reuses
`radio_catalog_daily_candidate_reconcile.review_candidates` and existing
`radio_stream_recheck_ledger` output. It does not duplicate stream transport,
DNS, TLS, decoder or signing code. It can run with a **private** input catalog
without uploading that catalog into the public repository.

## What it does

- Retains **every** historical GO station and each legacy stream even when
  Radio Browser did not find it today; preserves all RADIO BOB! records.
- Prepares one review task per historical stream and one per freshly discovered
  candidate. The UUID admission list is **never** a closed-world filter.
- Prioritizes MP3/AAC streams, especially legacy playback; HLS remains a
  separate track and cannot block other codecs.
- Matches cross-day evidence **only** when the UUID and exact SHA-256 of the
  original stream URL agree. A URL change cannot inherit an old success flag.
- Distinguishes candidate identities and duplicate risks without merging
  aliases or altering GO IDs. Transport evidence alone **never** certifies a
  live station.
- Emits report items containing stream **hashes** rather than raw URLs.
  No logo, audio, private key, favorite, device data or publication artifact.

## Offline invocation

From repository root, with private catalog input kept outside this repository:

```sh
python radio-catalog-lab/tools/radio_catalog_qualification_queue.py \
  --catalog /private/staged-radio-catalog.json \
  --discovery /scratch/candidates.json \
  --stream-evidence /scratch/stream-evidence.json \
  --output /scratch/release1-qualification-queue.json
```

`--stream-evidence` is optional for the first pass; the historical catalog
input must follow the central v1 shape. `--legacy-ids` can optionally point
to a JSON list of UUIDs still admitted in the old code but missing from the
central snapshot, so they remain explicitly classified for review.

No write-back is provided. The output refuses to overwrite a previous report.

## Interpreting counts and gates

`preservedHistoricalStreamCount` is a **stream count**, not an installed-device
station count. `discoveredCandidateCount` is a scan count, not new radios
published. `transportLaneCounts` is prioritization, not proof of playability.
All output rows say `technicalQualified=false`,
`editoriallyApproved=false`, and `publicationAllowed=false`.

A technical evidence ledger may indicate two successful MP3/AAC observations
on separate days. Those remain **review evidence**, never an automatic edit,
approval or publication. HLS must be independently rechecked without blocking
the MP3/AAC lane.

## Security and release status

Synthetic branch CI performs offline unit tests only. No live probing, cron,
secrets, Infomaniak, Pages, signed `current.json`, Android or Play Store.
Real release still requires complete device-baseline reconciliation, verified
streams and logos, editorial approval, the signed packager PR #511,
Flutter activation/rollback, Android Auto tests and the owner's authorization.

For the 27 historical admission UUIDs, continue using the private
`radio_catalog_coverage_gate.py`, `radio_catalog_uuid_reconcile.py` and
`radio_catalog_triage_preview.py`. Their classification is not a merge plan.
