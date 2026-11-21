# Grosses Ondes — non-production radio catalog TEST for APK diagnostic

**Date: 2026-11-21. Not the Grosses Ondes published radio catalog.**

This branch hosts isolated diagnostic generations for the Android APK in `Sarogal/GrossesOndes` PR #320. **The active TEST pointer now targets signed generation 4 after express user approval on 2026-11-21. Sequences 1–3 are synthetic and non-playable; generation 4 adds two officially sourced Punk channels. This is NOT a production editorial publication.**

- `current.json`: signed Ed25519 pointer, **NOW sequence 4** (TEST only; user-authorized). Original exact signed sequence-1 pointer preserved as `pending/test-current-v1.json` for auditing.
- `releases/<sha256>.json`: immutable signed payload targets for sequences **1, 2, 3 and 4**.
- `pending/test-current-v2.json`: reserved signed test pointer for sequence 2, NOT active.
- `pending/test-current-v3.json`: reserved signed test pointer for sequence 3, NOT active.
- `pending/test-current-v4.json`: exact signed duplicate of the **NOW ACTIVE TEST** pointer, carrying two official-source Punk streams, historic UUID aliases and one SHA-checked channel-specific logo; physical device validation remains pending.
- `TEST_PUBLIC_KEY.b64`: raw 32-byte Ed25519 test public key (base64), ID `go-apk-test-20261121`. Test private seed is not on GitHub.
- In the archived sequence 1 and pending 2/3, all synthetic candidates remain `quarantined` with non-playable `candidate` streams and no logos. **The active TEST generation 4** preserves those candidates and adds two test-only real active Punk channels with source-backed MP3 streams and a SHA image. It is not deployed to any production endpoint; installed TEST APKs only see it after a successful signed network refresh.

Test HTTPS base (public raw GitHub branch; **not GitHub Pages, not Infomaniak**):

`https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/feature/radio-central-apk-test-endpoint-20261121/grossesondes/radio-test-apk/`

The private test launcher pins this exact base and public key by default. Its source is `tools/Invoke-GrossesOndesCentralTestApk.ps1` in the private PR #320.

**User-authorized promotion completed:** `current.json` was updated byte-for-byte from `pending/test-current-v4.json` on this isolated branch. Releases 1–3 remain immutable. **Do not replace active v4 with v1/v2/v3 as a rollback:** clients correctly reject signed release sequence decreases. Recovery would require a new **higher sequence** signed with the TEST key, after review. No merge or production deployment.

Sequence 1 and its pending synthetic successors demonstrate signed HTTP download, sequence change, offline persistence, signature/digest refusal and non-destructive overlay. The now-active TEST-only v4 prepares the **live Punk and real logo acceptance trial**, supported by official provider sources, 3 time-separated live audio headers per channel, 6 seconds decoded by distro FFmpeg per channel and real artwork SHA/format/size review. These checks are not long-duration user listening; physical device review and acceptance are still required. The RADIO BOB general brand image is NOT claimed as a channel-specific Punk logo. Discovery remains open, without a closed station or source whitelist.

Security: do not reuse the test Ed25519 key in production; do not put the test package's signing key or the production catalog key into any branch.

## Real Punk preview, signed generation 4 (ACTIVE ON ISOLATED TEST BRANCH ONLY)

- `go-station-900010`: **RADIO BOB! BOBs Punk**; official https://www.radiobob.de/punk-stream, approved TEST MP3 192 source; UUID `9618c802-0601-11e8-ae97-52543be04c81`. The public publisher logo is NOT automatically substituted as a specific Punk image.
- `go-station-900011`: **ROCK ANTENNE Punk Rock**; official https://www.rockantenne.de/rockhoeren/streams/punk-rock, MP3. Official channel-specific JPEG SHA-256 `715d7a4cee2db4c3852ccd3336fcabbffd9ad727981538fe2ce43ec567375331` (484148 bytes, 2000×2000). UUID `960c4c2a-0601-11e8-ae97-52543be04c81`.
- Both primary MP3 streams decoded six seconds under real FFmpeg on a public GitHub runner in [evidence run #44893746785](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44893746785); timed independent samples in [run #44893230189](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44893230189). AAC alternatives remain `candidate_verified` until decoder/handset verification.
- Pointer `pending/test-current-v4.json` is signed using the **TEST** key only and refers to immutable content. After explicit user approval, `current.json` now contains the exact same bytes (generation **4**). Only Grosses Ondes **TEST** points here; the mobile app itself has not been rebuilt. Check phone signed sequence/source, Punk genre, radio playback, logo SHA, favorites and Android Auto. **No production merge or publication.**
