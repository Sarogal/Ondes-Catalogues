// Isolated, read-only artwork lookup for a future central-catalog cutover.
// Not imported by the existing V64 AudioHandler, RootShell or catalog loader.
// A synchronous MediaItem builder must consume only the prepared immutable map.
// Does not download, mutate favorites, delete files or change stream identities.
import 'android_auto_artwork_uris.dart';
import 'central_logo_android_auto_bridge.dart';
import 'central_logo_asset_store.dart';
import 'central_radio_catalog_core.dart';

typedef CentralArtworkLocalVerifier = Future<Uri?> Function({
  required CentralLogoAssetStore store,
  required CentralLogoDescriptor descriptor,
});

class CentralAndroidAutoArtworkIndex {
  CentralAndroidAutoArtworkIndex._(
    Map<String, Uri> artworkByMediaId,
    Map<String, Uri> verifiedCentralByMediaId,
  )   : _artworkByMediaId = Map<String, Uri>.unmodifiable(artworkByMediaId),
        _verifiedCentralByMediaId =
            Map<String, Uri>.unmodifiable(verifiedCentralByMediaId);

  final Map<String, Uri> _artworkByMediaId;
  final Map<String, Uri> _verifiedCentralByMediaId;

  /// Returns a verified local SHA URI, never a genre fallback or a network URL.
  /// The snapshot is prepared off the MediaItem path and remains read-only.
  /// A missing ID, retired station or unavailable asset returns null.
  Uri? verifiedCentralForStationId(String stationId) =>
      _verifiedCentralByMediaId[stationId];

  /// Includes permanent GO IDs and every mapped historical ID for active
  /// stations. Retired/quarantined entries are intentionally excluded.
  int get mappedIds => _artworkByMediaId.length;

  /// The legacy MediaItem builder can remain synchronous. An unknown or
  /// unavailable media ID always gets a locally bundled fallback image.
  Uri forMediaId(String mediaId, {String fallbackGenre = ''}) =>
      _artworkByMediaId[mediaId] ??
      AndroidAutoArtworkUris.forGenre(fallbackGenre);
}

class CentralAndroidAutoArtworkIndexBuilder {
  const CentralAndroidAutoArtworkIndexBuilder({
    this.verifyLocalArtwork =
        CentralLogoAndroidAutoBridge.verifiedArtworkUri,
  });

  /// Uses the Android Auto bridge by default, which checks the exact native
  /// provider directory and verifies the bytes with Flutter's decoder.
  /// Tests can inject an equivalent local verifier. No network access.
  final CentralArtworkLocalVerifier verifyLocalArtwork;

  Future<CentralAndroidAutoArtworkIndex> prepare({
    required ValidatedCentralCatalog catalog,
    required CentralLogoAssetStore store,
  }) async {
    final artwork = <String, Uri>{};
    final verifiedArtwork = <String, Uri>{};
    final ownerByMediaId = <String, String>{};
    final verifiedByDigest = <String, Uri?>{};

    for (final station in catalog.stations) {
      final state = (station['status'] as Map<String, dynamic>)['state'];
      if (state != 'active') continue;

      final goId = station['go_station_id'] as String;
      final genres = station['genres'] as List;
      final fallback = AndroidAutoArtworkUris.forGenre(
        genres.isNotEmpty && genres.first is String
            ? genres.first as String
            : '',
      );
      var selected = fallback;
      Uri? verifiedLocal;

      final descriptor = CentralLogoDescriptor.fromSignedStation(station);
      if (descriptor != null) {
        if (!verifiedByDigest.containsKey(descriptor.sha256)) {
          Uri? local;
          try {
            local = await verifyLocalArtwork(
              store: store,
              descriptor: descriptor,
            );
          } catch (_) {
            // Missing app support directory, malformed/corrupt image or I/O:
            // never expose an unchecked URI to the Android Auto MediaItem.
          }
          // A verifier must never redirect callers to arbitrary content://,
          // HTTP endpoints or a different digest.
          final expected =
              AndroidAutoArtworkUris.forCentralSha256(descriptor.sha256);
          verifiedByDigest[descriptor.sha256] =
              local == expected ? expected : null;
        }
        verifiedLocal = verifiedByDigest[descriptor.sha256];
        selected = verifiedLocal ?? fallback;
      }

      final ids = <String>{
        goId,
        ...(station['legacy_aliases'] as List).cast<String>(),
      };
      for (final id in ids) {
        final previousOwner = ownerByMediaId[id];
        if (previousOwner != null && previousOwner != goId) {
          throw const CentralCatalogException(
            'Conflicting Android Auto artwork identity',
          );
        }
        ownerByMediaId[id] = goId;
        artwork[id] = selected;
        if (verifiedLocal != null) verifiedArtwork[id] = verifiedLocal;
      }
    }
    return CentralAndroidAutoArtworkIndex._(artwork, verifiedArtwork);
  }
}
