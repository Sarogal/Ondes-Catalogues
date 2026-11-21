# Grosses Ondes — radio candidates (open discovery, TEST only)

**21 November 2026.** This directory is NOT a closed list of accepted stations, not a whitelist, not a signed playable release, and not the production catalog. It stores initial source-backed discoveries to exercise an expandable qualification workflow. Additional metal, punk, hard rock and related stations must be accepted into the discovery queue regardless of whether their IDs, domains, brands, publishers or locations were previously known.

## Punk candidates introduced after physical Android Auto TEST

The V64 embedded snapshot has 310 historical entries and zero stations tagged as primary `Punk`. Both Flutter's home carousel and Android Auto intentionally hide genres with zero matching playable stations. The signed TEST fixture generations 1–3 have only quarantined synthetic sources, so the real Punk category remains absent on the test APK even though the client supports `Punk`.

The initial entries in `punk_official_sources.json` come from the stations' own official pages:

- **RADIO BOB! BOBs Punk** — official station https://www.radiobob.de/punk-stream ; official stream references https://www.radiobob.de/radiobob/empfang/livestream ; legacy UUID `9618c802-0601-11e8-ae97-52543be04c81`.
- **ROCK ANTENNE Punk Rock** — station https://www.rockantenne.de/rockhoeren/streams/punk-rock ; published MP3 and AAC links https://www.rockantenne.de/rockhoeren/empfang/streamlinks ; legacy UUID `960c4c2a-0601-11e8-ae97-52543be04c81`.

This is **not** permission to set `streams[].state=verified`. External web evidence confirms the publisher's announced stream URL, not sustained decoding and sound. True qualification needs live transport evidence, stability checks, duplicate identity check, editorial review, and a signed monotonic release.

## Automated safety preflight

The workflow `.github/workflows/radio-open-candidates-evidence-ci.yml` is scoped to this isolated public testing branch and does **not** have write permissions.

- `probe_open_radio_candidates.py`: bounded live HTTPS audio-prefix probe, honest result `transport_audio_prefix` and `requires_audio_continuity_review=true`. A single successful fetch is never presented as an approved radio or proof of long playback.
- `probe_open_radio_artwork.py`: bounded network image fetching with decoder, size and SHA-256 evidence. An image with a calculated SHA is still **not** an editorially approved station-specific logo.
- Both offline unit test suites reject private HTTP endpoints and credentialed URLs, malformed audio/graphics, duplicates, unsafe status promotion and closed list assumptions.
- CI emits a temporary downloadable evidence artifact; it never changes `current.json`, generates a signing key, signs a release, pushes stations to production, or alters the original Android APK.

## Artwork identity

The RADIO BOB image is an official **network-brand** artwork candidate, not a Punk-specific logo. The ROCK ANTENNE image is taken directly from its official **Punk Rock stream page** and is a stronger channel-specific candidate. Both remain `state=unreviewed` until their actual bytes and visual identity are reviewed. The eventual central logo store must ingest only images that pass a real byte hash, file format, dimension and editorial identity review, then use SHA content addressing for both Flutter and Android Auto. Never replace a legitimate existing radio logo with an unverified generic image.

## Next gate

After evidence is available, explicitly review stream continuity, compare old/new UUIDs and URLs and ensure no existing RADIO BOB! or Wacken favorite can be lost. Produce a **separate versioned and signed TEST-only candidate** using the offline packager and keep the existing active pointer sequence 1 intact until the next on-device update/rollback test is planned. Verify that `Punk` then appears in both UI and Android Auto and that the real source artwork persists across reconnect and airplane mode. No production release or merge without the full acceptance checks.
