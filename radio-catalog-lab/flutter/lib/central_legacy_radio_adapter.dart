// Experimental adapter from an authenticated central catalog projection to
// legacy RadioStation models. No service/controller imports and no writes.
import 'radio_station_stub.dart';
import 'central_radio_catalog_core.dart';
import 'central_catalog_migration_gate.dart';
import 'central_radio_catalog_projection.dart';

class CentralLegacyRadioAdapter {
  const CentralLegacyRadioAdapter();

  /// Diagnostic only. Coverage means the *supplied* V64 snapshot is mapped;
  /// it never means that the installed APK or publication has been validated.
  CentralLegacyCoverageReport auditLegacySnapshot({
    required ValidatedCentralCatalog catalog,
    required Iterable<RadioStation> legacyStations,
    required Iterable<String> legacyFavoriteIds,
    required String sourceLabel,
  }) {
    return const CentralCatalogMigrationGate().audit(
      catalog: catalog,
      legacyStations: legacyStations.map(
        (station) => CentralLegacyObservation(
          primaryMediaId: station.id,
          historicalIds: station.allStationIds,
        ),
      ),
      legacyFavoriteIds: legacyFavoriteIds,
      sourceLabel: sourceLabel,
    );
  }

  /// The active V64 catalog supplies the stable MediaItem ID for already
  /// installed stations. A GO identity found under multiple distinct V64
  /// primary IDs is ambiguous and must be resolved before any cut-over.
  Map<String, String> preferredMediaIdsFromLegacy({
    required ValidatedCentralCatalog catalog,
    required Iterable<RadioStation> legacyStations,
  }) {
    final byGoId = <String, String>{};
    for (final old in legacyStations) {
      final previousId = old.id.trim();
      if (previousId.isEmpty) continue;

      final matchedGoIds = <String>{
        for (final alias in old.allStationIds)
          if (catalog.goIds.contains(alias))
            alias
          else if (catalog.aliasOwners.containsKey(alias))
            catalog.aliasOwners[alias]!,
      };
      if (matchedGoIds.isEmpty) continue;
      if (matchedGoIds.length != 1) {
        throw CentralCatalogException(
            'Ambiguous V64 station aliases for $previousId');
      }
      final goId = matchedGoIds.single;
      if (previousId != goId && catalog.aliasOwners[previousId] != goId) {
        throw CentralCatalogException(
            'V64 primary MediaItem ID is not an admitted alias: $previousId');
      }
      final first = byGoId[goId];
      if (first != null && first != previousId) {
        throw CentralCatalogException(
            'Two V64 MediaItem IDs mapped to one permanent GO station: $goId');
      }
      byGoId[goId] = previousId;
    }
    return Map<String, String>.unmodifiable(byGoId);
  }

  /// Only active and verified streams are converted to playable RadioStation.
  /// Quarantined and retired favorites remain in preview.favorites, not here.
  /// Every logo remains a genre fallback until its SHA-verified local object
  /// is installed by the separate future permanent logo cache.
  List<RadioStation> toPlayableLegacyStations(
      CentralCatalogPreview preview, {
      Iterable<RadioStation> legacyStations = const <RadioStation>[],
    }) {
    // A central snapshot may lack a qualified SHA logo even when the existing
    // app already displays a perfectly good historical logo. Never blank it.
    // This mapping is keyed by the unchanged PRIMARY MediaItem ID, never
    // station name, stream URL or image URL.
    final legacyByMediaId = <String, RadioStation>{};
    for (final station in legacyStations) {
      if (station.id.isEmpty ||
          legacyByMediaId.containsKey(station.id)) {
        throw const CentralCatalogException(
            'Duplicate/invalid historical media identity');
      }
      legacyByMediaId[station.id] = station;
    }
    final results = <RadioStation>[];
    final usedMediaIds = <String>{};
    for (final item in preview.playableStations) {
      if (!item.playable || item.verifiedStreams.isEmpty) {
        throw CentralCatalogException(
            'Unplayable central entry in active projection');
      }
      final primaryId = item.legacyMediaId;
      if (!usedMediaIds.add(primaryId)) {
        throw CentralCatalogException(
            'Duplicate legacy MediaItem ID across playable GO stations');
      }

      final genre = item.genres.first;
      if (genre == 'Tous' ||
          !MetalGenreResolver.displayGenres.contains(genre)) {
        throw CentralCatalogException(
            'Unsupported central genre for ${item.goStationId}: $genre');
      }

      final streams = item.verifiedStreams;
      final primary = streams.first;
      final variants = <RadioStreamVariant>[];

      for (final stream in streams.skip(1)) {
        variants.add(RadioStreamVariant(
          stationId: primaryId,
          streamUrl: stream.url,
          codec: stream.codec,
          bitrate: stream.bitrateKbps,
        ));
      }

      // Preserve every legacy favorite/MediaItem ID through streamVariants:
      // RadioStation.allStationIds is used by both existing favorites code
      // and historical station-resolution helpers. The primary URL is only
      // duplicated as an alias carrier; quality deduplication stays legacy.
      for (final alias in <String>{...item.legacyAliases, item.goStationId}) {
        if (alias == primaryId) continue;
        variants.add(RadioStreamVariant(
          stationId: alias,
          streamUrl: primary.url,
          codec: primary.codec,
          bitrate: primary.bitrateKbps,
        ));
      }

      // A non-matching/unknown old ID is NEVER used as an image fallback.
      // New stations have no legacy artwork and keep their genre fallback.
      final historical = legacyByMediaId[primaryId];
      results.add(RadioStation(
        id: primaryId,
        name: item.displayName,
        genre: genre,
        tags: item.tags.isEmpty ? item.genres : item.tags,
        streamUrl: primary.url,
        // Keep the historical logo EXACTLY as it already appears. A signed
        // central SHA asset will supersede it later through the separately
        // verified SHA cache path, never by clearing this URL.
        logoUrl: historical?.logoUrl ?? '',
        homepage: item.homepage,
        countryCode: item.countryCode,
        codec: primary.codec,
        bitrate: primary.bitrateKbps,
        votes: historical?.votes ?? 0,
        streamVariants: List<RadioStreamVariant>.unmodifiable(variants),
        catalogLogoUrl: historical?.catalogLogoUrl ?? '',
        logoSource: historical?.logoSource ?? 'genre-fallback',
      ));
    }
    return List<RadioStation>.unmodifiable(results);
  }
}
