// Pure-Dart, read-only compatibility resolver for existing Android Auto IDs.
// This is NOT wired to GrossesOndesAudioHandler.
import 'central_radio_catalog_core.dart';
import 'central_radio_catalog_projection.dart';

enum CentralMediaStatus { playable, quarantined, retired, unknown, malformed }

class CentralMediaLookup {
  const CentralMediaLookup({
    required this.status,
    required this.rawStationId,
    required this.goStationId,
    required this.browseContext,
    required this.station,
    required this.canonicalMediaId,
  });

  final CentralMediaStatus status;
  final String? rawStationId;
  final String? goStationId;
  final String? browseContext;
  final CentralProjectedStation? station;
  final String? canonicalMediaId;
  bool get playable => status == CentralMediaStatus.playable && station != null;
}

class CentralMediaIdentityResolver {
  CentralMediaIdentityResolver({
    required this.catalog,
    required this.preview,
  }) {
    if (!catalog.goIds.containsAll(preview.stationsByGoId.keys)) {
      throw const CentralCatalogException(
          'Projection contains identities outside the signed catalog');
    }
    for (final item in preview.stationsByGoId.values) {
      if (!catalog.goIds.contains(item.goStationId) ||
          item.goStationId != preview.stationsByGoId[item.goStationId]?.goStationId ||
          (item.legacyMediaId != item.goStationId &&
              catalog.aliasOwners[item.legacyMediaId] != item.goStationId)) {
        throw const CentralCatalogException('Invalid projected media identity');
      }
    }
  }

  static const stationPrefix = 'go:auto:station:';
  final ValidatedCentralCatalog catalog;
  final CentralCatalogPreview preview;

  CentralMediaLookup resolveStationId(String requestedId, {String? context}) {
    if (requestedId.isEmpty ||
        requestedId.length > 256 ||
        _containsControl(requestedId) ||
        (context != null && (context.isEmpty || context.length > 1024 ||
            _containsControl(context)))) {
      return _invalid(CentralMediaStatus.malformed, requestedId, context);
    }

    final goId = catalog.aliasOwners[requestedId] ??
        (catalog.goIds.contains(requestedId) ? requestedId : null);

    if (goId == null) {
      return _invalid(CentralMediaStatus.unknown, requestedId, context);
    }
    final station = preview.stationsByGoId[goId];

    if (station == null) {
      // A preserved tombstone may be favorited but must not start playback.
      return CentralMediaLookup(
        status: CentralMediaStatus.retired,
        rawStationId: requestedId,
        goStationId: goId,
        browseContext: context,
        station: null,
        canonicalMediaId: null,
      );
    }
    if (!station.playable) {
      return CentralMediaLookup(
        status: station.status == 'quarantined'
            ? CentralMediaStatus.quarantined
            : CentralMediaStatus.retired,
        rawStationId: requestedId,
        goStationId: goId,
        browseContext: context,
        station: null,
        canonicalMediaId: null,
      );
    }

    return CentralMediaLookup(
      status: CentralMediaStatus.playable,
      rawStationId: requestedId,
      goStationId: goId,
      browseContext: context,
      station: station,
      canonicalMediaId: _encode(station.legacyMediaId, context),
    );
  }

  CentralMediaLookup resolveMediaId(String mediaId) {
    if (mediaId.length > 2048 || !mediaId.startsWith(stationPrefix)) {
      return _invalid(CentralMediaStatus.malformed, null, null);
    }
    final body = mediaId.substring(stationPrefix.length);
    final separator = body.indexOf('|');
    final encodedId = separator < 0 ? body : body.substring(0, separator);
    final encodedContext = separator < 0 ? null : body.substring(separator + 1);

    if (encodedId.isEmpty ||
        (encodedContext != null &&
            (encodedContext.isEmpty || encodedContext.contains('|')))) {
      return _invalid(CentralMediaStatus.malformed, null, null);
    }

    try {
      final id = Uri.decodeComponent(encodedId);
      final context = encodedContext == null
          ? null
          : Uri.decodeComponent(encodedContext);
      // Accept only canonical round-trips: forbid ambiguous double-encoding,
      // raw pipe separators in IDs, malformed percent sequences or controls.
      if (Uri.encodeComponent(id) != encodedId ||
          (context != null && Uri.encodeComponent(context) != encodedContext)) {
        return _invalid(CentralMediaStatus.malformed, null, null);
      }
      return resolveStationId(id, context: context);
    } on FormatException {
      return _invalid(CentralMediaStatus.malformed, null, null);
    } on ArgumentError {
      // Uri.decodeComponent throws ArgumentError for malformed percent escapes.
      return _invalid(CentralMediaStatus.malformed, null, null);
    }
  }

  static String _encode(String stationId, String? context) {
    final id = Uri.encodeComponent(stationId);
    return context == null
        ? '$stationPrefix$id'
        : '$stationPrefix$id|${Uri.encodeComponent(context)}';
  }

  static bool _containsControl(String s) =>
      s.runes.any((c) => c < 32 || c == 127);

  static CentralMediaLookup _invalid(
      CentralMediaStatus status, String? id, String? context) {
    return CentralMediaLookup(
      status: status,
      rawStationId: id,
      goStationId: null,
      browseContext: context,
      station: null,
      canonicalMediaId: null,
    );
  }
}
