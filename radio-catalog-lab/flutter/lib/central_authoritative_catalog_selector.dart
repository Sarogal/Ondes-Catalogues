// Opt-in preparation for the future SERVER-AUTHORITATIVE radio release.
//
// Unlike the historical Release1 continuity overlay, this selector never
// consults, merges or adds a V64 station to the accepted radio list.
// Only Ed25519-verified central snapshots may become playable stations.
//
// This module is intentionally NOT wired to CatalogController until a
// complete, verified and editorially qualified catalog is published.
// No application or production behavior changes by adding this class.
import 'radio_station_stub.dart';
import 'central_legacy_radio_adapter.dart';
import 'central_radio_catalog_client.dart';
import 'central_radio_catalog_core.dart';
import 'central_radio_catalog_projection.dart';

enum CentralAuthoritySource {
  signedNetwork,
  signedDisk,
  signedDiskAfterNetworkFailure,
  signedDiskAfterProjectionFailure,
}

class CentralAuthoritySelection {
  CentralAuthoritySelection({
    required this.source,
    required this.snapshot,
    required Iterable<RadioStation> stations,
    required Iterable<String> originalFavoriteIds,
    required Iterable<String> unavailableFavoriteIds,
    required Iterable<String> unresolvedFavoriteIds,
    required this.networkAttempted,
    required this.networkFailed,
  })  : stations = List<RadioStation>.unmodifiable(stations),
        originalFavoriteIds = List<String>.unmodifiable(originalFavoriteIds),
        unavailableFavoriteIds =
            List<String>.unmodifiable(unavailableFavoriteIds),
        unresolvedFavoriteIds = List<String>.unmodifiable(unresolvedFavoriteIds);

  final CentralAuthoritySource source;
  final ValidatedCentralCatalog snapshot;
  final List<RadioStation> stations;
  final List<String> originalFavoriteIds;
  final List<String> unavailableFavoriteIds;
  final List<String> unresolvedFavoriteIds;
  final bool networkAttempted;
  final bool networkFailed;

  int get signedSequence => snapshot.pointer.sequence;

  /// This is intentionally only a prepared view, NOT an activation approval.
  /// Coverage, published signing key, logos, Android Auto and live-phone tests
  /// must be passed separately before the production cutover.
  bool get productionReleaseAuthorized => false;
}

class CentralAuthoritativeCatalogSelector {
  const CentralAuthoritativeCatalogSelector();

