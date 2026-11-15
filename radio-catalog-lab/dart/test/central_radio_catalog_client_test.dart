import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:go_radio_catalog_client_lab/central_radio_catalog_client.dart';
import 'package:go_radio_catalog_client_lab/central_radio_catalog_core.dart';
import 'package:test/test.dart';
import 'package:crypto/crypto.dart' as crypto;

Map<String, dynamic> station(int index, {String status = 'active'}) {
  final id = 'go-station-${index.toString().padLeft(6, '0')}';
  return {
    'go_station_id': id,
    'display_name': 'Fictional station $index',
    'country_code': 'FR',
    'genres': ['Heavy'],
    'homepage': 'https://example.org',
    'radio_browser_uuids': [
      {'uuid': 'legacy-$index', 'state': 'historical'}
    ],
    'legacy_aliases': ['legacy-$index'],
    'status': {
      'state': status,
      'reason_code': status == 'active' ? null : 'manual_editorial_decision',
      'changed_at': '2026-11-15T18:00:00Z'
    },
    'streams': [
      {
        'stream_id': 'stream-1',
        'url': 'https://example.org/audio-$index.mp3',
        'priority': 0,
        'protocol': 'https',
        'codec': 'mp3',
        'bitrate_kbps': 128,
        'state': 'verified'
      }
    ],
    'logo': null,
    'editorial': {
      'admission_state': 'approved',
      'reviewed_at': '2026-11-15T18:00:00Z',
      'evidence_refs': []
    }
  };
}

Map<String, dynamic> catalog(List<Map<String, dynamic>> stations,
    {int sequence = 1, List<Map<String, dynamic>> tombstones = const []}) {
  return {
    'schema_version': 1,
    'catalog_id': 'grosses-ondes-radio',
    'release_sequence': sequence,
    'generated_at': '2026-11-15T18:00:00Z',
    'stations': stations,
    'tombstones': tombstones,
  };
}

Uint8List jsonBytes(Object value) => Uint8List.fromList(utf8.encode(jsonEncode(value)));

late KeyPair signingPair;
late SimplePublicKey signingPublicKey;
late CentralCatalogVerifier verifier;

Future<Uint8List> signedPointer(Uint8List payload, int pointerSequence,
    {String keyId = 'test-only', String? digestOverride}) async {
  final digest = digestOverride ?? crypto.sha256.convert(payload).toString();
  final document = <String, dynamic>{
    'schema_version': 1,
    'catalog_id': 'grosses-ondes-radio',
    'release_sequence': pointerSequence,
    'published_at': '2026-11-15T18:00:00Z',
    'content_sha256': digest,
    'content_length': payload.length,
    'content_path': 'releases/$digest.json',
    'signature': {
      'algorithm': 'Ed25519',
      'key_id': keyId,
      'signature_base64': base64.encode(List<int>.filled(64, 0))
    }
  };
  final toSign = CentralCatalogPointer.parse(jsonBytes(document));
  final signed = await Ed25519().sign(toSign.signatureMessage, keyPair: signingPair);
  (document['signature'] as Map<String, dynamic>)['signature_base64'] =
      base64.encode(signed.bytes);
  return jsonBytes(document);
}

Future<ValidatedCentralCatalog> validatePayload(Uint8List payload,
    {int sequence = 1, ValidatedCentralCatalog? previous}) async {
  final pointer = await signedPointer(payload, sequence);
  return verifier.verify(pointerBytes: pointer, catalogBytes: payload, previous: previous);
}

