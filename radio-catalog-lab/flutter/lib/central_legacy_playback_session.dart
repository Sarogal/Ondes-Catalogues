// Experimental opt-in-only V64 playback facade around signed catalog identity.
// Does not modify GrossesOndesAudioHandler, preferences, recents or cache keys.
import 'radio_station_stub.dart';
import 'central_catalog_media_identity.dart';
import 'central_legacy_radio_adapter.dart';
import 'central_radio_catalog_core.dart';
import 'central_radio_catalog_projection.dart';
import 'central_verified_stream_plan.dart';

class CentralLegacyMediaChoice {
  const CentralLegacyMediaChoice({
    required this.status,
    required this.station,
    required this.browseContext,
    required this.canonicalMediaId,
    required this.goStationId,
  });

  final CentralMediaStatus status;
  final RadioStation? station;
  final String? browseContext;
  final String? canonicalMediaId;
  final String? goStationId;
  bool get playable => status == CentralMediaStatus.playable && station != null;
}

class CentralLegacyPlaybackSession {
  CentralLegacyPlaybackSession({
    required ValidatedCentralCatalog catalog,
    required CentralCatalogPreview preview,
    Iterable<RadioStation> legacyStations = const <RadioStation>[],
    CentralLegacyRadioAdapter adapter = const CentralLegacyRadioAdapter(),
  }) : _media = CentralMediaIdentityResolver(catalog: catalog, preview: preview),
       _preview = preview {
    // Keep historical logo provenance when preparing a central media tree.
    // Legacy IDs and artwork remain available even before SHA migration.
    final stations = adapter.toPlayableLegacyStations(
      preview, legacyStations: legacyStations);
    for (final projected in preview.playableStations) {
      final matches = stations
          .where((s) => s.id == projected.legacyMediaId)
          .toList(growable: false);
      if (matches.length != 1) {
        throw CentralCatalogException(
            'One central station must map to exactly one V64 RadioStation');
      }
      _byGoId[projected.goStationId] = matches.single;
    }
  }

  final CentralMediaIdentityResolver _media;
  final CentralCatalogPreview _preview;
  final Map<String, RadioStation> _byGoId = <String, RadioStation>{};
  late final CentralVerifiedStreamPlan _verifiedStreams =
      CentralVerifiedStreamPlan(media: _media);

  /// Future cut-over only. Unlike V64 availableStreams, this preserves
  /// independent verified fallback endpoints with identical codec/bitrate.
  /// Never mutate the existing player's preferences or stream list here.
  List<CentralProjectedStream> verifiedPlaybackCandidates(
    String historicalStationId, {
    String? previousVerifiedUrl,
  }) => _verifiedStreams.forStationId(
    historicalStationId,
    preferredVerifiedUrl: previousVerifiedUrl,
  );

  List<CentralProjectedStream> verifiedAndroidAutoCandidates(
    String mediaId, {
    String? previousVerifiedUrl,
  }) => _verifiedStreams.forAndroidAutoMediaId(
    mediaId,
    preferredVerifiedUrl: previousVerifiedUrl,
  );


  CentralLegacyMediaChoice resolveAndroidAutoMediaId(String mediaId) {
    final identity = _media.resolveMediaId(mediaId);
    return CentralLegacyMediaChoice(
      status: identity.status,
      station: identity.playable ? _byGoId[identity.goStationId] : null,
      browseContext: identity.browseContext,
      canonicalMediaId: identity.canonicalMediaId,
      goStationId: identity.goStationId,
    );
  }

  /// Resolve a previously serialized V64 recent/last station by its ID only,
  /// never by a potentially shared stream URL. Materialize fresh from the
  /// signed central snapshot: do NOT call RadioStation.fromJson on this result.
  RadioStation? restorePreviousStation(RadioStation stored) {
    final match = _media.resolveStationId(stored.id);
    if (!match.playable) return null;
    final projected = _preview.stationsByGoId[match.goStationId];
    final current = _byGoId[match.goStationId];
    if (projected == null || current == null) return null;

    // When the same exact old URL remains verified, restore that quality.
    // Otherwise use the current editorial primary stream. Never restore an
    // old unverified URL and never infer identity from a shared stream.
    for (final stream in projected.verifiedStreams) {
      if (stream.url == stored.streamUrl.trim()) {
        return current.copyWith(
          streamUrl: stream.url,
          codec: stream.codec,
          bitrate: stream.bitrateKbps,
        );
      }
    }
    return current;
  }

  /// Preview only; caller must keep original saved favorite IDs untouched.
  List<RadioStation> activeFavorites(Iterable<String> storedFavoriteIds) {
    final seen = <String>{};
    final result = <RadioStation>[];
    for (final id in storedFavoriteIds) {
      final match = _media.resolveStationId(id);
      if (!match.playable || !seen.add(match.goStationId!)) continue;
      final station = _byGoId[match.goStationId];
      if (station != null) result.add(station);
    }
    return List<RadioStation>.unmodifiable(result);
  }
}
