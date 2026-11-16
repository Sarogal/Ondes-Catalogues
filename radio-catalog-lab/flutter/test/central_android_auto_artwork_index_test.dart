import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart' as crypto;
import 'package:flutter_test/flutter_test.dart';
import 'package:go_radio_flutter_lab/android_auto_artwork_uris.dart';
import 'package:go_radio_flutter_lab/central_android_auto_artwork_index.dart';
import 'package:go_radio_flutter_lab/central_logo_asset_store.dart';
import 'package:go_radio_flutter_lab/central_radio_catalog_core.dart';

Uint8List image(int seed) => Uint8List.fromList(
      List<int>.generate(64, (index) => (seed + index) & 255),
    );

Map<String, dynamic> record(
  int index, {
  String status = 'active',
  String genre = 'Punk',
  Uint8List? logo,
  List<String>? aliases,
}) {
  final id = 'go-station-${index.toString().padLeft(6, '0')}';
  final digest = logo == null ? null : crypto.sha256.convert(logo).toString();
  return {
    'go_station_id': id,
    'status': <String, dynamic>{'state': status},
    'genres': [genre],
    'legacy_aliases': aliases ?? ['historical-$index'],
    'logo': logo == null
        ? null
        : {
            'asset_id': 'sha256:$digest',
            'sha256': digest,
            'byte_size': logo.length,
            'revision': 1,
            'url': 'https://images.example.org/$digest.png',
            'width': 512,
            'height': 512,
            'mime_type': 'image/png',
          },
  };
}

// Synthetic typed projection solely for pure index logic. The real path
// receives its ValidatedCentralCatalog from CentralCatalogVerifier.verify.
ValidatedCentralCatalog fixture(List<Map<String, dynamic>> stations) {
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
    stations,
    const <String, String>{},
    stations.map((station) => station['go_station_id'] as String).toSet(),
    stations
        .where((station) => station['status']['state'] == 'active')
        .map((station) => station['go_station_id'] as String)
        .toSet(),
  );
}

Future<CentralDecodedLogo> decoder(Uint8List _) async =>
    const CentralDecodedLogo(
      width: 512,
      height: 512,
      mimeType: 'image/png',
    );

void main() {
  late Directory temp;
  late CentralLogoAssetStore store;
  setUp(() async {
    temp = await Directory.systemTemp.createTemp('go-auto-artwork-');
    store = CentralLogoAssetStore(
      directory: Directory('${temp.path}/sha'),
      decoder: decoder,
    );
  });
  tearDown(() async {
    if (await temp.exists()) await temp.delete(recursive: true);
  });

  test('one verified SHA serves two stations and all historical IDs', () async {
    final bytes = image(1);
    final expectedSha = crypto.sha256.convert(bytes).toString();
    final descriptor = CentralLogoDescriptor.fromSignedStation(
      record(1, logo: bytes),
    )!;
    final installed = await store.ensure(
      target: descriptor,
      fetch: (_, __) async => bytes,
    );
    expect(installed.status, CentralLogoCacheStatus.downloaded);

    var verifications = 0;
    final builder = CentralAndroidAutoArtworkIndexBuilder(
      verifyLocalArtwork: ({required store, required descriptor}) async {
        verifications++;
        if (await store.findVerified(descriptor) == null) return null;
        return AndroidAutoArtworkUris.forCentralSha256(descriptor.sha256);
      },
    );
    final index = await builder.prepare(
      catalog: fixture([
        record(1, logo: bytes, aliases: ['historical-1', 'older-1']),
        record(2, logo: bytes, aliases: ['historical-2']),
      ]),
      store: store,
    );

    final expected = AndroidAutoArtworkUris.forCentralSha256(expectedSha);
    expect(index.forMediaId('go-station-000001'), expected);
    expect(index.forMediaId('historical-1'), expected);
    expect(index.forMediaId('older-1'), expected);
    expect(index.forMediaId('go-station-000002'), expected);
    expect(index.forMediaId('historical-2'), expected);
    expect(index.mappedIds, 5);
    expect(verifications, 1); // SHA object verified once, not per station.
    expect(await installed.image!.readAsBytes(), bytes);
  });

  test('missing SHA and absent logo retain station genre fallback', () async {
    final bytes = image(2);
    final index = await CentralAndroidAutoArtworkIndexBuilder(
      verifyLocalArtwork: ({required store, required descriptor}) =>
          Future<Uri?>.value(null),
    ).prepare(
      catalog: fixture([
        record(1, logo: bytes),
        record(2, genre: 'Death'),
      ]),
      store: store,
    );
    expect(index.forMediaId('historical-1'),
        AndroidAutoArtworkUris.forGenre('Punk'));
    expect(index.forMediaId('historical-2'),
        AndroidAutoArtworkUris.forGenre('Death'));
    expect(index.forMediaId('not-in-catalog'),
        AndroidAutoArtworkUris.forGenre(''));
    expect(await store.directory.exists(), isFalse);
  });

  test('quarantined and retired stations cannot expose cached SHA URI',
      () async {
    final bytes = image(3);
    var calls = 0;
    final index = await CentralAndroidAutoArtworkIndexBuilder(
      verifyLocalArtwork: ({required store, required descriptor}) async {
        calls++;
        return AndroidAutoArtworkUris.forCentralSha256(descriptor.sha256);
      },
    ).prepare(
      catalog: fixture([
        record(1, status: 'quarantined', logo: bytes),
        record(2, status: 'retired', logo: bytes),
      ]),
      store: store,
    );
    expect(index.mappedIds, 0);
    expect(index.forMediaId('historical-1'),
        AndroidAutoArtworkUris.forGenre(''));
    expect(calls, 0);
  });

  test('rejects untrusted or wrong-digest URI and uses fallback', () async {
    final bytes = image(4);
    for (final unsafe in <Uri>[
      Uri.parse('https://images.example.org/logo.png'),
      AndroidAutoArtworkUris.forCentralSha256('a' * 64),
    ]) {
      final index = await CentralAndroidAutoArtworkIndexBuilder(
        verifyLocalArtwork: ({required store, required descriptor}) async =>
            unsafe,
      ).prepare(catalog: fixture([record(1, logo: bytes)]), store: store);
      expect(index.forMediaId('historical-1'),
          AndroidAutoArtworkUris.forGenre('Punk'));
    }
  });

  test('failed native logo lookup falls back without damaging cache',
      () async {
    final bytes = image(5);
    final index = await CentralAndroidAutoArtworkIndexBuilder(
      verifyLocalArtwork: ({required store, required descriptor}) async {
        throw const FileSystemException('Disk is offline');
      },
    ).prepare(
      catalog: fixture([record(1, logo: bytes)]),
      store: store,
    );
    expect(index.forMediaId('historical-1'),
        AndroidAutoArtworkUris.forGenre('Punk'));
    expect(await store.directory.exists(), isFalse);
  });

  test('historical media ID collision is refused before use', () async {
    final indexer = CentralAndroidAutoArtworkIndexBuilder(
      verifyLocalArtwork: ({required store, required descriptor}) async => null,
    );
    await expectLater(
      indexer.prepare(
        catalog: fixture([
          record(1, aliases: ['same-old-id']),
          record(2, aliases: ['same-old-id']),
        ]),
        store: store,
      ),
      throwsA(isA<CentralCatalogException>()),
    );
  });
}
