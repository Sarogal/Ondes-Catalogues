# Grosses Ondes — HLS manifest-only laboratory (20 November 2026)

## Design and safety
Work isolated on PR #492, targeting discovery PR #474. This is NOT a publisher, and it does not edit catalog stations, logos, favorites, signed manifests, Android Auto or production services.

- HLS detection uses generic URLs ending in .m3u8 (query parameters allowed) in Radio Browser candidate discoveries. No UUID allowlist or limit on total new catalogue admissions is introduced. The five-URL bound is an isolated network test budget only.
- `radio_hls_manifest_evidence.py` parses only received manifest text. It never opens segments, variant streams, audio, encryption keys or any external references, and returns no reference URLs.
- The DNS-pinned transport checks all fetched addresses, retains hostname-based TLS validation, refuses non-public DNS answers and limits redirects. It reads at most 4 KiB for .m3u8 paths, at most four socket reads, without an HTTP Range request for those paths; general audio sampling remains bounded separately.
- A manifest at or above the 4 KiB cap cannot be declared complete. Other conservative pending reasons include incomplete, encrypted, alternative audio, master variants, and finite/endlisted VOD.
- `live_manifest_candidate` means a plausible metadata structure without ENDLIST and with at least two segments and bounded target-duration. It is NOT validated audio, not proof of live radio programming, and not publication approval.
- Technical verification and publication remain false in every HLS pilot result; candidate reports contain no segment URL, keys or binary media.

## GitHub Actions pilot results
Initial pilot #44766631207: success, 742 UUIDs observed during 11 Radio Browser search queries (NOT 742 new stations); five HLS URL probes. `manifest_incomplete`: 1, `master_ambiguous_pending`: 2, `master_single_variant_pending`: 1, `media_incomplete_segments`: 1. Zero confirmed audio.

Expanded bounded-manifest pilot #44767235252: success; the same 11 discovery queries and five HLS probes. `live_manifest_candidate`: 1, `manifest_oversized`: 1, `master_ambiguous_pending`: 2, `master_single_variant_pending`: 1. Zero streams certified or published. The improved result comes from reading up to 4 KiB of metadata, not from following or decoding any HLS segment.

Generic CI #44767129789: success, 200 Python tests covering generic discovery, HLS, stream pinning, response signatures, MPEG/AAC frame evidence, optional PCM decoding and multi-day non-publishing stream observations.

## Still necessary before automatic radio admission
1. Implement an independent, capped and anti-SSRF HLS segment/variant validator with no arbitrary rendition selection, robust redirects, encryption and codec handling. Do not treat manifest hints as proven playable radio.
2. Validate decoder output for HLS media with bounded resource budgets; observe stability on separate actual UTC dates and compare raw source identity against the complete signed catalogue, not against a permanent station UUID allowlist.
3. Test fallback behavior when manifests exceed 4 KiB, are HLS masters with multiple renditions, or have rapidly changing media sequences. Pending must never mean deletion.
4. Validate signing, secure rollout and rollback, all historic stations and RADIO BOB! artworks/favorites, offline cache and Android Auto before any production change.

## Operation
Workflow `.github/workflows/radio-hls-manifest-only-pilot.yml` runs on pushes to this isolated branch only when relevant HLS files change, or via explicit manual dispatch where enabled. There is no scheduled execution or publisher in this laboratory branch. The production catalog and Play Store are untouched.
