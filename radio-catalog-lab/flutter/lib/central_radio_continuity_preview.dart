// Release 1: additive, non-destructive read-only preview of a central catalog.
// No provider, controller, player, preferences, disk writes, or network imports.
// NOT a live cut-over or a permission to retire legacy stations.
import 'radio_station_stub.dart';
import 'central_legacy_radio_adapter.dart';
import 'central_radio_catalog_core.dart';
import 'central_radio_catalog_projection.dart';

class CentralRadioContinuityPreview {
  CentralRadioContinuityPreview({
    required Iterable<RadioStation> stations,
    required Iterable<String> preservedFavoriteIds,
    required Iterable<String> refreshedHistoricalIds,
    required Iterable<String> retainedHistoricalIds,
    required Iterable<String> appendedCentralGoIds,
    required Iterable<String> blockedCentralGoIds,
  })  : stations = List<RadioStation>.unmodifiable(stations),
        preservedFavoriteIds = List<String>.unmodifiable(preservedFavoriteIds),
        refreshedHistoricalIds = List<String>.unmodifiable(refreshedHistoricalIds),
        retainedHistoricalIds = List<String>.unmodifiable(retainedHistoricalIds),
        appendedCentralGoIds = List<String>.unmodifiable(appendedCentralGoIds),
        blockedCentralGoIds = List<String>.unmodifiable(blockedCentralGoIds);

  final List<RadioStation> stations;
  // A projection is never allowed to rewrite FavoritesService's v1 IDs.
  final List<String> preservedFavoriteIds;
  final List<String> refreshedHistoricalIds;
  final List<String> retainedHistoricalIds;
  final List<String> appendedCentralGoIds;
  final List<String> blockedCentralGoIds;

  // Eligibility still requires the full migration audit, real stream tests,
  // cache/Android Auto checks and a separate decision to activate.
  bool get authorizedForRelease => false;
}

class CentralRadioContinuityPlanner {
  const CentralRadioContinuityPlanner();

  /// Preserve EVERY pre-existing station in its original position, including
  /// quarantined, retired, unmapped and duplicate-named station entries. An
  /// authenticated remote catalog can refresh a known station only when its
  /// primary MediaItem ID matches exactly; a collision never silently merges.
  /// New remote-only stations may be appended when their IDs do not overlap
  /// any historical identity (primary or variant).
  CentralRadioContinuityPreview preview({
    required ValidatedCentralCatalog catalog,
    required CentralCatalogPreview central,
    required Iterable<RadioStation> legacyStations,
    required Iterable<String> legacyFavoriteIds,
  }) {
    if (!catalog.goIds.containsAll(central.stationsByGoId.keys)) {
      throw const CentralCatalogException('Untrusted central projection IDs');
    }
    final historical = List<RadioStation>.unmodifiable(legacyStations);
    final primaryIds = <String>{};
    final allHistoricalIds = <String>{};
    for (final station in historical) {
      if (station.id.trim().isEmpty || !primaryIds.add(station.id)) {
        throw const CentralCatalogException(
            'Duplicate or empty primary legacy station identity');
      }
      allHistoricalIds.addAll(station.allStationIds);
    }

    final converted = const CentralLegacyRadioAdapter()
        .toPlayableLegacyStations(central, legacyStations: historical);
    if (converted.length != central.playableStations.length) {
      throw const CentralCatalogException('Central projection lost a station');
    }
    final candidates = <String, RadioStation>{};
    for (var i = 0; i < converted.length; i++) {
      final goId = central.playableStations[i].goStationId;
      if (candidates.containsKey(goId)) {
        throw const CentralCatalogException('Duplicate central GO identity');
      }
      candidates[goId] = converted[i];
    }

    String? ownerOf(String id) => catalog.aliasOwners[id] ??
        (catalog.goIds.contains(id) ? id : null);

    final result = <RadioStation>[];
    final refreshed = <String>[];
    final retained = <String>[];
    final consumed = <String>{};

    for (final old in historical) {
      final goId = ownerOf(old.id);
      final candidate = goId == null ? null : candidates[goId];
      if (candidate == null || candidate.id != old.id ||
          !consumed.add(goId!)) {
        // An incomplete central catalog or a quarantine can NEVER cause an
        // existing radio to disappear in this preview. The original stream,
        // image, MediaItem identity and quality variants all remain intact.
        result.add(old);
        retained.add(old.id);
        continue;
      }
      if (candidate.logoUrl != old.logoUrl ||
          candidate.logoSource != old.logoSource ||
          candidate.catalogLogoUrl != old.catalogLogoUrl) {
        throw const CentralCatalogException(
            'A central conversion attempted to erase historical artwork');
      }
      result.add(candidate);
      refreshed.add(old.id);
    }

    final appended = <String>[];
    final blocked = <String>[];
    for (final projected in central.playableStations) {
      final goId = projected.goStationId;
      if (consumed.contains(goId)) continue;
      final candidate = candidates[goId]!;
      // An old UUID/variant might map to this GO station even when its primary
      // ID is not the preferred one. Do not add a second card for it.
      final clashesWithHistory = catalog.aliasOwners.entries.any(
            (entry) => entry.value == goId &&
                allHistoricalIds.contains(entry.key),
          ) ||
          allHistoricalIds.contains(goId) ||
          candidate.allStationIds.any(allHistoricalIds.contains);
      if (clashesWithHistory || primaryIds.contains(candidate.id) ||
          result.any((station) => station.id == candidate.id)) {
        blocked.add(goId);
        continue;
      }
      result.add(candidate);
      appended.add(goId);
    }

    if (result.length < historical.length ||
        !result.take(historical.length).every((s) =>
            primaryIds.contains(s.id))) {
      throw const CentralCatalogException('Historical station loss');
    }

    return CentralRadioContinuityPreview(
      stations: result,
      preservedFavoriteIds: legacyFavoriteIds,
      refreshedHistoricalIds: refreshed,
      retainedHistoricalIds: retained,
      appendedCentralGoIds: appended,
      blockedCentralGoIds: blocked,
    );
  }
}