  /// A null result means there is no safely usable signed source.
  ///
  /// The caller must NOT silently relabel an embedded V64 bootstrap as a
  /// "central catalog" or merge unverified Radio Browser results. A first
  /// install without Internet and without a signed cached snapshot should
  /// present an explicit offline-unavailable state.
  ///
  /// [allowNetwork] is explicit. Disk-only reads never make HTTP calls.
  Future<CentralAuthoritySelection?> select({
    required CentralRadioCatalogClient client,
    required Iterable<String> favoriteIds,
    bool allowNetwork = false,
    int minimumSignedSequence = 1,
  }) async {
    if (minimumSignedSequence < 1) {
      throw const CentralCatalogException('Invalid minimum release sequence');
    }
    final favorites = List<String>.unmodifiable(favoriteIds);
    List<ValidatedCentralCatalog> history;
    try {
      history = await client.disk.loadVerifiedHistory(client.verifier);
    } catch (_) {
      // Conflict or tampering in signed disk history must fail closed.
      history = const <ValidatedCentralCatalog>[];
    }

    ValidatedCentralCatalog? latestFromNetwork;
    bool networkFailed = false;
    if (allowNetwork) {
      try {
        latestFromNetwork = (await client.sync()).snapshot;
      } catch (_) {
        networkFailed = true;
      }
    }

    final candidates = <ValidatedCentralCatalog>[
      if (latestFromNetwork != null) latestFromNetwork,
      for (final saved in history)
        if (latestFromNetwork == null ||
            latestFromNetwork.pointer.sha256 != saved.pointer.sha256 ||
            latestFromNetwork.pointer.sequence != saved.pointer.sequence)
          saved,
    ];

    var priorRejected = false;
    for (final candidate in candidates) {
      try {
        // The TEST v4 predecessor contains only a few synthetic entries.
        // A new authoritative installation requires the first fully qualified
        // 320-radio signed generation, never that historical probe snapshot.
        if (candidate.pointer.sequence < minimumSignedSequence) {
          priorRejected = true;
          continue;
        }
        // The projection is built exclusively from the signed candidate.
        // Do not pass the old V64 list to the legacy-model compatibility
        // adapter. New, updated and retired stations follow the server.
        // The first historical alias is the canonical V64 primary UUID
        // restored by the signed migration. Do NOT re-read any embedded
        // V64 stations: both the playable list and legacy ID mapping come
        // solely from the authenticated server payload.
        final stableMediaIds = <String, String>{
          for (final station in candidate.stations)
            if ((station['legacy_aliases'] as List).isNotEmpty)
              station['go_station_id'] as String:
                  (station['legacy_aliases'] as List).first as String,
        };
        final preview = const CentralCatalogProjector().preview(
          catalog: candidate,
          legacyFavoriteIds: favorites,
          preferredLegacyMediaIds: stableMediaIds,
        );
        final rawPlayable = const CentralLegacyRadioAdapter()
            .toPlayableLegacyStations(preview);
        // Only the signed catalog can supply artwork keys. A signed URL is
        // metadata, NOT a permission to display unverified downloaded bytes.
        // The authority-only widget cache resolves this URL strictly through
        // the digest-verified CentralRelease1ExperimentalArtwork map.
        final signedArtworkUrls = <String, String>{
          for (final record in candidate.stations)
            if (record['logo'] is Map<String, dynamic>)
              record['go_station_id'] as String:
                  (record['logo'] as Map<String, dynamic>)['url'] as String,
        };
        final playable = rawPlayable.map((station) {
          final goId = candidate.aliasOwners[station.id] ?? station.id;
          final signedUrl = signedArtworkUrls[goId];
          return signedUrl == null
              ? station
              : station.copyWith(
                  logoUrl: signedUrl,
                  catalogLogoUrl: signedUrl,
                  logoSource: 'central-signed-sha-only',
                );
        }).toList(growable: false);
        if (playable.length != preview.playableStations.length ||
            playable.map((s) => s.id).toSet().length != playable.length) {
          throw const CentralCatalogException(
            'Authoritative projection lost or duplicated an active station',
          );
        }
        // An inactive historical favorite retains its stored original ID.
        final unavailable = <String>{
          for (final old in favorites)
            if (preview.favorites.unavailableFavorites.any(
              (record) => record.goStationId ==
                  (candidate.aliasOwners[old] ??
                      (candidate.goIds.contains(old) ? old : null)),
            ))
              old,
        };
        final source = identical(candidate, latestFromNetwork)
            ? CentralAuthoritySource.signedNetwork
            : priorRejected
                ? CentralAuthoritySource.signedDiskAfterProjectionFailure
                : networkFailed
                    ? CentralAuthoritySource.signedDiskAfterNetworkFailure
                    : CentralAuthoritySource.signedDisk;
        return CentralAuthoritySelection(
          source: source,
          snapshot: candidate,
          stations: playable,
          originalFavoriteIds: favorites,
          unavailableFavoriteIds: unavailable,
          unresolvedFavoriteIds: preview.favorites.unresolvedOriginalIds,
          networkAttempted: allowNetwork,
          networkFailed: networkFailed,
        );
      } catch (_) {
        // E.g. a signed but incompatible future genre: keep an older signed
        // compatible snapshot, NEVER supplement it with unsigned V64 data.
        priorRejected = true;
      }
    }
    return null;
  }
}