void main() {
  setUpAll(() async {
    signingPair = await Ed25519().newKeyPair();
    signingPublicKey = (await signingPair.extractPublicKey()) as SimplePublicKey;
    verifier = CentralCatalogVerifier(trustedKeys: {'test-only': signingPublicKey});
  });

  test('valid signed release succeeds, without activating any V64 behavior', () async {
    final payload = jsonBytes(catalog([station(1)]));
    final verified = await validatePayload(payload);
    expect(verified.stations, hasLength(1));
    expect(verified.aliasOwners['legacy-1'], 'go-station-000001');
  });

  test('missing production key fails closed', () async {
    final bytes = jsonBytes(catalog([station(1)]));
    final pointer = await signedPointer(bytes, 1);
    final emptyKeys = CentralCatalogVerifier(trustedKeys: {});
    await expectLater(
        emptyKeys.verifyPointer(pointer),
        throwsA(isA<CentralCatalogException>()));
  });

  test('unsigned pointer is forbidden', () async {
    final bytes = jsonBytes(catalog([station(1)]));
    final pointer = jsonDecode(utf8.decode(await signedPointer(bytes, 1)))
        as Map<String, dynamic>;
    pointer.remove('signature');
    await expectLater(verifier.verifyPointer(jsonBytes(pointer)),
        throwsA(isA<CentralCatalogException>()));
  });

  test('signature tampering is rejected before payload fetch', () async {
    final bytes = jsonBytes(catalog([station(1)]));
    final pointer = jsonDecode(utf8.decode(await signedPointer(bytes, 1)))
        as Map<String, dynamic>;
    pointer['published_at'] = '2026-11-16T18:00:00Z';
    await expectLater(verifier.verifyPointer(jsonBytes(pointer)),
        throwsA(isA<CentralCatalogException>()));
  });

  test('wrong digest is rejected even with genuine signed pointer', () async {
    final original = jsonBytes(catalog([station(1)]));
    final pointer = await signedPointer(original, 1);
    final modified = jsonBytes(catalog([station(2)]));
    await expectLater(
        verifier.verify(pointerBytes: pointer, catalogBytes: modified),
        throwsA(isA<CentralCatalogException>()));
  });

  test('path traversal is impossible even before signature verification', () async {
    final bytes = jsonBytes(catalog([station(1)]));
    final pointer = jsonDecode(utf8.decode(await signedPointer(bytes, 1)))
        as Map<String, dynamic>;
    pointer['content_path'] = '../../secrets';
    expect(() => CentralCatalogPointer.parse(jsonBytes(pointer)),
        throwsA(isA<CentralCatalogException>()));
  });

  test('legacy ID reassignment to another GO station is rejected', () async {
    final previous = await validatePayload(jsonBytes(catalog([station(1)])));
    final a = station(1);
    final b = station(2);
    a['legacy_aliases'] = <String>[];
    a['radio_browser_uuids'] = [];
    b['legacy_aliases'] = ['legacy-1', 'legacy-2'];
    b['radio_browser_uuids'] = [
      {'uuid': 'legacy-1', 'state': 'current'},
      {'uuid': 'legacy-2', 'state': 'current'},
    ];
    final bytes = jsonBytes(catalog([a, b], sequence: 2));
    await expectLater(validatePayload(bytes, sequence: 2, previous: previous),
        throwsA(isA<CentralCatalogException>()));
  });

  test('missing GO station is rejected even when aliases survive elsewhere', () async {
    final previous = await validatePayload(jsonBytes(catalog([station(1), station(2)])));
    final bytes = jsonBytes(catalog([station(2)], sequence: 2));
    await expectLater(validatePayload(bytes, sequence: 2, previous: previous),
        throwsA(isA<CentralCatalogException>()));
  });

  test('retired station can be kept as tombstone retaining historical favorite identity', () async {
    final previous = await validatePayload(jsonBytes(catalog([station(1), station(2)])));
    final next = jsonBytes(catalog([station(2)], sequence: 2, tombstones: [
      {
        'go_station_id': 'go-station-000001',
        'legacy_aliases': ['legacy-1'],
        'reason_code': 'retired_by_editorial_review',
        'retired_at': '2026-11-15T18:00:00Z'
      }
    ]));
    final verified = await validatePayload(next, sequence: 2, previous: previous);
    expect(verified.aliasOwners['legacy-1'], 'go-station-000001');
  });

  test('same body at higher signed sequence supports controlled rollback', () async {
    final oldBytes = jsonBytes(catalog([station(1)]));
    final first = await validatePayload(oldBytes);
    final second = await validatePayload(oldBytes, sequence: 2, previous: first);
    expect(second.pointer.sequence, 2);
    expect(second.pointer.sha256, first.pointer.sha256);
  });

  test('non-monotonic replay fails, even if old signature is genuine', () async {
    final bytes = jsonBytes(catalog([station(1)]));
    final previous = await validatePayload(bytes);
    await expectLater(validatePayload(bytes, previous: previous),
        throwsA(isA<CentralCatalogException>()));
  });

  test('large deletion cannot be shipped as a signed catalog', () async {
    final before = <Map<String, dynamic>>[
      for (var i = 1; i <= 210; i++) station(i)
    ];
    final last = await validatePayload(jsonBytes(catalog(before)));
    final after = <Map<String, dynamic>>[
      for (var i = 1; i <= 210; i++)
        station(i, status: i <= 30 ? 'retired' : 'active')
    ];
    await expectLater(
        validatePayload(jsonBytes(catalog(after, sequence: 2)),
            sequence: 2, previous: last),
        throwsA(isA<CentralCatalogException>()));
  });

  test('corrupt newest file falls back to the last valid local snapshot', () async {
    final tmp = await Directory.systemTemp.createTemp('go-radio-dart-test-');
    try {
      final store = CentralCatalogDiskStore(tmp);
      final valid = await validatePayload(jsonBytes(catalog([station(1)])));
      await store.persist(valid);
      final badFile = File(
          '${tmp.path}${Platform.pathSeparator}go-radio-v1-2-${List.filled(64, 'a').join()}.json');
      await badFile.writeAsString('{broken', flush: true);
      final got = await store.loadLatest(verifier);
      expect(got!.pointer.sequence, 1);
      expect(got.aliasOwners['legacy-1'], 'go-station-000001');
    } finally {
      await tmp.delete(recursive: true);
    }
  });

  test('offline load never requires a network request', () async {
    final tmp = await Directory.systemTemp.createTemp('go-radio-dart-offline-');
    try {
      var calls = 0;
      final client = CentralRadioCatalogClient(
          baseUri: Uri.parse('https://example.org/radio/catalog/v1/'),
          verifier: verifier,
          disk: CentralCatalogDiskStore(tmp),
          fetch: (uri, max) async {
            calls++;
            throw Exception('network intentionally unavailable');
          });
      expect(await client.loadOffline(), isNull);
      expect(calls, 0);
      final valid = await validatePayload(jsonBytes(catalog([station(1)])));
      await client.disk.persist(valid);
      expect((await client.loadOffline())!.stations, hasLength(1));
      expect(calls, 0);
    } finally {
      await tmp.delete(recursive: true);
    }
  });

  test('one network update, unchanged second pointer skips catalog fetch', () async {
    final tmp = await Directory.systemTemp.createTemp('go-radio-dart-sync-');
    try {
      final payload = jsonBytes(catalog([station(1)]));
      final pointer = await signedPointer(payload, 1);
      var pointerRequests = 0;
      var payloadRequests = 0;
      final client = CentralRadioCatalogClient(
          baseUri: Uri.parse('https://example.org/radio/catalog/v1/'),
          verifier: verifier,
          disk: CentralCatalogDiskStore(tmp),
          fetch: (uri, max) async {
            if (uri.path.endsWith('/current.json')) {
              pointerRequests++;
              return pointer;
            }
            payloadRequests++;
            return payload;
          });
      final first = await client.sync();
      expect(first.updated, isTrue);
      final second = await client.sync();
      expect(second.updated, isFalse);
      expect(pointerRequests, 2);
      expect(payloadRequests, 1);
      expect((await client.loadOffline())!.stations, hasLength(1));
    } finally {
      await tmp.delete(recursive: true);
    }
  });

  test('unknown catalog envelope fields are rejected', () async {
    final doc = catalog([station(1)])..['injected_field'] = 'unexpected';
    await expectLater(validatePayload(jsonBytes(doc)),
        throwsA(isA<CentralCatalogException>()));
  });

  test('duplicate Radio Browser UUIDs are rejected', () async {
    final s = station(1);
    final ids = (s['radio_browser_uuids'] as List);
    ids.add({'uuid': 'legacy-1', 'state': 'historical'});
    await expectLater(validatePayload(jsonBytes(catalog([s]))),
        throwsA(isA<CentralCatalogException>()));
  });

  test('bad logo dimensions cannot enter local snapshot', () async {
    final s = station(1);
    final digest = List.filled(64, 'a').join();
    s['logo'] = {
      'asset_id': 'sha256:$digest',
      'revision': 1,
      'url': 'https://example.org/logo.png',
      'sha256': digest,
      'byte_size': 1000,
      'width': 0,
      'height': 512,
      'mime_type': 'image/png'
    };
    await expectLater(validatePayload(jsonBytes(catalog([s]))),
        throwsA(isA<CentralCatalogException>()));
  });

  test('bad genre and fake timestamp are rejected', () async {
    final s = station(1);
    s['genres'] = ['Heavy', 'Heavy'];
    await expectLater(validatePayload(jsonBytes(catalog([s]))),
        throwsA(isA<CentralCatalogException>()));
    s['genres'] = ['Heavy'];
    (s['status'] as Map<String, dynamic>)['changed_at'] = 'not-a-date';
    await expectLater(validatePayload(jsonBytes(catalog([s]))),
        throwsA(isA<CentralCatalogException>()));
  });

  test('untrusted key prevents even the catalog HTTP request', () async {
    final tmp = await Directory.systemTemp.createTemp('go-radio-dart-fail-');
    try {
      final payload = jsonBytes(catalog([station(1)]));
      final pointer = await signedPointer(payload, 1);
      var payloadRequests = 0;
      final client = CentralRadioCatalogClient(
          baseUri: Uri.parse('https://example.org/radio/catalog/v1/'),
          verifier: CentralCatalogVerifier(trustedKeys: {}),
          disk: CentralCatalogDiskStore(tmp),
          fetch: (uri, max) async {
            if (uri.path.endsWith('current.json')) return pointer;
            payloadRequests++;
            return payload;
          });
      await expectLater(client.sync(), throwsA(isA<CentralCatalogException>()));
      expect(payloadRequests, 0);
    } finally {
      await tmp.delete(recursive: true);
    }
  });
}
