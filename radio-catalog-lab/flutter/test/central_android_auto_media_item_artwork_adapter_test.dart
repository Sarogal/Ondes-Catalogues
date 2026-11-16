import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:audio_service/audio_service.dart';
import 'package:crypto/crypto.dart' as crypto;
import 'package:flutter_test/flutter_test.dart';
import 'package:go_radio_flutter_lab/android_auto_artwork_uris.dart';
import 'package:go_radio_flutter_lab/central_android_auto_artwork_index.dart';
import 'package:go_radio_flutter_lab/central_android_auto_media_item_artwork_adapter.dart';
import 'package:go_radio_flutter_lab/central_logo_asset_store.dart';
import 'package:go_radio_flutter_lab/central_radio_catalog_core.dart';

const goId = 'go-station-000001';
const legacyId = 'historical-1';

Map<String, dynamic> station({
  String status = 'active',
  bool hasLogo = true,
}) {
  final digest = crypto.sha256.convert(utf8.encode('fixture-verified-logo')).toString();
  return <String, dynamic>{
    'go_station_id': goId,
    'status': <String, dynamic>{'state': status},
    'genres': <String>['Punk'],
    'legacy_aliases': <String>[legacyId],
    'logo': hasLogo
        ? <String, dynamic>{
            'asset_id': 'sha256:$digest',
            'sha256': digest,
            'byte_size': 64,
            'revision': 1,
            'url': 'https://images.example.org/$digest.png',
            'width': 512,
            'height': 512,
            'mime_type': 'image/png',
          }
        : null,
  };
}

ValidatedCentralCatalog fixture(List<Map<String, dynamic>> records) {
  final signature = base64.encode(List<int>.filled(64, 0));
  final digest = 'a' * 64;
  final pointerBytes = Uint8List.fromList(utf8.encode(jsonEncode({
    'schema_version': 1,
    'catalog_id': 'grosses-ondes-radio',
    'release_sequence': 1,
    'published_at': '2026-11-16T21:00:00Z',
    'content_sha256': digest,
    'content_length': 2,
    'content_path': 'releases/$digest.json',
    'signature': {
      'algorithm': 'Ed25519',
      'key_id': 'synthetic-only',
      'signature_base64': signature,
    },
  })));
  return ValidatedCentralCatalog(
    CentralCatalogPointer.parse(pointerBytes),
    pointerBytes,
    Uint8List.fromList([123, 125]),
    records,
    const <String, String>{},
    records.map((s) => s['go_station_id'] as String).toSet(),
    records
        .where((s) => s['status']['state'] == 'active')
        .map((s) => s['go_station_id'] as String)
        .toSet(),
  );
}

Future<CentralDecodedLogo> decoder(Uint8List _) async =>
    const CentralDecodedLogo(
      width: 512,
      height: 512,
      mimeType: 'image/png',
    );

Future<CentralAndroidAutoArtworkIndex> preparedIndex(
  List<Map<String, dynamic>> records, {
  bool verified = true,
}) async {
  final store = CentralLogoAssetStore(
    directory: Directory('${Directory.systemTemp.path}/unused-go-auto-media'),
    decoder: decoder,
  );
  return CentralAndroidAutoArtworkIndexBuilder(
    verifyLocalArtwork: ({required store, required descriptor}) async =>
        verified
            ? AndroidAutoArtworkUris.forCentralSha256(descriptor.sha256)
            : null,
  ).prepare(catalog: fixture(records), store: store);
}

MediaItem legacyItem({
  String stationId = legacyId,
  String? mediaId,
  Uri? artUri,
  bool playable = true,
}) {
  return MediaItem(
    id: mediaId ??
        'go:auto:station:${Uri.encodeComponent(stationId)}|'
            '${Uri.encodeComponent('go:auto:favorites')}',
    title: 'Radio historique',
    album: 'Grosses Ondes • EN DIRECT',
    artist: 'Punk',
    genre: 'Punk',
    artUri: artUri ?? AndroidAutoArtworkUris.forCachedLogo('old.img'),
    playable: playable,
    isLive: true,
    extras: <String, dynamic>{
      'stationId': stationId,
      'browseContext': 'go:auto:favorites',
      'streamUrl': 'https://audio.example.org/stream',
    },
  );
}

