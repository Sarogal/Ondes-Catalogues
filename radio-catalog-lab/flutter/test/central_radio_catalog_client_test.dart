import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:cryptography/cryptography.dart';
import 'package:go_radio_flutter_lab/central_radio_catalog_client.dart';
import 'package:go_radio_flutter_lab/central_radio_catalog_core.dart';
import 'package:go_radio_flutter_lab/central_radio_catalog_projection.dart';
import 'package:go_radio_flutter_lab/central_catalog_migration_gate.dart';
import 'package:go_radio_flutter_lab/central_catalog_media_identity.dart';
import 'package:flutter_test/flutter_test.dart';
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

  test('projection preserves every original favorite ID and groups aliases', () async {
    final original = station(1);
    (original['legacy_aliases'] as List).add('former-media-1');
    final payload = jsonBytes(catalog([original]));
    final trusted = await validatePayload(payload);
    final result = const CentralCatalogProjector().preview(
      catalog: trusted,
      legacyFavoriteIds: ['former-media-1', 'legacy-1', 'missing-uuid', 'legacy-1'],
      preferredLegacyMediaIds: {'go-station-000001': 'legacy-1'},
    );
    expect(result.playableStations.length, 1);
    expect(result.playableStations.single.legacyMediaId, 'legacy-1');
    expect(result.playableStations.single.goStationId, 'go-station-000001');
    expect(result.favorites.projectedGoIds, ['go-station-000001']);
    expect(result.favorites.originalIdsUnchanged,
        ['former-media-1', 'legacy-1', 'missing-uuid', 'legacy-1']);
    expect(result.favorites.unresolvedOriginalIds, ['missing-uuid']);
    expect(result.favorites.unavailableFavorites, isEmpty);
  });

  test('quarantined stations and retired tombstones remain favorites, not playable', () async {
    final quarantined = station(2, status: 'quarantined');
    (quarantined['status'] as Map<String, dynamic>)['reason_code'] = 'manual_review';
    quarantined['streams'] = <Map<String, dynamic>>[];
    final tomb = {
      'go_station_id': 'go-station-000003',
      'legacy_aliases': ['legacy-3'],
      'reason_code': 'editorial_retirement',
      'retired_at': '2026-11-15T18:00:00Z',
    };
    final trusted = await validatePayload(jsonBytes(
      catalog([station(1), quarantined], tombstones: [tomb])));
    final preview = const CentralCatalogProjector().preview(
        catalog: trusted, legacyFavoriteIds: ['legacy-3', 'legacy-2', 'legacy-1']);
    expect(preview.playableStations.map((s) => s.goStationId),
        ['go-station-000001']);
    expect(preview.favorites.projectedGoIds,
        ['go-station-000003', 'go-station-000002', 'go-station-000001']);
    expect(preview.favorites.unavailableFavorites.map((f) => f.status),
        ['retired', 'quarantined']);
    expect(preview.favorites.unavailableFavorites.first.displayName, isNull);
    expect(preview.stationsByGoId['go-station-000002']!.playable, isFalse);
  });

  test('bad historical MediaItem preference is rejected', () async {
    final trusted = await validatePayload(jsonBytes(catalog([station(1)])));
    expect(
        () => const CentralCatalogProjector().preview(
          catalog: trusted,
          legacyFavoriteIds: ['legacy-1'],
          preferredLegacyMediaIds: {'go-station-000001': 'unrelated-old-id'},
        ),
        throwsA(isA<CentralCatalogException>()));
  });

  test('projection includes only verified streams, retaining priority ordering', () async {
    final source = station(1);
    (source['streams'] as List).add({
      'stream_id': 'candidate-secondary',
      'url': 'https://example.org/candidate.mp3',
      'priority': 2,
      'protocol': 'https',
      'state': 'candidate',
    });
    (source['streams'] as List).add({
      'stream_id': 'verified-secondary',
      'url': 'https://example.org/verified.mp3',
      'priority': 1,
      'protocol': 'https',
      'state': 'verified',
      'codec': 'aac',
      'bitrate_kbps': 96,
    });
    final trusted = await validatePayload(jsonBytes(catalog([source])));
    final item = const CentralCatalogProjector().preview(
        catalog: trusted, legacyFavoriteIds: []).playableStations.single;
    expect(item.verifiedStreams.map((s) => s.id),
        ['stream-1', 'verified-secondary']);
    expect(item.verifiedStreams.any((s) => s.id == 'candidate-secondary'),
        isFalse);
  });

  test('GO primary ID is stable for new station without historical preference', () async {
    final trusted = await validatePayload(jsonBytes(catalog([station(1)])));
    final result = const CentralCatalogProjector().preview(
        catalog: trusted, legacyFavoriteIds: ['go-station-000001']);
    expect(result.playableStations.single.legacyMediaId, 'go-station-000001');
    expect(result.favorites.projectedGoIds, ['go-station-000001']);
  });

  test('preview immutable and never changes station source JSON', () async {
    final source = station(1);
    final payload = jsonBytes(catalog([source]));
    final trusted = await validatePayload(payload);
    final before = jsonEncode(source);
    final result = const CentralCatalogProjector().preview(
        catalog: trusted, legacyFavoriteIds: ['legacy-1']);
    expect(jsonEncode(source), before);
    expect(() => result.stationsByGoId.clear(), throwsUnsupportedError);
    expect(() => result.playableStations.clear(), throwsUnsupportedError);
    expect(() => result.favorites.originalIdsUnchanged.clear(),
        throwsUnsupportedError);
    expect(() => result.playableStations.first.legacyAliases.clear(),
        throwsUnsupportedError);
  });

  test('coverage of supplied V64 identities passes but never approves release',
      () async {
    final source = station(1);
    (source['legacy_aliases'] as List).add('variant-1');
    final trusted = await validatePayload(jsonBytes(catalog([source])));
    final report = const CentralCatalogMigrationGate().audit(
      catalog: trusted,
      legacyStations: [
        CentralLegacyObservation(
            primaryMediaId: 'legacy-1',
            historicalIds: {'legacy-1', 'variant-1'}),
      ],
      legacyFavoriteIds: ['variant-1', 'legacy-1'],
      sourceLabel: 'synthetic-supplied-cache',
    );
    expect(report.matchesObservedBaseline, isTrue);
    expect(report.observedLegacyStations, 1);
    expect(report.mappedLegacyStations, 1);
    expect(report.readyForRelease, isFalse);
  });

  test('legacy station missing from the central identities blocks coverage',
      () async {
    final trusted = await validatePayload(jsonBytes(catalog([station(1)])));
    final report = const CentralCatalogMigrationGate().audit(
      catalog: trusted,
      legacyStations: [
        CentralLegacyObservation(
            primaryMediaId: 'forgotten-uuid',
            historicalIds: {'forgotten-uuid'}),
      ],
      legacyFavoriteIds: [],
      sourceLabel: 'synthetic-v64',
    );
    expect(report.matchesObservedBaseline, isFalse);
    expect(report.missingPrimaryMediaIds, ['forgotten-uuid']);
  });

  test('unmapped stream variant blocks coverage even if primary is mapped',
      () async {
    final trusted = await validatePayload(jsonBytes(catalog([station(1)])));
    final report = const CentralCatalogMigrationGate().audit(
      catalog: trusted,
      legacyStations: [
        CentralLegacyObservation(
            primaryMediaId: 'legacy-1',
            historicalIds: {'legacy-1', 'forgotten-variant'}),
      ],
      legacyFavoriteIds: [],
      sourceLabel: 'synthetic-v64',
    );
    expect(report.matchesObservedBaseline, isFalse);
    expect(report.unmappedHistoricalIds, ['forgotten-variant']);
  });

  test('V64 merged station mixing two GO identities is marked ambiguous',
      () async {
    final trusted = await validatePayload(
        jsonBytes(catalog([station(1), station(2)])));
    final report = const CentralCatalogMigrationGate().audit(
      catalog: trusted,
      legacyStations: [
        CentralLegacyObservation(
            primaryMediaId: 'legacy-1',
            historicalIds: {'legacy-1', 'legacy-2'}),
      ],
      legacyFavoriteIds: [],
      sourceLabel: 'synthetic-v64',
    );
    expect(report.matchesObservedBaseline, isFalse);
    expect(report.ambiguousPrimaryMediaIds, ['legacy-1']);
  });

  test('unknown favorite ID prevents a clean migration report', () async {
    final trusted = await validatePayload(jsonBytes(catalog([station(1)])));
    final report = const CentralCatalogMigrationGate().audit(
      catalog: trusted,
      legacyStations: [
        CentralLegacyObservation(
            primaryMediaId: 'legacy-1', historicalIds: {'legacy-1'})
      ],
      legacyFavoriteIds: ['legacy-1', 'unknown-favorite'],
      sourceLabel: 'synthetic-v64',
    );
    expect(report.unresolvedFavoriteIds, ['unknown-favorite']);
    expect(report.matchesObservedBaseline, isFalse);
    expect(report.readyForRelease, isFalse);
  });

  test('duplicate primary IDs block the supplied-baseline comparison',
      () async {
    final trusted = await validatePayload(jsonBytes(catalog([station(1)])));
    final report = const CentralCatalogMigrationGate().audit(
      catalog: trusted,
      legacyStations: [
        CentralLegacyObservation(
            primaryMediaId: 'legacy-1', historicalIds: {'legacy-1'}),
        CentralLegacyObservation(
            primaryMediaId: 'legacy-1', historicalIds: {'legacy-1'}),
      ],
      legacyFavoriteIds: [],
      sourceLabel: 'synthetic-v64',
    );
    expect(report.matchesObservedBaseline, isFalse);
    expect(report.duplicatePrimaryMediaIds, ['legacy-1']);
  });

  test('empty or anonymous source is never a coverage approval', () async {
    final trusted = await validatePayload(jsonBytes(catalog([station(1)])));
    expect(
      () => const CentralCatalogMigrationGate().audit(
        catalog: trusted,
        legacyStations: [],
        legacyFavoriteIds: [],
        sourceLabel: '',
      ),
      throwsA(isA<CentralCatalogException>()),
    );
    final result = const CentralCatalogMigrationGate().audit(
      catalog: trusted, legacyStations: [], legacyFavoriteIds: [],
      sourceLabel: 'empty synthetic observation');
    expect(result.matchesObservedBaseline, isFalse);
  });

  test('Android Auto resolves old bookmark, keeps browse context and original primary ID', () async {
    final base = station(1);
    (base['legacy_aliases'] as List).add('old-aa-bookmark');
    final trusted = await validatePayload(jsonBytes(catalog([base])));
    final preview = const CentralCatalogProjector().preview(
      catalog: trusted,
      legacyFavoriteIds: ['old-aa-bookmark'],
      preferredLegacyMediaIds: {'go-station-000001': 'legacy-1'},
    );
    final resolver = CentralMediaIdentityResolver(catalog: trusted, preview: preview);
    final id = 'go:auto:station:old-aa-bookmark|go%3Aauto%3Afavorites';
    final match = resolver.resolveMediaId(id);
    expect(match.status, CentralMediaStatus.playable);
    expect(match.goStationId, 'go-station-000001');
    expect(match.browseContext, 'go:auto:favorites');
    expect(match.station!.displayName, 'Fictional station 1');
    expect(match.canonicalMediaId, 'go:auto:station:legacy-1|go%3Aauto%3Afavorites');
  });

  test('GO station ID also resolves without legacy ID', () async {
    final trusted = await validatePayload(jsonBytes(catalog([station(1)])));
    final preview = const CentralCatalogProjector().preview(
      catalog: trusted, legacyFavoriteIds: []);
    final resolver = CentralMediaIdentityResolver(catalog: trusted, preview: preview);
    final match = resolver.resolveMediaId('go:auto:station:go-station-000001');
    expect(match.playable, isTrue);
    expect(match.station!.goStationId, 'go-station-000001');
    expect(match.canonicalMediaId, 'go:auto:station:go-station-000001');
  });

  test('quarantined station bookmark is not playable', () async {
    final q = station(2, status: 'quarantined');
    (q['status'] as Map<String, dynamic>)['reason_code'] = 'review';
    q['streams'] = <Map<String,dynamic>>[];
    final trusted = await validatePayload(jsonBytes(catalog([station(1), q])));
    final preview = const CentralCatalogProjector().preview(
      catalog: trusted, legacyFavoriteIds: ['legacy-2']);
    final resolver = CentralMediaIdentityResolver(catalog: trusted, preview: preview);
    final result = resolver.resolveMediaId('go:auto:station:legacy-2|go%3Aauto%3Arecent');
    expect(result.status, CentralMediaStatus.quarantined);
    expect(result.playable, isFalse);
    expect(result.station, isNull);
    expect(result.goStationId, 'go-station-000002');
  });

  test('retired tombstone bookmark cannot play even when previously favorited', () async {
    final tomb = {
      'go_station_id': 'go-station-000004',
      'legacy_aliases': ['retired-uuid'],
      'reason_code': 'voluntary_retirement',
      'retired_at': '2026-11-15T18:00:00Z',
    };
    final trusted = await validatePayload(jsonBytes(catalog([station(1)], tombstones: [tomb])));
    final preview = const CentralCatalogProjector().preview(
      catalog: trusted, legacyFavoriteIds: ['retired-uuid']);
    final resolver = CentralMediaIdentityResolver(catalog: trusted, preview: preview);
    final result = resolver.resolveMediaId('go:auto:station:retired-uuid');
    expect(result.status, CentralMediaStatus.retired);
    expect(result.canonicalMediaId, isNull);
    expect(result.playable, isFalse);
  });

  test('unknown bookmark cannot be matched by a shared stream URL', () async {
    final trusted = await validatePayload(jsonBytes(catalog([station(1)])));
    final preview = const CentralCatalogProjector().preview(catalog: trusted, legacyFavoriteIds: []);
    final resolver = CentralMediaIdentityResolver(catalog: trusted, preview: preview);
    final unknown = resolver.resolveMediaId('go:auto:station:unknown');
    expect(unknown.status, CentralMediaStatus.unknown);
    expect(unknown.station, isNull);
  });

  test('malformed Android Auto IDs are rejected without throws', () async {
    final trusted = await validatePayload(jsonBytes(catalog([station(1)])));
    final preview = const CentralCatalogProjector().preview(catalog: trusted, legacyFavoriteIds: []);
    final resolver = CentralMediaIdentityResolver(catalog: trusted, preview: preview);
    for (final input in [
      'go:auto:genres',
      'go:auto:station:',
      'go:auto:station:legacy-1|',
      'go:auto:station:%XY',
      'go:auto:station:legacy-1|go:auto:all',
      'go:auto:station:legacy-1|a|b',
      'go:auto:station:legacy-1%0A',
    ]) {
      final match = resolver.resolveMediaId(input);
      expect(match.status, CentralMediaStatus.malformed, reason: input);
      expect(match.playable, isFalse);
    }
  });

  test('properly encoded spaces and genre contexts survive media-ID roundtrip', () async {
    final s = station(1);
    (s['legacy_aliases'] as List).add('legacy player');
    final trusted = await validatePayload(jsonBytes(catalog([s])));
    final preview = const CentralCatalogProjector().preview(
      catalog: trusted, legacyFavoriteIds: []);
    final resolver = CentralMediaIdentityResolver(catalog: trusted, preview: preview);
    final match = resolver.resolveMediaId(
        'go:auto:station:legacy%20player|go%3Aauto%3Agenre%3AHard%2520Rock');
    expect(match.playable, isTrue);
    expect(match.browseContext, 'go:auto:genre:Hard%20Rock');
    expect(match.canonicalMediaId,
        'go:auto:station:go-station-000001|go%3Aauto%3Agenre%3AHard%2520Rock');
  });

  test('invalid projection preferred ID cannot impersonate another station', () async {
    final trusted = await validatePayload(jsonBytes(catalog([station(1),station(2)])));
    final good = const CentralCatalogProjector().preview(
      catalog: trusted, legacyFavoriteIds: []);
    // Constructor validates trusted identity mapping of every projected GO ID.
    final bad = CentralCatalogPreview(
      stationsByGoId: {
        'go-station-000001': CentralProjectedStation(
          goStationId: 'go-station-000001', legacyMediaId: 'legacy-2',
          legacyAliases: const ['legacy-1'], displayName: 'Bad',
          genres: const ['Heavy'], tags: const ['heavy metal'], countryCode: 'FR',
          homepage: '', status: 'active', verifiedStreams:
              good.playableStations.first.verifiedStreams, logoSha256: null),
      },
      playableStations: good.playableStations,
      favorites: good.favorites,
    );
    expect(() => CentralMediaIdentityResolver(catalog: trusted, preview: bad),
        throwsA(isA<CentralCatalogException>()));
  });


  test('signed pointer and nested stations are immutable after validation', () async {
    final verified = await validatePayload(jsonBytes(catalog([station(1)])));
    expect(
      () => verified.pointer.raw['release_sequence'] = 500,
      throwsA(isA<UnsupportedError>()),
    );
    expect(
      () => (verified.pointer.raw['signature'] as Map<String, dynamic>)['key_id'] = 'forged',
      throwsA(isA<UnsupportedError>()),
    );
    final stationRecord = verified.stations.first;
    expect(
      () => (stationRecord['status'] as Map<String, dynamic>)['state'] = 'retired',
      throwsA(isA<UnsupportedError>()),
    );
    expect(
      () => ((stationRecord['streams'] as List).first as Map<String, dynamic>)['url'] =
          'https://example.org/forged.mp3',
      throwsA(isA<UnsupportedError>()),
    );
  });

  test('stations cannot disagree on dimensions for the same logo SHA', () async {
    final a = station(1);
    final b = station(2);
    final digest = List.filled(64, 'a').join();
    final descriptor = <String, dynamic>{
      'asset_id': 'sha256:$digest',
      'revision': 1,
      'url': 'https://example.org/official.png',
      'sha256': digest,
      'byte_size': 256,
      'width': 512,
      'height': 512,
      'mime_type': 'image/png',
    };
    a['logo'] = descriptor;
    b['logo'] = {...descriptor, 'width': 1024};
    await expectLater(
      validatePayload(jsonBytes(catalog([a, b]))),
      throwsA(isA<CentralCatalogException>()),
    );
    b['logo'] = {...descriptor, 'revision': 2, 'url': 'https://example.org/new.png'};
    final valid = await validatePayload(jsonBytes(catalog([a, b])));
    expect(valid.stations.length, 2);
  });

  test('authenticated snapshot bytes cannot be changed through exposed buffers', () async {
    final payload = jsonBytes(catalog([station(1)]));
    final pointer = await signedPointer(payload, 1);
    final verified = await verifier.verify(
      pointerBytes: pointer, catalogBytes: payload);
    final firstPointerByte = verified.pointerBytes.first;
    final firstCatalogByte = verified.catalogBytes.first;
    // Both the original inputs and public getters are independently mutable,
    // but none of them must alter the authenticated snapshot.
    pointer[0] = 0;
    payload[0] = 0;
    verified.pointerBytes[0] = 0;
    verified.catalogBytes[0] = 0;
    expect(verified.pointerBytes.first, firstPointerByte);
    expect(verified.catalogBytes.first, firstCatalogByte);
    final tmp = await Directory.systemTemp.createTemp('go-auth-buffer-');
    try {
      final disk = CentralCatalogDiskStore(tmp);
      await disk.persist(verified);
      expect((await disk.loadLatest(verifier))!.stations, hasLength(1));
    } finally {
      await tmp.delete(recursive: true);
    }
  });

  test('a signed update cannot reinterpret an existing logo SHA', () async {
    final first = station(1);
    final digest = List.filled(64, 'a').join();
    final logo = <String, dynamic>{
      'asset_id': 'sha256:$digest', 'revision': 1,
      'url': 'https://example.org/official.png',
      'sha256': digest, 'byte_size': 128,
      'width': 512, 'height': 512, 'mime_type': 'image/png'
    };
    first['logo'] = logo;
    final original = await validatePayload(jsonBytes(catalog([first])));
    final changed = station(1);
    changed['logo'] = {...logo, 'revision': 2, 'width': 1024};
    await expectLater(
      validatePayload(jsonBytes(catalog([changed], sequence: 2)),
          sequence: 2, previous: original),
      throwsA(isA<CentralCatalogException>()),
    );
    changed['logo'] = {...logo, 'revision': 2, 'url': 'https://example.org/moved.png'};
    final updated = await validatePayload(
      jsonBytes(catalog([changed], sequence: 2)),
      sequence: 2, previous: original);
    expect(updated.stations.length, 1);
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
