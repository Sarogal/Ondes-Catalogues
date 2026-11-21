# Grosses Ondes — non-production radio catalog TEST for APK diagnostic

**Date: 2026-11-21. Not the Grosses Ondes published radio catalog.**

This branch hosts isolated diagnostic generations for the Android APK in `Sarogal/GrossesOndes` PR #320. **Active sequence 1 and pending 2/3 are synthetic and non-playable. Pending sequence 4 is a separately reviewed REAL Punk test proposal. None is a production editorial publication.**

- `current.json`: signed Ed25519 pointer, initially sequence **1**.
- `releases/<sha256>.json`: immutable payloads for sequences 1, 2 and 3.
- `pending/test-current-v2.json`: reserved signed test pointer for sequence 2, NOT active.
- `pending/test-current-v3.json`: reserved signed test pointer for sequence 3, NOT active.
- `pending/test-current-v4.json`: **separately signed, NOT ACTIVE**, with two official-source Punk streams, historic UUID aliases and one SHA-checked channel-specific logo; requires physical device validation before any test-pointer promotion.
- `TEST_PUBLIC_KEY.b64`: raw 32-byte Ed25519 test public key (base64), ID `go-apk-test-20261121`. Test private seed is not on GitHub.
- In active sequence 1 and pending 2/3, all synthetic candidates remain `quarantined` with non-playable `candidate` streams and no logos. **The pending, unpromoted version 4 is intentionally different**: it contains two test-only real active Punk channels with source-backed MP3 streams and a SHA image; it has no effect on the currently installed APK while `current.json` points to sequence 1.

Test HTTPS base (public raw GitHub branch; **not GitHub Pages, not Infomaniak**):

`https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/feature/radio-central-apk-test-endpoint-20261121/grossesondes/radio-test-apk/`

The private test launcher pins this exact base and public key by default. Its source is `tools/Invoke-GrossesOndesCentralTestApk.ps1` in the private PR #320.

**Manual opt-in to sequence 2:** only after the sequence 1 phone/offline test, update `current.json` with the exact bytes from `pending/test-current-v2.json` (do not edit the signature or body). For sequence 3, similarly copy `pending/test-current-v3.json` after the second test. Release payloads MUST exist before changing the pointer. This public branch is not merged or deployed as a production catalog.

Sequence 1 and its pending synthetic successors demonstrate signed HTTP download, sequence change, offline persistence, signature/digest refusal and non-destructive overlay. The new TEST-only pending v4 prepares the **next live Punk and real logo acceptance trial**, supported by official provider sources, 3 time-separated live audio headers per channel, 6 seconds decoded by distro FFmpeg per channel and real artwork SHA/format/size review. These checks are not long-duration user listening; physical device review and acceptance are still required. The RADIO BOB general brand image is NOT claimed as a channel-specific Punk logo. Discovery remains open, without a closed station or source whitelist.

Security: do not reuse the test Ed25519 key in production; do not put the test package's signing key or the production catalog key into any branch.

## Proposed real Punk preview, pending signed generation 4 (NOT ACTIVE)

- `go-station-900010`: **RADIO BOB! BOBs Punk**; official https://www.radiobob.de/punk-stream, approved TEST MP3 192 source; UUID `9618c802-0601-11e8-ae97-52543be04c81`. The public publisher logo is NOT automatically substituted as a specific Punk image.
- `go-station-900011`: **ROCK ANTENNE Punk Rock**; official https://www.rockantenne.de/rockhoeren/streams/punk-rock, MP3. Official channel-specific JPEG SHA-256 `715d7a4cee2db4c3852ccd3336fcabbffd9ad727981538fe2ce43ec567375331` (484148 bytes, 2000×2000). UUID `960c4c2a-0601-11e8-ae97-52543be04c81`.
- Both primary MP3 streams decoded six seconds under real FFmpeg on a public GitHub runner in [evidence run #44893746785](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44893746785); timed independent samples in [run #44893230189](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44893230189). AAC alternatives remain `candidate_verified` until decoder/handset verification.
- Pointer `pending/test-current-v4.json` is signed using the **TEST** key only and refers to immutable content. `current.json` remains seq **1**, so **the APK on the phone has not changed**. Do not copy v4 into current before the separate user acceptance for remote update; do not merge or publish this into production.
