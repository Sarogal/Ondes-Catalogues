// DEBUG-ONLY MediaBrowser/MediaSession fixture. Not imported by main.dart,
// the production audio service, active handler or the central catalog client.
// It never plays a stream, reads a preference or performs a network request.
import 'package:audio_service/audio_service.dart';
import 'package:rxdart/rxdart.dart';

import '../central_android_auto_artwork_index.dart';
import '../central_android_auto_media_item_artwork_adapter.dart';

class CentralAndroidAutoDiagnosticHandler extends BaseAudioHandler {
  CentralAndroidAutoDiagnosticHandler({
    required List<MediaItem> legacyItems,
    required CentralAndroidAutoArtworkIndex artworkIndex,
    bool enableVerifiedArtwork = false,
    this.rootSubtitle = 'Aucun flux réseau, aucun audio',
  }) : _browseItems = List<MediaItem>.unmodifiable(
          legacyItems.map(
            CentralAndroidAutoMediaItemArtworkAdapter(
              index: artworkIndex,
              enabled: enableVerifiedArtwork,
            ).apply,
          ),
        ) {
    if (_browseItems.isEmpty ||
        _browseItems.any((item) => item.playable != true) ||
        _browseItems.map((item) => item.id).toSet().length != _browseItems.length) {
      throw ArgumentError('Diagnostic requires distinct playable MediaItems');
    }
    playbackState.add(PlaybackState(
      processingState: AudioProcessingState.ready,
      playing: false,
    ));
    queueTitle.add('Grosses Ondes — Diagnostic Android Auto');
    queue.add(_browseItems);
    mediaItem.add(_browseItems.first);
  }

  static const String browseId = 'go:diagnostic:auto:all';
  final List<MediaItem> _browseItems;
  final String rootSubtitle;
  final BehaviorSubject<Map<String, dynamic>> _rootChanges =
      BehaviorSubject<Map<String, dynamic>>.seeded(const {});
  final BehaviorSubject<Map<String, dynamic>> _stationChanges =
      BehaviorSubject<Map<String, dynamic>>.seeded(const {});

  List<MediaItem> get diagnosticItems => _browseItems;

  @override
  ValueStream<Map<String, dynamic>> subscribeToChildren(String parentMediaId) {
    return parentMediaId == browseId ? _stationChanges : _rootChanges;
  }

  @override
  Future<List<MediaItem>> getChildren(
    String parentMediaId, [
    Map<String, dynamic>? options,
  ]) async {
    if (parentMediaId == AudioService.browsableRootId) {
      return <MediaItem>[
        MediaItem(
          id: browseId,
          title: 'Radios — Diagnostic',
          playable: false,
          displaySubtitle: rootSubtitle,
        ),
      ];
    }
    if (parentMediaId == browseId) return _browseItems;
    return const <MediaItem>[];
  }

  @override
  Future<MediaItem?> getMediaItem(String mediaId) async {
    if (mediaId == browseId) {
      return const MediaItem(
        id: browseId,
        title: 'Radios — Diagnostic',
        playable: false,
      );
    }
    for (final item in _browseItems) {
      if (item.id == mediaId) return item;
    }
    return null;
  }

  @override
  Future<void> prepareFromMediaId(String mediaId, [Map<String, dynamic>? extras]) =>
      _selectMetadata(mediaId);

  @override
  Future<void> playFromMediaId(String mediaId, [Map<String, dynamic>? extras]) =>
      _selectMetadata(mediaId);

  @override
  Future<void> playMediaItem(MediaItem item) => _selectMetadata(item.id);

  /// Metadata only. Does not start an AudioPlayer and never sets playing=true.
  Future<void> _selectMetadata(String mediaId) async {
    final selected = await getMediaItem(mediaId);
    if (selected == null || selected.playable != true) return;
    mediaItem.add(selected);
  }

  @override
  Future<void> play() async {
    // A car UI may request PLAY; this fixture must remain silent and paused.
  }

  @override
  Future<void> pause() async {
    playbackState.add(playbackState.value.copyWith(playing: false));
  }

  @override
  Future<void> stop() async {
    playbackState.add(playbackState.value.copyWith(
      playing: false,
      processingState: AudioProcessingState.idle,
    ));
  }

  Future<void> closeFixture() async {
    await _rootChanges.close();
    await _stationChanges.close();
  }
}
