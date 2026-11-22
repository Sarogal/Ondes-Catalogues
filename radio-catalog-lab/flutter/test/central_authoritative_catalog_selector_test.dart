import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:crypto/crypto.dart' as crypto;
import 'package:cryptography/cryptography.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_radio_flutter_lab/central_authoritative_catalog_selector.dart';
import 'package:go_radio_flutter_lab/central_logo_preparation_plan.dart';
import 'package:go_radio_flutter_lab/central_radio_catalog_client.dart';
import 'package:go_radio_flutter_lab/central_radio_catalog_core.dart';

Uint8List encode(Object value) =>
    Uint8List.fromList(utf8.encode(jsonEncode(value)));

Map<String, dynamic> station(
  int id, {
  String state = 'active',
  String? stream,
  String? logoSha,
}) {
  final goId = 'go-station-${id.toString().padLeft(6, '0')}';
  return {
    'go_station_id': goId,
    'display_name': 'Remote Station ${id}',
    'country_code': 'FR',
    'genres': ['Heavy'],
    'tags': ['hard rock'],
    'homepage': 'https://radio.example.org/',
    'legacy_aliases': ['historical-${id.toString().padLeft(6, '0')}'],
    'radio_browser_uuids': [
      {'uuid': 'historical-${id.toString().padLeft(6, '0')}', 'state': 'historical'}
    ],
    'status': {
      'state': state,
      'reason_code': state == 'active' ? null : 'retired_by_editorial_review',
      'changed_at': '2026-11-22T18:00:00Z',
    },
    'streams': [
      {
        'stream_id': 'main',
        'url': stream ?? 'https://stream.example.org/radio${id}.mp3',
        'protocol': 'https',
        'priority': 0,
        'codec': 'MP3',
        'bitrate_kbps': 192,
        'state': 'verified',
      }
    ],
    'logo': logoSha == null ? null : {
      'asset_id': 'sha256:${logoSha}',
      'sha256': logoSha,
      'byte_size': 25000,
      'revision': 2,
      'width': 600,
      'height': 600,
      'mime_type': 'image/png',
      'url': 'https://cdn.example.org/logos/test.png',
    },
    'editorial': {
      'admission_state': 'approved',
      'reviewed_at': '2026-11-22T18:00:00Z',
      'evidence_refs': <String>[],
    },
  };
}

Uint8List body(int sequence, List<Map<String, dynamic>> stations) => encode({
  'schema_version': 1,
  'catalog_id': 'grosses-ondes-radio',
  'release_sequence': sequence,
  'generated_at': '2026-11-22T18:00:00Z',
  'stations': stations,
  'tombstones': [],
});

late SimpleKeyPair keyPair;
late CentralCatalogVerifier verifier;

Future<ValidatedCentralCatalog> signed(
  int sequence, List<Map<String, dynamic>> records, {
  ValidatedCentralCatalog? previous,
}) async {
  final payload = body(sequence, records);
  final digest = crypto.sha256.convert(payload).toString();
  final pointer = <String, dynamic>{
    'schema_version': 1,
    'catalog_id': 'grosses-ondes-radio',
    'release_sequence': sequence,
    'published_at': '2026-11-22T18:00:00Z',
    'content_sha256': digest,
    'content_length': payload.length,
    'content_path': 'releases/${digest}.json',
    'signature': {
      'algorithm': 'Ed25519',
      'key_id': 'synthetic-only',
      'signature_base64': base64.encode(List<int>.filled(64, 0)),
    },
  };
  final raw = CentralCatalogPointer.parse(encode(pointer));
  final signature = await Ed25519().sign(
    raw.signatureMessage, keyPair: keyPair);
  (pointer['signature'] as Map<String, dynamic>)['signature_base64'] =
      base64.encode(signature.bytes);
  return verifier.verify(
    pointerBytes: encode(pointer), catalogBytes: payload, previous: previous);
}

CentralRadioCatalogClient client(
  Directory root, {
  Future<Uint8List> Function(Uri, int)? fetch,
}) => CentralRadioCatalogClient(
  baseUri: Uri.parse('https://catalog.example.org/radio/'),
  verifier: verifier,
  disk: CentralCatalogDiskStore(root),
  fetch: fetch ?? (uri, bytes) async => throw StateError(
    'No network request permitted in offline test'),
);

