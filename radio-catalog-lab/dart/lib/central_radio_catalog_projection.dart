// Read-only, opt-in projection of an authenticated central catalog.
// No Flutter imports, no SharedPreferences and no audio/network side effects.
import 'central_radio_catalog_core.dart';

class CentralProjectedStream {
  const CentralProjectedStream({
    required this.id,
    required this.url,
    required this.codec,
    required this.bitrateKbps,
    required this.priority,
  });
  final String id;
  final String url;
  final String codec;
  final int bitrateKbps;
  final int priority;
}

class CentralProjectedStation {
  const CentralProjectedStation({
    required this.goStationId,
    required this.legacyMediaId,
    required this.legacyAliases,
    required this.displayName,
    required this.genres,
    required this.tags,
    required this.countryCode,
    required this.homepage,
    required this.status,
    required this.verifiedStreams,
    required this.logoSha256,
  });

  final String goStationId;

  // Existing Android Auto MediaItem IDs can keep the old primary UUID.
  // A brand-new station defaults to its permanent GO ID.
  final String legacyMediaId;
  final List<String> legacyAliases;
  final String displayName;
  final List<String> genres;
  final List<String> tags;
  final String countryCode;
  final String homepage;
  final String status;
  final List<CentralProjectedStream> verifiedStreams;
  final String? logoSha256;
  bool get playable => status == 'active' && verifiedStreams.isNotEmpty;
}

class CentralPreservedFavorite {
  const CentralPreservedFavorite({
    required this.goStationId,
    required this.status,
    this.displayName,
  });

  final String goStationId;
  final String status; // active, quarantined, retired
  final String? displayName;
  bool get playable => status == 'active';
}

class CentralFavoritePreview {
  const CentralFavoritePreview({
    required this.originalIdsUnchanged,
    required this.projectedGoIds,
    required this.unresolvedOriginalIds,
    required this.unavailableFavorites,
  });

  // Never overwrite FavoritesService's v1 key with this projection.
  final List<String> originalIdsUnchanged;
  final List<String> projectedGoIds;
  final List<String> unresolvedOriginalIds;
  final List<CentralPreservedFavorite> unavailableFavorites;
}

class CentralCatalogPreview {
  const CentralCatalogPreview({
    required this.stationsByGoId,
    required this.playableStations,
    required this.favorites,
  });

  final Map<String, CentralProjectedStation> stationsByGoId;
  final List<CentralProjectedStation> playableStations;
  final CentralFavoritePreview favorites;
}

class CentralCatalogProjector {
  const CentralCatalogProjector();

  /// [preferredLegacyMediaIds] comes from the currently installed V64
  /// catalog, not from Radio Browser. Invalid preferences fail closed.
  CentralCatalogPreview preview({
    required ValidatedCentralCatalog catalog,
    required Iterable<String> legacyFavoriteIds,
    Map<String, String> preferredLegacyMediaIds = const {},
  }) {
    final byId = <String, CentralProjectedStation>{};
    final playable = <CentralProjectedStation>[];

    for (final record in catalog.stations) {
      final goId = record['go_station_id'] as String;
      final state = (record['status'] as Map<String, dynamic>)['state'] as String;
      final aliases =
          List<String>.unmodifiable((record['legacy_aliases'] as List).cast<String>());
      final preferred = preferredLegacyMediaIds[goId];
      if (preferred != null &&
          preferred != goId &&
          catalog.aliasOwners[preferred] != goId) {
        throw CentralCatalogException(
            'Unrecognized historical MediaItem ID for $goId');
      }

      final mediaId = preferred ?? goId;
      final streamList = <CentralProjectedStream>[];
      for (final item in (record['streams'] as List)) {
        final row = item as Map<String, dynamic>;
        if (row['state'] != 'verified') continue;
        streamList.add(CentralProjectedStream(
          id: row['stream_id'] as String,
          url: row['url'] as String,
          codec: row['codec'] is String ? row['codec'] as String : 'UNKNOWN',
          bitrateKbps: row['bitrate_kbps'] is int ? row['bitrate_kbps'] as int : 0,
          priority: row['priority'] as int,
        ));
      }
      streamList.sort((a, b) {
        final p = a.priority.compareTo(b.priority);
        return p != 0 ? p : a.id.compareTo(b.id);
      });

      if (state == 'active' && streamList.isEmpty) {
        throw CentralCatalogException('Active station without verified stream: $goId');
      }

      final logo = record['logo'];
      final l = logo is Map<String, dynamic> ? logo['sha256'] as String? : null;
      final station = CentralProjectedStation(
        goStationId: goId,
        legacyMediaId: mediaId,
        legacyAliases: aliases,
        displayName: record['display_name'] as String,
        genres: List<String>.unmodifiable((record['genres'] as List).cast<String>()),
        tags: List<String>.unmodifiable(
          (record['tags'] is List
              ? (record['tags'] as List).cast<String>()
              : const <String>[])),
        countryCode: record['country_code'] is String
            ? record['country_code'] as String
            : '',
        homepage: record['homepage'] is String
            ? record['homepage'] as String
            : '',
        status: state,
        verifiedStreams: List<CentralProjectedStream>.unmodifiable(streamList),
        logoSha256: l,
      );
      if (byId.containsKey(goId)) {
        throw CentralCatalogException('Duplicate GO station: $goId');
      }
      byId[goId] = station;
      if (station.playable) playable.add(station);
    }

    // Unknown IDs remain in their original representation, never discarded.
    final original = List<String>.unmodifiable(legacyFavoriteIds);
    final resolved = <String>[];
    final unresolved = <String>[];
    final unavailable = <CentralPreservedFavorite>[];
    final seenGo = <String>{};

    for (final input in original) {
      final goId = catalog.aliasOwners[input] ??
          (catalog.goIds.contains(input) ? input : null);
      if (goId == null) {
        unresolved.add(input);
        continue;
      }
      if (!seenGo.add(goId)) continue;

      resolved.add(goId);
      final station = byId[goId];
      final status = station?.status ?? 'retired';
      if (status != 'active') {
        unavailable.add(CentralPreservedFavorite(
          goStationId: goId,
          status: status,
          displayName: station?.displayName,
        ));
      }
    }

    return CentralCatalogPreview(
      stationsByGoId: Map<String, CentralProjectedStation>.unmodifiable(byId),
      playableStations: List<CentralProjectedStation>.unmodifiable(playable),
      favorites: CentralFavoritePreview(
        originalIdsUnchanged: original,
        projectedGoIds: List<String>.unmodifiable(resolved),
        unresolvedOriginalIds: List<String>.unmodifiable(unresolved),
        unavailableFavorites:
            List<CentralPreservedFavorite>.unmodifiable(unavailable),
      ),
    );
  }
}
