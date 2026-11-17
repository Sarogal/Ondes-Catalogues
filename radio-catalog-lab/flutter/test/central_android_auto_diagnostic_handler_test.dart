import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:audio_service/audio_service.dart';
import 'package:crypto/crypto.dart' as crypto;
import 'package:flutter_test/flutter_test.dart';
import 'package:go_radio_flutter_lab/android_auto_artwork_uris.dart';
import 'package:go_radio_flutter_lab/central_android_auto_artwork_index.dart';
import 'package:go_radio_flutter_lab/central_logo_asset_store.dart';
import 'package:go_radio_flutter_lab/central_radio_catalog_core.dart';
import 'package:go_radio_flutter_lab/diagnostics/central_android_auto_diagnostic_handler.dart';

const legacy1 = 'diagnostic-legacy-1';
const legacy2 = 'diagnostic-legacy-2';
const media1 = 'go:auto:station:diagnostic-legacy-1|go%3Aauto%3Aall';
const media2 = 'go:auto:station:diagnostic-legacy-2|go%3Aauto%3Aall';

Map<String, dynamic> signedRecord(int index, {bool withLogo = true, String state = 'active'}) {
  final digest = crypto.sha256.convert(utf8.encode('test-session-image')).toString();
  return <String, dynamic>{
    'go_station_id': 'go-station-${index.toString().padLeft(6, '0')}',
    'legacy_aliases': <String>['diagnostic-legacy-$index'],
    'status': <String, dynamic>{'state': state},
    'genres': <String>['Punk'],
    'logo': !withLogo ? null : <String, dynamic>{
      'asset_id': 'sha256:$digest',
      'sha256': digest,
      'byte_size': 18,
      'revision': 1,
      'url': 'https://images.example.org/test.png',
      'width': 512,
      'height': 512,
      'mime_type': 'image/png',
    },
  };
}

ValidatedCentralCatalog fixture(List<Map<String, dynamic>> records) {
  final sig = base64.encode(List<int>.filled(64, 0));
  final hash = 'a' * 64;
  final pointer = Uint8List.fromList(utf8.encode(jsonEncode(<String, dynamic>{
    'schema_version': 1,
    'catalog_id': 'grosses-ondes-radio',
    'release_sequence': 1,
    'published_at': '2026-11-16T21:00:00Z',
    'content_sha256': hash,
    'content_length': 2,
    'content_path': 'releases/$hash.json',
    'signature': <String, dynamic>{
      'algorithm': 'Ed25519',
      'key_id': 'synthetic-only',
      'signature_base64': sig,
    },
  })));
  return ValidatedCentralCatalog(
    CentralCatalogPointer.parse(pointer),
    pointer,
    Uint8List.fromList([123, 125]),
    records,
    const <String, String>{},
    records.map((r) => r['go_station_id'] as String).toSet(),
    records.where((r) => r['status']['state'] == 'active')
        .map((r) => r['go_station_id'] as String).toSet(),
  );
}

Future<CentralAndroidAutoArtworkIndex> index({bool verified = true}) async {
  return CentralAndroidAutoArtworkIndexBuilder(
    verifyLocalArtwork: ({required store, required descriptor}) async =>
        verified ? AndroidAutoArtworkUris.forCentralSha256(descriptor.sha256) : null,
  ).prepare(
    catalog: fixture([
      signedRecord(1),
      signedRecord(2, withLogo: false),
      signedRecord(3, state: 'quarantined'),
    ]),
    store: CentralLogoAssetStore(
      directory: Directory('${Directory.systemTemp.path}/go-session-fixture-unused'),
      decoder: (_) async => const CentralDecodedLogo(
        width: 512, height: 512, mimeType: 'image/png',
      ),
    ),
  );
}