void main() {
  setUpAll(() async {
    keyPair = await Ed25519().newKeyPair();
    verifier = CentralCatalogVerifier(trustedKeys: {
      'synthetic-only': await keyPair.extractPublicKey(),
    });
  });

  late Directory folder;
  setUp(() async {
    folder = await Directory.systemTemp.createTemp('go-auth-only-');
  });
  tearDown(() async {
    await folder.delete(recursive: true);
  });

  const selector = CentralAuthoritativeCatalogSelector();

  test('first launch without signed snapshot returns no unsigned V64 list',
      () async {
    var calls = 0;
    final source = client(folder, fetch: (_, __) async {
      calls++;
      throw StateError('Must not fetch');
    });
    final result = await selector.select(
      client: source,
      favoriteIds: ['historical-000001'],
    );
    expect(result, isNull);
    expect(calls, 0);
  });

  test('signed-only release completely controls additions, edits, retirement',
      () async {
    final first = await signed(1, [station(1), station(2)]);
    final revised = await signed(2, [
      station(1, stream: 'https://stream.example.org/new.mp3',
          logoSha: List<String>.filled(64, 'a').join()),
      station(2, state: 'retired'),
      station(3),
    ], previous: first);
    var latest = first;
    var networkFetches = 0;
    final remote = client(folder, fetch: (uri, limit) async {
      networkFetches++;
      return uri.path.endsWith('current.json')
          ? latest.pointerBytes : latest.catalogBytes;
    });
    const favoriteIds = [
      'historical-000001', 'historical-000002', 'unresolved-favorite',
    ];
    final v1 = await selector.select(
      client: remote, favoriteIds: favoriteIds, allowNetwork: true);
    expect(v1, isNotNull);
    expect(v1!.stations.map((s) => s.id), [
      'historical-000001', 'historical-000002',
    ]);
    expect(v1.stations.first.allStationIds, contains('historical-000001'));
    expect(v1.signedSequence, 1);

    // Changing a server pointer is enough. No compiled file or local V64
    // baseline changes between these two requests.
    latest = revised;
    final v2 = await selector.select(
      client: remote, favoriteIds: favoriteIds, allowNetwork: true);
    expect(v2, isNotNull);
    expect(v2!.signedSequence, 2);
    expect(v2.source, CentralAuthoritySource.signedNetwork);
    expect(v2.stations.map((s) => s.id), [
      'historical-000001', 'historical-000003',
    ]);
    expect(v2.stations.first.streamUrl,
        'https://stream.example.org/new.mp3');
    expect(v2.stations.first.logoUrl, 'https://cdn.example.org/logos/test.png',
        reason: 'The signed URL is only a lookup key; Flutter must use a verified SHA file');
    expect(v2.stations.first.logoSource, 'central-signed-sha-only');
    expect(v2.originalFavoriteIds, favoriteIds);
    expect(v2.unavailableFavoriteIds, ['historical-000002']);
    expect(v2.unresolvedFavoriteIds, ['unresolved-favorite']);
    expect(v2.stations.first.allStationIds, contains('historical-000001'));
    expect(v2.stations.last.allStationIds, contains('historical-000003'));
    expect(CentralLogoPreparationPlanner().plan(v2.snapshot).items, hasLength(1));
    expect(networkFetches, 4);

    // Signed disk snapshot is the only offline radio source, not a mixture.
    final offline = await selector.select(
      client: client(folder), favoriteIds: favoriteIds);
    expect(offline!.source, CentralAuthoritySource.signedDisk);
    expect(offline.signedSequence, 2);
    expect(offline.stations.map((s) => s.id),
        v2.stations.map((s) => s.id));
    expect(offline.productionReleaseAuthorized, isFalse);
  });

  test('network outage uses last signed disk snapshot, never bootstrapped V64',
      () async {
    await client(folder).disk.persist(await signed(1, [station(1)]));
    var calls = 0;
    final result = await selector.select(
      client: client(folder, fetch: (_, __) async {
        calls++;
        throw const SocketException('test network outage');
      }),
      favoriteIds: ['historical-000001'], allowNetwork: true);
    expect(result!.source,
        CentralAuthoritySource.signedDiskAfterNetworkFailure);
    expect(result.networkFailed, isTrue);
    expect(result.stations, hasLength(1));
    expect(calls, 1);
  });

  test('signed-but-unsupported future genre cannot displace last good snapshot',
      () async {
    final older = await signed(1, [station(1)]);
    await client(folder).disk.persist(older);
    final experimental = station(1)..['genres'] = ['UnrecognizedGenre'];
    final newer = await signed(2, [experimental], previous: older);
    final result = await selector.select(
      client: client(folder, fetch: (uri, bytes) async =>
        uri.path.endsWith('current.json') ?
          newer.pointerBytes : newer.catalogBytes),
      favoriteIds: [], allowNetwork: true);
    expect(result!.source,
        CentralAuthoritySource.signedDiskAfterProjectionFailure);
    expect(result.signedSequence, 1);
    expect(result.stations.single.name, 'Remote Station 1');
  });

  test('untrusted remote key provides neither a radio nor a logo', () async {
    final signedRecord = await signed(1, [station(1)]);
    final invalid = CentralRadioCatalogClient(
      baseUri: Uri.parse('https://catalog.example.org/radio/'),
      verifier: const CentralCatalogVerifier(trustedKeys: {}),
      disk: CentralCatalogDiskStore(folder),
      fetch: (uri, limit) async =>
          uri.path.endsWith('current.json')
              ? signedRecord.pointerBytes : signedRecord.catalogBytes,
    );
    final result = await selector.select(
      client: invalid, favoriteIds: [], allowNetwork: true);
    expect(result, isNull);
  });
  test('signed first historical alias stays primary without consulting V64',
      () async {
    final only = station(4);
    only['legacy_aliases'] = ['legacy-original-v64-4', 'directory-new-4'];
    only['radio_browser_uuids'] = [
      {'uuid': 'legacy-original-v64-4', 'state': 'historical'},
      {'uuid': 'directory-new-4', 'state': 'current'},
    ];
    final signedRecord = await signed(1, [only]);
    await client(folder).disk.persist(signedRecord);
    final result = await selector.select(client: client(folder), favoriteIds: [
      'legacy-original-v64-4', 'directory-new-4'
    ]);
    expect(result!.stations.single.id, 'legacy-original-v64-4');
    expect(result.stations.single.allStationIds,
        containsAll(['legacy-original-v64-4','directory-new-4','go-station-000004']));
  });

}
