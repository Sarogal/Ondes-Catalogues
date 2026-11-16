// Isolated, opt-in artwork-only decorator for real audio_service MediaItems.
// It has no network, disk, synchronization, playback or preference dependency.
// GrossesOndesAudioHandler does not import or instantiate this class yet.
import 'package:audio_service/audio_service.dart';

import 'central_android_auto_artwork_index.dart';

class CentralAndroidAutoMediaItemArtworkAdapter {
  const CentralAndroidAutoMediaItemArtworkAdapter({
    required this.index,
    this.enabled = false,
  });

  final CentralAndroidAutoArtworkIndex index;

  /// Explicitly false until a separately approved Android Auto cutover.
  final bool enabled;

  /// Copies only artUri when an already prepared, verified SHA is available.
  /// Unknown, withdrawn, unverified and unmatched IDs retain the original
  /// MediaItem (including the legacy cached image or bundled genre fallback).
  /// Filtering stations from browse/queue remains the catalog's responsibility.
  MediaItem apply(MediaItem legacyItem) {
    if (!enabled || legacyItem.playable != true) return legacyItem;

    final stationId = legacyItem.extras?['stationId'];
    if (stationId is! String ||
        stationId.isEmpty ||
        !_matchesStationIdentity(legacyItem.id, stationId)) {
      return legacyItem;
    }

    final verified = index.verifiedCentralForStationId(stationId);
    if (verified == null || legacyItem.artUri == verified) return legacyItem;

    return legacyItem.copyWith(artUri: verified);
  }

  /// Mirrors the existing handler's go:auto:station:<encoded station ID>
  /// with its optional, separately encoded browse-context suffix.
  static bool _matchesStationIdentity(String mediaId, String stationId) {
    final prefix = 'go:auto:station:${Uri.encodeComponent(stationId)}';
    if (mediaId == prefix) return true;
    return mediaId.startsWith('$prefix|') &&
        mediaId.length > prefix.length + 1;
  }
}
