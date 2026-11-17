// QEMU-only DEBUG entrypoint for the native Android Auto media session.
// No production imports, HTTP, real radios, favorites or audio playback.
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:audio_service/audio_service.dart';
import 'package:crypto/crypto.dart' as crypto;
import 'package:cryptography/cryptography.dart';
import 'package:flutter/foundation.dart' show kReleaseMode;
import 'package:flutter/services.dart';
import 'package:flutter/widgets.dart';

import '../android_auto_artwork_uris.dart';
import '../central_android_auto_artwork_index.dart';
import '../central_flutter_logo_decoder.dart';
import '../central_logo_android_auto_bridge.dart';
import '../central_logo_asset_store.dart';
import '../central_radio_catalog_core.dart';
import 'central_android_auto_diagnostic_handler.dart';

Uint8List _bytes(Object value) => Uint8List.fromList(utf8.encode(jsonEncode(value)));

Map<String, dynamic> _radio(int n, Map<String, dynamic>? logo) => {
  'go_station_id': 'go-station-${n.toString().padLeft(6, '0')}',
  'display_name': 'QEMU diagnostic radio $n',
  'country_code': 'FR',
  'genres': ['Punk'],
  'tags': ['Punk'],
  'homepage': 'https://example.org',
  'radio_browser_uuids': [{'uuid': 'diagnostic-legacy-$n', 'state': 'historical'}],
  'legacy_aliases': ['diagnostic-legacy-$n'],
  'status': {'state': 'active', 'reason_code': null,
    'changed_at': '2026-11-16T21:00:00Z'},
  'streams': [{
    'stream_id': 'debug-stream-$n',
    'url': 'https://example.org/never-play-$n.mp3',
    'priority': 0, 'protocol': 'https', 'codec': 'mp3',
    'bitrate_kbps': 128, 'state': 'verified',
  }],
  'logo': logo,
  'editorial': {'admission_state': 'approved',
    'reviewed_at': '2026-11-16T21:00:00Z', 'evidence_refs': []},
};

Future<ValidatedCentralCatalog> _verifySignedCatalog(
    Map<String, dynamic> logo) async {
  final pair = await Ed25519().newKeyPair();
  final pub = await pair.extractPublicKey();
  final verifier = CentralCatalogVerifier(trustedKeys: {'qemu-only': pub});
  final content = _bytes({
    'schema_version': 1,
    'catalog_id': 'grosses-ondes-radio',
    'release_sequence': 1,
    'generated_at': '2026-11-16T21:00:00Z',
    'stations': [_radio(1, logo), _radio(2, null)],
    'tombstones': [],
  });
  final digest = crypto.sha256.convert(content).toString();
  final pointer = <String, dynamic>{
    'schema_version': 1,
    'catalog_id': 'grosses-ondes-radio',
    'release_sequence': 1,
    'published_at': '2026-11-16T21:00:00Z',
    'content_sha256': digest,
    'content_length': content.length,
    'content_path': 'releases/$digest.json',
    'signature': {'algorithm': 'Ed25519', 'key_id': 'qemu-only',
      'signature_base64': base64.encode(List<int>.filled(64, 0))},
  };
  final sig = await Ed25519().sign(
    CentralCatalogPointer.parse(_bytes(pointer)).signatureMessage,
    keyPair: pair,
  );
  (pointer['signature'] as Map<String, dynamic>)['signature_base64'] =
      base64.encode(sig.bytes);
  return verifier.verify(pointerBytes: _bytes(pointer), catalogBytes: content);
}

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const Directionality(
    textDirection: TextDirection.ltr,
    child: Center(child: Text('Grosses Ondes — MediaSession DEBUG (silencieuse)')),
  ));
  try {
    await _prepareAndPublish();
  } catch (error) {
    debugPrint('GO_AUTO_SESSION_FAIL ${error.runtimeType}');
  }
}