void main() {
  test('disabled by default: exact same MediaItem and legacy artUri', () async {
    final index = await preparedIndex([station()]);
    final original = legacyItem();
    final adapter = CentralAndroidAutoMediaItemArtworkAdapter(index: index);
    expect(identical(adapter.apply(original), original), isTrue);
  });

  test('opt-in sets the real MediaItem.artUri and retains media identity', () async {
    final index = await preparedIndex([station()]);
    final original = legacyItem();
    final decorated = CentralAndroidAutoMediaItemArtworkAdapter(
      index: index,
      enabled: true,
    ).apply(original);
    final expected = index.verifiedCentralForStationId(legacyId);
    expect(expected, isNotNull);
    expect(decorated.artUri, expected);
    expect(decorated.id, original.id);
    expect(decorated.title, original.title);
    expect(decorated.album, original.album);
    expect(decorated.artist, original.artist);
    expect(decorated.genre, original.genre);
    expect(decorated.playable, original.playable);
    expect(decorated.isLive, original.isLive);
    expect(decorated.extras, original.extras);
    expect(original.artUri, AndroidAutoArtworkUris.forCachedLogo('old.img'));
  });

  test('permanent GO station ID also resolves with no browse context', () async {
    final index = await preparedIndex([station()]);
    final original = legacyItem(
      stationId: goId,
      mediaId: 'go:auto:station:${Uri.encodeComponent(goId)}',
    );
    final updated = CentralAndroidAutoMediaItemArtworkAdapter(
      index: index,
      enabled: true,
    ).apply(original);
    expect(updated.artUri, index.verifiedCentralForStationId(goId));
    expect(updated.id, original.id);
  });

  test('missing SHA keeps valid legacy image (no genre downgrade)', () async {
    final index = await preparedIndex([station()], verified: false);
    final original = legacyItem();
    expect(index.verifiedCentralForStationId(legacyId), isNull);
    expect(identical(CentralAndroidAutoMediaItemArtworkAdapter(
      index: index,
      enabled: true,
    ).apply(original), original), isTrue);
  });

  test('absent logo retains the bundled genre fallback', () async {
    final index = await preparedIndex([station(hasLogo: false)]);
    final genre = AndroidAutoArtworkUris.forGenre('Punk');
    final original = legacyItem(artUri: genre);
    final result = CentralAndroidAutoMediaItemArtworkAdapter(
      index: index,
      enabled: true,
    ).apply(original);
    expect(identical(result, original), isTrue);
    expect(result.artUri, genre);
  });

  test('retired and quarantined identities cannot override artUri', () async {
    for (final state in <String>['quarantined', 'retired']) {
      final index = await preparedIndex([station(status: state)]);
      final original = legacyItem();
      expect(index.verifiedCentralForStationId(legacyId), isNull);
      expect(identical(CentralAndroidAutoMediaItemArtworkAdapter(
        index: index,
        enabled: true,
      ).apply(original), original), isTrue);
    }
  });

  test('mismatched MediaItem station ID and extras are never decorated', () async {
    final index = await preparedIndex([station()]);
    final original = legacyItem(
      mediaId: 'go:auto:station:another-station|go%3Aauto%3Aall',
    );
    expect(identical(CentralAndroidAutoMediaItemArtworkAdapter(
      index: index,
      enabled: true,
    ).apply(original), original), isTrue);
  });

  test('root or genre browse item remains intact', () async {
    final index = await preparedIndex([station()]);
    final original = legacyItem(
      playable: false,
      mediaId: 'go:auto:genres',
    );
    expect(identical(CentralAndroidAutoMediaItemArtworkAdapter(
      index: index,
      enabled: true,
    ).apply(original), original), isTrue);
  });

  test('unknown identity and malformed context keep legacy artwork', () async {
    final index = await preparedIndex([station()]);
    final adapter = CentralAndroidAutoMediaItemArtworkAdapter(
      index: index,
      enabled: true,
    );
    final unknown = legacyItem(stationId: 'missing-legacy-id');
    final malformed = legacyItem(mediaId: 'go:auto:station:historical-1|');
    expect(identical(adapter.apply(unknown), unknown), isTrue);
    expect(identical(adapter.apply(malformed), malformed), isTrue);
  });
}
