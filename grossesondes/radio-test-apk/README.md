# Grosses Ondes — non-production radio catalog TEST for APK diagnostic

**Date: 2026-11-21. Not the Grosses Ondes published radio catalog.**

This branch hosts deliberately synthetic, non-playable diagnostic catalog generations for the isolated Android APK in `Sarogal/GrossesOndes` PR #320. These are TEST-FIXTURE objects, not an editorial publication of any real station.

- `current.json`: signed Ed25519 pointer, initially sequence **1**.
- `releases/<sha256>.json`: immutable payloads for sequences 1, 2 and 3.
- `pending/test-current-v2.json`: reserved signed test pointer for sequence 2, NOT active.
- `pending/test-current-v3.json`: reserved signed test pointer for sequence 3, NOT active.
- `TEST_PUBLIC_KEY.b64`: raw 32-byte Ed25519 test public key (base64), ID `go-apk-test-20261121`. Test private seed is not on GitHub.
- All synthetic candidates remain `quarantined`. All stream states are `candidate`; no verified stream exists in any payload, no image or logo is supplied and no radio is made playable. Consequently, the real app should continue presenting its historical V64 radios, with sequence displayed in the TEST menu.

Test HTTPS base (public raw GitHub branch; **not GitHub Pages, not Infomaniak**):

`https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/feature/radio-central-apk-test-endpoint-20261121/grossesondes/radio-test-apk/`

The private test launcher pins this exact base and public key by default. Its source is `tools/Invoke-GrossesOndesCentralTestApk.ps1` in the private PR #320.

**Manual opt-in to sequence 2:** only after the sequence 1 phone/offline test, update `current.json` with the exact bytes from `pending/test-current-v2.json` (do not edit the signature or body). For sequence 3, similarly copy `pending/test-current-v3.json` after the second test. Release payloads MUST exist before changing the pointer. This public branch is not merged or deployed as a production catalog.

The test fixture demonstrates signed HTTP download, sequence change, offline persistence, signature/digest refusal and non-destructive overlay. It does NOT demonstrate a playable remotely added station or real RADIO BOB! logo. Those require separately verified real audio/artwork and editorial approval, without a closed station whitelist.

Security: do not reuse the test Ed25519 key in production; do not put the test package's signing key or the production catalog key into any branch.