Future<void> _prepareAndPublish() async {
  if (!Platform.isAndroid || kReleaseMode) {
    throw StateError('QEMU DEBUG only');
  }
  final asset = await rootBundle.load('assets/genres/punk.png');
  final png = asset.buffer.asUint8List(asset.offsetInBytes, asset.lengthInBytes);
  final decoded = await decodeCentralFlutterLogo(png);
  if (decoded.mimeType != 'image/png' || png.isEmpty) {
    throw StateError('Invalid bundled PNG');
  }
  final sha = crypto.sha256.convert(png).toString();
  final signedLogo = <String, dynamic>{
    'asset_id': 'sha256:$sha', 'sha256': sha, 'byte_size': png.length,
    'revision': 1, 'url': 'https://images.example.org/debug-only.png',
    'width': decoded.width, 'height': decoded.height,
    'mime_type': decoded.mimeType,
  };
  final verified = await _verifySignedCatalog(signedLogo);
  final store = await CentralLogoAndroidAutoBridge.createStore();
  final descriptor = CentralLogoDescriptor.fromSignedStation(
      verified.stations.first)!;
  final target = File('${store.directory.path}/$sha.img');
  // Reuse only an already verified object on media-service restart. Never
  // clobber an unexpected object. Host preflight requires a clean QEMU SHA.
  if (await store.findVerified(descriptor) == null) {
    if (await target.exists()) throw StateError('Nonverified existing SHA');
    final result = await store.ensure(
      target: descriptor,
      fetch: (_, __) async => png, // Bundled bytes, never a network fetch.
    );
    if (result.status != CentralLogoCacheStatus.downloaded) {
      throw StateError('Bundled SHA could not be installed');
    }
  }
  final index = await const CentralAndroidAutoArtworkIndexBuilder().prepare(
    catalog: verified, store: store,
  );
  final expected = AndroidAutoArtworkUris.forCentralSha256(sha);
  final fallback = AndroidAutoArtworkUris.forGenre('Punk');
  if (index.verifiedCentralForStationId('diagnostic-legacy-1') != expected ||
      index.verifiedCentralForStationId('diagnostic-legacy-2') != null) {
    throw StateError('Invalid offline artwork selection');
  }
  const context = 'go:auto:all';
  final items = <MediaItem>[
    MediaItem(
      id: 'go:auto:station:diagnostic-legacy-1|'
          '${Uri.encodeComponent(context)}',
      title: 'Diagnostic SHA vérifié', album: 'Grosses Ondes — Test',
      artist: 'Aucun flux audio', genre: 'Punk', playable: true, isLive: true,
      artUri: fallback, extras: const {
        'stationId': 'diagnostic-legacy-1', 'browseContext': context,
      },
    ),
    MediaItem(
      id: 'go:auto:station:diagnostic-legacy-2|'
          '${Uri.encodeComponent(context)}',
      title: 'Diagnostic vignette genre', album: 'Grosses Ondes — Test',
      artist: 'Aucun flux audio', genre: 'Punk', playable: true, isLive: true,
      artUri: fallback, extras: const {
        'stationId': 'diagnostic-legacy-2', 'browseContext': context,
      },
    ),
  ];
  final handler = await AudioService.init<CentralAndroidAutoDiagnosticHandler>(
    builder: () => CentralAndroidAutoDiagnosticHandler(
      legacyItems: items, artworkIndex: index, enableVerifiedArtwork: true,
    ),
    config: AudioServiceConfig(
      androidNotificationChannelId:
          'fr.grossesondes.app.channel.audio.session_probe',
      androidNotificationChannelName: 'Grosses Ondes — Diagnostic',
      androidNotificationOngoing: false,
      androidStopForegroundOnPause: true,
      androidBrowsableRootExtras: const {
        'android.media.browse.CONTENT_STYLE_SUPPORTED': true,
        'android.media.browse.CONTENT_STYLE_BROWSABLE_HINT': 1,
        'android.media.browse.CONTENT_STYLE_PLAYABLE_HINT': 1,
      },
    ),
  );
  final root = await handler.getChildren(AudioService.browsableRootId);
  final browse = await handler.getChildren(
    CentralAndroidAutoDiagnosticHandler.browseId,
  );
  if (root.length != 1 || browse.length != 2 ||
      browse.first.id != items.first.id || browse.last.id != items.last.id ||
      browse.first.artUri != expected || browse.last.artUri != fallback ||
      handler.mediaItem.value?.artUri != expected ||
      handler.playbackState.value.playing) {
    throw StateError('MediaBrowser/MediaSession diagnostic contract failed');
  }
  // Success here is from Dart AudioService.init, not an Android Auto UI proof.
  debugPrint('GO_AUTO_SESSION_READY sha=$sha uri=$expected '
      'fallback=$fallback browse=2 playing=false');
}
