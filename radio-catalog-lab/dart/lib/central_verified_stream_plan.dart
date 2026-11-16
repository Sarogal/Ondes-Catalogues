// Experimental stream fallback selector for the signed central catalogue.
// Never uses V64 RadioStation.availableStreams: that getter groups URLs by
// codec+bitrate and would silently drop independent mirrors at equal quality.
import 'central_catalog_media_identity.dart';
import 'central_radio_catalog_projection.dart';

class CentralVerifiedStreamPlan {
  const CentralVerifiedStreamPlan({required this.media});

  final CentralMediaIdentityResolver media;

  /// Return every distinct *verified* stream in editorial priority order.
  /// A previously selected URL is restored only when it is still verified
  /// for the very same permanent station ID. No URL-based identity matching.
  /// This is an isolated candidate plan, NOT a V64 playback hook.
  List<CentralProjectedStream> forStationId(
    String historicalId, {
    String? preferredVerifiedUrl,
  }) => _fromLookup(
    media.resolveStationId(historicalId),
    preferredVerifiedUrl: preferredVerifiedUrl,
  );

  /// Interpret legacy Android Auto bookmarks without trusting their URL or
  /// accepting playback for quarantined, retired or unknown identities.
  List<CentralProjectedStream> forAndroidAutoMediaId(
    String mediaId, {
    String? preferredVerifiedUrl,
  }) => _fromLookup(
    media.resolveMediaId(mediaId),
    preferredVerifiedUrl: preferredVerifiedUrl,
  );

  List<CentralProjectedStream> _fromLookup(
    CentralMediaLookup lookup, {
    String? preferredVerifiedUrl,
  }) {
    if (!lookup.playable) return const <CentralProjectedStream>[];
    final streams = lookup.station!.verifiedStreams;
    final byUrl = <String>{};
    final ordered = <CentralProjectedStream>[];
    final preferred = preferredVerifiedUrl?.trim();
    if (preferred != null && preferred.isNotEmpty) {
      for (final stream in streams) {
        if (stream.url == preferred && byUrl.add(stream.url)) {
          ordered.add(stream);
        }
      }
    }
    for (final stream in streams) {
      if (byUrl.add(stream.url)) ordered.add(stream);
    }
    return List<CentralProjectedStream>.unmodifiable(ordered);
  }
}
