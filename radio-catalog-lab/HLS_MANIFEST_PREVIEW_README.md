# Grosses Ondes — HLS bounded qualification laboratory (20 November 2026)

## Design and safety
Work isolated on PR #492, targeting discovery PR #474. This is NOT a publisher, and it does not edit catalog stations, logos, favorites, signed manifests, Android Auto or production services.

- HLS detection uses generic URLs ending in .m3u8 (query parameters allowed) in Radio Browser candidate discoveries. No UUID allowlist or limit on total new catalogue admissions is introduced. The five-URL bound is an isolated network test budget only.
- `radio_hls_manifest_evidence.py` only parses bounded metadata; it never opens external references or returns URLs. Separately and only with explicit opt-in, `radio_hls_segment_evidence.py` may request ONE manifest-selected segment, after validating its URL and using the DNS-pinned transport.
- The DNS-pinned transport checks all fetched addresses, retains hostname-based TLS validation, refuses non-public DNS answers and limits redirects. It reads at most 4 KiB for .m3u8 paths, at most four socket reads, without an HTTP Range request for those paths; general audio sampling remains bounded separately.
- A manifest at or above the 4 KiB cap cannot be declared complete. Other conservative pending reasons include incomplete, encrypted, alternative audio, master variants, and finite/endlisted VOD.
- `live_manifest_candidate` means a plausible metadata structure without ENDLIST and with at least two segments and bounded target-duration. It is NOT validated audio, not proof of live radio programming, and not publication approval.
- Technical verification and publication remain false in every HLS pilot result; candidate reports contain no segment URL, keys or binary media.

## GitHub Actions pilot results
Initial pilot #44766631207: success, 742 UUIDs observed during 11 Radio Browser search queries (NOT 742 new stations); five HLS URL probes. `manifest_incomplete`: 1, `master_ambiguous_pending`: 2, `master_single_variant_pending`: 1, `media_incomplete_segments`: 1. Zero confirmed audio.

Expanded bounded-manifest pilot #44767235252: success; the same 11 discovery queries and five HLS probes. `live_manifest_candidate`: 1, `manifest_oversized`: 1, `master_ambiguous_pending`: 2, `master_single_variant_pending`: 1. Zero streams certified or published. The improved result comes from reading up to 4 KiB of metadata, not from following or decoding any HLS segment.

Generic CI #44767129789: success, 200 Python tests covering generic discovery, HLS, stream pinning, response signatures, MPEG/AAC frame evidence, optional PCM decoding and multi-day non-publishing stream observations.

## Still necessary before automatic radio admission
1. The first independent segment/variant checker is implemented and tested: up to one simple live-media segment, at most one master variant, no arbitrary choice between qualities, no encryption/key/initialization-map fetch. Continue with real PCM decoding reliability, advanced HLS codecs, byte ranges, segment redirects (only after safety review), and missing-URL format coverage. Do not treat manifest hints or TS structure as proven playable radio.
2. Validate decoder output for HLS media with bounded resource budgets; observe stability on separate actual UTC dates and compare raw source identity against the complete signed catalogue, not against a permanent station UUID allowlist.
3. Test fallback behavior when manifests exceed 4 KiB, are HLS masters with multiple renditions, or have rapidly changing media sequences. Pending must never mean deletion.
4. Validate signing, secure rollout and rollback, all historic stations and RADIO BOB! artworks/favorites, offline cache and Android Auto before any production change.

## Operation
Workflow `.github/workflows/radio-hls-manifest-only-pilot.yml` runs on pushes to this isolated branch only when relevant HLS files change, or via explicit manual dispatch where enabled. There is no scheduled execution or publisher in this laboratory branch. The production catalog and Play Store are untouched.

## Extended live HLS segment pilot — same day

On the isolated branch, the HLS-specific network pilot now checks at most five `.m3u8` candidates and **at most one** independently validated segment in a run. A selected simple live-media manifest is preferred to a master playlist; if only a master is available, the system may follow at most one declared variant, never select arbitrarily among multiple renditions. Two explicit manifest redirects at most are validated hop by hop, preserving public DNS pinning and TLS downgrade protection.

HLS references to a same-origin relative segment or a public HTTPS CDN may be sampled with a separate **16 KiB maximum HTTP Range** request. Destination is revalidated, DNS resolves only to global addresses and TLS certificates are checked. Any segment redirect, private IP, credential-bearing URL, insecure absolute HTTP reference, map, encryption key, byte-range, unsupported segment format or multi-variant master is not followed. No station or full media is downloaded and no raw URL/segment/audio bytes are uploaded to GitHub artifacts.

Successful real HLS pilot [#44772581525](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44772581525): 11 Radio Browser searches returned 744 observed UUIDs (not 744 new stations); five HLS URL probes; one candidate live manifest; **one bounded segment with recognizable structure**; 0 technical approvals and 0 publications. Earlier runs correctly rejected unsafe references and showed only sanitized pending reasons.

The external FFmpeg decoder experiment [#44773156031](https://github.com/Sarogal/Ondes-Catalogues/actions/runs/44773156031) returned one structural HLS segment but **zero demonstrated PCM decodes**. The latest code also records an aggregate decoder outcome category (`not_decoded`, `decoder_failed_or_timed_out`, etc.) without media bytes, station links or credentials. A missing PCM proof must not be reinterpreted as proof of a dead radio.

Neither segment structure nor a hypothetical later positive PCM prefix establishes multi-day continuous playback, editorial identity or suitability for automatic publication. The app's first update still requires end-to-end signed catalogue, historic radio preservation, artwork SHA caching, favorites and Android Auto tests.