List<MediaItem> legacy() => [
  const MediaItem(
    id: media1,
    title: 'Diagnostic — Radio 1',
    album: 'Grosses Ondes • EN DIRECT',
    playable: true,
    isLive: true,
    artUri: null,
    extras: <String, dynamic>{
      'stationId': legacy1,
      'browseContext': 'go:auto:all',
    },
  ).copyWith(artUri: AndroidAutoArtworkUris.forGenre('Punk')),
  MediaItem(
    id: media2,
    title: 'Diagnostic — Radio 2',
    playable: true,
    artUri: AndroidAutoArtworkUris.forGenre('Punk'),
    extras: const <String, dynamic>{
      'stationId': legacy2,
      'browseContext': 'go:auto:all',
    },
  ),
];

void main() {
  test('browsable root and station IDs are stable with verified SHA', () async {
    final prepared = await index();
    final handler = CentralAndroidAutoDiagnosticHandler(
      legacyItems: legacy(),
      artworkIndex: prepared,
      enableVerifiedArtwork: true,
    );
    final root = await handler.getChildren(AudioService.browsableRootId);
    expect(root.single.id, CentralAndroidAutoDiagnosticHandler.browseId);
    expect(root.single.playable, isFalse);
    final children = await handler.getChildren(
      CentralAndroidAutoDiagnosticHandler.browseId,
    );
    expect(children.map((e) => e.id), <String>[media1, media2]);
    expect(children.first.artUri, prepared.verifiedCentralForStationId(legacy1));
    expect(children.last.artUri, AndroidAutoArtworkUris.forGenre('Punk'));
    expect((await handler.getMediaItem(media1))?.artUri, children.first.artUri);
    expect((await handler.getMediaItem(media2))?.artUri, children.last.artUri);
    expect(await handler.getMediaItem('go:auto:station:unknown'), isNull);
    await handler.closeFixture();
  });

  test('native-session source remains silent when play is requested', () async {
    final handler = CentralAndroidAutoDiagnosticHandler(
      legacyItems: legacy(), artworkIndex: await index(),
      enableVerifiedArtwork: true,
    );
    expect(handler.mediaItem.value?.id, media1);
    expect(handler.playbackState.value.playing, isFalse);
    await handler.play();
    await handler.playFromMediaId(media2);
    expect(handler.mediaItem.value?.id, media2);
    expect(handler.playbackState.value.playing, isFalse);
    await handler.prepareFromMediaId('unknown');
    expect(handler.mediaItem.value?.id, media2);
    await handler.closeFixture();
  });

  test('default disabled: never modifies artUri', () async {
    final handler = CentralAndroidAutoDiagnosticHandler(
      legacyItems: legacy(), artworkIndex: await index(),
    );
    expect(handler.diagnosticItems.first.artUri,
        AndroidAutoArtworkUris.forGenre('Punk'));
    expect(handler.mediaItem.value?.artUri,
        AndroidAutoArtworkUris.forGenre('Punk'));
    await handler.closeFixture();
  });

  test('missing SHA does not downgrade bundled genre artwork', () async {
    final handler = CentralAndroidAutoDiagnosticHandler(
      legacyItems: legacy(), artworkIndex: await index(verified: false),
      enableVerifiedArtwork: true,
    );
    expect(handler.diagnosticItems.first.artUri,
        AndroidAutoArtworkUris.forGenre('Punk'));
    await handler.closeFixture();
  });

  test('reject duplicate media IDs and empty library', () async {
    final art = await index();
    expect(
      () => CentralAndroidAutoDiagnosticHandler(
        legacyItems: const <MediaItem>[], artworkIndex: art,
      ),
      throwsArgumentError,
    );
    final items = legacy();
    expect(
      () => CentralAndroidAutoDiagnosticHandler(
        legacyItems: [items.first, items.first], artworkIndex: art,
      ),
      throwsArgumentError,
    );
  });

  test('unknown browsing node returns no station', () async {
    final handler = CentralAndroidAutoDiagnosticHandler(
      legacyItems: legacy(), artworkIndex: await index(),
      enableVerifiedArtwork: true,
    );
    expect(await handler.getChildren('go:auto:invalid'), isEmpty);
    expect((await handler.getMediaItem(CentralAndroidAutoDiagnosticHandler.browseId))
        ?.playable, isFalse);
    await handler.closeFixture();
  });
}
